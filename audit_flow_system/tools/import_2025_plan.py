from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import os
import re
from pathlib import Path
from typing import Any
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.config import WORKSPACE_ROOT
from ..core.db import SessionLocal, ensure_database_exists
from ..core.security import default_audit_scope
from ..models import Client, Project, ProjectMember, User, Workpaper
from ..services.bootstrap import seed_defaults
from ..services.project_scope import infer_audit_scope_from_file_rows
from ..services.workpaper_metadata import merge_workpaper_metadata


WORKBOOK_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
DEFAULT_PLAN_PATH = WORKSPACE_ROOT / "IT 审计需求计划.xlsx"
DEFAULT_SEARCH_ROOT = Path(os.getenv("AUDIT_FLOW_SEARCH_ROOT", str(WORKSPACE_ROOT))).expanduser()
SKIP_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "site-packages",
    "dist",
    "build",
    ".venv",
    "venv",
}
NEGATIVE_PATH_TOKENS = ("报销", "交通费", "客户提供资料", "银行账户", "对账单", "原始资料")
WORKPAPER_EXTENSIONS = {".xlsx", ".xlsm", ".docx"}
REQUIRED_ALEMBIC_REVISION = "0002_design_tables"


@dataclass
class PlanProject:
    row_no: int
    oa_project_no: str
    entity_name: str
    short_name: str
    industry: str
    assurance_type: str
    listed_board: str
    plan_status: str
    audit_period: str
    project_location: str
    branch: str
    audit_department: str
    first_partner_name: str
    second_partner_name: str
    finance_contact: str
    it_manager_name: str
    it_field_leader_name: str
    it_team: str
    planned_field_start: str
    it_field_start: str
    planned_submit_time: str
    system_scope: str
    itac_scope: str
    quote_without_tax: str
    quote_with_tax: str
    separate_contract: str
    remark: str


def shared_text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.findall(".//a:t", WORKBOOK_NS))


def column_index(ref: str) -> int:
    match = re.match(r"([A-Z]+)", ref)
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - 64
    return value - 1


def read_xlsx_rows(path: Path, sheet_name: str) -> dict[int, dict[int, str]]:
    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [shared_text(item) for item in root.findall("a:si", WORKBOOK_NS)]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        target = ""
        for sheet in workbook.findall("a:sheets/a:sheet", WORKBOOK_NS):
            if sheet.attrib["name"] == sheet_name:
                rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                target = rel_targets[rel_id]
                break
        if not target:
            raise ValueError(f"工作簿中不存在 sheet：{sheet_name}")

        sheet_path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
        sheet_root = ET.fromstring(archive.read(sheet_path))
        rows: dict[int, dict[int, str]] = {}
        for row in sheet_root.findall(".//a:sheetData/a:row", WORKBOOK_NS):
            row_no = int(row.attrib.get("r", "0"))
            values: dict[int, str] = {}
            for cell in row.findall("a:c", WORKBOOK_NS):
                idx = column_index(cell.attrib.get("r", "A1"))
                cell_type = cell.attrib.get("t")
                value_el = cell.find("a:v", WORKBOOK_NS)
                inline_el = cell.find("a:is", WORKBOOK_NS)
                value = ""
                if cell_type == "s" and value_el is not None and value_el.text is not None:
                    value = shared_strings[int(value_el.text)]
                elif cell_type == "inlineStr" and inline_el is not None:
                    value = shared_text(inline_el)
                elif value_el is not None and value_el.text is not None:
                    value = value_el.text
                values[idx] = normalize_cell(value)
            rows[row_no] = values
        return rows


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def excel_date_text(value: str) -> str:
    if not re.fullmatch(r"\d+(\.\d+)?", value or ""):
        return value
    number = float(value)
    if number < 30000 or number > 60000:
        return value
    return (datetime(1899, 12, 30) + timedelta(days=number)).date().isoformat()


