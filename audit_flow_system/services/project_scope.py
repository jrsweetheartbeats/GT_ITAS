from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any, Iterable

from ..models import Workpaper
from .workpaper_metadata import clean_cell_text, extract_workpaper_metadata


DATE_PATTERN = re.compile(
    r"(20\d{2})\s*(?:[./\-年])\s*(\d{1,2})\s*(?:[./\-月])\s*(\d{1,2})\s*日?"
)
YEAR_PATTERN = re.compile(r"20\d{2}")


@dataclass(frozen=True)
class InferredAuditScope:
    audit_year: int
    start: date
    end: date
    source: str
    raw_value: str


def _date_matches(text: str) -> list[date]:
    values: list[date] = []
    for match in DATE_PATTERN.finditer(text or ""):
        try:
            values.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    return values


def parse_audit_scope_text(value: Any, source: str = "") -> InferredAuditScope | None:
    text = clean_cell_text(value)
    if not text:
        return None
    dates = _date_matches(text)
    if len(dates) >= 2:
        start = min(dates)
        end = max(dates)
        return InferredAuditScope(end.year, start, end, source, text)
    if len(dates) == 1:
        end = dates[0]
        return InferredAuditScope(end.year, date(end.year, 1, 1), end, source, text)

    years = [int(item) for item in YEAR_PATTERN.findall(text)]
    if not years:
        return None
    start_year = min(years)
    end_year = max(years)
    return InferredAuditScope(end_year, date(start_year, 1, 1), date(end_year, 12, 31), source, text)


def _load_workpaper_fields(workpaper: Workpaper) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    try:
        loaded = json.loads(workpaper.extracted_fields_json or "{}")
        if isinstance(loaded, dict):
            fields.update(loaded)
    except json.JSONDecodeError:
        pass
    metadata = extract_workpaper_metadata(workpaper.file_path)
    for key, value in metadata.items():
        fields.setdefault(key, value)
    return fields


def _workpaper_priority(workpaper: Workpaper) -> tuple[int, str]:
    code = str(workpaper.code or "").upper()
    name = str(workpaper.name or "")
    path = Path(workpaper.file_path or "")
    text = f"{code} {name} {path.name}".upper()
    if "C22" in text:
        return (0, code or path.name)
    if "C21" in text or "A27" in text:
        return (1, code or path.name)
    return (2, code or path.name)


def infer_audit_scope_from_workpapers(workpapers: Iterable[Workpaper]) -> InferredAuditScope | None:
    for workpaper in sorted(workpapers, key=_workpaper_priority):
        fields = _load_workpaper_fields(workpaper)
        for key in ("audit_plan_period", "plan_period", "audit_period", "header_audit_period"):
            scope = parse_audit_scope_text(fields.get(key), source=f"{workpaper.code or workpaper.name or workpaper.id}:{key}")
            if scope:
                return scope
    return None


def infer_audit_scope_from_file_rows(rows: Iterable[dict[str, Any]]) -> InferredAuditScope | None:
    pseudo_workpapers: list[Workpaper] = []
    for index, row in enumerate(rows):
        file_path = row.get("file_path")
        if not file_path:
            continue
        pseudo_workpapers.append(
            Workpaper(
                id=index,
                code=row.get("code", ""),
                name=row.get("name", ""),
                file_path=file_path,
                extracted_fields_json="{}",
            )
        )
    return infer_audit_scope_from_workpapers(pseudo_workpapers)
