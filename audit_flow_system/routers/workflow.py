from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import can_view_project, current_user, ensure_project_viewer, is_admin, project_reviewer_ids, supervised_project_ids
from ..core.utils import obj_dict
from ..models import (
    Attachment,
    DocumentRequest,
    Project,
    ProjectMember,
    ReviewFinding,
    ReviewFindingResponse,
    ReviewRun,
    ReviewStep,
    Task,
    User,
    Workpaper,
    WorkpaperTemplate,
)
from ..services.delivery_deadline import delivery_info
from ..services.project_monitoring import build_project_monitoring, workpaper_monitor_item
from ..services.timeliness import overdue_payload


router = APIRouter()

DONE_STATUSES = {
    "approved",
    "closed",
    "completed",
    "done",
    "provided",
    "received",
    "resolved",
    "submitted",
    "uploaded",
    "已上传",
    "已关闭",
    "已完成",
    "已提供",
    "已收到",
    "已解决",
    "已提交",
}
ACTIVE_PROJECT_STATUSES = {
    "planning",
    "in_progress",
    "review",
    "active",
    "running",
    "项目准备",
    "项目实施",
    "复核整改",
    "计划中",
    "进行中",
    "正在执行",
}
OPEN_FINDING_STATUSES = {"open", "assigned", "changes_requested", "responded", "retained", "revised", "待处理", "已分派", "保留", "已修订", "待复核"}
RISK_FINDING_STATUSES = OPEN_FINDING_STATUSES | {"returned", "blocked", "退回", "阻塞"}

SYSTEM_KEYWORDS = [
    ("G-ERP", "财务核算", "财务主数据"),
    ("ERP", "财务核算", "财务主数据"),
    ("SAP", "财务核算", "财务主数据"),
    ("U8", "财务核算", "财务主数据"),
    ("iHR", "人员主数据", "人员身份数据"),
    ("HFM", "合并报表", "合并报表数据"),
    ("KSSP", "费用报销", "报销审批数据"),
    ("OA", "审批流", "审批记录"),
    ("MES", "生产执行", "生产订单"),
    ("WMS", "仓储物流", "存货流转数据"),
    ("CRM", "销售与客户", "客户主数据"),
    ("金蝶", "财务核算", "财务凭证"),
    ("数据库", "基础设施", "底层业务数据"),
]


def _is_done(status: str | None) -> bool:
    return str(status or "").lower() in DONE_STATUSES or str(status or "") in DONE_STATUSES


def _workpaper_done(status: str | None) -> bool:
    return str(status or "").lower() in {"approved", "completed", "closed", "done"}


def _is_active_project(status: str | None) -> bool:
    value = str(status or "").strip()
    return value.lower() in ACTIVE_PROJECT_STATUSES or value in ACTIVE_PROJECT_STATUSES


def _visible_projects(db: Session, user: User) -> list[Project]:
    rows = db.execute(select(Project).order_by(Project.id.desc())).scalars().all()
    return [row for row in rows if can_view_project(db, user, row)]


def _date_value(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else "")


def _project_label(project: Project) -> str:
    return project.entity_name or project.name


def _risk_level(high_count: int, medium_count: int, gap_count: int) -> str:
    if high_count > 0 or gap_count >= 5:
        return "高"
    if medium_count > 0 or gap_count > 0:
        return "中"
    return "低"


def _workpaper_percent(rows: list[Workpaper]) -> int:
    if not rows:
        return 0
    return round(sum(1 for row in rows if _workpaper_done(row.status)) / len(rows) * 100)


def _request_percent(rows: list[DocumentRequest]) -> int:
    if not rows:
        return 0
    return round(sum(1 for row in rows if _is_done(row.status)) / len(rows) * 100)