def parse_plan(path: Path) -> list[PlanProject]:
    rows = read_xlsx_rows(path, "IT审计2025")
    projects: list[PlanProject] = []
    for row_no in sorted(rows):
        if row_no < 9:
            continue
        row = rows[row_no]
        entity_name = row.get(3, "").strip()
        if not entity_name:
            continue
        sequence = row.get(1, "")
        if sequence and not re.fullmatch(r"\d+", sequence):
            continue
        projects.append(
            PlanProject(
                row_no=row_no,
                oa_project_no=row.get(2, ""),
                entity_name=entity_name,
                short_name=row.get(4, ""),
                industry=row.get(5, ""),
                assurance_type=row.get(10, "") or row.get(6, ""),
                listed_board=row.get(7, ""),
                plan_status=row.get(8, ""),
                audit_period=row.get(9, ""),
                project_location=row.get(11, ""),
                branch=row.get(12, ""),
                audit_department=row.get(13, ""),
                first_partner_name=row.get(14, ""),
                second_partner_name=row.get(15, ""),
                finance_contact=row.get(16, ""),
                it_manager_name=row.get(25, ""),
                it_field_leader_name=row.get(26, ""),
                it_team=row.get(27, ""),
                planned_field_start=excel_date_text(row.get(28, "")),
                it_field_start=excel_date_text(row.get(29, "")),
                planned_submit_time=excel_date_text(row.get(31, "")),
                system_scope=row.get(34, ""),
                itac_scope=row.get(35, ""),
                quote_without_tax=row.get(36, ""),
                quote_with_tax=row.get(37, ""),
                separate_contract=row.get(38, ""),
                remark=row.get(39, ""),
            )
        )
    return projects


def project_status(value: str) -> str:
    if "完成" in value:
        return "completed"
    if "现场结束" in value:
        return "fieldwork_done"
    if "未确认" in value:
        return "unconfirmed"
    if "未进场" in value:
        return "planning"
    if "进行" in value:
        return "in_progress"
    return "planning"


def audit_scope_for_period(value: str) -> tuple[int, date, date]:
    years = [int(item) for item in re.findall(r"20\d{2}", value or "")]
    if years:
        start_year = min(years)
        end_year = max(years)
        return end_year, date(start_year, 1, 1), date(end_year, 12, 31)
    if re.search(r"25", value or ""):
        return 2025, date(2025, 1, 1), date(2025, 12, 31)
    start, end = default_audit_scope(date(2026, 3, 1))
    return 2025, start, end


def clean_match_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def iter_candidate_dirs(root: Path, max_depth: int) -> list[Path]:
    root = root.expanduser()
    dirs: list[Path] = []
    for path, names, _ in os_walk_limited(root, max_depth):
        names[:] = [name for name in names if name not in SKIP_DIRS and not name.startswith(".")]
        current = Path(path)
        if current == root:
            continue
        dirs.append(current)
    return dirs


def os_walk_limited(root: Path, max_depth: int):
    root_depth = len(root.parts)
    for path_text, dirs, files in os.walk(root):
        path = Path(path_text)
        depth = len(path.parts) - root_depth
        if depth >= max_depth:
            dirs[:] = []
        yield path, dirs, files


def score_project_dir(project: PlanProject, path: Path) -> int:
    base = clean_match_text(path.name)
    full = clean_match_text(str(path))
    short = clean_match_text(project.short_name)
    entity = clean_match_text(project.entity_name)
    score = 0
    if short and base == short:
        score += 120
    if short and short in base:
        score += 90
    if short and short in full:
        score += 35
    if entity and entity in full:
        score += 70
    if "2025" in full:
        score += 10
    if "it审计" in full or "itgc" in full:
        score += 10
    if "底稿" in full:
        score += 5
    for token in NEGATIVE_PATH_TOKENS:
        if token in str(path):
            score -= 120
    return score


def find_project_root(project: PlanProject, candidates: list[Path]) -> tuple[str, int]:
    best_path = ""
    best_score = 0
    best_len = 10**9
    for path in candidates:
        score = score_project_dir(project, path)
        path_len = len(path.parts)
        if score > best_score or (score == best_score and score > 0 and path_len < best_len):
            best_path = str(path)
            best_score = score
            best_len = path_len
    return (best_path, best_score) if best_score >= 35 else ("", best_score)


def find_project_root_with_workpapers(project: PlanProject, candidates: list[Path]) -> tuple[str, int, list[dict[str, str]]]:
    scored = []
    for path in candidates:
        score = score_project_dir(project, path)
        if score >= 35:
            scored.append((score, len(path.parts), path))
    if not scored:
        return "", 0, []
    scored.sort(key=lambda item: (-item[0], item[1], str(item[2])))
    fallback_score, _, fallback_path = scored[0]
    fallback_workpapers: list[dict[str, str]] = []
    for score, _, path in scored[:12]:
        workpapers = scan_workpapers(str(path))
        if workpapers:
            return str(path), score, workpapers
        if path == fallback_path:
            fallback_workpapers = workpapers
    return str(fallback_path), fallback_score, fallback_workpapers


def infer_workpaper_code(path: Path) -> str:
    compact = re.sub(r"\s+", "", path.stem.upper())
    match = re.search(r"(C22(?:[._-]?[A-Z]{1,3}[._-]?\d+[A-Z]?)?|B\d{2}[A-Z]?(?:-\d+){0,4}|A\d{2}(?:-\d+)*)", compact)
    if match:
        return match.group(1).replace("_", "-").replace(".", "-")
    return ""


