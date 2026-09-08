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
from sqlalchemy import and_, func, or_, select
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
    ensure_workpaper_viewer,
    get_setting,
    hash_password,
    is_admin,
    normalize_module_order,
    require_admin,
    set_setting,
    validate_password_policy,
    visible_project_ids,
    supervised_project_ids,
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


router = APIRouter()


@router.get("/api/attachments/next-index")
def get_next_attachment_index(
    projectId: int,
    workpaperCode: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    project = get_or_404(db, Project, projectId, "项目")
    ensure_project_viewer(db, project, user)
    return {"index_no": next_attachment_index(db, projectId, workpaperCode)}


@router.get("/api/attachments")
def list_attachments(
    projectId: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    visible_ids = visible_project_ids(db, user)
    if not visible_ids:
        return []
    stmt = select(Attachment).where(Attachment.project_id.in_(visible_ids)).order_by(Attachment.index_no)
    if projectId is not None:
        project = get_or_404(db, Project, projectId, "项目")
        ensure_project_viewer(db, project, user)
        stmt = stmt.where(Attachment.project_id == projectId)
    return list_dict(db.execute(stmt).scalars().all())


@router.post("/api/attachments", status_code=201)
def create_attachment(body: AttachmentIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    project = get_or_404(db, Project, body.project_id, "项目")
    ensure_document_uploader(db, project, user)
    payload = body.model_dump()
    if payload.get("workpaper_id"):
        workpaper = get_or_404(db, Workpaper, payload["workpaper_id"], "底稿")
        if workpaper.project_id != project.id:
            raise HTTPException(status_code=400, detail="附件关联底稿不属于当前项目")
        ensure_workpaper_viewer(db, project, workpaper, user)
    elif project.id not in supervised_project_ids(db, user):
        raise HTTPException(status_code=403, detail="项目成员上传附件时必须关联本人编制的底稿")
    if not payload["index_no"]:
        code = ""
        if payload.get("workpaper_id"):
            wp = db.get(Workpaper, payload["workpaper_id"])
            code = wp.code if wp else ""
        payload["index_no"] = next_attachment_index(db, payload["project_id"], code)
    duplicate = db.execute(
        select(Attachment).where(
            Attachment.project_id == payload["project_id"],
            Attachment.index_no == payload["index_no"],
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="附件索引号已存在")
    item = Attachment(**payload, uploaded_by_user_id=user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.patch("/api/attachments/{attachment_id}")
def update_attachment(
    attachment_id: int,
    body: AttachmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    item = get_or_404(db, Attachment, attachment_id, "附件")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_document_uploader(db, project, user)
    current_workpaper = db.get(Workpaper, item.workpaper_id) if item.workpaper_id else None
    if current_workpaper is not None:
        ensure_workpaper_viewer(db, project, current_workpaper, user)
    elif project.id not in supervised_project_ids(db, user):
        raise HTTPException(status_code=403, detail="项目成员不能维护项目级公共附件")
    payload = body.model_dump()
    if payload["project_id"] != item.project_id:
        raise HTTPException(status_code=400, detail="附件不能通过编辑转移到其他项目")
    if payload.get("workpaper_id"):
        target_workpaper = get_or_404(db, Workpaper, payload["workpaper_id"], "底稿")
        if target_workpaper.project_id != project.id:
            raise HTTPException(status_code=400, detail="附件关联底稿不属于当前项目")
        ensure_workpaper_viewer(db, project, target_workpaper, user)
    duplicate = db.execute(
        select(Attachment).where(
            Attachment.project_id == payload["project_id"],
            Attachment.index_no == payload["index_no"],
            Attachment.id != attachment_id,
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="附件索引号已存在")
    apply_patch_to_model(item, payload)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/attachments/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    item = get_or_404(db, Attachment, attachment_id, "附件")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_document_uploader(db, project, user)
    workpaper = db.get(Workpaper, item.workpaper_id) if item.workpaper_id else None
    if workpaper is not None:
        ensure_workpaper_viewer(db, project, workpaper, user)
    elif project.id not in supervised_project_ids(db, user):
        raise HTTPException(status_code=403, detail="项目成员不能删除项目级公共附件")
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/api/projects/{project_id}/attachments/scan")
def scan_project_attachments(
    project_id: int,
    body: AttachmentScanIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    files = scan_project_attachment_files(project, body.subdir)
    existing_paths = {
        str(Path(path).expanduser())
        for path in db.execute(select(Attachment.file_path).where(Attachment.project_id == project.id)).scalars().all()
        if path
    }
    workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)
    ).scalars().all()
    workpaper_paths = {
        str(Path(wp.file_path).expanduser())
        for wp in workpapers
        if wp.file_path
    }
    scanned: list[dict[str, Any]] = []
    created = 0
    skipped = 0
    used_indexes = set(
        db.execute(select(Attachment.index_no).where(Attachment.project_id == project.id)).scalars().all()
    )
    next_by_code: dict[str, int] = {}

    def allocate_index(workpaper_code: str = "") -> str:
        base = sanitize_workpaper_code(workpaper_code) if workpaper_code else safe_project_code(project)
        start = next_by_code.get(base)
        if start is None:
            start = 1
            prefix = f"{base}-"
            for index_no in used_indexes:
                if index_no.startswith(prefix):
                    match = re.search(r"-(\d+)$", index_no)
                    if match:
                        start = max(start, int(match.group(1)) + 1)
        while f"{base}-{start}" in used_indexes:
            start += 1
        next_by_code[base] = start + 1
        index_no = f"{base}-{start}"
        used_indexes.add(index_no)
        return index_no

    for path in files:
        path_text = str(path)
        if path_text in workpaper_paths:
            skipped += 1
            scanned.append(
                {
                    "file_path": path_text,
                    "title": path.stem,
                    "file_type": file_type_for_path(path),
                    "workpaper_id": None,
                    "workpaper_code": "",
                    "index_no": "",
                    "status": "skipped",
                    "message": "已作为底稿文件登记，跳过附件登记",
                }
            )
            continue
        wp = guess_workpaper_for_file(path, workpapers)
        duplicate = path_text in existing_paths
        index_no = "" if duplicate else allocate_index(wp.code if wp else "")
        row = {
            "file_path": path_text,
            "title": path.stem,
            "file_type": file_type_for_path(path),
            "workpaper_id": wp.id if wp else None,
            "workpaper_code": wp.code if wp else "",
            "index_no": index_no,
            "status": "skipped" if duplicate else ("planned" if body.dry_run else "created"),
            "message": "已登记，跳过" if duplicate else ("预览登记" if body.dry_run else "已登记"),
        }
        if duplicate:
            skipped += 1
        elif not body.dry_run:
            db.add(
                Attachment(
                    project_id=project.id,
                    workpaper_id=wp.id if wp else None,
                    index_no=index_no,
                    title=path.stem,
                    file_path=path_text,
                    file_type=file_type_for_path(path),
                    referenced_in=wp.code if wp else "",
                    status="active",
                    uploaded_by_user_id=user.id,
                )
            )
            created += 1
        scanned.append(row)
    if not body.dry_run:
        db.commit()
    return {
        "project_id": project.id,
        "root": str(Path(project.project_root).expanduser()),
        "dry_run": body.dry_run,
        "found": len(files),
        "created": created,
        "skipped": skipped,
        "items": scanned,
    }


@router.post("/api/projects/{project_id}/attachments/reconcile-references")
def reconcile_attachment_references(
    project_id: int,
    body: AttachmentReferenceScanIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    attachments = db.execute(
        select(Attachment).where(Attachment.project_id == project.id).order_by(Attachment.index_no)
    ).scalars().all()
    workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)
    ).scalars().all()
    attachment_by_index = {att.index_no: att for att in attachments if att.index_no}
    index_set = set(attachment_by_index)
    supported_suffixes = {".xlsx", ".xlsm", ".docx", ".txt", ".csv"}
    items: list[dict[str, Any]] = []
    scanned_workpapers = 0
    matched_count = 0
    missing_count = 0
    updated = 0

    for wp in workpapers:
        if not wp.file_path:
            continue
        path = Path(wp.file_path).expanduser()
        if path.suffix.lower() not in supported_suffixes:
            continue
        if not path.exists() or not path.is_file():
            items.append(
                {
                    "workpaper_id": wp.id,
                    "workpaper_code": wp.code,
                    "workpaper_path": str(path),
                    "file_path": str(path),
                    "file_type": "引用",
                    "index_no": "",
                    "status": "error",
                    "message": "底稿文件不存在，无法勾稽附件引用",
                }
            )
            continue
        try:
            text = extract_workpaper_text(path)
        except Exception as exc:
            items.append(
                {
                    "workpaper_id": wp.id,
                    "workpaper_code": wp.code,
                    "workpaper_path": str(path),
                    "file_path": str(path),
                    "file_type": "引用",
                    "index_no": "",
                    "status": "error",
                    "message": f"读取底稿失败：{exc}",
                }
            )
            continue

        scanned_workpapers += 1
        tokens = candidate_reference_tokens(text)
        matched_indexes = sorted({index_no for index_no in index_set if index_no in text} | (tokens & index_set))
        missing_tokens = sorted(
            token for token in tokens if token not in index_set and likely_attachment_reference(token)
        )

        for index_no in matched_indexes:
            att = attachment_by_index[index_no]
            old_reference = att.referenced_in
            new_reference = append_reference(old_reference, wp.code)
            status = "unchanged" if new_reference == old_reference else ("planned" if body.dry_run else "updated")
            if not body.dry_run and new_reference != old_reference:
                att.referenced_in = new_reference
                updated += 1
            matched_count += 1
            items.append(
                {
                    "workpaper_id": wp.id,
                    "workpaper_code": wp.code,
                    "workpaper_path": str(path),
                    "file_path": att.file_path or str(path),
                    "file_type": "引用",
                    "attachment_id": att.id,
                    "attachment_title": att.title,
                    "title": att.title,
                    "index_no": index_no,
                    "status": status,
                    "message": "引用已存在" if status == "unchanged" else ("预览更新引用" if body.dry_run else "已更新引用"),
                }
            )

        for token in missing_tokens:
            missing_count += 1
            items.append(
                {
                    "workpaper_id": wp.id,
                    "workpaper_code": wp.code,
                    "workpaper_path": str(path),
                    "file_path": str(path),
                    "file_type": "引用",
                    "index_no": token,
                    "status": "missing",
                    "message": "底稿引用未在附件台账登记",
                }
            )

    if not body.dry_run:
        db.commit()
    return {
        "project_id": project.id,
        "dry_run": body.dry_run,
        "attachment_count": len(attachments),
        "scanned_workpapers": scanned_workpapers,
        "matched_count": matched_count,
        "missing_count": missing_count,
        "updated": updated,
        "items": items,
    }
