from __future__ import annotations

from pathlib import Path
import re
import shutil
from typing import Any

from fastapi import HTTPException, UploadFile

from ..autofill_rules import load_rules
from ..core.config import BASE_DIR
from ..models import DocumentRequest, Project


def c22_document_requests_from_rules() -> list[dict[str, Any]]:
    payload = load_rules()
    rows: list[dict[str, Any]] = []
    for rule in payload.get("rules", []):
        if rule.get("scope") != "C22":
            continue
        control_code = str(rule.get("sheet") or rule.get("id") or "")
        evidence = rule.get("evidence", [])
        direction = str(rule.get("content_template") or "")
        if not evidence:
            rows.append(
                {
                    "code": control_code,
                    "title": f"{control_code} {rule.get('name', '')}".strip(),
                    "control_code": control_code,
                    "direction": f"测试方向：{direction or rule.get('name', '')}",
                    "required": True,
                }
            )
            continue
        for index, item in enumerate(evidence, start=1):
            evidence_name = str(item.get("name") or f"{control_code} 支持资料")
            rows.append(
                {
                    "code": f"{control_code}-{index}",
                    "title": evidence_name,
                    "control_code": control_code,
                    "direction": "；".join(
                        part
                        for part in [
                            f"控制程序：{rule.get('name', '')}",
                            f"测试方向：{direction}" if direction else "",
                            f"资料用途：{item.get('purpose', '')}" if item.get("purpose") else "",
                        ]
                        if part
                    ),
                    "required": bool(item.get("required", True)),
                }
            )
    return rows


def safe_upload_name(filename: str) -> str:
    name = Path(filename or "upload.bin").name
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(". ")
    return cleaned or "upload.bin"


def document_upload_root(project: Project) -> Path:
    if project.project_root:
        return Path(project.project_root).expanduser() / "资料管理"
    return BASE_DIR / "uploads" / f"project_{project.id}"


def save_upload_files(project: Project, item: DocumentRequest, files: list[UploadFile]) -> list[str]:
    if not files:
        raise HTTPException(status_code=400, detail="未选择上传文件")
    folder_name = safe_upload_name(f"{item.control_code or item.code}_{item.title}")[:120]
    target_dir = document_upload_root(project) / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for upload in files:
        filename = safe_upload_name(upload.filename or "")
        target = target_dir / filename
        stem = target.stem
        suffix = target.suffix
        counter = 1
        while target.exists():
            target = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        with target.open("wb") as handle:
            shutil.copyfileobj(upload.file, handle)
        saved.append(str(target))
    return saved
