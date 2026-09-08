from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import PROJECTS_ROOT, WORKSPACE_ROOT
from ..models import Project, Workpaper, WorkpaperVersion
from .workpaper_catalog import BASIC_WORKPAPER_SPECS, WORKPAPER_STAGE_FOLDERS


# 保留旧名称，避免影响已有调用方。
DEFAULT_TEMPLATE_FILES = BASIC_WORKPAPER_SPECS

TEMPLATE_ROOT = WORKSPACE_ROOT / "IT审计标准" / "IT审计对应底稿模板"
STAGE_FOLDERS = WORKPAPER_STAGE_FOLDERS
PROJECT_FOLDER_STRUCTURE = (
    Path("底稿") / "计划阶段",
    Path("底稿") / "执行阶段",
    Path("底稿") / "结束阶段",
    Path("资料管理"),
    Path("复核记录"),
    Path("项目报告"),
)


def safe_project_folder_part(value: Any, fallback: str = "项目") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(value or "")).strip(" ._")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or fallback)[:100]


def default_project_root(project: Project, base_root: Path | None = None) -> Path:
    root = Path(base_root or PROJECTS_ROOT).expanduser()
    year = str(project.audit_year or "未定年度")
    entity = safe_project_folder_part(project.entity_name or project.name)
    code = safe_project_folder_part(project.code or project.name)
    return root / f"{year}_{entity}_{code}_P{project.id}"


def template_prefill(project: Project) -> dict[str, Any]:
    field_leader = project.field_leader.display_name if project.field_leader else ""
    project_reviewer = ""
    if project.project_leader:
        project_reviewer = project.project_leader.display_name
    elif project.manager:
        project_reviewer = project.manager.display_name
    b_preparers = "、".join(part for part in [project.second_partner_name, field_leader] if part)
    return {
        "project_name": project.name,
        "project_code": project.code,
        "oa_project_no": project.oa_project_no,
        "ims_project_no": project.ims_project_no,
        "entity_name": project.entity_name,
        "audit_year": project.audit_year,
        "audit_scope_start": project.audit_scope_start.isoformat() if project.audit_scope_start else "",
        "audit_scope_end": project.audit_scope_end.isoformat() if project.audit_scope_end else "",
        "audit_scope": f"{project.audit_scope_start or ''}至{project.audit_scope_end or ''}",
        "preparer": field_leader,
        "reviewer": project_reviewer,
        "b_preparer": b_preparers,
        "b_reviewer": project.first_partner_name,
    }


def _remove_created_paths(files: list[Path], directories: list[Path]) -> None:
    for path in reversed(files):
        path.unlink(missing_ok=True)
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            continue


def _ensure_directory(path: Path, created_directories: list[Path]) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current == current.parent:
            break
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    created_directories.extend(reversed(missing))


def rollback_project_workspace(report: dict[str, Any] | None) -> None:
    if not report:
        return
    files = [Path(value) for value in report.get("_created_files", [])]
    directories = [Path(value) for value in report.get("_created_directories", [])]
    _remove_created_paths(files, directories)


def public_workspace_report(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if not key.startswith("_")}


