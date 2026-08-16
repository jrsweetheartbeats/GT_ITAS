from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import re
import secrets
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from ..models import FeatureModule, LoginSession, Project, ProjectMember, RoleFeaturePermission, SystemSetting, User

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def default_password_for(username: str, now: Optional[datetime] = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d%H%M")
    return f"{str(username or '').strip().lower()}@{timestamp}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return secrets.compare_digest(candidate, digest)


DEFAULT_PASSWORD_POLICY = {
    "min_length": 8,
    "require_digit": True,
    "require_upper": True,
    "require_lower": True,
    "require_special": True,
    "expiry_days": 180,
}

DEFAULT_MODULE_ORDER = [
    "dashboard",
    "projectWorkspace",
    "qualityDashboard",
    "templates",
    "learning",
    "config",
]


def normalize_module_order(value: Any) -> list[str]:
    if not isinstance(value, list):
        return DEFAULT_MODULE_ORDER.copy()
    raw = [str(item) for item in value]
    if any(item not in DEFAULT_MODULE_ORDER for item in raw):
        return DEFAULT_MODULE_ORDER.copy()
    ordered = ["dashboard"]
    for item in raw:
        if item in DEFAULT_MODULE_ORDER and item != "dashboard" and item not in ordered:
            ordered.append(item)
    for item in DEFAULT_MODULE_ORDER:
        if item not in ordered:
            ordered.append(item)
    return ordered


def get_setting(db: Session, key: str, default: Any) -> Any:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return default


def set_setting(db: Session, key: str, value: Any) -> SystemSetting:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    payload = json.dumps(value, ensure_ascii=False)
    if row is None:
        row = SystemSetting(key=key, value=payload)
        db.add(row)
    else:
        row.value = payload
    return row


def validate_password_policy(password: str, policy: dict[str, Any]) -> None:
    if len(password or "") < int(policy.get("min_length", 6)):
        raise HTTPException(status_code=400, detail=f"密码长度至少 {policy.get('min_length', 6)} 位")
    if policy.get("require_digit") and not re.search(r"\d", password):
        raise HTTPException(status_code=400, detail="密码必须包含数字")
    if policy.get("require_upper") and not re.search(r"[A-Z]", password):
        raise HTTPException(status_code=400, detail="密码必须包含大写字母")
    if policy.get("require_lower") and not re.search(r"[a-z]", password):
        raise HTTPException(status_code=400, detail="密码必须包含小写字母")
    if policy.get("require_special") and not re.search(r"[^0-9A-Za-z]", password):
        raise HTTPException(status_code=400, detail="密码必须包含特殊字符")


def is_admin(user: User) -> bool:
    return bool(user.role and user.role.code == "admin")


MANAGER_MIN_RANK = 700


def is_manager_or_above(user: User) -> bool:
    """Return whether the user may create and arrange projects."""
    return is_admin(user) or bool(user.role and int(user.role.rank or 0) >= MANAGER_MIN_RANK)


def ensure_manager_or_above(user: User) -> None:
    if not is_manager_or_above(user):
        raise HTTPException(status_code=403, detail="仅项目经理级别及以上人员可新建或安排项目")


def role_feature_permissions(db: Session, user: User) -> dict[str, dict[str, bool]]:
    if not user.role_id:
        return {}
    rows = db.execute(
        select(RoleFeaturePermission, FeatureModule)
        .join(FeatureModule, RoleFeaturePermission.feature_module_id == FeatureModule.id)
        .where(RoleFeaturePermission.role_id == user.role_id, FeatureModule.enabled == True)  # noqa: E712
    ).all()
    return {
        module.code: {
            "view": bool(permission.can_view),
            "edit": bool(permission.can_edit),
            "manage": bool(permission.can_manage),
        }
        for permission, module in rows
    }


def feature_permission_payload(db: Session, user: User) -> dict[str, Any]:
    permissions = role_feature_permissions(db, user)
    if is_admin(user):
        modules = db.execute(select(FeatureModule).where(FeatureModule.enabled == True)).scalars().all()  # noqa: E712
        for module in modules:
            permissions[module.code] = {"view": True, "edit": True, "manage": True}
    return permissions


def has_feature_permission(db: Session, user: User, module_code: str, level: str = "view") -> bool:
    if is_admin(user):
        return True
    permission = role_feature_permissions(db, user).get(module_code)
    if not permission:
        return False
    if level == "manage":
        return permission["manage"]
    if level == "edit":
        return permission["edit"] or permission["manage"]
    return permission["view"] or permission["edit"] or permission["manage"]


def ensure_feature_permission(db: Session, user: User, module_code: str, level: str = "view") -> None:
    if not has_feature_permission(db, user, module_code, level):
        label = {"view": "查看", "edit": "编辑", "manage": "管理"}.get(level, level)
        raise HTTPException(status_code=403, detail=f"当前角色无权{label}该功能")


def authenticated_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="未登录")
    session = db.execute(
        select(LoginSession).where(LoginSession.token == token, LoginSession.active == True)  # noqa: E712
    ).scalar_one_or_none()
    if session is None or session.user.status != "active":
        raise HTTPException(status_code=401, detail="登录已失效")
    return session.user


def password_change_required(user: User) -> bool:
    return bool(
        user.must_change_password
        or (user.password_expires_at is not None and user.password_expires_at <= datetime.utcnow())
    )


def current_user(user: User = Depends(authenticated_user)) -> User:
    if password_change_required(user):
        raise HTTPException(status_code=403, detail="PASSWORD_CHANGE_REQUIRED")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    return user


def can_edit_project(user: User, project: Project) -> bool:
    if is_manager_or_above(user):
        return True
    allowed = {
        project.creator_user_id,
        project.project_leader_user_id,
        project.manager_user_id,
    }
    return user.id in allowed


def ensure_project_editor(project: Project, user: User) -> None:
    if not can_edit_project(user, project):
        raise HTTPException(status_code=403, detail="无权编辑该项目")


def default_audit_scope(today: Optional[date] = None) -> tuple[date, date]:
    current = today or date.today()
    year = current.year if current.month >= 10 else current.year - 1
    return date(year, 1, 1), date(year, 12, 31)


def is_project_member(db: Session, project_id: int, user_id: int) -> bool:
    return db.execute(
        select(func.count(ProjectMember.id)).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).scalar_one() > 0


def can_view_project(db: Session, user: User, project: Project) -> bool:
    return can_edit_project(user, project) or is_project_member(db, project.id, user.id)


def ensure_project_viewer(db: Session, project: Project, user: User) -> None:
    if not can_view_project(db, user, project):
        raise HTTPException(status_code=403, detail="无权查看该项目")


def can_upload_documents(db: Session, user: User, project: Project) -> bool:
    return can_view_project(db, user, project)


def ensure_document_uploader(db: Session, project: Project, user: User) -> None:
    if not can_upload_documents(db, user, project):
        raise HTTPException(status_code=403, detail="仅管理员、项目编辑人或项目成员可上传资料")
