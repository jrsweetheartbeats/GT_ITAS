from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
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
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import BASE_DIR, PROJECTS_ROOT, WORKSPACE_ROOT
from ..core.db import get_db, safe_database_label
from ..core.security import (
    DEFAULT_MODULE_ORDER,
    DEFAULT_PASSWORD_POLICY,
    can_edit_project,
    can_view_project,
    can_upload_documents,
    current_user,
    default_audit_scope,
    ensure_document_uploader,
    ensure_project_editor,
    ensure_workpaper_uploader,
    ensure_workpaper_viewer,
    ensure_project_viewer,
    get_setting,
    hash_password,
    is_admin,
    normalize_module_order,
    require_admin,
    set_setting,
    supervised_project_ids,
    validate_password_policy,
    visible_project_ids,
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
    WorkpaperVersion,
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
    WorkpaperPatchIn,
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
from ..services.materials import c22_document_requests_from_rules, save_batch_upload_file, save_upload_files, save_workpaper_file
from ..services.projects import copy_workpaper_file, replace_audit_year, seed_project_template_workpapers
from ..services.review import add_finding, run_external_rules, run_internal_review
from ..services.workpaper_headers import apply_project_headers_to_real_files, apply_project_headers_to_test_copies, scan_project_headers
from ..services.workpaper_metadata import merge_workpaper_metadata, parse_header_datetime, workpaper_header_fields
from ..services.workpaper_reader import read_workpaper_preview
from ..services.workpaper_catalog import BASIC_WORKPAPER_SPECS, normalize_workpaper_code, validate_workpaper_index_code
from ..services.audit_log import record_audit_log


router = APIRouter()


def _controlled_workpaper_path(value: str) -> Path:
    """Resolve a file only when it stays inside the ITAS project workspace."""
    if not str(value or "").strip():
        raise HTTPException(status_code=404, detail="该底稿尚未上传文件")
    path = Path(value).expanduser().resolve(strict=False)
    try:
        path.relative_to(PROJECTS_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="底稿文件不在受控工作区内") from exc
    return path
MAX_BATCH_FILE_SIZE_BYTES = 50 * 1024 * 1024


def _uploaded_workpaper_status(previous_status: str | None) -> str:
    """退回后上传新版本仍保持退回态，由显式重提操作重启复核。"""
    return "returned" if previous_status == "returned" else "draft"


def _validated_workpaper_code(value: Any) -> str:
    try:
        return validate_workpaper_index_code(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _is_unclaimed_standard_template(item: Workpaper) -> bool:
    try:
        metadata = json.loads(getattr(item, "extracted_fields_json", "") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return item.status == "draft" and metadata.get("workspace_initialized") is True


def _basic_workpaper_code_from_path(relative_path: str) -> str:
    filename = Path(relative_path or "").name.upper()
    if re.search(r"C22[.\-_](?:SA|PE|PM)-\d", filename):
        return ""
    for spec in sorted(BASIC_WORKPAPER_SPECS, key=lambda item: len(item["code"]), reverse=True):
        code = spec["code"]
        if re.search(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", filename):
            return code
    return ""


def _attachment_index_prefix_from_path(relative_path: str) -> str:
    """Use the nearest indexed folder as the stable prefix for non-workpaper files."""
    parts = list(Path(relative_path or "").parts)
    pattern = re.compile(
        r"(?<![A-Z0-9])(?:(?:C22)[.\-_])?((?:SA|PE|PM)-\d+[A-Z]?(?:-\d+[A-Z]?)*)(?![A-Z0-9])",
        flags=re.IGNORECASE,
    )
    for part in reversed(parts[:-1]):
        match = pattern.search(part.upper())
        if match:
            return match.group(1).upper()
    return ""


def _non_basic_workpaper_code_from_path(relative_path: str) -> str:
    """Recognize a standalone A/B/C workpaper index from a file or its nearest folder."""
    path = Path(relative_path or "")
    filename = path.name.upper()
    if _attachment_index_prefix_from_path(relative_path) or re.search(r"C22[.\-_](?:SA|PE|PM)-\d", filename):
        return ""
    pattern = re.compile(r"(?<![A-Z0-9])([ABC]\d{1,3}[A-Z]?(?:-\d+[A-Z]?)*)(?![A-Z0-9])")
    for part in [filename, *reversed(path.parts[:-1])]:
        match = pattern.search(part.upper())
        if match:
            return normalize_workpaper_code(match.group(1))
    return ""


def _stage_for_workpaper_code(code: str) -> str:
    if code.startswith("B"):
        return "planning"
    if code.startswith("A"):
        return "delivery"
    return "execution"


def _register_uploaded_workpaper(
    db: Session,
    project: Project,
    user: User,
    *,
    code: str,
    name: str,
    stage: str,
    file_path: str,
    original_filename: str,
    note: str = "",
) -> tuple[Workpaper, int, bool]:
    item = db.execute(
        select(Workpaper).where(Workpaper.project_id == project.id, Workpaper.code == code).order_by(Workpaper.id)
    ).scalars().first()
    created = item is None
    prior_status = item.status if item is not None else "draft"
    if item is not None:
        _ensure_existing_upload_allowed(item, project, user, user.id)
    if item is None:
        item = Workpaper(project_id=project.id, code=code, name=name)
        db.add(item)
        db.flush()
    next_version = int(
        db.execute(
            select(func.coalesce(func.max(WorkpaperVersion.version_no), 0)).where(
                WorkpaperVersion.workpaper_id == item.id
            )
        ).scalar_one()
    ) + 1
    item.name = name.strip() or item.name
    item.stage = stage or item.stage or "execution"
    item.file_path = file_path
    item.status = _uploaded_workpaper_status(prior_status)
    item.preparer_user_id = user.id
    item.year_updated = False
    item.extracted_fields_json = json.dumps(
        {"uploaded_filename": original_filename, "version": next_version, "batch_import": bool(note)},
        ensure_ascii=False,
    )
    db.add(
        WorkpaperVersion(
            workpaper_id=item.id,
            version_no=next_version,
            file_path=file_path,
            original_filename=original_filename,
            uploaded_by_user_id=user.id,
            note=note,
        )
    )
    return item, next_version, created


def _ensure_existing_upload_allowed(
    item: Workpaper,
    project: Project,
    user: User,
    assigned_preparer_id: int,
) -> None:
    if item.status not in {"draft", "returned"}:
        raise HTTPException(status_code=409, detail=f"底稿当前为 {item.status}，不允许覆盖上传；请等待复核或按复核流程退回")


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
    visible_ids = visible_project_ids(db, user)
    if not visible_ids:
        return []
    stmt = select(Workpaper).where(Workpaper.project_id.in_(visible_ids)).order_by(Workpaper.stage, Workpaper.code)
    if projectId is not None:
        project = get_or_404(db, Project, projectId, "项目")
        ensure_project_viewer(db, project, user)
        stmt = stmt.where(Workpaper.project_id == projectId)
    if status:
        stmt = stmt.where(Workpaper.status == status)
    rows = db.execute(stmt).scalars().all()
    if projectId is None:
        return list_dict(rows)
    workpaper_ids = [row.id for row in rows]
    latest_versions: dict[int, WorkpaperVersion] = {}
    latest_review_steps: dict[int, ReviewStep] = {}
    if workpaper_ids:
        versions = db.execute(
            select(WorkpaperVersion)
            .where(WorkpaperVersion.workpaper_id.in_(workpaper_ids))
            .order_by(WorkpaperVersion.workpaper_id, WorkpaperVersion.version_no.desc())
        ).scalars().all()
        for version in versions:
            latest_versions.setdefault(version.workpaper_id, version)
        review_steps = db.execute(
            select(ReviewStep)
            .where(ReviewStep.workpaper_id.in_(workpaper_ids), ReviewStep.reviewed_at.is_not(None))
            .order_by(ReviewStep.workpaper_id, ReviewStep.reviewed_at.desc())
        ).scalars().all()
        for step in review_steps:
            latest_review_steps.setdefault(step.workpaper_id, step)
    reviewer_ids = [step.reviewer_user_id for step in latest_review_steps.values() if step.reviewer_user_id]
    reviewers = {
        reviewer.id: reviewer
        for reviewer in db.execute(select(User).where(User.id.in_(reviewer_ids))).scalars().all()
    } if reviewer_ids else {}
    payload: list[dict[str, Any]] = []
    for row in rows:
        data = obj_dict(row)
        header_fields = workpaper_header_fields(row)
        latest_version = latest_versions.get(row.id)
        latest_review_step = latest_review_steps.get(row.id)
        data["preparer_name"] = row.preparer.display_name if row.preparer else header_fields.get("preparer", "")
        # These dates are workflow timestamps, not values parsed from the workpaper header.
        data["prepared_at"] = latest_version.created_at if latest_version else None
        data["reviewer_name"] = reviewers.get(latest_review_step.reviewer_user_id).display_name if latest_review_step and latest_review_step.reviewer_user_id and reviewers.get(latest_review_step.reviewer_user_id) else ""
        data["reviewed_at"] = latest_review_step.reviewed_at if latest_review_step else None
        data["header_fields"] = header_fields
        payload.append(data)
    return payload


@router.get("/api/projects/{project_id}/basic-workpaper-check")
def check_basic_workpapers(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Show completeness without adding placeholder workpapers to the file tree."""
    project = get_or_404(db, Project, project_id, "项目")
    ensure_project_viewer(db, project, user)
    stmt = select(Workpaper).where(Workpaper.project_id == project.id)
    by_code = {
        normalize_workpaper_code(item.code): item
        for item in db.execute(stmt).scalars().all()
    }
    items: list[dict[str, Any]] = []
    for spec in BASIC_WORKPAPER_SPECS:
        workpaper = by_code.get(spec["code"])
        uploaded = bool(workpaper and workpaper.file_path)
        items.append(
            {
                "code": spec["code"],
                "name": spec["name"],
                "stage": spec["stage"],
                "status": "uploaded" if uploaded else "missing",
                "workpaper_id": workpaper.id if workpaper else None,
                "file_path": workpaper.file_path if uploaded else "",
            }
        )
    uploaded_count = sum(item["status"] == "uploaded" for item in items)
    return {
        "project_id": project.id,
        "scope": "team" if project.id in supervised_project_ids(db, user) else "mine",
        "total": len(items),
        "uploaded": uploaded_count,
        "missing": len(items) - uploaded_count,
        "items": items,
    }


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
    stmt = select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)
    workpapers = db.execute(stmt).scalars().all()
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


@router.get("/api/workpapers/{workpaper_id}/download")
def download_workpaper(
    workpaper_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    """Return the registered workpaper file after applying normal file access rules."""
    workpaper = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, workpaper.project_id, "项目")
    ensure_workpaper_viewer(db, project, workpaper, user)
    path = _controlled_workpaper_path(str(workpaper.file_path or ""))
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="该底稿尚未上传文件或源文件已不存在")
    return FileResponse(path, filename=path.name)


@router.post("/api/workpapers/{workpaper_id}/open-local")
def open_workpaper_locally(
    workpaper_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Open the locally registered file, without transferring it through the browser.

    The web application runs with this local ITAS service, so the registered
    workpaper path is the authoritative local copy.  A missing path is not an
    error: the browser can then explicitly download the authorized file.
    """
    workpaper = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, workpaper.project_id, "项目")
    ensure_workpaper_viewer(db, project, workpaper, user)
    path = _controlled_workpaper_path(str(workpaper.file_path or ""))
    if not path.exists() or not path.is_file():
        return {"opened": False, "local_exists": False, "filename": path.name if path.name else ""}
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"本地文件存在，但无法调用默认应用打开：{exc}") from exc
    return {"opened": True, "local_exists": True, "filename": path.name}


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
    code = _validated_workpaper_code(code)
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
    ensure_workpaper_viewer(db, project, item, user)
    _controlled_workpaper_path(str(item.file_path or ""))
    data = read_workpaper_preview(item)
    steps = db.scalars(
        select(ReviewStep).where(ReviewStep.workpaper_id == item.id).order_by(ReviewStep.sequence_no)
    ).all()
    reviewer_ids = [step.reviewer_user_id for step in steps if step.reviewer_user_id]
    reviewers = {row.id: row for row in db.scalars(select(User).where(User.id.in_(reviewer_ids))).all()} if reviewer_ids else {}
    reviewed_steps = [step for step in steps if step.reviewed_at]
    latest_reviewed = max(reviewed_steps, key=lambda step: step.reviewed_at) if reviewed_steps else None
    latest_version = db.scalars(
        select(WorkpaperVersion)
        .where(WorkpaperVersion.workpaper_id == item.id)
        .order_by(WorkpaperVersion.version_no.desc())
    ).first()
    next_reviewer = next((step for step in steps if step.status in {"waiting", "pending", "in_review"}), None) or (steps[0] if steps else None)
    reviewer_user = reviewers.get(next_reviewer.reviewer_user_id) if next_reviewer and next_reviewer.reviewer_user_id else None
    header_fields = workpaper_header_fields(item)
    # Keep system execution dates independent from any template/header values.
    prepared_at = latest_version.created_at if latest_version else None
    reviewed_at = latest_reviewed.reviewed_at if latest_reviewed else None
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
    ensure_workpaper_uploader(db, project, user)
    payload = body.model_dump()
    if str(payload.get("file_path") or "").strip():
        raise HTTPException(status_code=422, detail="不支持登记服务器路径，请使用底稿上传接口")
    clean_code = _validated_workpaper_code(payload.get("code"))
    duplicate = db.execute(
        select(Workpaper.id).where(Workpaper.project_id == project.id, Workpaper.code == clean_code)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="同一项目内底稿编号必须唯一；如需修订请上传新版本")
    assigned_preparer_id = payload.get("preparer_user_id") or user.id
    assigned_preparer = get_or_404(db, User, assigned_preparer_id, "编制人")
    if not can_view_project(db, assigned_preparer, project):
        raise HTTPException(status_code=400, detail="编制人必须是本项目成员或项目负责人")
    if assigned_preparer_id != user.id and not can_edit_project(user, project):
        raise HTTPException(status_code=403, detail="项目成员只能以本人身份登记底稿")
    payload["preparer_user_id"] = assigned_preparer_id
    payload["code"] = clean_code
    payload["status"] = "draft"
    extracted = merge_workpaper_metadata(payload.pop("extracted_fields"), "")
    item = Workpaper(**payload, extracted_fields_json=json.dumps(extracted, ensure_ascii=False))
    db.add(item)
    db.flush()
    record_audit_log(db, None, "workpaper_registered", user=user, target_type="workpaper", target_id=item.id, project_id=project.id, details={"code": item.code})
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.post("/api/workpapers/upload", status_code=201)
def upload_workpaper(
    project_id: int = Form(...),
    code: str = Form(...),
    name: str = Form(...),
    stage: str = Form("execution"),
    preparer_user_id: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    project = get_or_404(db, Project, project_id, "项目")
    ensure_workpaper_uploader(db, project, user)
    assigned_preparer_id = preparer_user_id or user.id
    assigned_preparer = get_or_404(db, User, assigned_preparer_id, "编制人")
    if not can_view_project(db, assigned_preparer, project):
        raise HTTPException(status_code=400, detail="编制人必须是本项目成员或项目负责人")
    if assigned_preparer_id != user.id and not can_edit_project(user, project):
        raise HTTPException(status_code=403, detail="项目成员只能以本人身份上传底稿")
    clean_code = _validated_workpaper_code(code)
    item = db.execute(
        select(Workpaper)
        .where(Workpaper.project_id == project_id, Workpaper.code == clean_code)
        .order_by(Workpaper.id)
    ).scalars().first()
    prior_status = item.status if item is not None else "draft"
    if item is not None:
        _ensure_existing_upload_allowed(item, project, user, assigned_preparer_id)
    path = save_workpaper_file(project, file, stage)
    try:
        if item is None:
            item = Workpaper(project_id=project_id, code=clean_code, name=name.strip())
            db.add(item)
            db.flush()
        next_version = int(
            db.execute(
                select(func.coalesce(func.max(WorkpaperVersion.version_no), 0)).where(
                    WorkpaperVersion.workpaper_id == item.id
                )
            ).scalar_one()
        ) + 1
        item.name = name.strip() or item.name
        item.stage = stage or item.stage or "execution"
        item.file_path = path
        item.status = _uploaded_workpaper_status(prior_status)
        # The member uploading a replacement is the accountable preparer for it.
        item.preparer_user_id = assigned_preparer_id
        item.year_updated = False
        item.extracted_fields_json = json.dumps(
            {"uploaded_filename": Path(file.filename or path).name, "version": next_version},
            ensure_ascii=False,
        )
        db.add(
            WorkpaperVersion(
                workpaper_id=item.id,
                version_no=next_version,
                file_path=path,
                original_filename=Path(file.filename or path).name,
                uploaded_by_user_id=user.id,
            )
        )
        record_audit_log(
            db,
            None,
            "workpaper_uploaded",
            user=user,
            target_type="workpaper",
            target_id=item.id,
            project_id=project_id,
            details={"code": clean_code, "version": next_version, "filename": Path(file.filename or path).name},
        )
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        Path(path).unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="同一项目内底稿编号必须唯一") from exc
    except Exception:
        db.rollback()
        Path(path).unlink(missing_ok=True)
        raise
    data = obj_dict(item)
    data["version_no"] = next_version
    return data


@router.post("/api/workpapers/batch-upload", status_code=201)
def batch_upload_workpapers(
    project_id: int = Form(...),
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(default=[]),
    target_workpaper_id: Optional[int] = Form(None),
    confirm_large_files: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Import a browser-selected folder and retain its directory hierarchy in the file tree."""
    project = get_or_404(db, Project, project_id, "项目")
    ensure_workpaper_uploader(db, project, user)
    oversized = [
        f"{Path(item.filename or '未命名文件').name}（{(item.size or 0) / 1024 / 1024:.1f}MB）"
        for item in files
        if (item.size or 0) > MAX_BATCH_FILE_SIZE_BYTES
    ]
    if oversized and not confirm_large_files:
        raise HTTPException(
            status_code=409,
            detail="存在超过 50MB 的文件，请确认后再导入：" + "；".join(oversized[:10]),
        )
    target_workpaper = None
    if target_workpaper_id:
        target_workpaper = get_or_404(db, Workpaper, target_workpaper_id, "目标底稿")
        if target_workpaper.project_id != project.id:
            raise HTTPException(status_code=400, detail="目标底稿不属于当前项目")
        ensure_workpaper_viewer(db, project, target_workpaper, user)

    existing_workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)
    ).scalars().all()
    workpapers_by_code = {normalize_workpaper_code(item.code): item for item in existing_workpapers}
    used_indexes = set(
        db.execute(select(Attachment.index_no).where(Attachment.project_id == project.id)).scalars().all()
    )
    next_by_code: dict[str, int] = {}
    created_paths: list[Path] = []
    seen_workpaper_codes: set[str] = set()
    workpapers_created = 0
    workpapers_updated = 0
    attachments_created = 0
    skipped: list[dict[str, str]] = []

    def allocate_attachment_index(workpaper_code: str = "", folder_index_prefix: str = "") -> str:
        base = sanitize_workpaper_code(folder_index_prefix or workpaper_code) if (folder_index_prefix or workpaper_code) else safe_project_code(project)
        start = next_by_code.get(base, 1)
        if base not in next_by_code:
            prefix = f"{base}-"
            for index_no in used_indexes:
                if index_no.startswith(prefix):
                    match = re.search(r"-(\d+)$", index_no)
                    if match:
                        start = max(start, int(match.group(1)) + 1)
        while f"{base}-{start}" in used_indexes:
            start += 1
        index_no = f"{base}-{start}"
        used_indexes.add(index_no)
        next_by_code[base] = start + 1
        return index_no

    try:
        for index, upload in enumerate(files):
            relative_path = relative_paths[index] if index < len(relative_paths) else (upload.filename or "")
            filename = Path(upload.filename or "").name
            if not filename or filename.startswith(".") or filename.startswith("~$"):
                skipped.append({"file": relative_path or filename, "reason": "跳过隐藏文件或临时文件"})
                continue
            basic_code = _basic_workpaper_code_from_path(relative_path)
            non_basic_code = _non_basic_workpaper_code_from_path(relative_path)
            workpaper_code = basic_code or non_basic_code
            basic_spec = next((spec for spec in BASIC_WORKPAPER_SPECS if spec["code"] == workpaper_code), None)
            linked_workpaper = workpapers_by_code.get(workpaper_code) if workpaper_code else None
            if workpaper_code and workpaper_code not in seen_workpaper_codes:
                if linked_workpaper is not None:
                    _ensure_existing_upload_allowed(linked_workpaper, project, user, user.id)
                saved_path = save_batch_upload_file(project, upload, relative_path)
                created_paths.append(Path(saved_path))
                item, version_no, created = _register_uploaded_workpaper(
                    db,
                    project,
                    user,
                    code=workpaper_code,
                    name=basic_spec["name"] if basic_spec else Path(filename).stem,
                    stage=basic_spec["stage"] if basic_spec else _stage_for_workpaper_code(workpaper_code),
                    file_path=saved_path,
                    original_filename=filename,
                    note=f"批量文件夹导入：{relative_path}",
                )
                workpapers_by_code[workpaper_code] = item
                existing_workpapers.append(item)
                seen_workpaper_codes.add(workpaper_code)
                if created:
                    workpapers_created += 1
                else:
                    workpapers_updated += 1
                record_audit_log(
                    db,
                    None,
                    "workpaper_batch_uploaded",
                    user=user,
                    target_type="workpaper",
                    target_id=item.id,
                    project_id=project.id,
                    details={"code": workpaper_code, "version": version_no, "relative_path": relative_path},
                )
                continue

            linked_workpaper = linked_workpaper or guess_workpaper_for_file(Path(relative_path), existing_workpapers) or target_workpaper
            folder_index_prefix = _attachment_index_prefix_from_path(relative_path)
            if linked_workpaper is not None:
                ensure_workpaper_viewer(db, project, linked_workpaper, user)
            saved_path = save_batch_upload_file(project, upload, relative_path)
            created_paths.append(Path(saved_path))
            attachment = Attachment(
                project_id=project.id,
                workpaper_id=linked_workpaper.id if linked_workpaper else None,
                index_no=allocate_attachment_index(linked_workpaper.code if linked_workpaper else "", folder_index_prefix),
                title=Path(filename).stem,
                file_path=saved_path,
                file_type=file_type_for_path(Path(filename)),
                referenced_in=linked_workpaper.code if linked_workpaper else "",
                status="active",
                uploaded_by_user_id=user.id,
            )
            db.add(attachment)
            attachments_created += 1
        db.commit()
    except HTTPException:
        db.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    except Exception:
        db.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    return {
        "project_id": project.id,
        "files_received": len(files),
        "workpapers_created": workpapers_created,
        "workpapers_updated": workpapers_updated,
        "attachments_created": attachments_created,
        "skipped": skipped,
    }


@router.get("/api/workpapers/{workpaper_id}/versions")
def list_workpaper_versions(
    workpaper_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    item = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_workpaper_viewer(db, project, item, user)
    rows = db.execute(
        select(WorkpaperVersion)
        .where(WorkpaperVersion.workpaper_id == workpaper_id)
        .order_by(WorkpaperVersion.version_no.desc())
    ).scalars().all()
    return [
        {
            **obj_dict(row),
            "uploaded_by_name": row.uploaded_by.display_name if row.uploaded_by else "",
        }
        for row in rows
    ]


@router.patch("/api/workpapers/{workpaper_id}")
def update_workpaper(
    workpaper_id: int,
    body: WorkpaperPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    item = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_project_editor(project, user)
    payload = body.model_dump(exclude_unset=True)
    if "code" in payload:
        clean_code = _validated_workpaper_code(payload["code"])
        duplicate = db.execute(
            select(Workpaper.id).where(
                Workpaper.project_id == project.id,
                Workpaper.code == clean_code,
                Workpaper.id != item.id,
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="同一项目内底稿编号必须唯一")
        payload["code"] = clean_code
    if "preparer_user_id" in payload and payload["preparer_user_id"] is not None:
        preparer = get_or_404(db, User, payload["preparer_user_id"], "编制人")
        if not can_view_project(db, preparer, project):
            raise HTTPException(status_code=400, detail="编制人必须是本项目成员或项目负责人")
    apply_patch_to_model(item, payload)
    record_audit_log(db, None, "workpaper_metadata_updated", user=user, target_type="workpaper", target_id=item.id, project_id=project.id, details={"fields": sorted(payload)})
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/workpapers/{workpaper_id}", status_code=204)
def delete_workpaper(workpaper_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    item = get_or_404(db, Workpaper, workpaper_id, "底稿")
    project = get_or_404(db, Project, item.project_id, "项目")
    ensure_project_editor(project, user)
    version_count = db.execute(select(func.count(WorkpaperVersion.id)).where(WorkpaperVersion.workpaper_id == item.id)).scalar_one()
    step_count = db.execute(select(func.count(ReviewStep.id)).where(ReviewStep.workpaper_id == item.id)).scalar_one()
    finding_count = db.execute(select(func.count(ReviewFinding.id)).where(ReviewFinding.workpaper_id == item.id)).scalar_one()
    if item.status != "draft" or version_count or step_count or finding_count:
        raise HTTPException(status_code=409, detail="已上传、已提交或已形成复核历史的底稿不能物理删除")
    db.delete(item)
    db.commit()
    return Response(status_code=204)