def infer_stage(code: str, path: Path) -> str:
    text = clean_match_text(str(path))
    if code.startswith("B") or "项目准备" in text:
        return "planning"
    if code.startswith("A") or "项目交付" in text:
        return "delivery"
    return "execution"


def scan_workpapers(root: str, max_depth: int = 8) -> list[dict[str, str]]:
    if not root:
        return []
    root_path = Path(root).expanduser()
    if not root_path.exists() or not root_path.is_dir():
        return []
    rows: list[dict[str, str]] = []
    root_depth = len(root_path.parts)
    for path_text, dirs, files in os.walk(root_path):
        path = Path(path_text)
        depth = len(path.parts) - root_depth
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")]
        if depth >= max_depth:
            dirs[:] = []
        for filename in files:
            if filename.startswith("~$") or filename.startswith("."):
                continue
            file_path = path / filename
            if file_path.suffix.lower() not in WORKPAPER_EXTENSIONS:
                continue
            code = infer_workpaper_code(file_path)
            if not code:
                continue
            rows.append(
                {
                    "code": code,
                    "name": file_path.stem,
                    "stage": infer_stage(code, file_path),
                    "file_path": str(file_path),
                }
            )
    rows.sort(key=lambda item: (item["stage"], item["code"], item["file_path"]))
    return rows


def split_people(value: str) -> list[str]:
    names = []
    for part in re.split(r"[、,，/；;和]+", value or ""):
        name = part.strip()
        if not name or "实习" in name:
            continue
        if name not in names:
            names.append(name)
    return names


def find_user_id(db: Session, name: str) -> int | None:
    if not name:
        return None
    row = db.execute(select(User).where(User.display_name == name)).scalar_one_or_none()
    return row.id if row else None


def require_migrated_database(db: Session) -> None:
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "数据库尚未完成 Alembic migration，请先执行 `python3 -m alembic upgrade head`。"
        ) from exc
    if revision != REQUIRED_ALEMBIC_REVISION:
        raise RuntimeError(
            f"数据库 Alembic 版本为 {revision or '未初始化'}，需要 {REQUIRED_ALEMBIC_REVISION}；"
            "请先执行 `python3 -m alembic upgrade head`。"
        )


