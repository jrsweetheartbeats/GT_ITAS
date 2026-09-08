from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, ensure_database_exists, safe_database_label
from ..models import Attachment, Project, Workpaper
from ..services.attachments import file_type_for_path, guess_workpaper_for_file, safe_project_code, sanitize_workpaper_code
from ..services.project_scope import infer_audit_scope_from_file_rows
from ..services.workpaper_metadata import merge_workpaper_metadata


DEFAULT_SEARCH_ROOT = Path("/Users/lirui/PycharmProjects/PythonProject")
DEFAULT_BACKUP_DIR = Path(__file__).resolve().parents[1] / "db_backups"
WORKPAPER_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".docx", ".doc"}
ATTACHMENT_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".pdf", ".png", ".jpg", ".jpeg", ".txt", ".csv"}
SKIP_DIR_NAMES = {
    ".git",
    ".svn",
    ".idea",
    ".vscode",
    ".cursor",
    ".codex_work",
    ".codex_tmp",
    "__pycache__",
    "node_modules",
    "site-packages",
    "dist",
    "build",
    ".venv",
    "venv",
    "logs",
    "render_check",
    "_report_assets",
    "outputs",
    "output",
}
NEGATIVE_PATH_TOKENS = {
    "报销",
    "交通费",
    "发票",
    "客户提供资料",
    "客户提供数据",
    "公司提供资料",
    "原始资料",
    "银行账户",
    "对账单",
    "凭证抽样",
    "销售穿行抽样",
    "采购穿行抽样",
    "用户行为分析自动化",
    "代码脚本",
    "scripts",
    "会计分录测试",
}
EVIDENCE_PATH_TOKENS = {"审计证据", "证据", "附件", "资料管理", "佐证"}
SUPPORT_ATTACHMENT_TOKENS = EVIDENCE_PATH_TOKENS | {"资料", "样本", "穿行", "成本结转"}
SUPPORT_DIR_TOKENS = {"ITAC", "编制中底稿", "资料"}
DELIVERY_CODES = {"C21", "C21-1", "A27", "A27-1", "A14", "A14-3"}
COMPANY_STOP_WORDS = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "集团股份",
    "集团",
    "深圳市",
    "广东",
    "佛山市",
    "中国",
    "2025年IT审计",
    "IT审计",
    "年审",
)


def clean_key(value: str) -> str:
    text = str(value or "").upper()
    for word in COMPANY_STOP_WORDS:
        text = text.replace(word.upper(), "")
    text = re.sub(r"20\d{2}", "", text)
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", text)


def project_match_tokens(project: Project) -> list[str]:
    candidates = [
        project.name.split(" ")[0],
        project.name.replace("2025年IT审计", ""),
        project.entity_name,
        project.code,
        project.oa_project_no,
    ]
    tokens: list[str] = []
    for value in candidates:
        token = clean_key(value)
        if len(token) >= 2 and token not in tokens:
            tokens.append(token)
    return tokens


def path_has_any(path: Path, tokens: set[str]) -> bool:
    text = str(path)
    return any(token in text for token in tokens)


def infer_workpaper_code(path: Path) -> str:
    compact = re.sub(r"\s+", "", path.stem.upper())
    match = re.search(r"(B\d{2}[A-Z]?(?:[-_.]?\d+){0,4}|C\d{2}(?:[-_.]?\d+)?|A\d{2}(?:[-_.]?\d+)?)", compact)
    if not match:
        return ""
    return match.group(1).replace("_", "-").replace(".", "-")


def infer_stage(code: str, path: Path, root: Path) -> str:
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    code_norm = (code or "").upper()
    if code_norm in DELIVERY_CODES or code_norm.startswith("A27") or code_norm.startswith("A14"):
        return "delivery"
    if "3.项目交付" in rel or "项目交付" in rel or "项目总结" in rel:
        return "delivery"
    if "4.项目报告" in rel or "项目报告" in rel:
        return "reporting"
    if "1.项目准备" in rel or "项目准备" in rel or "项目计划" in rel:
        return "planning"
    if code_norm.startswith("B"):
        return "planning"
    return "execution"