def _project_core(
    project: Project,
    workpapers: list[Workpaper],
    requests: list[DocumentRequest],
    findings: list[ReviewFinding],
    tasks: list[Task],
    review_steps: list[ReviewStep] | None = None,
) -> dict[str, Any]:
    open_findings = [row for row in findings if str(row.status or "").lower() in OPEN_FINDING_STATUSES or row.status in OPEN_FINDING_STATUSES]
    high = sum(1 for row in open_findings if str(row.severity or "").lower() == "high" or row.severity == "高")
    medium = sum(1 for row in open_findings if str(row.severity or "").lower() == "medium" or row.severity == "中")
    pbc_gap_count = sum(1 for row in requests if not _is_done(row.status) and row.required)
    material_overdue_count = sum(1 for row in requests if overdue_payload(row.status, row.due_date).get("is_overdue"))
    step_overdue_count = sum(1 for row in (review_steps or []) if overdue_payload(row.status, row.due_date).get("is_overdue"))
    workpaper_rate = _workpaper_percent(workpapers)
    material_rate = _request_percent(requests)
    task_rate = round(sum(max(0, min(100, int(row.progress or 0))) for row in tasks) / len(tasks)) if tasks else 0
    progress_parts = [value for value in [workpaper_rate, material_rate, task_rate] if value > 0]
    legacy_progress = round(sum(progress_parts) / len(progress_parts)) if progress_parts else workpaper_rate
    monitoring = build_project_monitoring(project, workpapers, findings)
    progress = monitoring["readiness_rate"]
    delivery = delivery_info(project, workpapers)
    monitoring_status = monitoring["status"]
    risk_level = (
        "高"
        if monitoring_status == "red"
        else "中"
        if monitoring_status == "amber"
        else _risk_level(high, medium, pbc_gap_count)
    )
    return {
        "id": project.id,
        "name": project.name,
        "client": _project_label(project),
        "audit_year": project.audit_year,
        "audit_scope": {
            "start": _date_value(project.audit_scope_start),
            "end": _date_value(project.audit_scope_end),
        },
        "stage": project.status,
        "progress": progress,
        "legacy_progress": legacy_progress,
        "material_rate": material_rate,
        "workpaper_rate": monitoring["workpapers"]["preparation_rate"],
        "review_rate": monitoring["workpapers"]["review_rate"],
        "task_rate": task_rate,
        "pbc_gap_count": pbc_gap_count,
        "material_overdue_count": material_overdue_count,
        "step_overdue_count": step_overdue_count,
        "open_finding_count": len(open_findings),
        "high_risk_count": high,
        "risk_level": risk_level,
        "monitoring": monitoring,
        "due_days": delivery.get("due_days"),
        "delivery_date": _date_value(delivery.get("delivery_date")),
        "project_exit_date": _date_value(delivery.get("project_exit_date")),
        "delivery_source": delivery.get("delivery_source", ""),
        "delivery_source_type": delivery.get("delivery_source_type", ""),
        "delivery_source_workpaper_id": delivery.get("delivery_source_workpaper_id"),
        "delivery_source_workpaper_code": delivery.get("delivery_source_workpaper_code", ""),
        "delivery_source_workpaper_name": delivery.get("delivery_source_workpaper_name", ""),
    }


def _rows_by_project(rows: list[Any]) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[int(row.project_id)].append(row)
    return grouped


def _project_findings(db: Session, project_ids: set[int]) -> dict[int, list[ReviewFinding]]:
    grouped: dict[int, list[ReviewFinding]] = defaultdict(list)
    if not project_ids:
        return grouped
    rows = db.execute(
        select(ReviewFinding, ReviewRun)
        .join(ReviewRun, ReviewFinding.run_id == ReviewRun.id)
        .where(ReviewRun.project_id.in_(project_ids))
    ).all()
    for finding, run in rows:
        grouped[int(run.project_id)].append(finding)
    return grouped


