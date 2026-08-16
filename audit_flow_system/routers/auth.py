from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, Response, UploadFile
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
    authenticated_user,
    can_edit_project,
    can_upload_documents,
    current_user,
    default_audit_scope,
    ensure_document_uploader,
    ensure_project_editor,
    feature_permission_payload,
    get_setting,
    hash_password,
    is_admin,
    normalize_module_order,
    password_change_required,
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
    AuditLog,
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
    PasswordChangeIn,
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
from ..services.audit_log import record_audit_log


router = APIRouter()


@router.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@router.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.execute(select(func.count(Role.id))).scalar_one()
    return {"status": "ok", "database": safe_database_label()}


@router.post("/api/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if user is None or user.status != "active" or not verify_password(body.password, user.password_hash):
        record_audit_log(db, request, "login", user=user, username=body.username, success=False, details={"reason": "账号或密码错误"})
        db.commit()
        raise HTTPException(status_code=401, detail="账号或密码错误")
    token = secrets.token_urlsafe(40)
    db.add(LoginSession(token=token, user_id=user.id))
    must_change = password_change_required(user)
    record_audit_log(db, request, "login", user=user, success=True, details={"must_change_password": must_change})
    db.commit()
    data = obj_dict(user)
    data["role_code"] = user.role.code if user.role else ""
    data["role_name"] = user.role.name if user.role else ""
    data["is_admin"] = is_admin(user)
    data["permissions"] = feature_permission_payload(db, user)
    data.pop("password_hash", None)
    data["must_change_password"] = must_change
    return {"token": token, "user": data, "must_change_password": must_change}


@router.post("/api/logout", status_code=204)
def logout(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(authenticated_user),
) -> Response:
    _, _, token = authorization.partition(" ")
    session = db.execute(select(LoginSession).where(LoginSession.token == token)).scalar_one_or_none()
    if session is not None:
        session.active = False
        db.commit()
    return Response(status_code=204)


@router.get("/api/me")
def me(user: User = Depends(authenticated_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    data = obj_dict(user)
    data["role_code"] = user.role.code if user.role else ""
    data["role_name"] = user.role.name if user.role else ""
    data["is_admin"] = is_admin(user)
    data["permissions"] = feature_permission_payload(db, user)
    data["must_change_password"] = password_change_required(user)
    data.pop("password_hash", None)
    return data


@router.post("/api/password/change")
def change_own_password(
    body: PasswordChangeIn,
    request: Request,
    user: User = Depends(authenticated_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not verify_password(body.current_password, user.password_hash):
        record_audit_log(db, request, "password_change", user=user, success=False, details={"reason": "当前密码错误"})
        db.commit()
        raise HTTPException(status_code=400, detail="当前密码错误")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    policy = get_setting(db, "password_policy", DEFAULT_PASSWORD_POLICY)
    validate_password_policy(body.new_password, policy)
    changed_at = datetime.utcnow()
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = changed_at
    user.password_expires_at = changed_at + timedelta(days=int(policy.get("expiry_days", 180)))
    user.must_change_password = False
    record_audit_log(db, request, "password_change", user=user, success=True, details={"expires_at": user.password_expires_at})
    db.commit()
    return {"changed": True, "password_expires_at": user.password_expires_at}


@router.get("/api/audit-logs")
def list_audit_logs(
    action: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        stmt = select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "username": row.username,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "project_id": row.project_id,
            "success": row.success,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "details": json.loads(row.detail_json or "{}"),
            "occurred_at": row.occurred_at,
        }
        for row in rows
    ]
