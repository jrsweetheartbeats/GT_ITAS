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


@router.get("/api/roles")
def list_roles(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    return list_dict(db.execute(select(Role).order_by(Role.rank.desc(), Role.id)).scalars().all())


@router.post("/api/roles", status_code=201)
def create_role(body: RoleIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = Role(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.patch("/api/roles/{role_id}")
def update_role(role_id: int, body: RoleIn, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = get_or_404(db, Role, role_id, "角色")
    apply_patch_to_model(item, body.model_dump())
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/roles/{role_id}", status_code=204)
def delete_role(role_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> Response:
    item = get_or_404(db, Role, role_id, "角色")
    db.delete(item)
    db.commit()
    return Response(status_code=204)