@router.get("/api/workflow/dashboard")
def workflow_dashboard(
    activeOnly: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    projects = _visible_projects(db, user)
    # 工作流入口返回当前账号可见的全部项目，不再按项目状态过滤。
    project_ids = {row.id for row in projects}
    supervised_ids = supervised_project_ids(db, user)
    own_only_ids = project_ids - supervised_ids
    workpapers = _rows_by_project(
        db.execute(
            select(Workpaper).where(
                (Workpaper.project_id.in_(supervised_ids))
                | ((Workpaper.project_id.in_(own_only_ids)) & (Workpaper.preparer_user_id == user.id))
            )
        ).scalars().all() if project_ids else []
    )
    requests = _rows_by_project(
        db.execute(select(DocumentRequest).where(DocumentRequest.project_id.in_(project_ids))).scalars().all()
        if project_ids
        else []
    )
    tasks = _rows_by_project(
        db.execute(
            select(Task).where(
                (Task.project_id.in_(supervised_ids))
                | ((Task.project_id.in_(own_only_ids)) & (Task.owner_user_id == user.id))
            )
        ).scalars().all() if project_ids else []
    )
    review_steps = defaultdict(list)
    if project_ids:
        step_rows = db.execute(
            select(ReviewStep, Workpaper)
            .join(Workpaper, ReviewStep.workpaper_id == Workpaper.id)
            .where(
                (Workpaper.project_id.in_(supervised_ids))
                | ((Workpaper.project_id.in_(own_only_ids)) & (Workpaper.preparer_user_id == user.id))
            )
        ).all()
        for step, workpaper in step_rows:
            review_steps[int(workpaper.project_id)].append(step)
    findings = _project_findings(db, project_ids)
    for project_id in own_only_ids:
        findings[project_id] = [row for row in findings.get(project_id, []) if row.assignee_user_id == user.id]
    project_rows = [
        _project_core(
            project,
            workpapers.get(project.id, []),
            requests.get(project.id, []),
            findings.get(project.id, []),
            tasks.get(project.id, []),
            review_steps.get(project.id, []),
        )
        for project in projects
    ]
    open_findings = [item for rows in findings.values() for item in rows if item.status in RISK_FINDING_STATUSES or str(item.status or "").lower() in RISK_FINDING_STATUSES]
    pbc_gap_count = sum(row["pbc_gap_count"] for row in project_rows)
    material_overdue_count = sum(row["material_overdue_count"] for row in project_rows)
    step_overdue_count = sum(row["step_overdue_count"] for row in project_rows)
    returned_count = sum(1 for item in open_findings if str(item.status or "").lower() == "returned" or item.status == "退回")
    high_risk_count = sum(1 for item in open_findings if str(item.severity or "").lower() == "high" or item.severity == "高")
    workpaper_missing_count = sum(row["monitoring"]["workpapers"]["missing_count"] for row in project_rows)
    preparation_gap_count = sum(
        max(
            0,
            row["monitoring"]["workpapers"]["available_count"]
            - row["monitoring"]["workpapers"]["prepared_count"],
        )
        for row in project_rows
    )
    review_gap_count = sum(
        max(
            0,
            row["monitoring"]["workpapers"]["available_count"]
            - row["monitoring"]["workpapers"]["reviewed_count"],
        )
        for row in project_rows
    )
    review_pending_confirmation_count = sum(
        row["monitoring"]["review"]["pending_confirmation_count"] for row in project_rows
    )
    quality_project_ids = {
        project.id
        for project in projects
        if is_admin(user) or user.id in project_reviewer_ids(project)
    }
    pending_confirmation_rows = db.execute(
        select(ReviewFinding, ReviewRun, Project)
        .join(ReviewRun, ReviewFinding.run_id == ReviewRun.id)
        .join(Project, ReviewRun.project_id == Project.id)
        .where(
            ReviewRun.project_id.in_(quality_project_ids),
            ReviewFinding.status == "responded",
        )
        .order_by(ReviewFinding.updated_at.desc(), ReviewFinding.id.desc())
    ).all() if quality_project_ids else []
    pending_finding_ids = [finding.id for finding, _run, _project in pending_confirmation_rows]
    latest_response_by_finding: dict[int, ReviewFindingResponse] = {}
    if pending_finding_ids:
        response_rows = db.execute(
            select(ReviewFindingResponse)
            .where(ReviewFindingResponse.finding_id.in_(pending_finding_ids))
            .order_by(ReviewFindingResponse.finding_id, ReviewFindingResponse.round_no.desc())
        ).scalars().all()
        for response in response_rows:
            latest_response_by_finding.setdefault(response.finding_id, response)
    pending_confirmations = []
    for finding, _run, project in pending_confirmation_rows:
        response = latest_response_by_finding.get(finding.id)
        pending_confirmations.append(
            {
                "finding_id": finding.id,
                "project_id": project.id,
                "project_name": project.name,
                "issue_no": finding.issue_no,
                "issue": finding.issue,
                "workpaper": finding.workpaper_file or finding.target,
                "review_stage": finding.review_stage,
                "responder_name": response.responder.display_name if response and response.responder else "项目组成员",
                "response_text": response.response_text if response else finding.project_reply,
                "responded_at": _date_value(response.created_at if response else finding.updated_at),
            }
        )
    alerts = []
    for item in pending_confirmations:
        alerts.append(
            {
                "project_id": item["project_id"],
                "project_name": item["project_name"],
                "finding_id": item["finding_id"],
                "level": "high",
                "priority": 0,
                "code": "review_response_waiting_confirmation",
                "title": f"{item['responder_name']}已回复，待质控确认解决",
                "detail": item["issue"][:120],
            }
        )
    for row in project_rows:
        for blocker in row["monitoring"]["blockers"][:3]:
            if blocker["code"] == "review_pending_confirmation" and row["id"] in quality_project_ids:
                continue
            alerts.append(
                {
                    "project_id": row["id"],
                    "project_name": row["name"],
                    "level": blocker["level"],
                    "priority": 1 if blocker["level"] == "high" else 2,
                    "code": blocker["code"],
                    "title": blocker["message"],
                    "detail": row["monitoring"]["next_action"],
                }
            )
    alerts.sort(key=lambda item: (item.get("priority", 2), item["project_id"]))
    templates = db.execute(
        select(WorkpaperTemplate).where(WorkpaperTemplate.default_enabled == True).order_by(WorkpaperTemplate.sort_order)  # noqa: E712
    ).scalars().all()
    return {
        "metrics": {
            "visible_projects": len(project_rows),
            "pbc_gap_count": pbc_gap_count,
            "material_overdue_count": material_overdue_count,
            "step_overdue_count": step_overdue_count,
            "returned_count": returned_count,
            "high_risk_count": high_risk_count,
            "workpaper_missing_count": workpaper_missing_count,
            "preparation_gap_count": preparation_gap_count,
            "review_gap_count": review_gap_count,
            "review_pending_confirmation_count": review_pending_confirmation_count,
            "blocked_project_count": sum(1 for row in project_rows if row["monitoring"]["status"] == "red"),
        },
        "projects": project_rows[:20],
        "pending_confirmations": pending_confirmations[:20],
        "alerts": alerts[:12],
        "todos": [
            {
                "id": row.id,
                "severity": row.severity,
                "status": row.status,
                "title": row.issue[:80],
                "target": row.target,
                "due_date": _date_value(row.due_date),
            }
            for row in open_findings[:8]
        ],
        "template_updates": [
            {
                "code": row.code,
                "name": row.name,
                "version": row.version,
                "applicable_year": row.applicable_year,
                "update_note": row.update_note,
            }
            for row in templates[:8]
        ],
    }


@router.get("/api/projects/{project_id}/workflow-summary")
def project_workflow_summary(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        return {}
    ensure_project_viewer(db, project, user)
    supervised = project.id in supervised_project_ids(db, user)
    workpaper_stmt = select(Workpaper).where(Workpaper.project_id == project_id)
    if not supervised:
        workpaper_stmt = workpaper_stmt.where(Workpaper.preparer_user_id == user.id)
    workpapers = db.execute(workpaper_stmt).scalars().all()
    requests = db.execute(select(DocumentRequest).where(DocumentRequest.project_id == project_id)).scalars().all()
    task_stmt = select(Task).where(Task.project_id == project_id)
    if not supervised:
        task_stmt = task_stmt.where(Task.owner_user_id == user.id)
    tasks = db.execute(task_stmt).scalars().all()
    review_steps = db.execute(
        select(ReviewStep)
        .join(Workpaper, ReviewStep.workpaper_id == Workpaper.id)
        .where(Workpaper.project_id == project_id)
    ).scalars().all()
    findings = _project_findings(db, {project_id}).get(project_id, [])
    if not supervised:
        own_workpaper_ids = {row.id for row in workpapers}
        review_steps = [row for row in review_steps if row.workpaper_id in own_workpaper_ids]
        findings = [row for row in findings if row.assignee_user_id == user.id]
    member_stmt = select(ProjectMember).where(ProjectMember.project_id == project_id)
    if not supervised:
        member_stmt = member_stmt.where(ProjectMember.user_id == user.id)
    members = db.execute(member_stmt).scalars().all()
    summary = _project_core(project, workpapers, requests, findings, tasks, review_steps)
    summary["members"] = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "name": row.user.display_name if row.user else "",
            "role": row.role_on_project,
            "module": row.module,
            "workload": row.workload,
        }
        for row in members
    ]
    summary["leaders"] = {
        "project_leader": project.project_leader.display_name if project.project_leader else "",
        "manager": project.manager.display_name if project.manager else "",
        "quality_reviewer": project.quality_reviewer.display_name if project.quality_reviewer else "",
        "field_leader": project.field_leader.display_name if project.field_leader else "",
        "director": project.director.display_name if project.director else "",
        "partner": project.partner.display_name if project.partner else "",
        "first_partner": project.first_partner_name,
        "second_partner": project.second_partner_name,
    }
    return summary


