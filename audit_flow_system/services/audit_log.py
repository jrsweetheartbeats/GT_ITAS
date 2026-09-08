from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from ..models import AuditLog, User


def record_audit_log(
    db: Session,
    request: Optional[Request],
    action: str,
    *,
    user: Optional[User] = None,
    username: str = "",
    target_type: str = "",
    target_id: Optional[int] = None,
    project_id: Optional[int] = None,
    success: bool = True,
    details: Optional[dict[str, Any]] = None,
) -> AuditLog:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip() if request else ""
    ip_address = forwarded or (request.client.host if request and request.client else "")
    row = AuditLog(
        user_id=user.id if user else None,
        username=(user.username if user else username)[:120],
        action=action[:80],
        target_type=target_type[:80],
        target_id=target_id,
        project_id=project_id,
        success=success,
        ip_address=ip_address[:80],
        user_agent=(request.headers.get("user-agent", "") if request else "")[:500],
        detail_json=json.dumps(details or {}, ensure_ascii=False, default=str),
        occurred_at=datetime.utcnow(),
    )
    db.add(row)
    return row