def is_workpaper_file(path: Path, root: Path) -> bool:
    if path.suffix.lower() not in WORKPAPER_EXTENSIONS:
        return False
    code = infer_workpaper_code(path)
    if not code:
        return False
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    if any(token in rel for token in EVIDENCE_PATH_TOKENS):
        return False
    return True


def is_attachment_file(path: Path, root: Path, tokens: set[str] | None = None) -> bool:
    if path.suffix.lower() not in ATTACHMENT_EXTENSIONS:
        return False
    tokens = tokens or EVIDENCE_PATH_TOKENS
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    return any(token in rel for token in tokens)


def scan_files(
    root: Path,
    max_depth: int,
    attachment_tokens: set[str] | None = None,
) -> tuple[list[dict[str, str]], list[Path]]:
    root = root.expanduser()
    if not root.exists() or not root.is_dir():
        return [], []
    workpapers: list[dict[str, str]] = []
    attachments: list[Path] = []
    root_depth = len(root.parts)
    workpaper_paths: set[str] = set()
    for path_text, dirs, files in os.walk(root):
        path = Path(path_text)
        depth = len(path.parts) - root_depth
        dirs[:] = [
            name
            for name in dirs
            if name not in SKIP_DIR_NAMES and not name.startswith(".") and name != "__MACOSX"
        ]
        if depth >= max_depth:
            dirs[:] = []
        for filename in files:
            if filename.startswith("~$") or filename.startswith("."):
                continue
            file_path = path / filename
            suffix = file_path.suffix.lower()
            if suffix not in ATTACHMENT_EXTENSIONS:
                continue
            if path_has_any(file_path, NEGATIVE_PATH_TOKENS):
                continue
            if is_workpaper_file(file_path, root):
                code = infer_workpaper_code(file_path)
                workpaper_paths.add(str(file_path))
                workpapers.append(
                    {
                        "code": code,
                        "name": file_path.stem,
                        "stage": infer_stage(code, file_path, root),
                        "file_path": str(file_path),
                    }
                )
            elif is_attachment_file(file_path, root, attachment_tokens):
                attachments.append(file_path)
    workpapers.sort(key=lambda row: (row["stage"], row["code"], row["file_path"]))
    attachments = sorted(path for path in attachments if str(path) not in workpaper_paths)
    return workpapers, attachments


def has_workpaper_markers(path: Path) -> bool:
    try:
        names = {child.name for child in path.iterdir() if child.is_dir()}
    except OSError:
        return False
    marker_names = {
        "1.项目准备",
        "2.项目实施",
        "3.项目交付",
        "4.项目报告",
        "项目准备",
        "项目实施",
        "项目交付",
        "项目计划",
        "项目总结",
        "IT审计底稿",
        "ITA底稿",
    }
    return bool(names & marker_names) or any("IT审计底稿" in name for name in names)


def candidate_dirs(search_root: Path, max_depth: int) -> list[Path]:
    search_root = search_root.expanduser()
    candidates: list[Path] = []
    root_depth = len(search_root.parts)
    for path_text, dirs, _files in os.walk(search_root):
        path = Path(path_text)
        depth = len(path.parts) - root_depth
        dirs[:] = [
            name
            for name in dirs
            if name not in SKIP_DIR_NAMES and not name.startswith(".") and name != "__MACOSX"
        ]
        if depth > max_depth:
            dirs[:] = []
            continue
        if path == search_root:
            continue
        if path_has_any(path, NEGATIVE_PATH_TOKENS):
            continue
        if depth <= max_depth and has_workpaper_markers(path):
            candidates.append(path)
    candidates.sort(key=lambda item: (len(item.parts), str(item)))
    return candidates


def match_project_root(project: Project, candidates: list[Path]) -> tuple[Path | None, int]:
    tokens = project_match_tokens(project)
    best_path: Path | None = None
    best_score = 0
    for candidate in candidates:
        text = clean_key(str(candidate))
        score = 0
        for token in tokens:
            if token and token in text:
                score = max(score, len(token))
        if score > best_score:
            best_path = candidate
            best_score = score
    return (best_path, best_score) if best_score >= 2 else (None, 0)


