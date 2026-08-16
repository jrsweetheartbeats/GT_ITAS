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
from sqlalchemy import func, or_, select
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
    ensure_manager_or_above,
    ensure_project_editor,
    ensure_project_viewer,
    get_setting,
    hash_password,
    is_admin,
    is_manager_or_above,
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
    WorkpaperTreeNodeOut,
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
from ..services.project_scope import infer_audit_scope_from_workpapers
from ..services.projects import copy_workpaper_file, replace_audit_year, seed_project_template_workpapers
from ..services.review import add_finding, run_external_rules, run_internal_review
from ..services.delivery_deadline import delivery_info
from ..services.workpaper_reader import build_workpaper_tree


router = APIRouter()


@router.get("/api/projects")
def list_projects(
    status: Optional[str] = Query(default=None),
    activeOnly: bool = Query(default=False),
    includeDelivery: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    stmt = select(Project).order_by(Project.id.desc())
    if activeOnly:
        stmt = stmt.where(Project.status.in_(["in_progress", "active", "running", "进行中", "正在执行"]))
    elif status:
        stmt = stmt.where(Project.status == status)
    rows = db.execute(stmt).scalars().all()
    if not is_manager_or_above(user):
        rows = [row for row in rows if can_view_project(db, user, row)]
    project_ids = {row.id for row in rows}
    member_counts = dict(
        db.execute(select(ProjectMember.project_id, func.count(ProjectMember.id)).group_by(ProjectMember.project_id)).all()
    )
    workpaper_counts = dict(
        db.execute(select(Workpaper.project_id, func.count(Workpaper.id)).group_by(Workpaper.project_id)).all()
    )
    attachment_counts = dict(
        db.execute(select(Attachment.project_id, func.count(Attachment.id)).group_by(Attachment.project_id)).all()
    )
    task_counts = dict(db.execute(select(Task.project_id, func.count(Task.id)).group_by(Task.project_id)).all())
    delivery_workpapers: dict[int, list[Workpaper]] = {}
    if includeDelivery and project_ids:
        delivery_rows = db.execute(
            select(Workpaper).where(
                Workpaper.project_id.in_(project_ids),
                or_(Workpaper.code.like("B60-2-3%"), Workpaper.name.like("%计划备忘录%")),
            )
        ).scalars().all()
        for workpaper in delivery_rows:
            delivery_workpapers.setdefault(workpaper.project_id, []).append(workpaper)
    payload = []
    for row in rows:
        data = obj_dict(row)
        delivery = delivery_info(row, delivery_workpapers.get(row.id, [])) if includeDelivery else {}
        data["manager_name"] = row.manager.display_name if row.manager else ""
        data["project_leader_name"] = row.project_leader.display_name if row.project_leader else ""
        data["quality_reviewer_name"] = row.quality_reviewer.display_name if row.quality_reviewer else ""
        data["field_leader_name"] = row.field_leader.display_name if row.field_leader else ""
        data["client_name"] = row.client.entity_name if row.client else ""
        data["member_count"] = int(member_counts.get(row.id, 0))
        data["workpaper_count"] = int(workpaper_counts.get(row.id, 0))
        data["attachment_count"] = int(attachment_counts.get(row.id, 0))
        data["task_count"] = int(task_counts.get(row.id, 0))
        data["can_edit"] = can_edit_project(user, row)
        if includeDelivery:
            data["due_days"] = delivery.get("due_days")
            data["delivery_date"] = delivery.get("delivery_date").isoformat() if delivery.get("delivery_date") else ""
            data["project_exit_date"] = delivery.get("project_exit_date").isoformat() if delivery.get("project_exit_date") else ""
            data["delivery_source"] = delivery.get("delivery_source", "")
            data["delivery_source_type"] = delivery.get("delivery_source_type", "")
            data["delivery_source_workpaper_id"] = delivery.get("delivery_source_workpaper_id")
            data["delivery_source_workpaper_code"] = delivery.get("delivery_source_workpaper_code", "")
            data["delivery_source_workpaper_name"] = delivery.get("delivery_source_workpaper_name", "")
        payload.append(data)
    return payload


@router.post("/api/projects", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_manager_or_above(user)
    ensure_feature_permission(db, user, "projects", "edit")
    payload = body.model_dump()
    if payload.get("client_id"):
        client = get_or_404(db, Client, payload["client_id"], "客户")
        payload["entity_name"] = payload.get("entity_name") or client.entity_name
    if not payload.get("audit_scope_start") or not payload.get("audit_scope_end"):
        start, end = default_audit_scope()
        payload["audit_scope_start"] = payload.get("audit_scope_start") or start
        payload["audit_scope_end"] = payload.get("audit_scope_end") or end
    item = Project(**payload, creator_user_id=user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    template_count = seed_project_template_workpapers(db, item)
    db.commit()
    data = obj_dict(item)
    data["template_workpapers_created"] = template_count
    return data


@router.patch("/api/projects/{project_id}")
def update_project(project_id: int, body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    item = get_or_404(db, Project, project_id, "项目")
    ensure_manager_or_above(user)
    ensure_feature_permission(db, user, "projects", "edit")
    ensure_project_editor(item, user)
    payload = body.model_dump()
    if payload.get("client_id"):
        client = get_or_404(db, Client, payload["client_id"], "客户")
        payload["entity_name"] = payload.get("entity_name") or client.entity_name
    apply_patch_to_model(item, payload)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.post("/api/projects/{project_id}/audit-scope/infer")
def infer_project_audit_scope(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    item = get_or_404(db, Project, project_id, "项目")
    ensure_feature_permission(db, user, "projects", "edit")
    ensure_project_editor(item, user)
    workpapers = db.execute(select(Workpaper).where(Workpaper.project_id == project_id).order_by(Workpaper.code)).scalars().all()
    inferred = infer_audit_scope_from_workpapers(workpapers)
    if not inferred:
        raise HTTPException(status_code=404, detail="未从底稿首页识别到截止日或审计期间")
    item.audit_year = inferred.audit_year
    item.audit_scope_start = inferred.start
    item.audit_scope_end = inferred.end
    db.commit()
    db.refresh(item)
    data = obj_dict(item)
    data["audit_scope_source"] = inferred.source
    data["audit_scope_raw_value"] = inferred.raw_value
    return data


@router.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    item = get_or_404(db, Project, project_id, "项目")
    ensure_feature_permission(db, user, "projects", "manage")
    ensure_project_editor(item, user)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.get("/api/projects/{project_id}/contacts")
def list_contacts(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    rows = db.execute(
        select(EnterpriseContact).where(EnterpriseContact.project_id == project_id).order_by(EnterpriseContact.id)
    ).scalars().all()
    return list_dict(rows)


@router.post("/api/projects/{project_id}/contacts", status_code=201)
def create_contact(project_id: int, body: ContactIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_feature_permission(db, user, "projects", "edit")
    ensure_project_editor(project, user)
    item = EnterpriseContact(project_id=project_id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    item = get_or_404(db, EnterpriseContact, contact_id, "对接人")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_feature_permission(db, user, "projects", "edit")
    ensure_project_editor(project, user)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.get("/api/projects/{project_id}/members")
def list_members(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    rows = db.execute(
        select(ProjectMember).where(ProjectMember.project_id == project_id).order_by(ProjectMember.id)
    ).scalars().all()
    payload = []
    for row in rows:
        data = obj_dict(row)
        data["display_name"] = row.user.display_name
        data["username"] = row.user.username
        data["role_name"] = row.user.role.name if row.user.role else ""
        payload.append(data)
    return payload


@router.get("/api/projects/{project_id}/workpaper-tree", response_model=list[WorkpaperTreeNodeOut])
def get_project_workpaper_tree(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == project_id).order_by(Workpaper.stage, Workpaper.code)
    ).scalars().all()
    attachments = db.execute(
        select(Attachment).where(Attachment.project_id == project_id).order_by(Attachment.index_no, Attachment.id)
    ).scalars().all()
    return build_workpaper_tree(workpapers, attachments)


@router.post("/api/projects/{project_id}/members", status_code=201)
def create_member(project_id: int, body: MemberIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_manager_or_above(user)
    ensure_feature_permission(db, user, "projects", "edit")
    ensure_project_editor(project, user)
    get_or_404(db, User, body.user_id, "用户")
    item = ProjectMember(project_id=project_id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/members/{member_id}", status_code=204)
def delete_member(member_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    item = get_or_404(db, ProjectMember, member_id, "项目成员")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_manager_or_above(user)
    ensure_feature_permission(db, user, "projects", "edit")
    ensure_project_editor(project, user)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.get("/api/tasks")
def list_tasks(
    projectId: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    stmt = select(Task).order_by(Task.id)
    if projectId is not None:
        stmt = stmt.where(Task.project_id == projectId)
    rows = db.execute(stmt).scalars().all()
    project_ids = {row.project_id for row in rows}
    projects_by_id = {
        row.id: row
        for row in db.execute(select(Project).where(Project.id.in_(project_ids))).scalars().all()
    } if project_ids else {}
    visible_projects = {project_id for project_id, project in projects_by_id.items() if can_view_project(db, user, project)}
    payload = []
    for row in rows:
        if row.project_id not in visible_projects:
            continue
        data = obj_dict(row)
        data["owner_name"] = row.owner.display_name if row.owner else ""
        project = projects_by_id.get(row.project_id)
        data["project_name"] = project.name if project else ""
        data["entity_name"] = project.entity_name if project else ""
        payload.append(data)
    return payload


@router.post("/api/tasks", status_code=201)
def create_task(body: TaskIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    project = get_or_404(db, Project, body.project_id, "项目")
    ensure_feature_permission(db, user, "resourcePlan", "edit")
    ensure_project_editor(project, user)
    item = Task(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.patch("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    item = get_or_404(db, Task, task_id, "任务")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_feature_permission(db, user, "resourcePlan", "edit")
    ensure_project_editor(project, user)
    apply_patch_to_model(item, body.model_dump())
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    item = get_or_404(db, Task, task_id, "任务")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_feature_permission(db, user, "resourcePlan", "edit")
    ensure_project_editor(project, user)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/api/projects/{project_id}/init-from-prior")
def init_from_prior(
    project_id: int,
    body: InitFromPriorIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    prior_id = body.prior_project_id or project.prior_project_id
    if not prior_id:
        raise HTTPException(status_code=400, detail="未指定以前年度项目")
    prior = get_or_404(db, Project, prior_id, "以前年度项目")

    prior_workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == prior.id).order_by(Workpaper.id)
    ).scalars().all()
    created = 0
    copied_files = 0
    for old in prior_workpapers:
        new_name, name_changed = replace_audit_year(old.name, prior.audit_year, project.audit_year)
        new_file_path = ""
        if body.copy_files:
            new_file_path = copy_workpaper_file(old.file_path, project, new_name, prior.audit_year)
            copied_files += 1 if new_file_path else 0
        item = Workpaper(
            project_id=project.id,
            code=old.code,
            name=new_name,
            stage=old.stage,
            file_path=new_file_path or old.file_path,
            source_workpaper_id=old.id,
            status="draft",
            preparer_user_id=old.preparer_user_id,
            year_updated=name_changed,
            extracted_fields_json=old.extracted_fields_json,
        )
        db.add(item)
        created += 1
    db.commit()
    return {"created_workpapers": created, "copied_files": copied_files}
