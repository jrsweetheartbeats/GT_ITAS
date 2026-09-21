"""Catalog and helpers for per-chapter courseware notes."""
from __future__ import annotations

from typing import Any


COURSEWARE_CHAPTERS = (
    {"key": "orientation", "title": "一、本节定位与学习目标", "module": "定位与目标"},
    {"key": "concept", "title": "二、核心概念", "module": "核心概念"},
    {"key": "practice", "title": "三、如何落实到审计工作", "module": "程序与证据"},
    {"key": "walkthrough", "title": "四、结合本任务进行推演", "module": "任务推演"},
    {"key": "risk", "title": "五、风险实质与影响传导", "module": "风险实质"},
    {"key": "checklist", "title": "六、完成标准与提交前自查", "module": "完成标准"},
)

CHAPTER_BY_KEY = {item["key"]: item for item in COURSEWARE_CHAPTERS}


def chapter_payload(rows: list[Any]) -> list[dict[str, Any]]:
    by_key = {str(row.chapter_key): row for row in rows}
    payload = []
    for item in COURSEWARE_CHAPTERS:
        row = by_key.get(item["key"])
        payload.append({
            "key": item["key"],
            "title": item["title"],
            "module": item["module"],
            "content": row.content if row is not None else "",
            "updatedAt": row.updated_at.isoformat() if row is not None and row.updated_at else "",
        })
    return payload


def group_notes_by_module(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for note in notes:
        module = str(note.get("module") or "其他")
        bucket = index.get(module)
        if bucket is None:
            bucket = {"module": module, "chapters": []}
            index[module] = bucket
            grouped.append(bucket)
        bucket["chapters"].append(note)
    return grouped
