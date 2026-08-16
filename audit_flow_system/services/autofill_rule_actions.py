from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AutofillRuleAction, User


ACTION_STATUSES = {
    "pending_confirm",
    "skipped",
    "resolved",
    "converted_to_manual_correction",
}


def clean_action_text(value: Any, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip()
    if limit and len(text) > limit:
        return text[:limit]
    return text


def action_key_for(*, rule_id: Any, workpaper_code: Any, target_field: Any, locator: Any) -> str:
    raw = "\u001f".join(
        [
            clean_action_text(rule_id).lower(),
            clean_action_text(workpaper_code).lower(),
            clean_action_text(target_field).lower(),
            clean_action_text(locator).lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def locator_text_for_row(row: dict[str, Any]) -> str:
    return " / ".join(
        clean_action_text(row.get(key))
        for key in ["sheet", "cell", "locator", "paragraph", "table"]
        if clean_action_text(row.get(key))
    )


def action_key_for_row(row: dict[str, Any]) -> str:
    return action_key_for(
        rule_id=row.get("rule_id"),
        workpaper_code=row.get("workpaper_code"),
        target_field=row.get("target_field") or row.get("field"),
        locator=locator_text_for_row(row),
    )


def validate_action_status(status: str) -> str:
    value = clean_action_text(status)
    if value not in ACTION_STATUSES:
        raise HTTPException(status_code=400, detail="不支持的处理状态")
    return value


def action_to_summary(item: AutofillRuleAction) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "action_key": item.action_key,
        "rule_id": item.rule_id,
        "workpaper_code": item.workpaper_code,
        "workpaper_name": item.workpaper_name,
        "target_field": item.target_field,
        "locator": item.locator,
        "action_status": item.action_status,
        "action_note": item.action_note,
        "source_verification_status": item.source_verification_status,
        "conflict_message": item.conflict_message,
        "created_by_user_id": item.created_by_user_id,
        "updated_by_user_id": item.updated_by_user_id,
        "created_at": item.created_at.isoformat() if item.created_at else "",
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }


def list_project_rule_actions(db: Session, project_id: int) -> list[AutofillRuleAction]:
    return (
        db.execute(
            select(AutofillRuleAction)
            .where(AutofillRuleAction.project_id == project_id)
            .order_by(
                AutofillRuleAction.workpaper_code,
                AutofillRuleAction.rule_id,
                AutofillRuleAction.target_field,
                AutofillRuleAction.id,
            )
        )
        .scalars()
        .all()
    )


def action_index_for_project(db: Session, project_id: int) -> dict[str, dict[str, Any]]:
    return {item.action_key: action_to_summary(item) for item in list_project_rule_actions(db, project_id)}


def upsert_project_rule_action(
    db: Session,
    *,
    project_id: int,
    user: User,
    payload: dict[str, Any],
) -> AutofillRuleAction:
    status = validate_action_status(payload.get("action_status") or "pending_confirm")
    locator = clean_action_text(payload.get("locator"), 2000)
    action_key = action_key_for(
        rule_id=payload.get("rule_id"),
        workpaper_code=payload.get("workpaper_code"),
        target_field=payload.get("target_field"),
        locator=locator,
    )
    item = db.execute(
        select(AutofillRuleAction).where(
            AutofillRuleAction.project_id == project_id,
            AutofillRuleAction.action_key == action_key,
        )
    ).scalar_one_or_none()
    now = datetime.utcnow()
    if item is None:
        item = AutofillRuleAction(
            project_id=project_id,
            action_key=action_key,
            created_by_user_id=user.id,
        )
        db.add(item)
    item.rule_id = clean_action_text(payload.get("rule_id"), 160)
    item.workpaper_code = clean_action_text(payload.get("workpaper_code"), 120)
    item.workpaper_name = clean_action_text(payload.get("workpaper_name"), 240)
    item.target_field = clean_action_text(payload.get("target_field"), 240)
    item.locator = locator
    item.action_status = status
    item.action_note = clean_action_text(payload.get("action_note"), 2000)
    item.source_verification_status = clean_action_text(payload.get("source_verification_status"), 40)
    item.conflict_message = clean_action_text(payload.get("conflict_message"), 2000)
    item.updated_by_user_id = user.id
    item.updated_at = now
    db.commit()
    db.refresh(item)
    return item


def patch_project_rule_action(
    db: Session,
    *,
    project_id: int,
    action_id: int,
    user: User,
    payload: dict[str, Any],
) -> AutofillRuleAction | None:
    item = db.execute(
        select(AutofillRuleAction).where(
            AutofillRuleAction.project_id == project_id,
            AutofillRuleAction.id == action_id,
        )
    ).scalar_one_or_none()
    if item is None:
        return None
    if payload.get("action_status") is not None:
        item.action_status = validate_action_status(payload.get("action_status") or "")
    if payload.get("action_note") is not None:
        item.action_note = clean_action_text(payload.get("action_note"), 2000)
    if payload.get("source_verification_status") is not None:
        item.source_verification_status = clean_action_text(payload.get("source_verification_status"), 40)
    if payload.get("conflict_message") is not None:
        item.conflict_message = clean_action_text(payload.get("conflict_message"), 2000)
    item.updated_by_user_id = user.id
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item
