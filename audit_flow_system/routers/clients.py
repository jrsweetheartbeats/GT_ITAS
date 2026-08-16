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
    can_view_project,
    can_upload_documents,
    current_user,
    default_audit_scope,
    ensure_document_uploader,
    ensure_project_editor,
    ensure_feature_permission,
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
    ClientIssuesOut,
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
from ..services.c21_issue_reader import client_c21_issues


router = APIRouter()


@router.get("/api/clients")
def list_clients(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    rows = db.execute(select(Client).order_by(Client.id.desc())).scalars().all()
    payload = []
    for row in rows:
        data = obj_dict(row)
        data["it_contacts"] = list_dict(row.it_contacts)
        payload.append(data)
    return payload


@router.get("/api/clients/{client_id}/issues", response_model=ClientIssuesOut)
def list_client_issues(
    client_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    client = get_or_404(db, Client, client_id, "客户")
    projects = db.execute(select(Project).where(Project.client_id == client.id).order_by(Project.id.desc())).scalars().all()
    visible_projects = [project for project in projects if can_view_project(db, user, project)]
    return client_c21_issues(db, client, visible_projects)


@router.post("/api/clients", status_code=201)
def create_client(body: ClientIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "clients", "edit")
    item = Client(**body.model_dump(), creator_user_id=user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.patch("/api/clients/{client_id}")
def update_client(
    client_id: int,
    body: ClientIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "clients", "edit")
    item = get_or_404(db, Client, client_id, "客户")
    apply_patch_to_model(item, body.model_dump())
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/clients/{client_id}", status_code=204)
def delete_client(client_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    ensure_feature_permission(db, user, "clients", "manage")
    item = get_or_404(db, Client, client_id, "客户")
    linked_projects = db.execute(select(Project).where(Project.client_id == client_id)).scalars().all()
    for project in linked_projects:
        project.client_id = None
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/api/clients/{client_id}/it-contacts", status_code=201)
def create_client_it_contact(
    client_id: int,
    body: ClientITContactIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "clients", "edit")
    get_or_404(db, Client, client_id, "客户")
    item = ClientITContact(client_id=client_id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return obj_dict(item)


@router.delete("/api/client-it-contacts/{contact_id}", status_code=204)
def delete_client_it_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    ensure_feature_permission(db, user, "clients", "edit")
    item = get_or_404(db, ClientITContact, contact_id, "客户IT联系人")
    db.delete(item)
    db.commit()
    return Response(status_code=204)
