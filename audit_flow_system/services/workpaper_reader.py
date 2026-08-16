from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from docx import Document
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..core.utils import obj_dict
from ..models import Attachment, Workpaper


STAGE_ORDER = ("planning", "execution", "delivery", "reporting")
REQUIRED_DELIVERY_CODES = ("C21-1", "C21", "A27-1", "A14-3")
STAGE_LABELS = {
    "planning": "1.项目准备",
    "execution": "2.项目实施",
    "delivery": "3.项目交付",
    "reporting": "4.项目报告",
    "completion": "3.项目交付",
}


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage or "", stage or "未分组")


def workpaper_node(workpaper: Workpaper) -> dict[str, Any]:
    return {
        "id": f"workpaper-{workpaper.id}",
        "type": "workpaper",
        "label": f"{workpaper.code} {workpaper.name}".strip(),
        "workpaper_id": workpaper.id,
        "code": workpaper.code,
        "name": workpaper.name,
        "stage": workpaper.stage,
        "status": workpaper.status,
        "file_path": workpaper.file_path,
        "children": [],
    }


def attachment_node(attachment: Attachment) -> dict[str, Any]:
    label = " ".join(part for part in [attachment.index_no, attachment.title] if part).strip()
    return {
        "id": f"attachment-{attachment.id}",
        "type": "attachment",
        "label": label or attachment.file_path or f"附件 {attachment.id}",
        "attachment_id": attachment.id,
        "workpaper_id": attachment.workpaper_id,
        "index_no": attachment.index_no,
        "name": attachment.title,
        "file_type": attachment.file_type,
        "status": attachment.status,
        "file_path": attachment.file_path,
        "referenced_in": attachment.referenced_in,
        "children": [],
    }


