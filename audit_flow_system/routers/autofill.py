from __future__ import annotations

from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import uuid
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
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
    current_user,
    default_audit_scope,
    ensure_document_uploader,
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
    AutofillRuleActionIn,
    AutofillRuleActionPatchIn,
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
    ReviewDecisionIn,
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
from ..services.autofill import (
    DEFAULT_AUTOFILL_ALLOWED_FIELD_KEYS,
    autofill_plan,
    autofill_rules_payload,
    autofill_suggestions,
    filter_plan_by_allowed_fields,
    filter_suggestions_by_allowed_fields,
)
from ..services.autofill_rule_actions import (
    action_to_summary,
    list_project_rule_actions,
    patch_project_rule_action,
    upsert_project_rule_action,
)
from ..services.autofill_rule_inspector import inspect_autofill_rules, inspect_project_autofill_rules
from ..services.projects import copy_workpaper_file, replace_audit_year, seed_project_template_workpapers
from ..services.review import add_finding, run_external_rules, run_internal_review
from ..services.rule_exporter import build_rule_inspection_export
from ..services.autofill_rule_visualization import build_autofill_rule_visualization, build_rule_visualization_export
from ..services.rule_manual_corrections import (
    apply_approved_manual_corrections_to_plan,
    apply_manual_corrections_to_payload,
    correction_to_summary,
    create_import_batch,
    get_import_batch,
    import_batch_to_summary,
    list_import_batches,
    list_project_manual_corrections,
    run_import_batch,
    update_correction_status,
)


router = APIRouter()


@router.get("/api/autofill-rules")
def list_autofill_rules(user: User = Depends(current_user)) -> dict[str, Any]:
    return autofill_rules_payload()


@router.get("/api/autofill-rule-inspection")
def inspect_autofill_rule_definitions(user: User = Depends(current_user)) -> dict[str, Any]:
    return inspect_autofill_rules()


@router.get("/api/projects/{project_id}/autofill-suggestions")
def list_autofill_suggestions(
    project_id: int,
    scope: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    attachments = db.execute(
        select(Attachment).where(Attachment.project_id == project.id).order_by(Attachment.index_no)
    ).scalars().all()
    allowed_keys = get_setting(db, "autofill_allowed_field_keys", DEFAULT_AUTOFILL_ALLOWED_FIELD_KEYS)
    all_suggestions = autofill_suggestions(list_dict(attachments), scope)
    suggestions = filter_suggestions_by_allowed_fields(all_suggestions, allowed_keys)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "attachment_count": len(attachments),
        "suggestion_count": len(suggestions),
        "scope_filtered_count": max(0, len(all_suggestions) - len(suggestions)),
        "suggestions": suggestions,
    }


@router.get("/api/projects/{project_id}/autofill-rule-inspection")
def inspect_project_autofill_rule_definitions(
    project_id: int,
    include_template_scan: bool = Query(default=False, alias="includeTemplateScan"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    attachments = db.execute(
        select(Attachment).where(Attachment.project_id == project.id).order_by(Attachment.index_no)
    ).scalars().all()
    workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)
    ).scalars().all()
    payload = inspect_project_autofill_rules(
        list_dict(workpapers),
        list_dict(attachments),
        include_template_scan=include_template_scan,
    )
    payload["project_id"] = project.id
    payload["project_name"] = project.name
    apply_manual_corrections_to_payload(payload, list_project_manual_corrections(db, project.id))
    return payload


@router.get("/api/projects/{project_id}/autofill-rule-inspection/export")
def export_project_autofill_rule_definitions(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    attachments = db.execute(
        select(Attachment).where(Attachment.project_id == project.id).order_by(Attachment.index_no)
    ).scalars().all()
    workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)
    ).scalars().all()
    payload = inspect_project_autofill_rules(list_dict(workpapers), list_dict(attachments))
    payload["project_id"] = project.id
    payload["project_name"] = project.name
    apply_manual_corrections_to_payload(payload, list_project_manual_corrections(db, project.id))
    content = build_rule_inspection_export(payload)
    filename = f"底稿填写规则_{project.name or project.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/api/projects/{project_id}/autofill-rule-visualization")