def imported_client_description(project: PlanProject) -> str:
    payload = {
        "source": "IT 审计需求计划.xlsx",
        "short_name": project.short_name,
        "industry": project.industry,
        "listed_board": project.listed_board,
        "project_location": project.project_location,
        "branch": project.branch,
        "audit_department": project.audit_department,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def imported_project_description(project: PlanProject, project_root: str, workpaper_count: int) -> str:
    payload = {
        "source": "IT 审计需求计划.xlsx",
        "plan_row": project.row_no,
        "short_name": project.short_name,
        "assurance_type": project.assurance_type,
        "plan_status": project.plan_status,
        "audit_period": project.audit_period,
        "finance_contact": project.finance_contact,
        "it_manager_name": project.it_manager_name,
        "it_field_leader_name": project.it_field_leader_name,
        "it_team": project.it_team,
        "planned_field_start": project.planned_field_start,
        "it_field_start": project.it_field_start,
        "planned_submit_time": project.planned_submit_time,
        "system_scope": project.system_scope,
        "itac_scope": project.itac_scope,
        "quote_without_tax": project.quote_without_tax,
        "quote_with_tax": project.quote_with_tax,
        "separate_contract": project.separate_contract,
        "matched_project_root": project_root,
        "scanned_workpaper_count": workpaper_count,
        "remark": project.remark,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_projects(plan_path: Path, search_root: Path, max_depth: int, apply: bool) -> dict[str, Any]:
    projects = parse_plan(plan_path)
    candidates = iter_candidate_dirs(search_root, max_depth)
    preview_items = []
    for item in projects:
        root, score, workpapers = find_project_root_with_workpapers(item, candidates)
        preview_items.append({"plan": item, "project_root": root, "match_score": score, "workpapers": workpapers})

    summary = {
        "plan_path": str(plan_path),
        "search_root": str(search_root),
        "plan_projects": len(projects),
        "matched_roots": sum(1 for item in preview_items if item["project_root"]),
        "scanned_workpapers": sum(len(item["workpapers"]) for item in preview_items),
        "clients_created": 0,
        "clients_updated": 0,
        "projects_created": 0,
        "projects_updated": 0,
        "workpapers_created": 0,
        "members_created": 0,
        "applied": apply,
        "samples": [
            {
                "entity_name": item["plan"].entity_name,
                "short_name": item["plan"].short_name,
                "oa_project_no": item["plan"].oa_project_no,
                "project_root": item["project_root"],
                "workpapers": len(item["workpapers"]),
            }
            for item in preview_items[:12]
        ],
    }
    if not apply:
        return summary

    ensure_database_exists()
    with SessionLocal() as db:
        require_migrated_database(db)
        seed_defaults(db)
        admin = db.execute(select(User).where(User.username == "ita_admin")).scalar_one_or_none()
        for item in preview_items:
            plan: PlanProject = item["plan"]
            project_root = item["project_root"]
            workpapers = item["workpapers"]
            client = db.execute(select(Client).where(Client.entity_name == plan.entity_name)).scalar_one_or_none()
            if client is None:
                client = Client(
                    entity_name=plan.entity_name,
                    creator_user_id=admin.id if admin else None,
                    description=imported_client_description(plan),
                )
                db.add(client)
                db.flush()
                summary["clients_created"] += 1
            else:
                client.description = imported_client_description(plan)
                summary["clients_updated"] += 1

            audit_year, scope_start, scope_end = audit_scope_for_period(plan.audit_period)
            inferred_scope = infer_audit_scope_from_file_rows(workpapers)
            if inferred_scope:
                audit_year = inferred_scope.audit_year
                scope_start = inferred_scope.start
                scope_end = inferred_scope.end
            project = None
            if plan.oa_project_no:
                project = db.execute(
                    select(Project).where(Project.oa_project_no == plan.oa_project_no, Project.client_id == client.id)
                ).scalar_one_or_none()
            if project is None:
                project = db.execute(
                    select(Project).where(Project.client_id == client.id, Project.audit_year == audit_year)
                ).scalar_one_or_none()
            if project is None:
                project = Project(client_id=client.id, creator_user_id=admin.id if admin else None)
                db.add(project)
                summary["projects_created"] += 1
            else:
                summary["projects_updated"] += 1

            project.name = f"{plan.short_name or plan.entity_name} {audit_year}年IT审计"
            project.code = plan.oa_project_no or project.code or (plan.short_name or plan.entity_name)
            project.oa_project_no = plan.oa_project_no
            project.client_id = client.id
            project.entity_name = plan.entity_name
            project.audit_year = audit_year
            project.audit_scope_start = scope_start
            project.audit_scope_end = scope_end
            project.status = project_status(plan.plan_status)
            project.project_root = project_root
            project.first_partner_name = plan.first_partner_name
            project.second_partner_name = plan.second_partner_name
            project.manager_user_id = find_user_id(db, plan.it_manager_name)
            project.project_leader_user_id = find_user_id(db, plan.it_field_leader_name) or project.manager_user_id
            project.field_leader_user_id = find_user_id(db, plan.it_field_leader_name)
            project.description = imported_project_description(plan, project_root, len(workpapers))
            db.flush()

            member_names = split_people("、".join([plan.it_manager_name, plan.it_field_leader_name, plan.it_team]))
            for name in member_names:
                user_id = find_user_id(db, name)
                if not user_id:
                    continue
                exists = db.execute(
                    select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id)
                ).scalar_one_or_none()
                if exists is None:
                    db.add(ProjectMember(project_id=project.id, user_id=user_id, role_on_project="项目成员", module="IT审计"))
                    summary["members_created"] += 1

            existing_paths = set(
                db.execute(select(Workpaper.file_path).where(Workpaper.project_id == project.id)).scalars().all()
            )
            for workpaper in workpapers:
                if workpaper["file_path"] in existing_paths:
                    continue
                db.add(
                    Workpaper(
                        project_id=project.id,
                        code=workpaper["code"],
                        name=workpaper["name"],
                        stage=workpaper["stage"],
                        file_path=workpaper["file_path"],
                        status="draft",
                        extracted_fields_json=json.dumps(
                            merge_workpaper_metadata(
                                {"source": "扫描已有项目底稿", "project_root": project_root},
                                workpaper["file_path"],
                            ),
                            ensure_ascii=False,
                        ),
                    )
                )
                existing_paths.add(workpaper["file_path"])
                summary["workpapers_created"] += 1
        db.commit()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 2025 年 IT 审计需求计划和已有项目底稿")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH, help="IT 审计需求计划.xlsx 路径")
    parser.add_argument("--search-root", type=Path, default=DEFAULT_SEARCH_ROOT, help="已有项目底稿扫描根目录")
    parser.add_argument("--max-depth", type=int, default=4, help="项目目录匹配扫描深度")
    parser.add_argument("--apply", action="store_true", help="实际写入数据库；不传时仅预览")
    args = parser.parse_args()
    result = import_projects(args.plan.expanduser(), args.search_root.expanduser(), args.max_depth, args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
