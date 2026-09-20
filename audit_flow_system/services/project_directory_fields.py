"""Helpers for the homepage project-directory columns."""
from __future__ import annotations

import json
from typing import Any


HOME_DIRECTORY_FIELDS = (
    "department",
    "scope_description",
    "business_revenue",
    "charge_with_tax",
    "charge_without_tax",
)


def split_project_description(raw: str | None) -> tuple[dict[str, str], str]:
    """Pull homepage fields out of a JSON description and keep leftover notes."""
    text = str(raw or "").strip()
    empty = {key: "" for key in HOME_DIRECTORY_FIELDS}
    if not text:
        return empty, ""
    try:
        data = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return empty, text
    if not isinstance(data, dict):
        return empty, text
    fields = {key: str(data.get(key) or "").strip() for key in HOME_DIRECTORY_FIELDS}
    leftover: dict[str, Any] = {
        key: value
        for key, value in data.items()
        if key not in HOME_DIRECTORY_FIELDS and key != "_legacy_notes"
    }
    notes = str(data.get("_legacy_notes") or "").strip()
    if leftover:
        if notes:
            leftover["_legacy_notes"] = notes
        return fields, json.dumps(leftover, ensure_ascii=False)
    return fields, notes