def get_project_autofill_rule_visualization(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    return build_autofill_rule_visualization(db, project, list_project_manual_corrections(db, project.id))


@router.get("/api/projects/{project_id}/autofill-rule-actions")
def list_project_autofill_rule_actions(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    actions = list_project_rule_actions(db, project.id)
    return {
        "project_id": project.id,
        "actions": [action_to_summary(item) for item in actions],
    }


@router.post("/api/projects/{project_id}/autofill-rule-actions")
def upsert_project_autofill_rule_action(
    project_id: int,
    body: AutofillRuleActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    action = upsert_project_rule_action(
        db,
        project_id=project.id,
        user=user,
        payload=body.model_dump(),
    )
    return {"project_id": project.id, "action": action_to_summary(action)}


@router.patch("/api/projects/{project_id}/autofill-rule-actions/{action_id}")
def patch_project_autofill_rule_action(
    project_id: int,
    action_id: int,
    body: AutofillRuleActionPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    action = patch_project_rule_action(
        db,
        project_id=project.id,
        action_id=action_id,
        user=user,
        payload=body.model_dump(exclude_unset=True),
    )
    if not action:
        raise HTTPException(status_code=404, detail="处理状态不存在")
    return {"project_id": project.id, "action": action_to_summary(action)}


@router.get("/api/projects/{project_id}/autofill-rule-visualization/export")
def export_project_autofill_rule_visualization(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    payload = build_autofill_rule_visualization(db, project, list_project_manual_corrections(db, project.id))
    content = build_rule_visualization_export(payload)
    filename = f"底稿填写规则可视化_{project.name or project.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/api/projects/{project_id}/autofill-rule-inspection/import-corrections")
async def import_project_autofill_rule_corrections(
    project_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可导入规则人工修正")
    project = get_or_404(db, Project, project_id, "项目")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    safe_name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", file.filename or "manual_corrections.xlsx")
    upload_dir = BASE_DIR / "data" / "rule_manual_correction_imports"
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}_{safe_name}"
    upload_path.write_bytes(content)
    batch = create_import_batch(
        db,
        project_id=project.id,
        user=user,
        filename=file.filename or "",
        file_path=str(upload_path),
    )
    background_tasks.add_task(run_import_batch, batch.id)
    return {"batch_id": batch.id, "status": batch.status, "filename": batch.filename}


@router.get("/api/projects/{project_id}/autofill-rule-inspection/imports")
def list_project_autofill_rule_correction_imports(
    project_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    rows = list_import_batches(db, project.id, limit=limit)
    return {"project_id": project.id, "imports": [import_batch_to_summary(item) for item in rows]}


@router.get("/api/projects/{project_id}/autofill-rule-inspection/imports/{batch_id}")
def get_project_autofill_rule_correction_import(
    project_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    batch = get_import_batch(db, project.id, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return import_batch_to_summary(batch)


@router.post("/api/projects/{project_id}/autofill-rule-inspection/corrections/{correction_id}/approve")
def approve_project_autofill_rule_correction(
    project_id: int,
    correction_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可审批规则人工修正")
    project = get_or_404(db, Project, project_id, "项目")
    item = update_correction_status(
        db,
        project_id=project.id,
        correction_id=correction_id,
        user=user,
        status="approved",
    )
    if not item:
        raise HTTPException(status_code=404, detail="人工修正不存在")
    return {"correction": correction_to_summary(item)}


@router.post("/api/projects/{project_id}/autofill-rule-inspection/corrections/{correction_id}/reject")
def reject_project_autofill_rule_correction(
    project_id: int,
    correction_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可驳回规则人工修正")
    project = get_or_404(db, Project, project_id, "项目")
    item = update_correction_status(
        db,
        project_id=project.id,
        correction_id=correction_id,
        user=user,
        status="rejected",
    )
    if not item:
        raise HTTPException(status_code=404, detail="人工修正不存在")
    return {"correction": correction_to_summary(item)}


@router.post("/api/projects/{project_id}/autofill-plan")
def create_autofill_plan(
    project_id: int,
    body: AutofillPlanIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    if body.apply:
        raise HTTPException(status_code=400, detail="真实底稿写回当前禁用；请仅使用 dry-run 预览或测试副本验证入口")
    attachments = db.execute(
        select(Attachment).where(Attachment.project_id == project.id).order_by(Attachment.index_no)
    ).scalars().all()
    workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)
    ).scalars().all()
    allowed_keys = get_setting(db, "autofill_allowed_field_keys", DEFAULT_AUTOFILL_ALLOWED_FIELD_KEYS)
    all_suggestions = autofill_suggestions(list_dict(attachments), body.scope)
    suggestions = filter_suggestions_by_allowed_fields(all_suggestions, allowed_keys)
    project_context = obj_dict(project)
    contacts = db.execute(
        select(EnterpriseContact).where(EnterpriseContact.project_id == project.id).order_by(EnterpriseContact.id)
    ).scalars().all()
    members = db.execute(
        select(ProjectMember).where(ProjectMember.project_id == project.id).order_by(ProjectMember.id)
    ).scalars().all()
    project_context["contacts"] = list_dict(contacts)
    project_context["members"] = [
        {
            **obj_dict(member),
            "username": member.user.username if member.user else "",
            "display_name": member.user.display_name if member.user else "",
            "email": member.user.email if member.user else "",
        }
        for member in members
    ]
    plan = autofill_plan(
        suggestions,
        list_dict(workpapers),
        project_context,
        body.apply,
    )
    raw_plan_count = len(plan)
    plan = filter_plan_by_allowed_fields(plan, allowed_keys)
    corrections = list_project_manual_corrections(db, project.id)
    apply_approved_manual_corrections_to_plan(plan, corrections)
    summary = {
        "planned": sum(1 for item in plan if item.get("status") == "planned"),
        "changed": sum(1 for item in plan if item.get("status") == "changed"),
        "unchanged": sum(1 for item in plan if item.get("status") == "unchanged"),
        "skipped": sum(1 for item in plan if item.get("status") == "skipped"),
        "blocked": sum(1 for item in plan if item.get("status") == "blocked"),
        "manual_correction_approved": sum(
            1 for item in plan if item.get("value_source") == "manual_correction_approved"
        ),
        "manual_correction_conflict": sum(
            1 for item in plan if item.get("value_source") == "manual_correction_conflict"
        ),
        "scope_filtered": max(0, raw_plan_count - len(plan)),
    }
    run = AutofillRun(
        project_id=project.id,
        scope=body.scope or "",
        apply=body.apply,
        status="completed",
        suggestion_count=len(suggestions),
        workpaper_count=len(workpapers),
        plan_count=len(plan),
        planned_count=summary["planned"],
        changed_count=summary["changed"],
        unchanged_count=summary["unchanged"],
        skipped_count=summary["skipped"],
        blocked_count=summary["blocked"],
        summary=(
            f"{'写回' if body.apply else '预览'}完成：计划 {summary['planned']}，变更 {summary['changed']}，"
            f"不变 {summary['unchanged']}，跳过 {summary['skipped']}，阻塞 {summary['blocked']}"
        ),
    )
    db.add(run)
    db.flush()
    for item in plan:
        db.add(
            AutofillPlanItem(
                run_id=run.id,
                rule_id=str(item.get("rule_id") or ""),
                scope=str(item.get("scope") or ""),
                workbook_path=str(item.get("workbook_path") or ""),
                sheet_name=str(item.get("sheet_name") or ""),
                field=str(item.get("field") or ""),
                locator=str(item.get("locator") or ""),
                cell=str(item.get("cell") or ""),
                old_value=str(item.get("old_value") or ""),
                new_value=str(item.get("new_value") or ""),
                value_source=str(item.get("value_source") or "rule"),
                manual_correction_id=item.get("manual_correction_id") or None,
                original_rule_value=str(item.get("original_rule_value") or ""),
                status=str(item.get("status") or ""),
                message=str(item.get("message") or ""),
            )
        )
    db.commit()
    db.refresh(run)
    return {
        "run_id": run.id,
        "project_id": project.id,
        "project_name": project.name,
        "apply": body.apply,
        "suggestion_count": len(suggestions),
        "scope_filtered_count": max(0, len(all_suggestions) - len(suggestions)),
        "workpaper_count": len(workpapers),
        "plan_count": len(plan),
        "summary": summary,
        "plan": plan,
    }


@router.get("/api/autofill-runs")
def list_autofill_runs(
    projectId: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    stmt = select(AutofillRun).order_by(AutofillRun.id.desc()).limit(50)
    if projectId is not None:
        stmt = select(AutofillRun).where(AutofillRun.project_id == projectId).order_by(AutofillRun.id.desc()).limit(50)
    rows = db.execute(stmt).scalars().all()
    return list_dict(rows)


@router.get("/api/autofill-runs/{run_id}/items")
def list_autofill_run_items(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    get_or_404(db, AutofillRun, run_id, "自动填写记录")
    rows = db.execute(
        select(AutofillPlanItem).where(AutofillPlanItem.run_id == run_id).order_by(AutofillPlanItem.id)
    ).scalars().all()
    return list_dict(rows)