@router.get("/api/projects/{project_id}/scope-items")
def project_scope_items(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        return {"items": []}
    ensure_project_viewer(db, project, user)
    text_rows = [project.name, project.entity_name, project.project_root, project.description]
    text_rows.extend(row.name + " " + row.file_path for row in db.execute(select(Workpaper).where(Workpaper.project_id == project_id)).scalars())
    text_rows.extend(row.title + " " + row.file_path for row in db.execute(select(Attachment).where(Attachment.project_id == project_id)).scalars())
    text_rows.extend(row.title + " " + row.direction for row in db.execute(select(DocumentRequest).where(DocumentRequest.project_id == project_id)).scalars())
    haystack = "\n".join(text_rows)
    items = []
    for keyword, process, sensitivity in SYSTEM_KEYWORDS:
        if keyword.lower() not in haystack.lower():
            continue
        risk = "高" if keyword in {"HFM", "数据库"} else "中" if keyword in {"ERP", "G-ERP", "SAP", "金蝶", "MES"} else "低"
        items.append(
            {
                "system_name": keyword,
                "system_type": "应用系统" if keyword != "数据库" else "基础设施",
                "owner": "",
                "business_process": process,
                "in_scope": True,
                "scope_reason": "从项目底稿、附件或资料清单名称中识别，需项目经理确认",
                "risk_level": risk,
                "confidence": 70 if keyword == "数据库" else 78,
                "data_sensitivity": sensitivity,
                "dependencies": "",
                "source": "derived_from_existing_records",
                "manager_confirmed": False,
            }
        )
    if not items:
        items.append(
            {
                "system_name": "待识别系统范围",
                "system_type": "",
                "owner": "",
                "business_process": "",
                "in_scope": False,
                "scope_reason": "现有项目资料中未识别到明确系统名称",
                "risk_level": "待评估",
                "confidence": 0,
                "data_sensitivity": "",
                "dependencies": "",
                "source": "not_available",
                "manager_confirmed": False,
            }
        )
    return {"project_id": project_id, "items": items}


@router.get("/api/projects/{project_id}/pbc-gaps")
def project_pbc_gaps(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        return {"items": []}
    ensure_project_viewer(db, project, user)
    rows = db.execute(select(DocumentRequest).where(DocumentRequest.project_id == project_id).order_by(DocumentRequest.id)).scalars().all()
    items = []
    for row in rows:
        data = obj_dict(row)
        data["is_gap"] = row.required and not _is_done(row.status)
        data["gap_reason"] = "" if not data["is_gap"] else "资料未收到或状态未关闭"
        items.append(data)
    return {
        "project_id": project_id,
        "total": len(items),
        "gap_count": sum(1 for item in items if item["is_gap"]),
        "items": items,
    }


@router.get("/api/projects/{project_id}/workpaper-execution-summary")
def project_workpaper_execution_summary(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        return {"items": []}
    ensure_project_viewer(db, project, user)
    supervised = project.id in supervised_project_ids(db, user)
    workpaper_stmt = select(Workpaper).where(Workpaper.project_id == project_id).order_by(Workpaper.stage, Workpaper.code)
    if not supervised:
        workpaper_stmt = workpaper_stmt.where(Workpaper.preparer_user_id == user.id)
    workpapers = db.execute(workpaper_stmt).scalars().all()
    workpaper_ids = {row.id for row in workpapers}
    attachment_counts = Counter(
        dict(
            db.execute(
                select(Attachment.workpaper_id, func.count(Attachment.id))
                .where(Attachment.project_id == project_id, Attachment.workpaper_id.in_(workpaper_ids))
                .group_by(Attachment.workpaper_id)
            ).all()
        )
    )
    finding_rows = db.execute(
        select(ReviewFinding, ReviewRun)
        .join(ReviewRun, ReviewFinding.run_id == ReviewRun.id)
        .where(ReviewRun.project_id == project_id)
    ).all()
    finding_counts: Counter[int] = Counter()
    for finding, _run in finding_rows:
        if not supervised and finding.assignee_user_id != user.id:
            continue
        if finding.workpaper_id in workpaper_ids:
            finding_counts[finding.workpaper_id] += 1
            continue
        target = str(finding.target or "")
        for workpaper in workpapers:
            if workpaper.code and workpaper.code in target:
                finding_counts[workpaper.id] += 1
                break
    items = []
    for row in workpapers:
        data = obj_dict(row)
        monitor = workpaper_monitor_item(row)
        data["preparer_name"] = row.preparer.display_name if row.preparer else ""
        data["attachment_count"] = int(attachment_counts.get(row.id, 0))
        data["finding_count"] = int(finding_counts.get(row.id, 0))
        data["is_done"] = _workpaper_done(row.status)
        data["monitoring"] = monitor
        items.append(data)
    available_count = sum(1 for item in items if item["monitoring"]["file_exists"])
    prepared_count = sum(1 for item in items if item["monitoring"]["preparation_complete"])
    reviewed_count = sum(1 for item in items if item["monitoring"]["review_complete"])
    return {
        "project_id": project_id,
        "total": len(items),
        "done_count": sum(1 for item in items if item["is_done"]),
        "available_count": available_count,
        "missing_count": max(0, len(items) - available_count),
        "prepared_count": prepared_count,
        "reviewed_count": reviewed_count,
        "execution_rate": round(prepared_count / len(items) * 100) if items else 0,
        "review_rate": round(reviewed_count / len(items) * 100) if items else 0,
        "items": items,
    }
