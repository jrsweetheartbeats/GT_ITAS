from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


OPEN_LIKE_STATUSES = {
    "pending",
    "waiting",
    "open",
    "assigned",
    "retained",
    "revised",
    "待处理",
    "待复核",
    "已分派",
    "保留",
}

DONE_LIKE_STATUSES = {
    "approved",
    "closed",
    "completed",
    "done",
    "provided",
    "received",
    "resolved",
    "submitted",
    "uploaded",
    "已上传",
    "已关闭",
    "已完成",
    "已提供",
    "已收到",
    "已解决",
    "已提交",
}


def normalize_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text[:10]).date()
        except ValueError:
            return None
    return None


def is_open_like(status: str | None) -> bool:
    raw = str(status or "").strip()
    return raw in OPEN_LIKE_STATUSES or raw.lower() in OPEN_LIKE_STATUSES


def is_done_like(status: str | None) -> bool:
    raw = str(status or "").strip()
    return raw in DONE_LIKE_STATUSES or raw.lower() in DONE_LIKE_STATUSES


def overdue_payload(status: str | None, due: Any, today: date | None = None) -> dict[str, Any]:
    due_date = normalize_date(due)
    current = today or datetime.utcnow().date()
    is_overdue = bool(due_date and is_open_like(status) and current > due_date)
    return {
        "due_date": due_date.isoformat() if due_date else "",
        "is_overdue": is_overdue,
        "overdue_days": (max(0, (current - due_date).days) if due_date else 0),
    }


def days_after(start: date, days: int) -> date:
    return start + timedelta(days=max(0, int(days or 0)))


def waiting_days(entered_at: datetime | None, now: datetime | None = None) -> int:
    if entered_at is None:
        return 0
    current = now or datetime.utcnow()
    return max(0, (current - entered_at).days)
