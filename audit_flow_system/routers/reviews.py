from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from docx import Document
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import BASE_DIR, WORKSPACE_ROOT
from ..core.db import get_db, safe_database_label
from ..core.security import (
    DEFAULT_MODULE_ORDER,
    DEFAULT_PASSWORD_POLICY,
    can_edit_project,
    can_upload_documents,
    can_view_project,
    current_user,
    default_audit_scope,
    ensure_document_uploader,
    ensure_feature_permission,
    ensure_project_editor,
    ensure_project_viewer,
    get_setting,
    hash_password,
    is_admin,
    normalize_module_order,
    require_admin,
    set_setting,
    validate_password_policy,
    verify_password,
)
from ..core.utils import apply_patch_to_model, get_or_404, list_dict, obj_dict
from ..models import (
    Attachment,
    AutomationRule,
    AutofillPlanItem,
    AutofillRun,
    Client,
    ClientITContact,
    DocumentRequest,
    EnterpriseContact,
    LoginSession,
    Project,
    ProjectMember,
    ReviewFinding,
    ReviewFindingHistory,
    ReviewRun,
    ReviewStep,
    Role,
    Task,
    User,
    Workpaper,
)
from ..schemas import (
    AttachmentIn,
    AttachmentReferenceScanIn,
    AttachmentScanIn,
    AutomationRuleIn,
    AutofillPlanIn,
    ClientITContactIn,
    ClientIn,
    ContactIn,
    DocumentRequestUploadIn,
    InitFromPriorIn,
    LoginIn,
    MemberIn,
    PasswordPolicyIn,
    ProjectIn,
    ReviewFindingAssignIn,
    ReviewDecisionIn,
    ReviewFindingIn,
    ReviewFindingPatchIn,
    ReviewFindingReplyIn,
    ReviewRunIn,
    RoleIn,
    TaskIn,
    UserIn,
    WorkpaperIn,
)


from ..services.attachments import (
    append_reference,
    candidate_reference_tokens,
    extract_workpaper_text,
    file_type_for_path,
    guess_workpaper_for_file,
    likely_attachment_reference,
    next_attachment_index,
    safe_project_code,
    sanitize_workpaper_code,
    scan_project_attachment_files,
)
from ..services.materials import c22_document_requests_from_rules, save_upload_files
from ..services.projects import copy_workpaper_file, replace_audit_year, seed_project_template_workpapers
from ..services.review import add_finding, run_external_rules, run_internal_review
from ..services.timeliness import days_after, overdue_payload, waiting_days
from ..services.privacy import project_redaction_terms, redact_text


router = APIRouter()


OPEN_FINDING_STATUSES = {"open", "assigned", "retained", "revised", "待处理", "已分派", "保留", "已修订"}


def _history_payload(history: ReviewFindingHistory) -> dict[str, Any]:
    data = obj_dict(history)
    data["operator_name"] = history.operator.display_name if history.operator else ""
    return data


def _matched_workpaper_for_finding(db: Session, finding: ReviewFinding, run: ReviewRun) -> Workpaper | None:
    if run.workpaper_id:
        item = db.get(Workpaper, run.workpaper_id)
        if item:
            return item
    text = f"{finding.target or ''} {finding.issue or ''}".lower()
    if not text.strip():
        return None
    attachments = db.execute(
        select(Attachment).where(Attachment.project_id == run.project_id).order_by(Attachment.index_no)
    ).scalars().all()
    for attachment in attachments:
        if attachment.workpaper_id and attachment.index_no and attachment.index_no.lower() in text:
            item = db.get(Workpaper, attachment.workpaper_id)
            if item:
                return item
    workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == run.project_id).order_by(Workpaper.code)
    ).scalars().all()
    for item in sorted(workpapers, key=lambda row: len(row.code or ""), reverse=True):
        code = (item.code or "").lower()
        name = (item.name or "").lower()
        if (code and code in text) or (name and name in text):
            return item
    return None


