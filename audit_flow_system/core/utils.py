from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .db import Base

def obj_dict(obj: Any) -> dict[str, Any]:
    data = {col.key: getattr(obj, col.key) for col in obj.__mapper__.columns}
    if "extracted_fields_json" in data:
        try:
            data["extracted_fields"] = json.loads(data["extracted_fields_json"] or "{}")
        except json.JSONDecodeError:
            data["extracted_fields"] = {}
    return data


def list_dict(rows: list[Any]) -> list[dict[str, Any]]:
    return [obj_dict(row) for row in rows]


def get_or_404(db: Session, model: type[Base], item_id: int, label: str) -> Any:
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    return item


def apply_patch_to_model(item: Any, payload: dict[str, Any]) -> Any:
    for key, value in payload.items():
        if key == "extracted_fields":
            setattr(item, "extracted_fields_json", json.dumps(value, ensure_ascii=False))
        elif hasattr(item, key):
            setattr(item, key, value)
    return item
