from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import WORKSPACE_ROOT
from ..models import Project, Workpaper


DEFAULT_TEMPLATE_FILES: list[dict[str, str]] = [
    {"code": "B22A-4-1", "name": "IT概要", "stage": "planning", "source": "templates/B22A-4-1_IT概要.xlsx"},
    {"code": "B22A-4-2", "name": "重大业务流程涉及的信息系统", "stage": "planning", "source": "templates/B22A-4-2_重大业务流程涉及的信息系统.xlsx"},
    {"code": "B22A-4-3", "name": "了解IT环境", "stage": "planning", "source": "templates/B22A-4-3_了解IT环境.xlsm"},
    {"code": "B22A-4-4-1", "name": "了解IT一般控制", "stage": "planning", "source": "templates/B22A-4-4-1_了解IT一般控制.xlsx"},
    {"code": "B22A-4-4-2", "name": "IT一般控制职责分离分析", "stage": "planning", "source": "templates/B22A-4-4-2_IT一般控制职责分离分析.xlsx"},
    {"code": "B23-15", "name": "了解信息处理控制", "stage": "planning", "source": "templates/B23-15_了解信息处理控制.xlsx"},
    {"code": "B60-2-1", "name": "IT复杂性判断表", "stage": "planning", "source": "templates/B60-2-1_IT复杂性判断表.docx"},
    {"code": "B60-2-2", "name": "IT审计进场前通知表", "stage": "planning", "source": "templates/B60-2-2_IT审计进场前通知表.docx"},
    {"code": "B60-2-3", "name": "IT审计计划备忘录", "stage": "planning", "source": "templates/B60-2-3_IT审计计划备忘录.docx"},
    {"code": "C22", "name": "IT一般控制测试", "stage": "execution", "source": "templates/C22_IT一般控制测试.xlsx"},
    {"code": "C21", "name": "具有信息技术专业技能的项目组成员", "stage": "reporting", "source": "templates/C21_具有信息技术专业技能的项目组成员.xlsx"},
    {"code": "C21-1", "name": "IT审计发现汇总表", "stage": "reporting", "source": "templates/C21-1_IT审计发现汇总表.xlsx"},
    {"code": "C26", "name": "信息处理控制测试", "stage": "execution", "source": "templates/C26_信息处理控制测试.xlsx"},
    {"code": "A27-1", "name": "IT审计总结备忘录", "stage": "reporting", "source": "templates/A27-1_IT审计总结备忘录.docx"},
]


def template_prefill(project: Project) -> dict[str, Any]:
    field_leader = project.field_leader.display_name if project.field_leader else ""
    project_reviewer = ""
    if project.project_leader:
        project_reviewer = project.project_leader.display_name
    elif project.manager:
        project_reviewer = project.manager.display_name
    b_preparers = "、".join(part for part in [project.second_partner_name, field_leader] if part)
    return {
        "entity_name": project.entity_name,
        "audit_scope": f"{project.audit_scope_start or ''}至{project.audit_scope_end or ''}",
        "preparer": field_leader,
        "reviewer": project_reviewer,
        "b_preparer": b_preparers,
        "b_reviewer": project.first_partner_name,
    }


def seed_project_template_workpapers(db: Session, project: Project) -> int:
    created = 0
    prefill = template_prefill(project)
    target_root: Optional[Path] = None
    if project.project_root:
        target_root = Path(project.project_root).expanduser() / "IT审计底稿模板"
        target_root.mkdir(parents=True, exist_ok=True)
    for spec in DEFAULT_TEMPLATE_FILES:
        exists = db.execute(
            select(Workpaper).where(Workpaper.project_id == project.id, Workpaper.code == spec["code"])
        ).scalar_one_or_none()
        if exists is not None:
            continue
        file_path = ""
        source = WORKSPACE_ROOT / spec["source"]
        if target_root is not None and source.exists() and source.is_file():
            target = target_root / source.name
            if not target.exists():
                shutil.copy2(source, target)
            file_path = str(target)
        is_b = spec["code"].startswith("B")
        extracted = {
            **prefill,
            "preparer": prefill["b_preparer"] if is_b else prefill["preparer"],
            "reviewer": prefill["b_reviewer"] if is_b else prefill["reviewer"],
            "template_source": str(source),
        }
        db.add(
            Workpaper(
                project_id=project.id,
                code=spec["code"],
                name=spec["name"],
                stage=spec["stage"],
                file_path=file_path,
                status="draft",
                preparer_user_id=project.field_leader_user_id,
                extracted_fields_json=json.dumps(extracted, ensure_ascii=False),
            )
        )
        created += 1
    return created


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