def _finding_payload(
    finding: ReviewFinding,
    run: ReviewRun,
    project: Project,
    db: Session | None = None,
) -> dict[str, Any]:
    data = obj_dict(finding)
    data["run_id"] = run.id
    data["project_id"] = project.id
    data["project_name"] = project.name
    data["entity_name"] = project.entity_name
    data["run_mode"] = run.mode
    data["run_status"] = run.status
    data["run_summary"] = run.summary
    discovered_at = finding.created_at or run.started_at or datetime.utcnow()
    due_date = finding.due_date or days_after(discovered_at.date(), 5)
    data["discovered_at"] = discovered_at
    data.update(overdue_payload(finding.status or "open", due_date))
    data["review_comment"] = finding.review_comment
    data["assignee_user_id"] = finding.assignee_user_id
    data["assignee_name"] = finding.assignee.display_name if finding.assignee else ""
    if db is not None:
        workpaper = _matched_workpaper_for_finding(db, finding, run)
        owner = finding.assignee or (workpaper.preparer if workpaper else project.project_leader)
        data["workpaper_id"] = workpaper.id if workpaper else run.workpaper_id
        data["workpaper_code"] = workpaper.code if workpaper else ""
        data["workpaper_name"] = workpaper.name if workpaper else ""
        data["owner_user_id"] = owner.id if owner else None
        data["owner_name"] = owner.display_name if owner else ""
        histories = db.execute(
            select(ReviewFindingHistory)
            .where(ReviewFindingHistory.finding_id == finding.id)
            .order_by(ReviewFindingHistory.id.desc())
            .limit(20)
        ).scalars().all()
        data["histories"] = [_history_payload(row) for row in histories]
    return data


def _setting_int(db: Session, key: str, default: int) -> int:
    try:
        return int(get_setting(db, key, default))
    except (TypeError, ValueError):
        return default


def _role_sla_days(db: Session, role_code: str) -> int:
    default_sla = _setting_int(db, "review_sla_days", 3)
    return _setting_int(db, f"review_sla_days_{role_code}", default_sla)


def _enter_review_step(db: Session, step: ReviewStep, now: datetime | None = None) -> None:
    current = now or datetime.utcnow()
    step.entered_at = current
    step.sla_days = _role_sla_days(db, step.reviewer_role_code)
    step.due_date = days_after(current.date(), step.sla_days)


def _review_step_payload(step: ReviewStep, workpaper: Workpaper | None = None, project: Project | None = None) -> dict[str, Any]:
    data = obj_dict(step)
    data.update(overdue_payload(step.status, step.due_date))
    data["waiting_days"] = waiting_days(step.entered_at)
    if workpaper is not None:
        data["workpaper_id"] = workpaper.id
        data["workpaper_code"] = workpaper.code
        data["workpaper_name"] = workpaper.name
        data["project_id"] = workpaper.project_id
    if project is not None:
        data["project_name"] = project.name
        data["entity_name"] = project.entity_name
    return data


def _finding_query():
    return (
        select(ReviewFinding, ReviewRun, Project)
        .join(ReviewRun, ReviewFinding.run_id == ReviewRun.id)
        .join(Project, ReviewRun.project_id == Project.id)
    )


def _is_open_finding(status: str) -> bool:
    return (status or "open") in OPEN_FINDING_STATUSES


