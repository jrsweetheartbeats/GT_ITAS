from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile
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
    ReviewRun,
    ReviewStep,
    Role,
    Task,
    User,
    Workpaper,
    WorkpaperTemplate,
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
    WorkpaperPreviewOut,
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
from ..services.workpaper_headers import apply_project_headers_to_real_files, apply_project_headers_to_test_copies, scan_project_headers
from ..services.workpaper_metadata import merge_workpaper_metadata, parse_header_datetime, workpaper_header_fields
from ..services.workpaper_reader import read_workpaper_preview


router = APIRouter()

WORKPAPER_UPLOAD_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".pdf", ".csv", ".txt"}
MAX_WORKPAPER_UPLOAD_BYTES = 50 * 1024 * 1024


def _template_source_path(template: WorkpaperTemplate) -> Path:
    source = Path(template.source_path or "").expanduser()
    if source.is_absolute():
        return source
    return WORKSPACE_ROOT / source


def _safe_template_filename(name: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", Path(name or "template").name).strip("._")
    return stem or "template"


@router.get("/api/workpapers")
def list_workpapers(
    projectId: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    stmt = select(Workpaper).order_by(Workpaper.stage, Workpaper.code)
    if projectId is not None:
        project = get_or_404(db, Project, projectId, "项目")
        ensure_project_viewer(db, project, user)
        stmt = stmt.where(Workpaper.project_id == projectId)
    if status:
        stmt = stmt.where(Workpaper.status == status)
    rows = db.execute(stmt).scalars().all()
    if projectId is None:
        rows = [row for row in rows if can_view_project(db, user, get_or_404(db, Project, row.project_id, "项目"))]
        return list_dict(rows)
    payload: list[dict[str, Any]] = []
    for row in rows:
        data = obj_dict(row)
        header_fields = workpaper_header_fields(row)
        data["preparer_name"] = row.preparer.display_name if row.preparer else header_fields.get("preparer", "")
        data["prepared_at"] = parse_header_datetime(header_fields.get("prepared_date")) or row.created_at
        data["reviewer_name"] = header_fields.get("reviewer", "")
        data["reviewed_at"] = parse_header_datetime(header_fields.get("reviewed_date"))
        data["header_fields"] = header_fields
        payload.append(data)
    return payload


@router.get("/api/workpaper-templates")
def list_workpaper_templates(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(WorkpaperTemplate).order_by(WorkpaperTemplate.stage, WorkpaperTemplate.sort_order, WorkpaperTemplate.code)
    ).scalars().all()
    payload = []
    for row in rows:
        path = _template_source_path(row)
        data = obj_dict(row)
        data["file_exists"] = path.exists() and path.is_file()
        data["filename"] = path.name
        data["resolved_path"] = str(path)
        payload.append(data)
    return payload


@router.get("/api/projects/{project_id}/workpaper-headers")
def scan_project_workpaper_headers(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    workpapers = db.execute(select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)).scalars().all()
    return scan_project_headers(project, workpapers)


@router.post("/api/projects/{project_id}/workpaper-headers/test-copy")
def apply_project_workpaper_headers_to_test_copies(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    workpapers = db.execute(select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)).scalars().all()
    return apply_project_headers_to_test_copies(project, workpapers)


@router.post("/api/projects/{project_id}/workpaper-headers/apply")
def apply_project_workpaper_headers_to_real_workpapers(
    project_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_editor(project, user)
    if body.get("confirm_real_write") is not True:
        raise HTTPException(status_code=400, detail="真实写入需要 confirm_real_write=true")
    workpapers = db.execute(select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)).scalars().all()
    report = apply_project_headers_to_real_files(project, workpapers)
    db.commit()
    return report


@router.get("/api/workpaper-templates/{template_id}/download")
def download_workpaper_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    template = get_or_404(db, WorkpaperTemplate, template_id, "底稿模板")
    path = _template_source_path(template)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="模板文件不存在")
    return FileResponse(path, filename=path.name)


@router.post("/api/workpaper-templates", status_code=201)
def upload_workpaper_template(
    file: UploadFile = File(...),
    code: str = Form(...),
    name: str = Form(...),
    stage: str = Form("execution"),
    version: str = Form("uploaded"),
    applicable_year: Optional[int] = Form(None),
    update_note: str = Form(""),
    is_latest: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="未选择模板文件")
    safe_name = _safe_template_filename(file.filename)
    digest = hashlib.sha256(f"{code}:{version}:{datetime.utcnow().isoformat()}:{safe_name}".encode("utf-8")).hexdigest()[:10]
    target_dir = WORKSPACE_ROOT / "templates"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{code}_{version}_{digest}_{safe_name}"
    with target_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    if is_latest:
        existing_same_code = db.execute(select(WorkpaperTemplate).where(WorkpaperTemplate.code == code)).scalars().all()
        for item in existing_same_code:
            item.is_latest = False

    template = db.execute(
        select(WorkpaperTemplate).where(WorkpaperTemplate.code == code, WorkpaperTemplate.version == version)
    ).scalar_one_or_none()
    if template is None:
        max_sort = db.execute(select(func.max(WorkpaperTemplate.sort_order))).scalar_one() or 0
        template = WorkpaperTemplate(code=code, version=version, sort_order=max_sort + 10)
        db.add(template)
    template.name = name
    template.stage = stage or "execution"
    template.source_path = str(target_path)
    template.applicable_year = applicable_year
    template.update_note = update_note or ""
    template.description = update_note or template.description or ""
    template.default_enabled = True
    template.is_latest = is_latest
    db.commit()
    db.refresh(template)
    data = obj_dict(template)
    data["file_exists"] = target_path.exists()
    data["filename"] = target_path.name
    data["resolved_path"] = str(target_path)
    return data


@router.get("/api/workpapers/{workpaper_id}/preview", response_model=WorkpaperPreviewOut)
def preview_workpaper(
    workpaper_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    item = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_project_viewer(db, project, user)
    data = read_workpaper_preview(item)
    steps = db.scalars(
        select(ReviewStep).where(ReviewStep.workpaper_id == item.id).order_by(ReviewStep.sequence_no)
    ).all()
    reviewer_ids = [step.reviewer_user_id for step in steps if step.reviewer_user_id]
    reviewers = {row.id: row for row in db.scalars(select(User).where(User.id.in_(reviewer_ids))).all()} if reviewer_ids else {}
    reviewed_steps = [step for step in steps if step.reviewed_at]
    latest_reviewed = max(reviewed_steps, key=lambda step: step.reviewed_at) if reviewed_steps else None
    next_reviewer = next((step for step in steps if step.status in {"waiting", "pending", "in_review"}), None) or (steps[0] if steps else None)
    reviewer_user = reviewers.get(next_reviewer.reviewer_user_id) if next_reviewer and next_reviewer.reviewer_user_id else None
    header_fields = workpaper_header_fields(item)
    prepared_at = parse_header_datetime(header_fields.get("prepared_date")) or item.created_at
    reviewed_at = latest_reviewed.reviewed_at if latest_reviewed else parse_header_datetime(header_fields.get("reviewed_date"))
    data.update(
        {
            "preparer_name": item.preparer.display_name if item.preparer else header_fields.get("preparer", ""),
            "prepared_at": prepared_at,
            "reviewer_name": reviewer_user.display_name if reviewer_user else (next_reviewer.reviewer_role_code if next_reviewer else header_fields.get("reviewer", "")),
            "reviewed_at": reviewed_at,
            "header_fields": header_fields,
            "review_started": bool(steps),
            "review_steps": [
                {
                    "sequence_no": step.sequence_no,
                    "reviewer_role_code": step.reviewer_role_code,
                    "reviewer_name": reviewers.get(step.reviewer_user_id).display_name if step.reviewer_user_id and reviewers.get(step.reviewer_user_id) else "",
                    "status": step.status,
                    "comment": step.comment,
                    "reviewed_at": step.reviewed_at,
                }
                for step in steps
            ],
        }
    )
    return data


@router.post("/api/workpapers", status_code=201)
def create_workpaper(body: WorkpaperIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    project = get_or_404(db, Project, body.project_id, "项目")
    ensure_project_editor(project, user)
    payload = body.model_dump()
    extracted = merge_workpaper_metadata(payload.pop("extracted_fields"), payload.get("file_path", ""))
    item = Workpaper(**payload, extracted_fields_json=json.dumps(extracted, ensure_ascii=False))
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.post("/api/projects/{project_id}/workpapers/upload", status_code=201)
async def upload_project_workpaper(
    project_id: int,
    file: UploadFile = File(...),
    code: str = Form(...),
    name: str = Form(...),
    stage: str = Form("execution"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_feature_permission(db, user, "workpaperExecution", "edit")
    ensure_document_uploader(db, project, user)
    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()
    if not original_name or extension not in WORKPAPER_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 Excel、Word、PDF、CSV 和 TXT 底稿文件")
    safe_name = _safe_template_filename(original_name)
    target_dir = BASE_DIR / "uploads" / "workpapers" / str(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{datetime.utcnow():%Y%m%d%H%M%S}_{secrets.token_hex(5)}_{safe_name}"
    written = 0
    try:
        with target_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_WORKPAPER_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="底稿文件不能超过 50 MB")
                output.write(chunk)
        item = Workpaper(
            project_id=project_id,
            code=code.strip(),
            name=name.strip(),
            stage=stage.strip() or "execution",
            file_path=str(target_path),
            status="draft",
            preparer_user_id=user.id,
            extracted_fields_json="{}",
        )
        if not item.code or not item.name:
            raise HTTPException(status_code=400, detail="底稿编号和名称不能为空")
        db.add(item)
        db.commit()
        db.refresh(item)
    except Exception:
        db.rollback()
        target_path.unlink(missing_ok=True)
        raise
    data = obj_dict(item)
    data["uploaded_filename"] = original_name
    data["uploaded_size"] = written
    return data


@router.patch("/api/workpapers/{workpaper_id}")
def update_workpaper(
    workpaper_id: int,
    body: WorkpaperIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    item = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_project_editor(project, user)
    apply_patch_to_model(item, body.model_dump())
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/workpapers/{workpaper_id}", status_code=204)
def delete_workpaper(workpaper_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    item = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_project_editor(project, user)
    db.delete(item)
    db.commit()
    return Response(status_code=204)
