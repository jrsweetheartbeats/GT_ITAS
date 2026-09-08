from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..core.config import BASE_DIR


CATALOG_PATH = BASE_DIR / "data" / "review_issue_catalog.json"


@lru_cache(maxsize=1)
def review_issue_catalog() -> list[dict[str, Any]]:
    if not CATALOG_PATH.is_file():
        return []
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def filter_review_issue_catalog(
    *,
    scope: str = "",
    workpaper: str = "",
    keyword: str = "",
    limit: int = 2000,
) -> list[dict[str, Any]]:
    scope_key = scope.strip().lower()
    workpaper_key = workpaper.strip().lower()
    keyword_key = keyword.strip().lower()
    rows: list[dict[str, Any]] = []
    for item in review_issue_catalog():
        if scope_key and str(item.get("scope") or "").lower() != scope_key:
            continue
        if workpaper_key and workpaper_key not in str(item.get("workpaper") or "").lower():
            continue
        haystack = " ".join(str(item.get(key) or "") for key in ("workpaper", "index_code", "description", "category")).lower()
        if keyword_key and keyword_key not in haystack:
            continue
        rows.append(item)
        if len(rows) >= limit:
            break
    return rows
