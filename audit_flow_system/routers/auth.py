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
    feature_permission_payload,
    get_setting,
    hash_password,
    is_admin,
    normalize_module_order,
    require_admin,
    set_setting,
    validate_password_policy,
    verify_password,
)
from ..core.config import session_ttl_minutes
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
    PasswordResetChallenge,
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
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
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
from ..services.sms import SmsError, mask_mobile, normalize_cn_mobile, send_verification_sms


router = APIRouter()


@router.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@router.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.execute(select(func.count(Role.id))).scalar_one()
    return {"status": "ok", "database": safe_database_label()}


@router.post("/api/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if user is None or user.status != "active" or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    token = secrets.token_urlsafe(40)
    db.add(LoginSession(token=token, user_id=user.id, expires_at=datetime.utcnow() + timedelta(minutes=session_ttl_minutes())))
    db.commit()
    data = obj_dict(user)
    data["role_code"] = user.role.code if user.role else ""
    data["role_name"] = user.role.name if user.role else ""
    data["is_admin"] = is_admin(user)
    data["permissions"] = feature_permission_payload(db, user)
    data.pop("password_hash", None)
    return {"token": token, "user": data}


def _active_user_by_username(db: Session, username: str) -> User:
    user = db.execute(select(User).where(User.username == username.strip())).scalar_one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=400, detail="账号不存在或已停用")
    return user


@router.post("/api/password-reset/request")
def request_password_reset(body: PasswordResetRequestIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _active_user_by_username(db, body.username)
    phone = normalize_cn_mobile(user.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="该账号未登记手机号，请联系管理员在用户资料中补充")
    latest = db.execute(
        select(PasswordResetChallenge)
        .where(PasswordResetChallenge.user_id == user.id)
        .order_by(PasswordResetChallenge.created_at.desc(), PasswordResetChallenge.id.desc())
    ).scalars().first()
    if latest and latest.consumed_at is None and latest.created_at and datetime.utcnow() - latest.created_at < timedelta(seconds=60):
        raise HTTPException(status_code=429, detail="验证码已发送，请 60 秒后再试")
    code = f"{secrets.randbelow(1000000):06d}"
    db.add(PasswordResetChallenge(
        user_id=user.id,
        phone=phone,
        code_hash=hash_password(code),
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    ))
    try:
        sms = send_verification_sms(phone, code)
    except SmsError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()
    payload = {
        "ok": True,
        "maskedPhone": mask_mobile(phone),
        "expiresInSeconds": 300,
        "provider": sms.provider,
        "message": f"验证码已发送至 {mask_mobile(phone)}",
    }
    if sms.debug_code:
        payload["debugCode"] = sms.debug_code
        payload["message"] += "（当前为本地调试模式，未走收费短信通道）"
    return payload


@router.post("/api/password-reset/confirm")
def confirm_password_reset(body: PasswordResetConfirmIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _active_user_by_username(db, body.username)
    if body.new_password != body.new_password.strip() or not body.new_password.strip():
        raise HTTPException(status_code=400, detail="请输入新密码")
    validate_password_policy(body.new_password, get_setting(db, "password_policy", DEFAULT_PASSWORD_POLICY))
    challenge = db.execute(
        select(PasswordResetChallenge)
        .where(
            PasswordResetChallenge.user_id == user.id,
            PasswordResetChallenge.consumed_at.is_(None),
            PasswordResetChallenge.expires_at > datetime.utcnow(),
        )
        .order_by(PasswordResetChallenge.created_at.desc(), PasswordResetChallenge.id.desc())
    ).scalars().first()
    if challenge is None:
        raise HTTPException(status_code=400, detail="验证码无效或已过期，请重新获取")
    if int(challenge.attempt_count or 0) >= 5:
        raise HTTPException(status_code=400, detail="验证码错误次数过多，请重新获取")
    challenge.attempt_count = int(challenge.attempt_count or 0) + 1
    if not verify_password(str(body.code).strip(), challenge.code_hash):
        db.commit()
        raise HTTPException(status_code=400, detail="验证码不正确")
    user.password_hash = hash_password(body.new_password)
    challenge.consumed_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "message": "密码已更新，请使用新密码登录"}


@router.post("/api/logout", status_code=204)
def logout(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    _, _, token = authorization.partition(" ")
    session = db.execute(select(LoginSession).where(LoginSession.token == token)).scalar_one_or_none()
    if session is not None:
        session.active = False
        db.commit()
    return Response(status_code=204)


@router.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    data = obj_dict(user)
    data["role_code"] = user.role.code if user.role else ""
    data["role_name"] = user.role.name if user.role else ""
    data["is_admin"] = is_admin(user)
    data["permissions"] = feature_permission_payload(db, user)
    data.pop("password_hash", None)
    return data