def initialize_project_workspace(db: Session, project: Project) -> dict[str, Any]:
    """Create a project-owned workpaper tree, copy templates and fill standard headers."""
    if not project.project_root:
        raise ValueError("项目根目录不能为空")
    root = Path(project.project_root).expanduser()
    if project.project_type != "it_audit":
        # 非 IT 项目使用项目目录下已有的资料和底稿，不复制 IT 审计标准模板。
        return {
            "project_root": str(root),
            "folders_created": 0,
            "workpapers_created": 0,
            "versions_created": 0,
            "header_files_updated": 0,
            "header_fields_changed": 0,
            "headers": [],
            "_created_files": [],
            "_created_directories": [],
        }
    sources = [(spec, TEMPLATE_ROOT / spec["source"]) for spec in DEFAULT_TEMPLATE_FILES]
    missing = [str(source) for _, source in sources if not source.is_file()]
    if missing:
        raise FileNotFoundError("基础底稿模板缺失：" + "；".join(missing))

    created_files: list[Path] = []
    created_directories: list[Path] = []
    created_workpapers: list[Workpaper] = []
    prefill = template_prefill(project)
    try:
        for relative in PROJECT_FOLDER_STRUCTURE:
            directory = root / relative
            if not directory.exists():
                _ensure_directory(directory, created_directories)

        for spec, source in sources:
            exists = db.execute(
                select(Workpaper).where(Workpaper.project_id == project.id, Workpaper.code == spec["code"])
            ).scalar_one_or_none()
            if exists is not None:
                continue
            target_dir = root / "底稿" / STAGE_FOLDERS[spec["stage"]]
            target = target_dir / source.name
            if target.exists():
                suffix = 1
                while target.exists():
                    target = target_dir / f"{source.stem}_{suffix}{source.suffix}"
                    suffix += 1
            try:
                shutil.copy2(source, target)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            created_files.append(target)
            is_b = spec["code"].startswith("B")
            extracted = {
                **prefill,
                "preparer": prefill["b_preparer"] if is_b else prefill["preparer"],
                "reviewer": prefill["b_reviewer"] if is_b else prefill["reviewer"],
                "template_source": str(source),
                "workspace_initialized": True,
            }
            workpaper = Workpaper(
                project_id=project.id,
                code=spec["code"],
                name=spec["name"],
                stage=spec["stage"],
                file_path=str(target),
                status="draft",
                # 标准底稿初始为待认领状态；项目成员首次上传时成为编制人。
                preparer_user_id=None,
                extracted_fields_json=json.dumps(extracted, ensure_ascii=False),
            )
            db.add(workpaper)
            db.flush()
            db.add(
                WorkpaperVersion(
                    workpaper_id=workpaper.id,
                    version_no=1,
                    file_path=str(target),
                    original_filename=source.name,
                    uploaded_by_user_id=project.creator_user_id,
                    note="项目创建时由标准模板自动生成",
                )
            )
            created_workpapers.append(workpaper)

        from .workpaper_headers import (
            SUPPORTED_EXCEL,
            SUPPORTED_WORD,
            apply_docx_headers,
            apply_docx_project_placeholders,
            apply_excel_headers,
            scan_workpaper_headers,
            update_workpaper_header_cache,
        )

        updated_files = 0
        changed_fields = 0
        header_results: list[dict[str, Any]] = []
        for workpaper in created_workpapers:
            scan = scan_workpaper_headers(project, workpaper)
            if scan.get("status") == "error":
                raise RuntimeError(f"{workpaper.code} 项目主数据写入检查失败：{scan.get('message') or '未知错误'}")
            fields = scan.get("fields", [])
            path = Path(workpaper.file_path)
            changed = 0
            if fields and path.suffix.lower() in SUPPORTED_EXCEL:
                changed = apply_excel_headers(path, fields)
            elif fields and path.suffix.lower() in SUPPORTED_WORD:
                changed = apply_docx_headers(path, fields)
            if path.suffix.lower() in SUPPORTED_WORD:
                changed += apply_docx_project_placeholders(path, project, workpaper)
            update_workpaper_header_cache(workpaper, fields)
            updated_files += int(bool(fields or changed))
            changed_fields += changed
            header_results.append({
                "workpaper_code": workpaper.code,
                "status": scan.get("status"),
                "message": scan.get("message", ""),
                "recognized_fields": len(fields),
                "changed_fields": changed,
            })

        return {
            "project_root": str(root),
            "folders_created": len(created_directories),
            "workpapers_created": len(created_workpapers),
            "versions_created": len(created_workpapers),
            "header_files_updated": updated_files,
            "header_fields_changed": changed_fields,
            "headers": header_results,
            "_created_files": [str(path) for path in created_files],
            "_created_directories": [str(path) for path in created_directories],
        }
    except Exception:
        _remove_created_paths(created_files, created_directories)
        raise


def seed_project_template_workpapers(db: Session, project: Project) -> int:
    """Backward-compatible wrapper for callers that only need the created count."""
    return int(initialize_project_workspace(db, project)["workpapers_created"])


def replace_audit_year(text: str, previous_year: Optional[int], next_year: Optional[int]) -> tuple[str, bool]:
    if not text or not previous_year or not next_year:
        return text, False
    updated = text.replace(str(previous_year), str(next_year))
    return updated, updated != text


def copy_workpaper_file(source_path: str, project: Project, name: str, previous_year: Optional[int]) -> str:
    if not source_path or not project.project_root:
        return ""
    src = Path(source_path).expanduser()
    if not src.exists() or not src.is_file():
        return ""
    target_root = Path(project.project_root).expanduser() / "底稿引用"
    target_root.mkdir(parents=True, exist_ok=True)
    target_name, _ = replace_audit_year(src.name, previous_year, project.audit_year)
    if target_name == src.name and project.audit_year:
        target_name = f"{src.stem}_{project.audit_year}{src.suffix}"
    dst = target_root / target_name
    shutil.copy2(src, dst)
    return str(dst)