def attachment_sheet_name(attachment: Attachment) -> str:
    reference = (attachment.referenced_in or "").strip()
    candidates = [
        r"\[([^\]]+)\]",
        r"([^!\s,，;；]+)!\$?[A-Z]{1,3}\$?\d+",
        r"(?:sheet|工作表|页签|表单)\s*[:：]\s*([^,，;；\s]+)",
    ]
    for pattern in candidates:
        match = re.search(pattern, reference, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()[:80] or "未识别Sheet"
    return "未识别Sheet"


def safe_node_part(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value or "").strip("-")[:80] or "sheet"


def attachment_folder_node(parent_id: str, attachments: list[Attachment]) -> dict[str, Any]:
    by_sheet: dict[str, list[Attachment]] = {}
    for attachment in attachments:
        by_sheet.setdefault(attachment_sheet_name(attachment), []).append(attachment)
    sheet_nodes = [
        {
            "id": f"{parent_id}-attachments-sheet-{safe_node_part(sheet)}",
            "type": "attachment_sheet_folder",
            "label": sheet,
            "sheet": sheet,
            "status": str(len(rows)),
            "children": [attachment_node(attachment) for attachment in rows],
        }
        for sheet, rows in sorted(by_sheet.items(), key=lambda item: (item[0] == "未识别Sheet", item[0]))
    ]
    return {
        "id": f"{parent_id}-attachments",
        "type": "attachment_folder",
        "label": "附件文件夹",
        "status": str(len(attachments)),
        "children": sheet_nodes,
    }


def delivery_placeholder_node(code: str) -> dict[str, Any]:
    return {
        "id": f"delivery-required-{code}",
        "type": "workpaper_placeholder",
        "label": f"{code} 未登记",
        "code": code,
        "name": f"{code}（未登记）",
        "stage": "delivery",
        "status": "missing",
        "children": [],
    }


def normalize_code(code: str) -> str:
    return (code or "").strip().upper()


def preview_recognition_note(workpaper: Workpaper) -> str:
    code = normalize_code(workpaper.code)
    if tree_stage_for_workpaper(workpaper) == "planning" or code.startswith(("A", "B")) or code in {"C21", "C21-1"}:
        return "已按底稿结构展示可识别内容。"
    return "该底稿暂不识别关键字段，仅展示可读取的文件内容。"


def tree_stage_for_workpaper(workpaper: Workpaper) -> str:
    code = normalize_code(workpaper.code)
    path = workpaper.file_path or ""
    if code in {normalize_code(item) for item in REQUIRED_DELIVERY_CODES} or code.startswith(("A27", "A14")):
        return "delivery"
    if "3.项目交付" in path or "项目交付" in path or "项目总结" in path:
        return "delivery"
    if "4.项目报告" in path or "项目报告" in path:
        return "reporting"
    if "1.项目准备" in path or "项目准备" in path or "项目计划" in path:
        return "planning"
    return workpaper.stage or "unknown"


def ensure_delivery_workpapers(delivery_group: dict[str, Any]) -> None:
    children = delivery_group["children"]
    by_code = {normalize_code(child.get("code", "")): child for child in children if child.get("code")}
    ordered: list[dict[str, Any]] = []
    used: set[int] = set()
    for code in REQUIRED_DELIVERY_CODES:
        node = by_code.get(normalize_code(code)) or delivery_placeholder_node(code)
        ordered.append(node)
        used.add(id(node))
    ordered.extend(child for child in children if id(child) not in used)
    delivery_group["children"] = ordered


def build_workpaper_tree(workpapers: list[Workpaper], attachments: list[Attachment] | None = None) -> list[dict[str, Any]]:
    attachments = attachments or []
    workpaper_ids = {workpaper.id for workpaper in workpapers}
    attachments_by_workpaper: dict[int, list[Attachment]] = {}
    loose_attachments: list[Attachment] = []
    for attachment in attachments:
        if attachment.workpaper_id and attachment.workpaper_id in workpaper_ids:
            attachments_by_workpaper.setdefault(attachment.workpaper_id, []).append(attachment)
        else:
            loose_attachments.append(attachment)

    groups: dict[str, dict[str, Any]] = {
        key: {
            "id": f"stage-{key}",
            "type": "stage",
            "label": stage_label(key),
            "stage": key,
            "children": [],
        }
        for key in STAGE_ORDER
    }
    for wp in workpapers:
        key = tree_stage_for_workpaper(wp)
        group = groups.setdefault(
            key,
            {
                "id": f"stage-{key}",
                "type": "stage",
                "label": stage_label(key),
                "stage": key,
                "children": [],
            },
        )
        node = workpaper_node(wp)
        node["stage"] = key
        linked_attachments = attachments_by_workpaper.get(wp.id, [])
        if linked_attachments:
            node["children"].append(attachment_folder_node(node["id"], linked_attachments))
        group["children"].append(node)
    if loose_attachments:
        groups["execution"]["children"].append(attachment_folder_node("stage-execution-loose", loose_attachments))
    ensure_delivery_workpapers(groups["delivery"])
    known = [groups[key] for key in STAGE_ORDER]
    unknown = [groups[key] for key in sorted(groups) if key not in STAGE_ORDER]
    return known + unknown


def preview_lines_from_excel(path: Path, max_lines: int) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    wb = load_workbook(path, read_only=True, data_only=True, keep_vba=path.suffix.lower() == ".xlsm")
    try:
        lines: list[str] = []
        sheets: list[str] = []
        sheet_sections: list[dict[str, Any]] = []
        for ws in wb.worksheets:
            sheets.append(ws.title)
            if len(lines) >= max_lines:
                continue
            lines.append(f"[{ws.title}]")
            rows: list[dict[str, Any]] = []
            for row in ws.iter_rows():
                cells: list[dict[str, Any]] = []
                for cell in row:
                    if cell.value in (None, ""):
                        continue
                    value = str(cell.value).strip()
                    if not value:
                        continue
                    cells.append(
                        {
                            "cell": f"{get_column_letter(cell.column)}{cell.row}",
                            "location": f"{ws.title}!{get_column_letter(cell.column)}{cell.row}",
                            "value": value,
                        }
                    )
                if not cells:
                    continue
                rows.append({"row": row[0].row if row else 0, "cells": cells})
                lines.append(" | ".join(f"{cell['cell']} {cell['value']}" for cell in cells))
                if len(lines) >= max_lines:
                    break
            sheet_sections.append({"sheet": ws.title, "rows": rows})
        return lines, sheets, sheet_sections
    finally:
        wb.close()


def preview_lines_from_docx(path: Path, max_lines: int) -> tuple[list[str], list[dict[str, Any]]]:
    doc = Document(path)
    lines: list[str] = []
    rows: list[dict[str, Any]] = []
    for index, paragraph in enumerate(doc.paragraphs, start=1):
        text = paragraph.text.strip()
        if not text:
            continue
        lines.append(f"段落{index} {text}")
        rows.append({"row": index, "cells": [{"cell": f"段落{index}", "location": f"正文!段落{index}", "value": text}]})
        if len(lines) >= max_lines:
            return lines[:max_lines], [{"sheet": "正文", "rows": rows[:max_lines]}]
    for table in doc.tables:
        for row_index, row in enumerate(table.rows, start=1):
            cells = []
            for col_index, cell in enumerate(row.cells, start=1):
                value = cell.text.strip()
                if value:
                    cells.append({"cell": f"表格{row_index}-{col_index}", "location": f"正文!表格{row_index}-{col_index}", "value": value})
            if cells:
                rows.append({"row": row_index, "cells": cells})
                lines.append(" | ".join(f"{cell['cell']} {cell['value']}" for cell in cells))
            if len(lines) >= max_lines:
                return lines[:max_lines], [{"sheet": "正文", "rows": rows[:max_lines]}]
    return lines[:max_lines], [{"sheet": "正文", "rows": rows[:max_lines]}]


def preview_lines_from_text(path: Path, max_lines: int) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()[:max_lines]


def read_workpaper_preview(workpaper: Workpaper, max_lines: int = 120) -> dict[str, Any]:
    data = obj_dict(workpaper)
    data.update(
        {
            "file_exists": False,
            "file_type": "",
            "preview_text": "",
            "lines": [],
            "sheets": [],
            "sheet_sections": [],
            "recognition_note": "",
            "error": "",
        }
    )
    if not workpaper.file_path:
        data["error"] = "底稿未维护文件路径"
        return data
    path = Path(workpaper.file_path).expanduser()
    data["file_path"] = str(path)
    data["file_type"] = path.suffix.lower().lstrip(".")
    data["recognition_note"] = preview_recognition_note(workpaper)
    if not path.exists() or not path.is_file():
        data["error"] = f"底稿文件不存在：{path}"
        return data
    data["file_exists"] = True
    try:
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            lines, sheets, sheet_sections = preview_lines_from_excel(path, max_lines)
            data["lines"] = lines
            data["sheets"] = sheets
            data["sheet_sections"] = sheet_sections
        elif path.suffix.lower() == ".docx":
            lines, sheet_sections = preview_lines_from_docx(path, max_lines)
            data["lines"] = lines
            data["sheet_sections"] = sheet_sections
        elif path.suffix.lower() in {".txt", ".csv"}:
            data["lines"] = preview_lines_from_text(path, max_lines)
        else:
            data["error"] = f"暂不支持预览该文件类型：{path.suffix or '无扩展名'}"
            return data
    except Exception as exc:
        data["error"] = f"底稿预览读取失败：{exc}"
        return data
    data["preview_text"] = "\n".join(data["lines"])
    return data
