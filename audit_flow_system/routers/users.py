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
from sqlalchemy import delete, func, select
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


@router.get("/api/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    rows = db.execute(select(User).order_by(User.id)).scalars().all()
    payload = []
    for row in rows:
        data = obj_dict(row)
        data["role_name"] = row.role.name if row.role else ""
        data["role_code"] = row.role.code if row.role else ""
        data.pop("password_hash", None)
        payload.append(data)
    return payload


@router.post("/api/users", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    payload = body.model_dump()
    password = payload.pop("password")
    if not password:
        raise HTTPException(status_code=400, detail="创建用户时必须设置初始密码")
    validate_password_policy(password, get_setting(db, "password_policy", DEFAULT_PASSWORD_POLICY))
    item = User(**payload, password_hash=hash_password(password))
    db.add(item)
    db.commit()
    db.refresh(item)
    data = obj_dict(item)
    data.pop("password_hash", None)
    return data


@router.patch("/api/users/{user_id}")
def update_user(user_id: int, body: UserIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = get_or_404(db, User, user_id, "用户")
    payload = body.model_dump()
    password = payload.pop("password", None)
    apply_patch_to_model(item, payload)
    if password:
        validate_password_policy(password, get_setting(db, "password_policy", DEFAULT_PASSWORD_POLICY))
        item.password_hash = hash_password(password)
    db.commit()
    db.refresh(item)
    data = obj_dict(item)
    data.pop("password_hash", None)
    return data


@router.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> Response:
    item = get_or_404(db, User, user_id, "用户")
    db.execute(delete(LoginSession).where(LoginSession.user_id == item.id))
    db.delete(item)
    db.commit()
    return Response(status_code=204)
