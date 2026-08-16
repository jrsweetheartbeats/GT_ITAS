from __future__ import annotations

from datetime import date
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
    current_user,
    default_audit_scope,
    ensure_document_uploader,
    ensure_project_editor,
    get_setting,
    hash_password,
    is_admin,
    normalize_module_order,
    require_admin,
    set_setting,
    validate_password_policy,
    verify_password,
)
from ..core.utils import apply_patch_to_model, get_or_404, obj_dict
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
    DueDateIn,
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
from ..services.timeliness import days_after, overdue_payload


router = APIRouter()


def _setting_int(db: Session, key: str, default: int) -> int:
    try:
        return int(get_setting(db, key, default))
    except (TypeError, ValueError):
        return default


def _document_request_payload(item: DocumentRequest) -> dict[str, Any]:
    data = obj_dict(item)
    data.update(overdue_payload(item.status, item.due_date))
    return data


@router.get("/api/projects/{project_id}/document-requests")
def list_document_requests(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    get_or_404(db, Project, project_id, "项目")
    rows = db.execute(
        select(DocumentRequest).where(DocumentRequest.project_id == project_id).order_by(DocumentRequest.control_code, DocumentRequest.id)
    ).scalars().all()
    return [_document_request_payload(row) for row in rows]


@router.post("/api/projects/{project_id}/document-requests/generate")
def generate_document_requests(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    existing_codes = set(
        db.execute(select(DocumentRequest.code).where(DocumentRequest.project_id == project_id)).scalars().all()
    )
    requested_at = date.today()
    due_date = days_after(requested_at, _setting_int(db, "document_request_due_days", 7))
    created = 0
    for row in c22_document_requests_from_rules():
        if row["code"] in existing_codes:
            continue
        db.add(DocumentRequest(project_id=project_id, requested_at=requested_at, due_date=due_date, **row))
        created += 1
    db.commit()
    return {"project_id": project_id, "created": created}


@router.post("/api/projects/{project_id}/document-requests/meeting-minutes")
def ensure_meeting_minutes_request(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    item = db.execute(
        select(DocumentRequest).where(DocumentRequest.project_id == project.id, DocumentRequest.code == "MEETING-MINUTES")
    ).scalars().first()
    created = False
    if item is None:
        requested_at = date.today()
        item = DocumentRequest(
            project_id=project.id,
            code="MEETING-MINUTES",
            title="访谈会议纪要",
            control_code="项目过程",
            direction="项目过程中形成的访谈会议纪要、访谈记录、会议签到或沟通纪要，可按文件或文件夹上传。",
            required=False,
            status="pending",
            requested_at=requested_at,
            due_date=days_after(requested_at, _setting_int(db, "document_request_due_days", 7)),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        created = True
    data = _document_request_payload(item)
    data["created"] = created
    return data


@router.patch("/api/document-requests/{request_id}/due-date")
def update_document_request_due_date(
    request_id: int,
    body: DueDateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    item = get_or_404(db, DocumentRequest, request_id, "资料清单")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_project_editor(project, user)
    item.due_date = body.due_date
    db.commit()
    db.refresh(item)
    return _document_request_payload(item)


@router.post("/api/document-requests/{request_id}/upload")
def upload_document_request(
    request_id: int,
    body: DocumentRequestUploadIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    item = get_or_404(db, DocumentRequest, request_id, "资料清单")
    project = get_or_404(db, Project, item.project_id, "项目")
    if not can_upload_documents(db, user, project):
        raise HTTPException(status_code=403, detail="仅项目成员可上传资料")
    paths = [path for path in body.file_paths if path]
    if not paths:
        raise HTTPException(status_code=400, detail="未提供上传文件路径")
    item.file_path = "\n".join(paths)
    item.status = "uploaded"
    item.uploaded_by_user_id = user.id
    db.commit()
    db.refresh(item)
    return _document_request_payload(item)


@router.post("/api/document-requests/{request_id}/files")
def upload_document_request_files(
    request_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    item = get_or_404(db, DocumentRequest, request_id, "资料清单")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_document_uploader(db, project, user)
    saved = save_upload_files(project, item, files)
    existing = [path for path in (item.file_path or "").splitlines() if path.strip()]
    item.file_path = "\n".join(existing + saved)
    item.status = "uploaded"
    item.uploaded_by_user_id = user.id
    db.commit()
    db.refresh(item)
    data = _document_request_payload(item)
    data["saved_files"] = saved
    return data