def project_support_roots(project: Project, primary_root: Path) -> list[Path]:
    roots: list[Path] = []
    parent = primary_root.parent
    if not parent.exists() or not parent.is_dir():
        return roots
    project_tokens = project_match_tokens(project)
    parent_clean = clean_key(parent.name)
    parent_matches_project = any(
        token in parent_clean or parent_clean in token or (len(token) >= 2 and token[-2:] in parent_clean)
        for token in project_tokens
    )
    for child in parent.iterdir():
        if not child.is_dir() or child == primary_root:
            continue
        if child.name in SKIP_DIR_NAMES or child.name.startswith(".") or path_has_any(child, NEGATIVE_PATH_TOKENS):
            continue
        name_text = child.name.upper()
        if not any(token.upper() in name_text for token in SUPPORT_DIR_TOKENS):
            continue
        clean_name = clean_key(child.name)
        matches_project = False
        for token in project_tokens:
            if token in clean_name or clean_name in token:
                matches_project = True
                break
            if len(token) >= 2 and token[-2:] in clean_name:
                matches_project = True
                break
        if project_tokens and not (matches_project or parent_matches_project):
            continue
        roots.append(child)
    roots.sort(key=lambda item: str(item))
    return roots


def unique_workpapers(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for row in rows:
        key = str(Path(row["file_path"]).expanduser())
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def allocate_index(project: Project, used_indexes: set[str], next_by_code: dict[str, int], workpaper_code: str = "") -> str:
    base = sanitize_workpaper_code(workpaper_code) if workpaper_code else safe_project_code(project)
    start = next_by_code.get(base)
    if start is None:
        start = 1
        prefix = f"{base}-"
        for index_no in used_indexes:
            if index_no.startswith(prefix):
                match = re.search(r"-(\d+)$", index_no)
                if match:
                    start = max(start, int(match.group(1)) + 1)
    while f"{base}-{start}" in used_indexes:
        start += 1
    next_by_code[base] = start + 1
    index_no = f"{base}-{start}"
    used_indexes.add(index_no)
    return index_no


def backup_rows(db: Session, backup_dir: Path) -> str:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"project_file_sync_before_{stamp}.json"
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "database": safe_database_label(),
        "projects": [
            {"id": p.id, "name": p.name, "entity_name": p.entity_name, "project_root": p.project_root}
            for p in db.execute(select(Project).order_by(Project.id)).scalars().all()
        ],
        "workpapers": [
            {"id": w.id, "project_id": w.project_id, "code": w.code, "name": w.name, "stage": w.stage, "file_path": w.file_path}
            for w in db.execute(select(Workpaper).order_by(Workpaper.project_id, Workpaper.id)).scalars().all()
        ],
        "attachments": [
            {
                "id": a.id,
                "project_id": a.project_id,
                "workpaper_id": a.workpaper_id,
                "index_no": a.index_no,
                "title": a.title,
                "file_path": a.file_path,
                "file_type": a.file_type,
                "status": a.status,
            }
            for a in db.execute(select(Attachment).order_by(Attachment.project_id, Attachment.id)).scalars().all()
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def sync_project_files(
    search_root: Path,
    candidate_depth: int,
    file_depth: int,
    apply: bool,
    project_id: int | None = None,
    include_attachments: bool = True,
) -> dict[str, Any]:
    ensure_database_exists()
    with SessionLocal() as db:
        projects_stmt = select(Project).order_by(Project.id)
        if project_id is not None:
            projects_stmt = projects_stmt.where(Project.id == project_id)
        projects = list(db.execute(projects_stmt).scalars().all())
        candidates = candidate_dirs(search_root, candidate_depth)
        summary: dict[str, Any] = {
            "database": safe_database_label(),
            "search_root": str(search_root.expanduser()),
            "candidate_dirs": len(candidates),
            "projects_seen": len(projects),
            "projects_scanned": 0,
            "projects_without_root": 0,
            "project_roots_updated": 0,
            "project_scopes_inferred": 0,
            "project_scopes_updated": 0,
            "workpapers_found": 0,
            "workpapers_created": 0,
            "workpapers_updated": 0,
            "workpapers_relinked": 0,
            "attachments_found": 0,
            "attachments_created": 0,
            "attachments_updated": 0,
            "support_roots_scanned": 0,
            "include_attachments": include_attachments,
            "skipped_projects": [],
            "samples": [],
            "applied": apply,
            "backup_path": "",
        }
        if apply:
            summary["backup_path"] = backup_rows(db, DEFAULT_BACKUP_DIR)
        for project in projects:
            root: Path | None = None
            if project.project_root and Path(project.project_root).expanduser().is_dir():
                root = Path(project.project_root).expanduser()
            else:
                matched, score = match_project_root(project, candidates)
                if matched is not None:
                    root = matched
                    if apply and project.project_root != str(matched):
                        project.project_root = str(matched)
                        summary["project_roots_updated"] += 1
                else:
                    summary["projects_without_root"] += 1
                    summary["skipped_projects"].append({"project_id": project.id, "project_name": project.name, "reason": "未匹配到项目文件夹"})
                    continue
            scan_roots: list[tuple[Path, set[str]]] = [(root, EVIDENCE_PATH_TOKENS)]
            support_roots = project_support_roots(project, root)
            scan_roots.extend((support_root, SUPPORT_ATTACHMENT_TOKENS) for support_root in support_roots)
            summary["support_roots_scanned"] += len(support_roots)
            workpapers = []
            attachment_paths = []
            for scan_root, attachment_tokens in scan_roots:
                root_workpapers, root_attachments = scan_files(scan_root, file_depth, attachment_tokens)
                workpapers.extend(root_workpapers)
                attachment_paths.extend(root_attachments)
            workpapers = unique_workpapers(workpapers)
            attachment_paths = unique_paths(attachment_paths) if include_attachments else []
            if not workpapers and not attachment_paths:
                summary["skipped_projects"].append({"project_id": project.id, "project_name": project.name, "root": str(root), "reason": "项目目录下未识别到底稿或附件"})
                continue
            summary["projects_scanned"] += 1
            summary["workpapers_found"] += len(workpapers)
            summary["attachments_found"] += len(attachment_paths)
            inferred_scope = infer_audit_scope_from_file_rows(workpapers)
            if inferred_scope:
                summary["project_scopes_inferred"] += 1
                scope_changed = (
                    project.audit_year != inferred_scope.audit_year
                    or project.audit_scope_start != inferred_scope.start
                    or project.audit_scope_end != inferred_scope.end
                )
                if apply and scope_changed:
                    project.audit_year = inferred_scope.audit_year
                    project.audit_scope_start = inferred_scope.start
                    project.audit_scope_end = inferred_scope.end
                    summary["project_scopes_updated"] += 1

            existing_workpapers = {
                str(Path(path).expanduser()): wp
                for path, wp in db.execute(
                    select(Workpaper.file_path, Workpaper).where(Workpaper.project_id == project.id)
                ).all()
                if path
            }
            stale_workpapers_by_code: dict[str, list[Workpaper]] = {}
            for existing_workpaper in existing_workpapers.values():
                if existing_workpaper.file_path and Path(existing_workpaper.file_path).expanduser().is_file():
                    continue
                stale_workpapers_by_code.setdefault(existing_workpaper.code.upper(), []).append(existing_workpaper)
            relinked_workpaper_ids: set[int] = set()
            for row in workpapers:
                path_key = str(Path(row["file_path"]).expanduser())
                existing = existing_workpapers.get(path_key)
                if existing is not None:
                    changed = False
                    for field in ("code", "name", "stage"):
                        if getattr(existing, field) != row[field]:
                            if apply:
                                setattr(existing, field, row[field])
                            changed = True
                    if apply:
                        existing.extracted_fields_json = json.dumps(
                            merge_workpaper_metadata(
                                {"source": "按项目文件夹同步", "project_root": str(root)},
                                row["file_path"],
                            ),
                            ensure_ascii=False,
                        )
                    if changed:
                        summary["workpapers_updated"] += 1
                    continue
                stale_candidates = [
                    candidate
                    for candidate in stale_workpapers_by_code.get(row["code"].upper(), [])
                    if candidate.id not in relinked_workpaper_ids
                ]
                if len(stale_candidates) == 1:
                    stale = stale_candidates[0]
                    relinked_workpaper_ids.add(stale.id)
                    summary["workpapers_relinked"] += 1
                    if apply:
                        stale.code = row["code"]
                        stale.name = row["name"]
                        stale.stage = row["stage"]
                        stale.file_path = row["file_path"]
                        stale.extracted_fields_json = json.dumps(
                            merge_workpaper_metadata(
                                {"source": "按项目文件夹重新定位", "project_root": str(root)},
                                row["file_path"],
                            ),
                            ensure_ascii=False,
                        )
                        existing_workpapers[path_key] = stale
                    continue
                summary["workpapers_created"] += 1
                if apply:
                    wp = Workpaper(
                        project_id=project.id,
                        code=row["code"],
                        name=row["name"],
                        stage=row["stage"],
                        file_path=row["file_path"],
                        status="draft",
                        extracted_fields_json=json.dumps(
                            merge_workpaper_metadata(
                                {"source": "按项目文件夹同步", "project_root": str(root)},
                                row["file_path"],
                            ),
                            ensure_ascii=False,
                        ),
                    )
                    db.add(wp)
                    existing_workpapers[path_key] = wp
            if apply:
                db.flush()

            workpaper_list = list(
                db.execute(select(Workpaper).where(Workpaper.project_id == project.id).order_by(Workpaper.code)).scalars().all()
            )
            workpaper_paths = {str(Path(wp.file_path).expanduser()) for wp in workpaper_list if wp.file_path}
            existing_attachments = {
                str(Path(path).expanduser()): att
                for path, att in db.execute(
                    select(Attachment.file_path, Attachment).where(Attachment.project_id == project.id)
                ).all()
                if path
            }
            used_indexes = set(
                index for index in db.execute(select(Attachment.index_no).where(Attachment.project_id == project.id)).scalars().all() if index
            )
            next_by_code: dict[str, int] = {}
            for path in attachment_paths:
                path_key = str(path.expanduser())
                if path_key in workpaper_paths:
                    continue
                wp = guess_workpaper_for_file(path, workpaper_list)
                existing = existing_attachments.get(path_key)
                if existing is not None:
                    changed = False
                    updates = {
                        "title": path.stem,
                        "file_type": file_type_for_path(path),
                        "workpaper_id": wp.id if wp else None,
                        "referenced_in": wp.code if wp else existing.referenced_in,
                    }
                    for field, value in updates.items():
                        if getattr(existing, field) != value:
                            if apply:
                                setattr(existing, field, value)
                            changed = True
                    if changed:
                        summary["attachments_updated"] += 1
                    continue
                index_no = allocate_index(project, used_indexes, next_by_code, wp.code if wp else "")
                summary["attachments_created"] += 1
                if apply:
                    db.add(
                        Attachment(
                            project_id=project.id,
                            workpaper_id=wp.id if wp else None,
                            index_no=index_no,
                            title=path.stem,
                            file_path=path_key,
                            file_type=file_type_for_path(path),
                            referenced_in=wp.code if wp else "",
                            status="active",
                        )
                    )
            if len(summary["samples"]) < 15:
                summary["samples"].append(
                    {
                        "project_id": project.id,
                        "project_name": project.name,
                        "root": str(root),
                        "workpapers": len(workpapers),
                        "attachments": len(attachment_paths),
                    }
                )
        if apply:
            db.commit()
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="按项目文件夹同步底稿和附件到系统")
    parser.add_argument("--search-root", type=Path, default=DEFAULT_SEARCH_ROOT)
    parser.add_argument("--candidate-depth", type=int, default=3)
    parser.add_argument("--file-depth", type=int, default=10)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--workpapers-only", action="store_true", help="只同步项目根目录和底稿，不登记附件")
    args = parser.parse_args()
    result = sync_project_files(
        search_root=args.search_root,
        candidate_depth=args.candidate_depth,
        file_depth=args.file_depth,
        apply=args.apply,
        project_id=args.project_id,
        include_attachments=not args.workpapers_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