@router.get("/api/automation-rules")
def list_automation_rules(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    return list_dict(db.execute(select(AutomationRule).order_by(AutomationRule.code)).scalars().all())


@router.post("/api/automation-rules", status_code=201)
def create_automation_rule(
    body: AutomationRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    item = AutomationRule(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.post("/api/review-runs", status_code=201)
def create_review_run(body: ReviewRunIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    project = get_or_404(db, Project, body.project_id, "项目")
    ensure_document_uploader(db, project, user)
    run = ReviewRun(project_id=body.project_id, workpaper_id=body.workpaper_id, mode="auto", status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    run.started_at = datetime.utcnow()
    try:
        count = run_external_rules(db, run) if body.use_external_rules else run_internal_review(db, run)
        run.status = "completed"
        run.summary = f"自动复核完成，发现 {count} 项问题"
    except Exception as exc:
        run.status = "failed"
        run.summary = f"自动复核失败：{exc}"
        add_finding(db, run, "SYS-001", "high", "review-run", run.summary)
    finally:
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
    return obj_dict(run)


@router.get("/api/review-runs")
def list_review_runs(
    projectId: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    stmt = select(ReviewRun).order_by(ReviewRun.id.desc())
    if projectId is not None:
        project = get_or_404(db, Project, projectId, "项目")
        ensure_project_viewer(db, project, user)
        stmt = stmt.where(ReviewRun.project_id == projectId)
    rows = db.execute(stmt).scalars().all()
    if projectId is None:
        rows = [row for row in rows if can_view_project(db, user, get_or_404(db, Project, row.project_id, "项目"))]
    payload = []
    for row in rows:
        data = obj_dict(row)
        data["finding_count"] = len(row.findings)
        payload.append(data)
    return payload


@router.get("/api/projects/{project_id}/llm-review/redacted-preview")
def llm_review_redacted_preview(
    project_id: int,
    workpaperId: Optional[int] = Query(default=None),
    maxChars: int = Query(default=2000, ge=200, le=20000),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    terms = project_redaction_terms(db, project)
    stmt = select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)
    if workpaperId is not None:
        stmt = stmt.where(Workpaper.id == workpaperId)
    workpapers = db.execute(stmt.limit(5)).scalars().all()
    items: list[dict[str, Any]] = []
    total_stats: dict[str, int] = {}
    for workpaper in workpapers:
        path = Path(workpaper.file_path or "").expanduser()
        if not workpaper.file_path or not path.exists() or not path.is_file():
            continue
        text = extract_workpaper_text(path)
        redacted_text, stats = redact_text(text, terms)
        for key, count in stats.items():
            total_stats[key] = total_stats.get(key, 0) + count
        preview_text = redacted_text[:maxChars]
        items.append(
            {
                "workpaper_id": workpaper.id,
                "code": workpaper.code,
                "name": workpaper.name,
                "file_type": path.suffix.lower().lstrip("."),
                "redacted_text": preview_text,
                "char_count": len(preview_text),
            }
        )
    return {
        "project_id": project.id,
        "project_name": "[项目名称]",
        "redaction_enabled": True,
        "redaction_stats": total_stats,
        "items": items,
    }


@router.get("/api/review-runs/{run_id}/findings")
def list_review_findings(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    run = get_or_404(db, ReviewRun, run_id, "复核任务")
    project = get_or_404(db, Project, run.project_id, "项目")
    ensure_project_viewer(db, project, user)
    rows = db.execute(
        select(ReviewFinding).where(ReviewFinding.run_id == run_id).order_by(ReviewFinding.severity.desc(), ReviewFinding.id)
    ).scalars().all()
    return list_dict(rows)


@router.get("/api/review-findings")
def list_all_review_findings(
    projectId: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    stmt = _finding_query().order_by(ReviewFinding.id.desc())
    if projectId is not None:
        project = get_or_404(db, Project, projectId, "项目")
        ensure_project_viewer(db, project, user)
        stmt = stmt.where(ReviewRun.project_id == projectId)
    if status:
        stmt = stmt.where(ReviewFinding.status == status)
    if severity:
        stmt = stmt.where(ReviewFinding.severity == severity)
    rows = db.execute(stmt).all()
    if projectId is None:
        rows = [row for row in rows if can_view_project(db, user, row[2])]
    return [_finding_payload(finding, run, project, db) for finding, run, project in rows]


@router.post("/api/review-findings", status_code=201)
def create_manual_review_finding(
    body: ReviewFindingIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    if body.run_id:
        run = get_or_404(db, ReviewRun, body.run_id, "复核任务")
        project = get_or_404(db, Project, run.project_id, "项目")
    else:
        if body.project_id is None:
            raise HTTPException(status_code=400, detail="人工问题记录必须选择项目")
        project = get_or_404(db, Project, body.project_id, "项目")
        run = db.execute(
            select(ReviewRun)
            .where(ReviewRun.project_id == project.id, ReviewRun.mode == "manual")
            .order_by(ReviewRun.id.desc())
        ).scalars().first()
        if run is None:
            run = ReviewRun(
                project_id=project.id,
                mode="manual",
                status="completed",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                summary="人工复核问题记录",
            )
            db.add(run)
            db.flush()
    ensure_project_editor(project, user)
    finding = ReviewFinding(
        run_id=run.id,
        rule_code=body.rule_code or "MANUAL",
        severity=body.severity or "medium",
        target=body.target or "",
        issue=body.issue,
        evidence=body.evidence or "",
        status=body.status or "open",
        assignee_user_id=body.assignee_user_id,
        due_date=body.due_date,
        review_comment=body.review_comment or "",
    )
    if finding.assignee_user_id is None:
        workpaper = _matched_workpaper_for_finding(db, finding, run)
        if workpaper and workpaper.preparer_user_id:
            finding.assignee_user_id = workpaper.preparer_user_id
    db.add(finding)
    db.flush()
    db.add(
        ReviewFindingHistory(
            finding_id=finding.id,
            operator_user_id=user.id,
            old_status="",
            new_status=finding.status,
            comment="创建人工复核问题",
            change_summary="创建问题记录",
        )
    )
    count = db.execute(select(func.count(ReviewFinding.id)).where(ReviewFinding.run_id == run.id)).scalar_one()
    run.status = "completed"
    run.finished_at = datetime.utcnow()
    run.summary = f"人工复核问题记录，累计 {count} 项"
    db.commit()
    db.refresh(finding)
    db.refresh(run)
    return _finding_payload(finding, run, project, db)


@router.patch("/api/review-findings/{finding_id}")
def update_review_finding(
    finding_id: int,
    body: ReviewFindingPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    row = db.execute(_finding_query().where(ReviewFinding.id == finding_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="复核问题不存在")
    finding, run, project = row
    ensure_project_editor(project, user)
    payload = body.model_dump(exclude_unset=True)
    history_comment = str(payload.pop("history_comment", "") or "")
    old_status = finding.status or ""
    changes: list[str] = []
    labels = {
        "rule_code": "问题类型",
        "severity": "严重程度",
        "target": "底稿/位置",
        "issue": "问题描述",
        "evidence": "整改说明",
        "status": "状态",
        "assignee_user_id": "责任人",
        "due_date": "截止日期",
        "review_comment": "复核意见",
    }
    for key, value in payload.items():
        if value is not None:
            old_value = getattr(finding, key, None)
            if old_value != value:
                changes.append(f"{labels.get(key, key)}：{old_value or '空'} -> {value or '空'}")
            setattr(finding, key, value)
    if run.mode == "manual":
        run.finished_at = datetime.utcnow()
    if changes or history_comment:
        db.add(
            ReviewFindingHistory(
                finding_id=finding.id,
                operator_user_id=user.id,
                old_status=old_status,
                new_status=finding.status or "",
                comment=history_comment,
                change_summary="；".join(changes) or "补充处理说明",
            )
        )
    db.commit()
    db.refresh(finding)
    return _finding_payload(finding, run, project, db)


@router.post("/api/review-findings/{finding_id}/reply")
def reply_review_finding(
    finding_id: int,
    body: ReviewFindingReplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    row = db.execute(_finding_query().where(ReviewFinding.id == finding_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="复核问题不存在")
    finding, run, project = row
    ensure_feature_permission(db, user, "findingKanban", "edit")
    ensure_document_uploader(db, project, user)
    reply = body.reply.strip()
    if not reply:
        raise HTTPException(status_code=400, detail="回复内容不能为空")
    old_status = finding.status or ""
    finding.review_comment = reply
    finding.status = "revised"
    db.add(
        ReviewFindingHistory(
            finding_id=finding.id,
            operator_user_id=user.id,
            old_status=old_status,
            new_status=finding.status,
            comment=reply,
            change_summary="项目成员提交整改回复，等待复核人员确认",
        )
    )
    if run.mode == "manual":
        run.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(finding)
    return _finding_payload(finding, run, project, db)


@router.post("/api/review-findings/{finding_id}/assign")
def assign_review_finding(
    finding_id: int,
    body: ReviewFindingAssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    row = db.execute(_finding_query().where(ReviewFinding.id == finding_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="复核问题不存在")
    finding, run, project = row
    ensure_project_editor(project, user)
    assignee = get_or_404(db, User, body.assignee_user_id, "责任人")
    old_status = finding.status or ""
    finding.assignee_user_id = assignee.id
    finding.due_date = body.due_date
    finding.status = "assigned"
    assignee_name = assignee.display_name or assignee.username or f"用户 #{assignee.id}"
    assignment_comment = str(body.assignment_comment or "").strip()
    summary_parts = [
        f"分派给{assignee_name}",
        f"截止日期：{body.due_date.isoformat()}",
        f"分派说明：{assignment_comment or '无'}",
    ]
    db.add(
        ReviewFindingHistory(
            finding_id=finding.id,
            operator_user_id=user.id,
            old_status=old_status,
            new_status=finding.status,
            comment=assignment_comment,
            change_summary="；".join(summary_parts),
        )
    )
    if run.mode == "manual":
        run.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(finding)
    return _finding_payload(finding, run, project, db)


@router.get("/api/review-findings/{finding_id}/history")
def list_review_finding_history(
    finding_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    row = db.execute(_finding_query().where(ReviewFinding.id == finding_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="复核问题不存在")
    _finding, _run, project = row
    ensure_project_viewer(db, project, user)
    histories = db.execute(
        select(ReviewFindingHistory)
        .where(ReviewFindingHistory.finding_id == finding_id)
        .order_by(ReviewFindingHistory.id.desc())
    ).scalars().all()
    return [_history_payload(item) for item in histories]


@router.get("/api/review-dashboard")
def review_dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    rows = db.execute(_finding_query().order_by(ReviewFinding.id.desc())).all()
    rows = [row for row in rows if can_view_project(db, user, row[2])]
    by_project: dict[int, dict[str, Any]] = {}
    by_rule: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    manual_count = 0
    open_count = 0
    for finding, run, project in rows:
        project_bucket = by_project.setdefault(
            project.id,
            {
                "project_id": project.id,
                "project_name": project.name,
                "entity_name": project.entity_name,
                "total": 0,
                "open": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "manual": 0,
            },
        )
        status = finding.status or "open"
        severity = finding.severity or "medium"
        project_bucket["total"] += 1
        project_bucket[severity] = project_bucket.get(severity, 0) + 1
        if _is_open_finding(status):
            project_bucket["open"] += 1
            open_count += 1
        if run.mode == "manual":
            project_bucket["manual"] += 1
            manual_count += 1
        by_rule[finding.rule_code or "未分类"] = by_rule.get(finding.rule_code or "未分类", 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        payload = _finding_payload(finding, run, project, db)
        if payload.get("is_overdue"):
            overdue.append(payload)
        if len(recent) < 20:
            recent.append(payload)
    material_overdue: list[dict[str, Any]] = []
    material_rows = db.execute(
        select(DocumentRequest, Project)
        .join(Project, DocumentRequest.project_id == Project.id)
        .where(DocumentRequest.due_date.is_not(None))
        .order_by(DocumentRequest.due_date, DocumentRequest.id)
    ).all()
    for request_item, project in material_rows:
        if not can_view_project(db, user, project):
            continue
        payload = obj_dict(request_item)
        payload.update(overdue_payload(request_item.status, request_item.due_date))
        if not payload.get("is_overdue"):
            continue
        payload["project_id"] = project.id
        payload["project_name"] = project.name
        payload["entity_name"] = project.entity_name
        material_overdue.append(payload)
        bucket = by_project.setdefault(
            project.id,
            {
                "project_id": project.id,
                "project_name": project.name,
                "entity_name": project.entity_name,
                "total": 0,
                "open": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "manual": 0,
            },
        )
        bucket["material_overdue_count"] = bucket.get("material_overdue_count", 0) + 1
    step_overdue: list[dict[str, Any]] = []
    step_rows = db.execute(
        select(ReviewStep, Workpaper, Project)
        .join(Workpaper, ReviewStep.workpaper_id == Workpaper.id)
        .join(Project, Workpaper.project_id == Project.id)
        .where(ReviewStep.due_date.is_not(None))
        .order_by(ReviewStep.due_date, ReviewStep.id)
    ).all()
    for step, workpaper, project in step_rows:
        if not can_view_project(db, user, project):
            continue
        payload = _review_step_payload(step, workpaper, project)
        if not payload.get("is_overdue"):
            continue
        step_overdue.append(payload)
        bucket = by_project.setdefault(
            project.id,
            {
                "project_id": project.id,
                "project_name": project.name,
                "entity_name": project.entity_name,
                "total": 0,
                "open": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "manual": 0,
            },
        )
        bucket["step_overdue_count"] = bucket.get("step_overdue_count", 0) + 1
    by_project_rows = sorted(by_project.values(), key=lambda item: (item["open"], item["total"]), reverse=True)
    return {
        "total": len(rows),
        "open": open_count,
        "manual": manual_count,
        "auto": len(rows) - manual_count,
        "overdue": len(overdue),
        "overdue_findings": sorted(overdue, key=lambda item: item.get("overdue_days", 0), reverse=True)[:20],
        "material_overdue": sorted(material_overdue, key=lambda item: item.get("overdue_days", 0), reverse=True)[:20],
        "step_overdue": sorted(step_overdue, key=lambda item: item.get("overdue_days", 0), reverse=True)[:20],
        "projects_with_findings": len(by_project_rows),
        "by_project": by_project_rows,
        "by_rule": [
            {"rule_code": code, "count": count}
            for code, count in sorted(by_rule.items(), key=lambda item: item[1], reverse=True)[:30]
        ],
        "by_severity": [{"severity": key, "count": value} for key, value in sorted(by_severity.items())],
        "by_status": [{"status": key, "count": value} for key, value in sorted(by_status.items())],
        "recent": recent,
    }


@router.post("/api/workpapers/{workpaper_id}/submit")
def submit_workpaper(workpaper_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    wp = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, wp.project_id, "项目")
    ensure_document_uploader(db, project, user)
    existing = db.execute(select(ReviewStep).where(ReviewStep.workpaper_id == wp.id)).scalars().all()
    if not existing:
        now = datetime.utcnow()
        role_codes = ["manager", "senior_manager", "director", "partner", "quality"]
        for index, role_code in enumerate(role_codes, start=1):
            step = ReviewStep(
                workpaper_id=wp.id,
                sequence_no=index,
                reviewer_role_code=role_code,
                status="pending" if index == 1 else "waiting",
            )
            if index == 1:
                _enter_review_step(db, step, now)
            db.add(step)
    wp.status = "submitted"
    db.commit()
    return {"status": "submitted"}


@router.get("/api/workpapers/{workpaper_id}/review-steps")
def list_review_steps(
    workpaper_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    get_or_404(db, Workpaper, workpaper_id, "底稿")
    rows = db.execute(
        select(ReviewStep).where(ReviewStep.workpaper_id == workpaper_id).order_by(ReviewStep.sequence_no)
    ).scalars().all()
    return [_review_step_payload(row) for row in rows]


@router.post("/api/review-steps/{step_id}/approve")
def approve_review_step(
    step_id: int,
    body: ReviewDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    step = get_or_404(db, ReviewStep, step_id, "复核步骤")
    wp = get_or_404(db, Workpaper, step.workpaper_id, "底稿")
    step.status = "approved"
    step.comment = body.comment
    step.reviewer_user_id = body.reviewer_user_id
    step.reviewed_at = datetime.utcnow()
    next_step = db.execute(
        select(ReviewStep)
        .where(ReviewStep.workpaper_id == step.workpaper_id, ReviewStep.sequence_no > step.sequence_no)
        .order_by(ReviewStep.sequence_no)
    ).scalars().first()
    if next_step:
        next_step.status = "pending"
        _enter_review_step(db, next_step)
        wp.status = "in_review"
    else:
        wp.status = "approved"
    db.commit()
    return {"status": wp.status}


@router.post("/api/review-steps/{step_id}/reject")
def reject_review_step(
    step_id: int,
    body: ReviewDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    step = get_or_404(db, ReviewStep, step_id, "复核步骤")
    wp = get_or_404(db, Workpaper, step.workpaper_id, "底稿")
    step.status = "rejected"
    step.comment = body.comment
    step.reviewer_user_id = body.reviewer_user_id
    step.reviewed_at = datetime.utcnow()
    wp.status = "returned"
    db.commit()
    return {"status": "returned"}
