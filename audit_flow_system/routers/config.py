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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import BASE_DIR, WORKSPACE_ROOT, deepseek_config_status
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
from ..services.autofill import (
    DEFAULT_AUTOFILL_ALLOWED_FIELD_KEYS,
    autofill_scope_config,
    normalize_autofill_allowed_keys,
)


router = APIRouter()


@router.get("/api/config/deepseek-status")
def get_deepseek_status(user: User = Depends(current_user)) -> dict[str, Any]:
    return deepseek_config_status()


@router.get("/api/config/password-policy")
def get_password_policy(user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_setting(db, "password_policy", DEFAULT_PASSWORD_POLICY)


@router.patch("/api/config/password-policy")
def update_password_policy(
    body: PasswordPolicyIn,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    policy = body.model_dump()
    set_setting(db, "password_policy", policy)
    db.commit()
    return policy


@router.get("/api/config/module-order")
def get_module_order(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"order": normalize_module_order(get_setting(db, "module_order", DEFAULT_MODULE_ORDER))}


@router.patch("/api/config/module-order")
def update_module_order(
    body: dict[str, list[str]],
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    order = normalize_module_order(body.get("order", []))
    set_setting(db, "module_order", order)
    db.commit()
    return {"order": order}


@router.get("/api/config/autofill-scope")
def get_autofill_scope_config(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    keys = get_setting(db, "autofill_allowed_field_keys", DEFAULT_AUTOFILL_ALLOWED_FIELD_KEYS)
    return autofill_scope_config(keys)


@router.patch("/api/config/autofill-scope")
def update_autofill_scope_config(
    body: dict[str, list[str]],
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    keys = normalize_autofill_allowed_keys(body.get("enabled_keys", []))
    set_setting(db, "autofill_allowed_field_keys", keys)
    db.commit()
    return autofill_scope_config(keys)


@router.get("/api/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, int]:
    return {
        "users": db.execute(select(func.count(User.id))).scalar_one(),
        "roles": db.execute(select(func.count(Role.id))).scalar_one(),
        "projects": db.execute(select(func.count(Project.id))).scalar_one(),
        "workpapers": db.execute(select(func.count(Workpaper.id))).scalar_one(),
        "attachments": db.execute(select(func.count(Attachment.id))).scalar_one(),
        "open_findings": db.execute(
            select(func.count(ReviewFinding.id)).where(ReviewFinding.status == "open")
        ).scalar_one(),
    }
