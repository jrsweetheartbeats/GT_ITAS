from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, Optional

from docx import Document
from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .autofill_rules import load_rules


LARGE_WORKBOOK_PREVIEW_LIMIT = 50 * 1024 * 1024
READONLY_SCAN_MAX_ROWS = 300
READONLY_SCAN_MAX_COLS = 160


@dataclass
class FillTarget:
    rule_id: str
    scope: str
    workbook_path: str
    sheet_name: str
    field: str
    locator: str
    cell: str
    old_value: Any
    new_value: Any
    status: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "scope": self.scope,
            "workbook_path": self.workbook_path,
            "sheet_name": self.sheet_name,
            "field": self.field,
            "locator": self.locator,
            "cell": self.cell,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "status": self.status,
            "message": self.message,
        }


def norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def display(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "..."


def load_workbook_for_write_plan(path: Path):
    return load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")


def load_workbook_for_preview(path: Path):
    return load_workbook(
        path,
        read_only=True,
        data_only=False,
        keep_links=False,
        keep_vba=path.suffix.lower() == ".xlsm",
    )


def resolve_sheet_name(wb, sheet_name: str) -> str:
    if not sheet_name:
        return ""
    if sheet_name in wb.sheetnames:
        return sheet_name
    wanted = norm(sheet_name)
    for candidate in wb.sheetnames:
        if norm(candidate) == wanted:
            return candidate
    return sheet_name


def real_cell(ws: Worksheet, cell: Cell | MergedCell) -> Cell | MergedCell:
    if not isinstance(cell, MergedCell):
        return cell
    for merged_range in ws.merged_cells.ranges:
        if cell.coordinate in merged_range:
            return ws.cell(merged_range.min_row, merged_range.min_col)
    return cell


def is_writable_cell(cell: Cell | MergedCell) -> bool:
    return not isinstance(cell, MergedCell)


def find_label_cell(ws: Worksheet, label: str, *, allow_contains: bool = True) -> Optional[Cell]:
    wanted = norm(label)
    if not wanted:
        return None
    for row in ws.iter_rows():
        for cell in row:
            text = norm(cell.value)
            if text == wanted or (allow_contains and wanted in text):
                resolved = real_cell(ws, cell)
                return resolved if isinstance(resolved, Cell) else None
    return None


def find_any_label_cell(ws: Worksheet, labels: list[str]) -> Optional[Cell]:
    for label in labels:
        cell = find_label_cell(ws, label, allow_contains=False)
        if cell is not None:
            return cell
    for label in labels:
        cell = find_label_cell(ws, label)
        if cell is not None:
            return cell
    return None


def cell_right(ws: Worksheet, cell: Cell, offset: int = 1) -> Cell | MergedCell:
    return real_cell(ws, ws.cell(cell.row, cell.column + offset))


def cell_below(ws: Worksheet, cell: Cell, offset: int = 1) -> Cell | MergedCell:
    return real_cell(ws, ws.cell(cell.row + offset, cell.column))


def first_distinct_right_cell(ws: Worksheet, label_cell: Cell, max_offset: int = 12) -> Cell | MergedCell:
    fallback: Cell | MergedCell = cell_right(ws, label_cell, 1)
    for offset in range(1, max_offset + 1):
        candidate = cell_right(ws, label_cell, offset)
        if candidate.coordinate != label_cell.coordinate:
            return candidate
    return fallback


def right_value_cell(ws: Worksheet, label_cell: Cell) -> Cell | MergedCell:
    fallback = first_distinct_right_cell(ws, label_cell)
    for offset in range(1, 13):
        candidate = cell_right(ws, label_cell, offset)
        if candidate.coordinate == label_cell.coordinate:
            continue
        if candidate.value not in (None, ""):
            return candidate
    return fallback


def resolve_profile_locator(profiles: dict[str, Any], locator: str) -> dict[str, Any]:
    current: Any = profiles
    for part in locator.split("."):
        if not isinstance(current, dict) or part not in current:
            return {}
        current = current[part]
    return current if isinstance(current, dict) else {}


def resolve_target_cell(ws: Worksheet, profiles: dict[str, Any], target: dict[str, Any]) -> tuple[Optional[Cell | MergedCell], str]:
    locator = target.get("locator", "")
    profile = resolve_profile_locator(profiles, locator) if locator else {}
    label = target.get("label") or profile.get("label")
    labels = target.get("labels") or profile.get("labels")
    write_mode = target.get("write") or profile.get("write", "same_row_right")

    label_cell: Optional[Cell]
    if labels:
        label_cell = find_any_label_cell(ws, list(labels))
    elif label:
        label_cell = find_label_cell(ws, str(label))
    else:
        return None, "target has no label locator"

    if label_cell is None:
        return None, f"label not found: {label or labels}"

    if write_mode == "next_non_empty_or_right":
        return right_value_cell(ws, label_cell), ""
    if write_mode == "same_column_below":
        return cell_below(ws, label_cell), ""
    if write_mode == "same_row_right":
        return first_distinct_right_cell(ws, label_cell), ""
    return cell_right(ws, label_cell), f"unknown write mode {write_mode}, used same_row_right"


def locate_header_range(ws: Worksheet, headers: list[str]) -> tuple[str, str]:
    wanted = [norm(header) for header in headers if header]
    if not wanted:
        return "", "target has no headers"
    for row_idx in range(1, ws.max_row + 1):
        found_cols: list[int] = []
        row_values = [ws.cell(row_idx, col_idx).value for col_idx in range(1, ws.max_column + 1)]
        compact_values = [norm(value) for value in row_values]
        for header in wanted:
            matched_col = None
            for col_idx, text in enumerate(compact_values, start=1):
                if header == text or header in text:
                    matched_col = col_idx
                    break
            if matched_col is None:
                break
            found_cols.append(matched_col)
        if len(found_cols) == len(wanted):
            start_col = min(found_cols)
            end_col = max(found_cols)
            next_row = row_idx + 1
            return f"{get_column_letter(start_col)}{next_row}:{get_column_letter(end_col)}{next_row}", ""
    return "", f"headers not found: {headers}"


def locate_header_columns(ws: Worksheet, headers: list[str]) -> tuple[Optional[int], dict[str, int], str]:
    wanted = [(header, norm(header)) for header in headers if header]
    if not wanted:
        return None, {}, "target has no headers"
    for row_idx in range(1, ws.max_row + 1):
        matched: dict[str, int] = {}
        compact_values = [norm(ws.cell(row_idx, col_idx).value) for col_idx in range(1, ws.max_column + 1)]
        for original, header in wanted:
            for col_idx, text in enumerate(compact_values, start=1):
                if header == text or header in text:
                    matched[original] = col_idx
                    break
        if len(matched) >= max(2, min(len(wanted), 3)):
            return row_idx, matched, ""
    return None, {}, f"headers not found: {headers}"


def readonly_iter_values(ws, *, max_rows: int = READONLY_SCAN_MAX_ROWS, max_cols: int = READONLY_SCAN_MAX_COLS):
    column_limit = min(ws.max_column or max_cols, max_cols)
    for row_idx, row_values in enumerate(
        ws.iter_rows(max_row=max_rows, max_col=column_limit, values_only=True),
        start=1,
    ):
        yield row_idx, list(row_values)


def readonly_find_label_cell(ws, labels: list[str]) -> tuple[str, Any, str]:
    wanted = [norm(label) for label in labels if label]
    if not wanted:
        return "", None, "target has no label locator"
    for row_idx, row_values in readonly_iter_values(ws):
        compact_values = [norm(value) for value in row_values]
        for col_idx, text in enumerate(compact_values, start=1):
            if not text or not any(label == text or label in text for label in wanted):
                continue
            target_col = min(col_idx + 1, len(row_values))
            old_value = row_values[target_col - 1] if target_col - 1 < len(row_values) else None
            return f"{get_column_letter(target_col)}{row_idx}", old_value, ""
    return "", None, "label not found: " + " | ".join(labels)


def readonly_locate_header_range(ws, headers: list[str]) -> tuple[str, str]:
    wanted = [norm(header) for header in headers if header]
    if not wanted:
        return "", "target has no headers"
    for row_idx, row_values in readonly_iter_values(ws):
        compact_values = [norm(value) for value in row_values]
        found_cols: list[int] = []
        for header in wanted:
            matched_col = None
            for col_idx, text in enumerate(compact_values, start=1):
                if header == text or header in text:
                    matched_col = col_idx
                    break
            if matched_col is None:
                break
            found_cols.append(matched_col)
        if len(found_cols) == len(wanted):
            start_col = min(found_cols)
            end_col = max(found_cols)
            next_row = row_idx + 1
            return f"{get_column_letter(start_col)}{next_row}:{get_column_letter(end_col)}{next_row}", ""
    return "", f"headers not found in first {READONLY_SCAN_MAX_ROWS} rows: {headers}"


def suggestion_attachments(suggestion: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for evidence in suggestion.get("matched_evidence", []):
        for att in evidence.get("attachments", []):
            key = str(att.get("id") or att.get("index_no") or att.get("title") or att.get("file_path"))
            if key in seen:
                continue
            seen.add(key)
            result.append(att)
    return result


def compact_attachment_text(attachments: list[dict[str, Any]]) -> str:
    return norm(
        " ".join(
            " ".join(str(att.get(key, "")) for key in ("index_no", "title", "file_path"))
            for att in attachments
        )
    )


SYSTEM_KEYWORDS: list[tuple[str, list[str]]] = [
    ("小艾系统", ["小艾系统", "小艾"]),
    ("金蝶云星空系统", ["金蝶云星空", "云星空"]),
    ("资金系统", ["资金系统", "资金管理系统", "保融科技"]),
    ("用友U8系统", ["u8", "用友u8"]),
    ("用友NC系统", ["nc", "用友nc"]),
    ("金蝶EAS系统", ["eas", "金蝶eas"]),
    ("金蝶系统", ["金蝶"]),
    ("SAP系统", ["sap"]),
    ("Oracle ERP系统", ["oracle ebs", "oracle erp"]),
    ("CRM系统", ["crm", "客户关系"]),
    ("MES系统", ["mes", "制造执行"]),
    ("WMS系统", ["wms", "仓储", "仓库管理"]),
    ("SRM系统", ["srm", "供应商关系"]),
    ("PLM系统", ["plm", "产品生命周期"]),
    ("数据仓库", ["数据仓库", "数仓", "dwh"]),
    ("商城系统", ["商城", "电商"]),
    ("旺店通系统", ["旺店通", "wdt"]),
    ("OA系统", ["oa", "办公"]),
    ("BOSS系统", ["boss"]),
    ("ERP系统", ["erp"]),
    ("财务共享系统", ["财务共享"]),
]


PROCESS_KEYWORDS: list[tuple[str, list[str], str]] = [
    ("销售与收款", ["销售", "收款", "收入", "订单", "应收"], "销售、订单、收入确认、应收"),
    ("采购与付款", ["采购", "付款", "供应商", "应付"], "采购、供应商、应付"),
    ("生产/存货与成本", ["生产", "存货", "库存", "成本", "wms", "仓储"], "生产、库存、成本"),
    ("费用与报销", ["费用", "报销", "预算"], "费用报销、预算"),
    ("资金管理", ["资金", "银行", "银企", "网银"], "资金、银行、付款"),
    ("总账与财务报告", ["总账", "凭证", "报表", "财务报告", "会计分录"], "总账、凭证、报表"),
    ("人力资源与薪酬", ["人力", "薪酬", "工资", "员工", "花名册"], "人力资源、薪酬"),
]


def infer_systems(text: str) -> list[str]:
    systems: list[str] = []
    for name, keywords in SYSTEM_KEYWORDS:
        if name == "金蝶系统" and any(item in systems for item in ["金蝶云星空系统", "金蝶EAS系统"]):
            continue
        if any(norm(keyword) in text for keyword in keywords) and name not in systems:
            systems.append(name)
    return systems


def infer_process_rows(suggestion: dict[str, Any]) -> list[dict[str, str]]:
    attachments = suggestion_attachments(suggestion)
    prep_attachments = [
        att for att in attachments
        if not str(att.get("index_no", "")).upper().startswith("C22.")
    ]
    if prep_attachments:
        attachments = prep_attachments
    text = compact_attachment_text(attachments)
    systems = infer_systems(text)
    systems_text = "、".join(systems) if systems else "主要财务及业务系统"
    rows: list[dict[str, str]] = []
    for process, keywords, module in PROCESS_KEYWORDS:
        if any(norm(keyword) in text for keyword in keywords):
            rows.append(
                {
                    "重大业务流程": process,
                    "涉及的信息系统": systems_text,
                    "关键系统模块（如有）": module,
                    "索引号": "B22A-4-3",
                    "对信息系统的依赖程度": "高",
                    "是否纳入本次审计的测试范围": "是",
                    "备注": "由附件名称自动识别，需人工确认系统范围和索引号。",
                }
            )
    if not rows:
        rows.append(
            {
                "重大业务流程": "主要业务流程",
                "涉及的信息系统": systems_text,
                "关键系统模块（如有）": "财务及业务相关模块",
                "索引号": "B22A-4-3",
                "对信息系统的依赖程度": "高",
                "是否纳入本次审计的测试范围": "是",
                "备注": "由附件名称自动识别，需人工确认流程分类、系统范围和索引号。",
            }
        )
    return rows


B41_HEADER_ALIASES = {
    "sequence": ["序号"],
    "system": ["IT应用程序或基础设施", "应用程序或基础设施"],
    "description": ["功能描述", "应用程序描述"],
    "index_no": ["索引号"],
    "factor": ["复杂因素判断要素"],
    "yes_no": ["是/否"],
    "complexity": ["复杂性"],
    "strategy_impact": ["对审计策略的影响", "对审计策略的影响的影响"],
    "remark": ["备注"],
}


SYSTEM_DESCRIPTIONS: list[tuple[list[str], str]] = [
    (["小艾"], "支撑采购、销售、仓储、物流、订单、产品和客服等电商运营与财务相关流程。"),
    (["金蝶云星空", "云星空"], "支撑财务核算、税务、供应链和报表等业财一体化管理。"),
    (["资金系统"], "支撑资金流动性、收付、监控、分析和合规管理等资金流程。"),
    (["oracle ebs", "oracle erp"], "支撑财务核算、采购、销售、库存和报表等业财一体化流程。"),
    (["sap"], "整合财务会计、采购、销售、库存、生产及总账等核心模块，支持主要业务流程和财务报告相关数据处理。"),
    (["u8", "用友u8"], "支撑财务核算、供应链、采购、销售、库存及总账等业务和财务处理。"),
    (["nc", "用友nc"], "支撑集团财务、采购、销售、库存、应收应付及总账等业务财务一体化管理。"),
    (["金蝶"], "支撑财务核算、供应链、采购、销售、库存和报表等业务财务处理。"),
    (["erp"], "支撑采购、销售、库存、生产、成本和财务核算等核心业务流程。"),
    (["crm"], "支撑线索、客户、商机、合同、销售跟进和回款等销售管理流程。"),
    (["mes"], "支撑生产计划执行、工序流转、生产数据采集和质量追溯等生产过程管理。"),
    (["wms", "仓储"], "支撑入库、出库、库存、仓储作业和物流相关数据处理。"),
    (["商城", "电商"], "支撑线上销售、订单、客户、支付或发货等电商业务流程。"),
    (["旺店通"], "支撑订单、库存、发货、退换货和电商业务数据管理。"),
    (["oa"], "支撑审批流、费用报销、合同审批、办公协同和流程流转。"),
    (["oracle", "数据库"], "承载业务系统或财务系统相关数据存储和查询处理。"),
    (["数据仓库", "数仓"], "汇集业务和财务数据，支持报表、分析和管理决策。"),
]


def describe_system(system_name: str, text: str) -> str:
    compact_name = norm(system_name)
    compact_text = norm(text)
    for keywords, description in SYSTEM_DESCRIPTIONS:
        if any(norm(keyword) in compact_name for keyword in keywords):
            return description
    for keywords, description in SYSTEM_DESCRIPTIONS:
        if any(norm(keyword) in compact_text for keyword in keywords):
            return description
    modules = []
    for process, keywords, module in PROCESS_KEYWORDS:
        if any(norm(keyword) in compact_text for keyword in keywords):
            modules.append(module)
    if modules:
        return "支撑" + "、".join(dict.fromkeys(modules)) + "等业务和财务相关流程。"
    return "支撑主要业务流程和财务报告相关数据处理，具体模块和边界需结合系统清单确认。"


def infer_b41_system_rows(suggestion: dict[str, Any]) -> list[dict[str, str]]:
    attachments = suggestion_attachments(suggestion)
    text = compact_attachment_text(attachments)
    systems = infer_systems(text)
    if not systems:
        systems = ["主要财务及业务系统"]
    rows: list[dict[str, str]] = []
    for index, system in enumerate(systems, start=1):
        rows.append(
            {
                "sequence": str(index),
                "system": system,
                "description": describe_system(system, text),
                "index_no": f"B22A-4-3-{index}",
                "remark": "由附件名称自动识别，需人工确认系统边界、接口和复杂性判断。",
            }
        )
    return rows


def locate_b41_columns(ws: Worksheet) -> tuple[Optional[int], dict[str, int], str]:
    system_match = find_header_match(ws, B41_HEADER_ALIASES["system"])
    if system_match is None:
        return None, {}, "B22A-4-1 system header not found"
    header_row = system_match[0]

    def find_near(aliases: list[str], row_start: int, row_end: int) -> Optional[int]:
        normalized_aliases = [norm(alias) for alias in aliases if alias]
        for row_idx in range(row_start, min(ws.max_row, row_end) + 1):
            for col_idx in range(1, ws.max_column + 1):
                text = norm(ws.cell(row_idx, col_idx).value)
                if not text:
                    continue
                if any(alias == text or alias in text for alias in normalized_aliases):
                    return col_idx
        return None

    columns: dict[str, int] = {}
    for field in ("sequence", "system", "description", "index_no", "complexity", "strategy_impact", "remark"):
        col_idx = find_near(B41_HEADER_ALIASES[field], header_row, header_row)
        if col_idx is not None:
            columns[field] = col_idx
    for field in ("factor", "yes_no"):
        col_idx = find_near(B41_HEADER_ALIASES[field], header_row, header_row + 2)
        if col_idx is not None:
            columns[field] = col_idx
    required = {"sequence", "system", "description", "index_no", "factor", "yes_no"}
    missing = sorted(required - set(columns))
    if missing:
        return None, {}, "B22A-4-1 headers not found: " + ", ".join(missing)
    return header_row + 1, columns, ""


def b41_block_start_rows(ws: Worksheet, header_row: int, sequence_col: int, system_col: int) -> list[int]:
    starts: list[int] = []
    for row_idx in range(header_row + 1, ws.max_row + 1):
        seq_value = ws.cell(row_idx, sequence_col).value
        system_value = ws.cell(row_idx, system_col).value
        if str(seq_value or "").strip().isdigit() or system_value not in (None, ""):
            starts.append(row_idx)
    return starts


def b41_factor_answer(system_name: str, factor_text: Any, all_text: str) -> str:
    text = norm(str(factor_text or "") + " " + system_name + " " + all_text)
    system_text = norm(system_name)
    enterprise_system = any(keyword in system_text for keyword in ["sap", "erp", "u8", "nc", "金蝶", "mes", "wms", "crm", "商城", "旺店通", "小艾", "资金系统"])
    if "自动化程序" in text:
        return "是" if enterprise_system else "否"
    if "报告" in text:
        return "是" if any(keyword in text for keyword in ["财务", "报表", "总账", "sap", "erp", "u8", "nc", "金蝶", "数据仓库", "数仓"]) else "否"
    if "接口" in text or "数据输入" in text:
        return "是" if len(infer_systems(all_text)) > 1 or any(keyword in text for keyword in ["接口", "商城", "旺店通", "sap", "erp", "mes", "wms"]) else "否"
    if "大量的数据" in text or "数据仓库" in text:
        return "是" if any(keyword in text for keyword in ["数据仓库", "数仓", "sap", "erp", "商城", "旺店通", "mes", "wms"]) else "否"
    if "定制开发" in text or "重大定制" in text:
        return "是" if any(keyword in text for keyword in ["自研", "定制", "mes", "商城"]) else "否"
    if "复杂的主机" in text or "云基础设施" in text:
        return "是" if any(keyword in text for keyword in ["云", "saas", "服务器", "数据中心"]) else "否"
    if "供应商" in text:
        return "是" if any(keyword in text for keyword in ["供应商", "saas", "第三方", "oracle", "sap", "金蝶", "用友"]) else "否"
    if "跨平台" in text:
        return "是" if len(infer_systems(all_text)) >= 4 else "否"
    if "信息技术部门" in text or "专业技能" in text:
        return "是" if any(keyword in text for keyword in ["it", "信息技术", "运维", "开发"]) else "否"
    if "访问权限" in text:
        return "是" if enterprise_system else "否"
    if "互联网访问" in text:
        return "是" if any(keyword in text for keyword in ["商城", "电商", "crm", "oa", "互联网"]) else "否"
    if "修改" in text or "开发周期" in text or "版本升级" in text or "平台变更" in text:
        return "是" if any(keyword in text for keyword in ["变更", "上线", "发布", "自研", "定制"]) else "否"
    return "否"


def classify_system(system_name: str) -> str:
    text = norm(system_name)
    if "资金系统" in text:
        return "资金管理系统"
    if "小艾" in text:
        return "ERP/业务运营系统"
    if any(keyword in text for keyword in ["sap", "erp", "u8", "nc", "金蝶", "用友"]):
        return "ERP/财务业务系统"
    if any(keyword in text for keyword in ["商城", "电商", "旺店通", "crm"]):
        return "销售/业务系统"
    if any(keyword in text for keyword in ["mes", "wms", "srm", "plm"]):
        return "业务运营系统"
    if "oa" in text:
        return "办公及审批系统"
    return "应用系统"


def database_for_system(system_name: str) -> str:
    text = norm(system_name)
    # 数据库必须以系统清单或 IT 环境调查表为准，不能根据产品名称推测。
    # 例如金蝶云星空在不同项目可能使用 SQL Server 或其他数据库。
    if any(keyword in text for keyword in ["金蝶云星空", "资金系统", "小艾"]):
        return "需根据系统清单确认"
    if "sap" in text:
        return "HANA"
    if any(keyword in text for keyword in ["u8", "sql", "mes", "crm"]):
        return "SQL Server"
    if any(keyword in text for keyword in ["nc", "oracle", "plm"]):
        return "Oracle"
    if any(keyword in text for keyword in ["商城", "旺店通", "wms"]):
        return "MySQL"
    return "需根据系统清单确认"


def os_for_system(system_name: str) -> str:
    text = norm(system_name)
    if any(keyword in text for keyword in ["商城", "旺店通", "nc", "oracle", "sap"]):
        return "Linux"
    if any(keyword in text for keyword in ["u8", "sql", "oa", "crm"]):
        return "Windows Server"
    return "需根据系统清单确认"


def infer_b43_app_rows(suggestion: dict[str, Any]) -> list[dict[str, str]]:
    text = compact_attachment_text(suggestion_attachments(suggestion))
    systems = infer_systems(text) or ["主要财务及业务系统"]
    processes = infer_process_rows(suggestion)
    process_text = "、".join(dict.fromkeys(row["重大业务流程"] for row in processes))
    rows: list[dict[str, str]] = []
    for index, system in enumerate(systems, start=1):
        rows.append(
            {
                "index_no": f"B22A-4-3-1-{index}",
                "category": classify_system(system),
                "system": system,
                "version": system.replace("系统", "") or "-",
                "description": describe_system(system, text),
                "owner": "总公司及相关使用单位",
                "go_live": "需根据系统清单确认",
                "processes": process_text or "主要业务及财务报告相关流程",
                "database": database_for_system(system),
                "os": os_for_system(system),
                "server": "本地机房/云服务器，需根据系统清单确认",
                "network": "局域网/广域网，需根据系统清单确认",
                "maintainer": "IT部门、系统管理员或供应商",
                "third_party": "Yes" if any(keyword in text for keyword in ["供应商", "saas", "云", "idc", "第三方"]) else "No",
            }
        )
    return rows


def infer_b43_infra_rows(app_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for app in app_rows:
        for category, value, suffix in (("数据库", app["database"], "数据库"), ("操作系统", app["os"], "操作系统")):
            if value == "需根据系统清单确认":
                continue
            rows.append(
                {
                    "index_no": f"B22A-4-3-2-{len(rows) + 1}",
                    "name": f"{app['system']}{suffix}",
                    "app": app["system"],
                    "category": category,
                    "version": value,
                    "description": f"支撑{app['system']}运行的{suffix}环境。",
                    "location": app["server"],
                    "maintainer": app["maintainer"],
                    "third_party": app["third_party"],
                }
            )
    rows.append(
        {
            "index_no": f"B22A-4-3-2-{len(rows) + 1}",
            "name": "防火墙及网络安全设备",
            "app": "整体IT环境",
            "category": "网络安全设备",
            "version": "-",
            "description": "用于限制网络边界访问并保护关键系统环境。",
            "location": "机房/云网络边界",
            "maintainer": "IT部门或供应商",
            "third_party": "Yes",
        }
    )
    return rows


def locate_header_row_and_columns(ws: Worksheet, aliases: dict[str, list[str]], required: set[str]) -> tuple[Optional[int], dict[str, int], str]:
    for row_idx in range(1, min(ws.max_row, 20) + 1):
        columns: dict[str, int] = {}
        values = [norm(ws.cell(row_idx, col_idx).value) for col_idx in range(1, ws.max_column + 1)]
        for field, field_aliases in aliases.items():
            normalized_aliases = [norm(alias) for alias in field_aliases]
            for col_idx, text in enumerate(values, start=1):
                if any(alias == text or alias in text for alias in normalized_aliases):
                    columns[field] = col_idx
                    break
        if required <= set(columns):
            return row_idx, columns, ""
    return None, {}, "headers not found: " + ", ".join(sorted(required))


def locate_header_columns_anywhere(ws: Worksheet, aliases: dict[str, list[str]], required: set[str], *, max_row: int = 10) -> tuple[Optional[int], dict[str, int], str]:
    columns: dict[str, int] = {}
    rows: list[int] = []
    for field, field_aliases in aliases.items():
        match = find_header_match(ws, field_aliases, max_row=max_row)
        if match is not None:
            rows.append(match[0])
            columns[field] = match[1]
    missing = sorted(required - set(columns))
    if missing:
        return None, {}, "headers not found: " + ", ".join(missing)
    return max(rows) if rows else None, columns, ""


B43_APP_ALIASES = {
    "index_no": ["索引号", "序号/索引号"],
    "category": ["类别"],
    "system": ["应用程序名称"],
    "version": ["应用程序版本"],
    "description": ["应用程序描述"],
    "owner": ["系统所属单位"],
    "go_live": ["上线时间及最近升级时间"],
    "processes": ["涉及的重大业务流程"],
    "database": ["数据库"],
    "os": ["操作系统"],
    "server": ["服务器设备编号", "服务器的物理位置"],
    "network": ["网络"],
    "maintainer": ["维护此应用程序及其环境的人员"],
    "third_party": ["是否有服务机构或其它第三方参与"],
}

B43_INFRA_ALIASES = {
    "index_no": ["索引号", "序号/索引号"],
    "name": ["名称", "基础设施名称"],
    "app": ["对应的应用程序名称"],
    "category": ["类别"],
    "version": ["版本", "版本（如适用）"],
    "description": ["描述"],
    "location": ["服务器的物理位置"],
    "maintainer": ["维护人员"],
    "third_party": ["服务机构或第三方参与"],
}

B43_PROCESS_ALIASES = {
    "index_no": ["索引号", "序号/索引号"],
    "system": ["应用程序名称"],
    "app_index": ["索引号（应用程序）"],
    "access": ["管理访问权限并向员工提供权限的流程", "管理访问权限并将其提供给员工的流程"],
    "auth": ["对应用程序用户进行身份验证"],
    "access_complexity": ["访问权限管理流程的复杂性", "管理访问权限的过程的复杂性"],
    "security_complexity": ["IT环境安全的复杂性"],
    "change": ["管理变更的流程", "管理变化的过程"],
    "change_level": ["记录 IT 环境的变化程度"],
    "implemented": ["在此期间实施的应用程序"],
    "conversion": ["在此期间的数据转换"],
    "source_code": ["源代码"],
}

B43_INFO_ALIASES = {
    "index_no": ["索引号", "序号/索引号"],
    "system": ["应用程序名称"],
    "app_index": ["索引号（应用程序）"],
    "operations": ["有关IT运作的流程"],
    "communication": ["IT 环境中的通信"],
    "batch": ["自动化处理"],
    "reports": ["系统生成报告"],
    "input": ["将数据输入到 IT 应用程序中"],
    "data_complexity": ["处理数据的数量和复杂性"],
    "customization": ["定制化程度", "描述自定义级别"],
    "emerging": ["新兴技术的使用"],
}


INFO_PROCESSING_HEADERS = [
    "控制类别",
    "信息处理控制索引号",
    "业务流程和交易",
    "财务报表项目",
    "财务报表认定",
    "潜在错报风险",
    "信息处理控制及数据",
    "实际控制活动",
    "自动/人工",
    "预防性/检查性",
    "频率",
    "涉及应用程序",
]

INFO_PROCESSING_TEMPLATES: dict[str, dict[str, str]] = {
    "销售与收款": {
        "控制类别": "系统接口",
        "业务流程和交易": "销售与收款",
        "财务报表项目": "营业收入、应收账款、银行存款",
        "财务报表认定": "完整性、准确性、存在和发生",
        "潜在错报风险": "销售订单、发货、开票或收款数据传递不完整或不准确，导致收入和应收记录错误。",
        "信息处理控制及数据": "销售订单、发货记录、对账/开票信息及收款认领数据。",
        "实际控制活动": "依据销售与收款流程，确认业务系统、商城/CRM/ERP及财务系统内关键单据状态、接口传输和审批流转与流程资料一致，并关注异常或未传输记录的处理。",
        "自动/人工": "自动/人工",
        "预防性/检查性": "预防性/检查性",
        "频率": "按需",
    },
    "采购与付款": {
        "控制类别": "自动控制",
        "业务流程和交易": "采购与付款",
        "财务报表项目": "存货、应付账款、期间费用、银行存款",
        "财务报表认定": "完整性、准确性、存在和发生",
        "潜在错报风险": "采购申请、订单、验收、入库或付款审批未按流程执行，导致采购和付款记录不准确或不完整。",
        "信息处理控制及数据": "采购申请、采购订单、收货/入库、发票、付款申请及审批记录。",
        "实际控制活动": "依据采购与付款关键流程，确认ERP/OA/财务系统中采购申请、订单、收货、发票和付款审批的关键字段、状态流转和控制活动是否与流程图一致。",
        "自动/人工": "自动/人工",
        "预防性/检查性": "预防性/检查性",
        "频率": "按需",
    },
    "生产/存货与成本": {
        "控制类别": "自动控制",
        "业务流程和交易": "生产、存货与成本",
        "财务报表项目": "存货、营业成本、生产成本",
        "财务报表认定": "完整性、准确性、计价或分摊",
        "潜在错报风险": "生产领料、完工入库、库存移动或成本结转数据不完整或不准确，导致存货和成本错报。",
        "信息处理控制及数据": "生产工单、领料/发料、入库、库存移动、成本结转及相关审批状态。",
        "实际控制活动": "从ERP/MES/WMS等系统查看生产订单、领料、材料出库、产成品入库、库存移动和成本结转记录，确认关键单据状态、审批限制和删除/修改限制。",
        "自动/人工": "自动",
        "预防性/检查性": "预防性/检查性",
        "频率": "按需",
    },
    "费用与报销": {
        "控制类别": "自动控制",
        "业务流程和交易": "费用报销",
        "财务报表项目": "期间费用、其他应付款、银行存款",
        "财务报表认定": "完整性、准确性、计价或分摊",
        "潜在错报风险": "报销单据字段、预算校验或审批流配置错误，导致费用确认或付款处理不准确。",
        "信息处理控制及数据": "费用报销申请、预算校验、审批流、付款申请及凭证生成数据。",
        "实际控制活动": "确认OA/费控/财务共享或ERP系统对报销申请必填字段、预算状态、审批流和付款/凭证生成的系统控制是否按流程执行。",
        "自动/人工": "自动",
        "预防性/检查性": "预防性",
        "频率": "按需",
    },
    "资金管理": {
        "控制类别": "自动控制",
        "业务流程和交易": "资金收付",
        "财务报表项目": "银行存款、应收账款、应付账款",
        "财务报表认定": "存在性、完整性、准确性",
        "潜在错报风险": "付款审批、收款认领、银企传输或状态回写错误，导致资金交易金额、对象或入账期间不准确。",
        "信息处理控制及数据": "付款申请、支付审批、收款认领、银企接口、支付状态和回写记录。",
        "实际控制活动": "确认资金系统、网银/银企平台和财务系统之间的付款审批、支付状态回写、收款认领及异常处理记录是否完整准确。",
        "自动/人工": "自动/人工",
        "预防性/检查性": "预防性/检查性",
        "频率": "按需",
    },
    "总账与财务报告": {
        "控制类别": "系统报表",
        "业务流程和交易": "总账与财务报告",
        "财务报表项目": "所有科目",
        "财务报表认定": "完整性、准确性、列报",
        "潜在错报风险": "系统过账、结账或报表生成逻辑不准确，导致财务报表不完整或不准确。",
        "信息处理控制及数据": "总账凭证、过账状态、结账记录、试算平衡表、资产负债表和利润表等系统生成报告。",
        "实际控制活动": "确认总账过账、关账、报表生成和复核流程，关注系统生成报告的数据来源、参数、权限限制和复核留痕。",
        "自动/人工": "自动",
        "预防性/检查性": "预防性/检查性",
        "频率": "每月一次",
    },
    "人力资源与薪酬": {
        "控制类别": "自动控制",
        "业务流程和交易": "人力资源与薪酬",
        "财务报表项目": "应付职工薪酬、期间费用",
        "财务报表认定": "完整性、准确性、计价或分摊",
        "潜在错报风险": "人员主数据、薪酬计算或薪酬入账数据不完整或不准确，导致薪酬相关科目错报。",
        "信息处理控制及数据": "人员主数据、考勤、薪酬计算、审批和薪酬凭证生成数据。",
        "实际控制活动": "确认人事/薪酬系统和财务系统间人员主数据、薪酬计算、审批和凭证生成的控制活动及异常处理记录。",
        "自动/人工": "自动/人工",
        "预防性/检查性": "预防性/检查性",
        "频率": "每月一次",
    },
}


def find_b43_sheet(wb, keyword: str) -> Optional[Worksheet]:
    for ws in wb.worksheets:
        if keyword in ws.title:
            return ws
    return None


def b43_access_process(system: str) -> str:
    return f"{system}用户新增、变更及离职权限调整由业务或部门负责人提出申请，经授权审批后由系统管理员或IT人员配置；需保留申请、审批和配置记录。"


def b43_change_process(system: str) -> str:
    return f"{system}变更应通过需求提出、影响评估、测试验证、审批和上线发布流程执行；重大变更需保留测试、审批、上线和回退记录。"


def b43_info_process(app: dict[str, str]) -> dict[str, str]:
    system = app["system"]
    return {
        "operations": f"{system}支持{app['processes']}等流程，系统管理员或业务负责人监控关键处理结果和异常。",
        "communication": "存在系统间数据传输或接口的，应取得接口清单、传输频率、异常处理和对账证据；如无接口需由业务和IT人员确认。",
        "batch": "根据系统清单和作业调度资料确认批处理或定时任务；未取得资料时按需人工确认。",
        "reports": "需识别财务或业务依赖的系统生成报告，并关注报表逻辑、参数和数据来源。",
        "input": "业务数据通过人工录入、接口导入或系统自动生成进入应用系统，需结合流程资料确认。",
        "data_complexity": "涉及业务和财务相关数据处理，数据量和复杂程度需结合交易量、接口和报表使用情况判断。",
        "customization": "需结合系统来源、二次开发和定制报表情况判断定制化程度。",
        "emerging": "No",
    }


def find_info_processing_sheet(wb) -> Optional[Worksheet]:
    for ws in wb.worksheets:
        title = norm(ws.title)
        if "b23" in title or "信息处理控制" in title:
            return ws
    return wb.worksheets[0] if wb.worksheets else None


def infer_info_processing_rows(suggestion: dict[str, Any]) -> list[dict[str, str]]:
    attachments = suggestion_attachments(suggestion)
    text = compact_attachment_text(attachments)
    systems = infer_systems(text)
    systems_text = "、".join(systems) if systems else "主要财务及业务系统"
    process_rows = infer_process_rows(suggestion)
    processes = [row["重大业务流程"] for row in process_rows]
    if not processes:
        processes = ["总账与财务报告"]

    rows: list[dict[str, str]] = []
    for index, process in enumerate(dict.fromkeys(processes), start=1):
        template = INFO_PROCESSING_TEMPLATES.get(process)
        if template is None:
            template = {
                "控制类别": "自动控制",
                "业务流程和交易": process,
                "财务报表项目": "相关财务报表项目",
                "财务报表认定": "完整性、准确性、存在和发生",
                "潜在错报风险": f"{process}相关系统数据处理不完整或不准确，导致财务报表相关项目错报。",
                "信息处理控制及数据": f"{process}相关系统单据、审批、接口或报表数据。",
                "实际控制活动": f"依据{process}流程资料，确认系统关键单据、审批状态、接口传输和系统生成报告与流程描述一致，并关注异常处理记录。",
                "自动/人工": "自动/人工",
                "预防性/检查性": "预防性/检查性",
                "频率": "按需",
            }
        row = dict(template)
        row["信息处理控制索引号"] = f"B23-15-{index}"
        row["涉及应用程序"] = systems_text
        rows.append(row)
    return rows


def locate_info_processing_columns(ws: Worksheet) -> tuple[Optional[int], dict[str, int], str]:
    header_row, columns, issue = locate_header_row_and_columns(
        ws,
        {header: [header] for header in INFO_PROCESSING_HEADERS},
        {"控制类别", "信息处理控制索引号", "业务流程和交易", "实际控制活动", "涉及应用程序"},
    )
    if header_row is None:
        return None, {}, "B23-15 headers not found: " + issue
    return header_row, columns, ""


def info_processing_data_rows(ws: Worksheet, header_row: int, count: int) -> tuple[list[int], int]:
    rows: list[int] = []
    insert_at = ws.max_row + 1
    for row_idx in range(header_row + 1, ws.max_row + 1):
        row_text = norm(" ".join(str(ws.cell(row_idx, col_idx).value or "") for col_idx in range(1, ws.max_column + 1)))
        if "填写说明" in row_text or "本表根据" in row_text:
            insert_at = row_idx
            break
        rows.append(row_idx)
        if len(rows) >= count:
            break
    return rows, insert_at


def copy_row_format(ws: Worksheet, source_row: int, target_row: int) -> None:
    for col_idx in range(1, ws.max_column + 1):
        source = ws.cell(source_row, col_idx)
        target = ws.cell(target_row, col_idx)
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.alignment:
            target.alignment = copy(source.alignment)
        if source.font:
            target.font = copy(source.font)
        if source.fill:
            target.fill = copy(source.fill)
        if source.border:
            target.border = copy(source.border)


def plan_b23_info_processing_rows(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    header_row, columns, issue = locate_info_processing_columns(ws)
    if header_row is None:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="info_processing_rows",
                locator="headers:B23-15",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message=issue,
            )
        ], False

    inferred = infer_info_processing_rows(suggestion)
    data_rows, insert_at = info_processing_data_rows(ws, header_row, len(inferred))
    results: list[FillTarget] = []
    changed = False
    inserted_rows = 0
    for offset, row_data in enumerate(inferred):
        if offset < len(data_rows):
            row_idx = data_rows[offset]
            inserted = False
        else:
            row_idx = insert_at + inserted_rows
            inserted = True
            if apply:
                ws.insert_rows(row_idx)
                copy_row_format(ws, max(header_row + 1, row_idx - 1), row_idx)
                inserted_rows += 1
                changed = True
        for header in INFO_PROCESSING_HEADERS:
            col_idx = columns.get(header)
            if not col_idx:
                continue
            if inserted and not apply:
                results.append(
                    FillTarget(
                        rule_id=suggestion.get("rule_id", ""),
                        scope=suggestion.get("scope", ""),
                        workbook_path=str(workbook_path),
                        sheet_name=ws.title,
                        field=f"info_processing_rows.{offset + 1}.{header}",
                        locator=f"headers:{header}",
                        cell=f"{get_column_letter(col_idx)}{row_idx}",
                        old_value=None,
                        new_value=row_data.get(header, ""),
                        status="planned",
                        message="B23-15 row will be inserted before instruction section if apply=true",
                    )
                )
                continue
            item, item_changed = cell_plan(
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                field=f"info_processing_rows.{offset + 1}.{header}",
                locator=f"headers:{header}",
                row_idx=row_idx,
                col_idx=col_idx,
                new_value=row_data.get(header, ""),
                apply=apply,
                message=(
                    "B23-15 row inserted before instruction section"
                    if inserted
                    else "B23-15 info processing control inferred from matched attachments"
                ),
            )
            results.append(item)
            changed = changed or item_changed
    return results, changed


B6022_DIRECT_FIELDS: dict[str, tuple[list[str], int, str]] = {
    "project_no": (["IT审计项目编号"], 2, "IT审计项目编号"),
    "entrusted_unit": (["委托单位"], 2, "委托单位"),
    "entity_full_name": (["被审计单位名称（全称）", "被审计单位名称"], 1, "被审计单位名称"),
    "subsidiaries": (["下属子公司"], 1, "下属子公司"),
    "industry": (["被审计单位所属行业"], 1, "被审计单位所属行业"),
    "site_address": (["IT审计现场地址"], 1, "IT审计现场地址"),
    "schedule": (["IT审计时限"], 3, "IT审计时限"),
    "confirmed_scope": (["IT团队与项目组确认后的测试内容、范围"], 2, "测试内容范围"),
}

B6022_SCOPE_HEADERS: dict[str, tuple[list[str], int]] = {
    "scope_itgc": (["信息技术一般控制（ITGC）", "信息技术一般控制"], 1),
    "scope_itac": (["信息技术应用控制测试（ITAC）", "信息技术应用控制"], 1),
    "scope_journal": (["会计分录测试"], 1),
    "scope_extract": (["数据提取"], 1),
    "scope_analysis": (["数据分析"], 1),
    "leap": (["是否使用LEAP软件", "是否使用Leap软件", "是否使用LEAPr软件", "是否使用Leapr软件"], 2),
    "requirement_desc": (["对IT团队的要求或核查需求描述"], 2),
}


def format_cn_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        return f"{match.group(1)}年{int(match.group(2)):02d}月{int(match.group(3)):02d}日"
    return text


def first_context_contact(project_context: Optional[dict[str, Any]]) -> dict[str, Any]:
    contacts = (project_context or {}).get("contacts") or []
    if not isinstance(contacts, list) or not contacts:
        return {}
    for contact in contacts:
        text = norm(" ".join(str(contact.get(key, "")) for key in ("title", "department", "responsibility")))
        if any(keyword in text for keyword in ["it", "信息", "运维", "系统", "数字化"]):
            return contact
    return contacts[0]


def context_member(project_context: Optional[dict[str, Any]], keywords: list[str]) -> dict[str, Any]:
    members = (project_context or {}).get("members") or []
    if not isinstance(members, list):
        return {}
    wanted = [norm(keyword) for keyword in keywords]
    scored: list[tuple[int, dict[str, Any]]] = []
    for member in members:
        text = norm(" ".join(str(member.get(key, "")) for key in ("role_on_project", "module", "display_name", "username")))
        if any(keyword in text for keyword in wanted):
            score = 1
            if "it" in text or "信息" in text:
                score += 3
            if "负责人" in text or "leader" in text:
                score += 2
            if "合伙人" in text and "负责人" not in text:
                score -= 1
            scored.append((score, member))
    if scored:
        return sorted(scored, key=lambda item: item[0], reverse=True)[0][1]
    return members[0] if members else {}


def member_name(member: dict[str, Any], default: str = "待补充") -> str:
    return str(member.get("display_name") or member.get("username") or member.get("name") or default)


def member_email(member: dict[str, Any]) -> str:
    return str(member.get("email") or "待补充")


def infer_b6022_values(suggestion: dict[str, Any], project_context: Optional[dict[str, Any]]) -> dict[str, str]:
    text = compact_attachment_text(suggestion_attachments(suggestion))
    has_itac = any(keyword in text for keyword in ["itac", "信息处理控制", "应用控制", "b23"])
    has_journal = "会计分录" in text or "journal" in text
    start = format_cn_date((project_context or {}).get("start_date"))
    end = format_cn_date((project_context or {}).get("end_date"))
    schedule = f"{start}-{end}" if start and end else "待补充进场时间-离场时间"
    scopes = ["ITGC"]
    if has_itac:
        scopes.append("ITAC")
    if has_journal:
        scopes.append("会计分录测试")
    if len(scopes) == 1:
        scopes.extend(["ITAC", "会计分录测试"])
    scope_text = "、".join(scopes)

    contact = first_context_contact(project_context)
    partner = context_member(project_context, ["合伙人", "partner"])
    manager = context_member(project_context, ["经理", "项目负责", "manager"])
    it_consultant = context_member(project_context, ["顾问", "审计师"])
    it_leader = context_member(project_context, ["负责人", "leader"])

    return {
        "project_no": str((project_context or {}).get("code") or "待补充项目编号"),
        "entrusted_unit": "待补充委托单位",
        "entity_full_name": str((project_context or {}).get("entity_name") or "待补充被审计单位名称"),
        "subsidiaries": "详见主体明细或待补充",
        "industry": "待补充所属行业",
        "site_address": "待补充现场地址或远程配合方式",
        "schedule": schedule,
        "scope_itgc": "√",
        "scope_itac": "√" if has_itac or "ITAC" in scopes else "X",
        "scope_journal": "√" if has_journal or "会计分录测试" in scopes else "X",
        "scope_extract": "X",
        "scope_analysis": "X",
        "leap": "N",
        "requirement_desc": scope_text,
        "confirmed_scope": scope_text,
        "customer_name": str(contact.get("name") or "待补充"),
        "customer_title": str(contact.get("title") or contact.get("department") or "待补充"),
        "customer_phone": str(contact.get("phone") or "待补充"),
        "customer_email": str(contact.get("email") or "待补充"),
        "partner_name": member_name(partner),
        "partner_phone": str(partner.get("phone") or "待补充"),
        "partner_email": member_email(partner),
        "manager_name": member_name(manager),
        "it_consultant_name": member_name(it_consultant),
        "it_consultant_phone": str(it_consultant.get("phone") or "待补充"),
        "it_consultant_email": member_email(it_consultant),
        "it_leader_name": member_name(it_leader),
        "it_leader_phone": str(it_leader.get("phone") or "待补充"),
        "it_leader_email": member_email(it_leader),
        "travel_customer": "X",
        "travel_project": "√",
        "travel_it": "X",
    }


def plan_cell_object(
    *,
    suggestion: dict[str, Any],
    workbook_path: Path,
    ws: Worksheet,
    field: str,
    locator: str,
    cell: Cell | MergedCell,
    new_value: str,
    apply: bool,
    message: str,
) -> tuple[FillTarget, bool]:
    resolved = real_cell(ws, cell)
    if not isinstance(resolved, Cell) or not is_writable_cell(resolved):
        return (
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field=field,
                locator=locator,
                cell=resolved.coordinate if hasattr(resolved, "coordinate") else "",
                old_value=display(getattr(resolved, "value", None)),
                new_value=new_value,
                status="blocked",
                message="target is not writable",
            ),
            False,
        )
    old_value = resolved.value
    status = "planned"
    changed = False
    if apply and old_value != new_value:
        resolved.value = new_value
        changed = True
        status = "changed"
    elif old_value == new_value:
        status = "unchanged"
    if status != "skipped" and old_value not in (None, "", new_value):
        message += "; existing value will be overwritten if apply=true"
    return (
        FillTarget(
            rule_id=suggestion.get("rule_id", ""),
            scope=suggestion.get("scope", ""),
            workbook_path=str(workbook_path),
            sheet_name=ws.title,
            field=field,
            locator=locator,
            cell=resolved.coordinate,
            old_value=display(old_value),
            new_value=new_value,
            status=status,
            message=message,
        ),
        changed,
    )


def cell_below_label(ws: Worksheet, aliases: list[str], row_offset: int) -> tuple[Optional[Cell | MergedCell], str]:
    match = find_header_match(ws, aliases, max_row=35)
    if match is None:
        return None, "label not found: " + " | ".join(aliases)
    row_idx, col_idx = match
    return real_cell(ws, ws.cell(row_idx + row_offset, col_idx)), ""


def find_section_columns(ws: Worksheet, section_aliases: list[str], field_aliases: dict[str, list[str]]) -> tuple[Optional[int], dict[str, int], str]:
    section = find_header_match(ws, section_aliases, max_row=35)
    if section is None:
        return None, {}, "section not found: " + " | ".join(section_aliases)
    section_row, _ = section
    columns: dict[str, int] = {}
    for field, aliases in field_aliases.items():
        wanted = [norm(alias) for alias in aliases if alias]
        for row_idx in range(section_row, min(ws.max_row, section_row + 4) + 1):
            for col_idx in range(1, ws.max_column + 1):
                text = norm(ws.cell(row_idx, col_idx).value)
                if text and any(alias == text or alias in text for alias in wanted):
                    columns[field] = col_idx
                    break
            if field in columns:
                break
    return section_row, columns, ""


def find_travel_columns(ws: Worksheet) -> tuple[Optional[int], dict[str, int], str]:
    section = find_header_match(ws, ["差旅费用承担"], max_row=35)
    if section is None:
        return None, {}, "section not found: 差旅费用承担"
    section_row, section_col = section
    aliases = {
        "travel_customer": ["客户"],
        "travel_project": ["项目组"],
        "travel_it": ["IT团队"],
    }
    columns: dict[str, int] = {}
    for field, field_aliases in aliases.items():
        wanted = [norm(alias) for alias in field_aliases]
        for row_idx in range(section_row + 1, min(ws.max_row, section_row + 4) + 1):
            for col_idx in range(section_col, ws.max_column + 1):
                text = norm(ws.cell(row_idx, col_idx).value)
                if text and any(alias == text for alias in wanted):
                    columns[field] = col_idx
                    break
            if field in columns:
                break
    return section_row, columns, ""


def add_b6022_plan(
    results: list[FillTarget],
    *,
    suggestion: dict[str, Any],
    workbook_path: Path,
    ws: Worksheet,
    field: str,
    locator: str,
    cell: Optional[Cell | MergedCell],
    new_value: str,
    apply: bool,
    message: str,
) -> bool:
    if cell is None:
        results.append(
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field=field,
                locator=locator,
                cell="",
                old_value=None,
                new_value=new_value,
                status="blocked",
                message=message,
            )
        )
        return False
    item, changed = plan_cell_object(
        suggestion=suggestion,
        workbook_path=workbook_path,
        ws=ws,
        field=field,
        locator=locator,
        cell=cell,
        new_value=new_value,
        apply=apply,
        message=message,
    )
    results.append(item)
    return changed


def plan_b6022_entrance_notice(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    project_context: Optional[dict[str, Any]],
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    values = infer_b6022_values(suggestion, project_context)
    results: list[FillTarget] = []
    changed = False

    for field, (aliases, row_offset, label) in B6022_DIRECT_FIELDS.items():
        cell, issue = cell_below_label(ws, aliases, row_offset)
        changed = add_b6022_plan(
            results,
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"entrance_notice.{field}",
            locator=label,
            cell=cell,
            new_value=values[field],
            apply=apply,
            message=issue or "B60-2-2 field inferred from project context and matched attachments",
        ) or changed

    for field, (aliases, offset) in B6022_SCOPE_HEADERS.items():
        cell, issue = cell_below_label(ws, aliases, offset)
        changed = add_b6022_plan(
            results,
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"entrance_notice.{field}",
            locator="scope:" + field,
            cell=cell,
            new_value=values[field],
            apply=apply,
            message=issue or "B60-2-2 scope inferred from matched attachments",
        ) or changed

    customer_row, customer_cols, customer_issue = find_section_columns(
        ws,
        ["客户IT部门人员联系方式"],
        {
            "customer_name": ["姓名"],
            "customer_title": ["职务"],
            "customer_phone": ["手机号/座机", "手机号"],
            "customer_email": ["邮箱"],
        },
    )
    for field in ("customer_name", "customer_title", "customer_phone", "customer_email"):
        cell = ws.cell(customer_row + 2, customer_cols[field]) if customer_row and field in customer_cols else None
        changed = add_b6022_plan(
            results,
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"entrance_notice.{field}",
            locator="客户IT部门人员联系方式:" + field,
            cell=cell,
            new_value=values[field],
            apply=apply,
            message=customer_issue or "B60-2-2 customer contact inferred from project contacts",
        ) or changed

    project_row, project_cols, project_issue = find_section_columns(
        ws,
        ["审计项目组联系方式"],
        {
            "partner_name": ["项目合伙人"],
            "partner_phone": ["手机号"],
            "partner_email": ["邮箱"],
            "manager_name": ["项目负责经理"],
        },
    )
    for field in ("partner_name", "partner_phone", "partner_email", "manager_name"):
        cell = ws.cell(project_row + 2, project_cols[field]) if project_row and field in project_cols else None
        changed = add_b6022_plan(
            results,
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"entrance_notice.{field}",
            locator="审计项目组联系方式:" + field,
            cell=cell,
            new_value=values[field],
            apply=apply,
            message=project_issue or "B60-2-2 project team contact inferred from project members",
        ) or changed

    it_row, it_cols, it_issue = find_section_columns(
        ws,
        ["IT团队联系方式"],
        {
            "it_consultant_name": ["IT顾问", "IT合伙人", "项目合伙人"],
            "it_consultant_phone": ["手机号"],
            "it_consultant_email": ["邮箱"],
            "it_leader_name": ["IT团队负责人"],
            "it_leader_phone": ["手机号"],
            "it_leader_email": ["邮箱"],
        },
    )
    it_field_order = (
        ("it_consultant_name", 0),
        ("it_consultant_phone", 0),
        ("it_consultant_email", 0),
        ("it_leader_name", 0),
        ("it_leader_phone", 1),
        ("it_leader_email", 1),
    )
    used_phone_email = {"it_consultant_phone": 0, "it_consultant_email": 0, "it_leader_phone": 1, "it_leader_email": 1}
    for field, _ in it_field_order:
        col_idx = it_cols.get(field)
        if field in used_phone_email:
            aliases = ["手机号"] if "phone" in field else ["邮箱"]
            section = find_header_match(ws, ["IT团队联系方式"], max_row=35)
            if section is not None:
                section_row = section[0]
                matches = []
                wanted = [norm(alias) for alias in aliases]
                for row_idx in range(section_row, min(ws.max_row, section_row + 4) + 1):
                    for candidate_col in range(1, ws.max_column + 1):
                        text = norm(ws.cell(row_idx, candidate_col).value)
                        if text and any(alias == text or alias in text for alias in wanted):
                            matches.append(candidate_col)
                index = used_phone_email[field]
                if len(matches) > index:
                    col_idx = matches[index]
        cell = ws.cell(it_row + 2, col_idx) if it_row and col_idx else None
        changed = add_b6022_plan(
            results,
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"entrance_notice.{field}",
            locator="IT团队联系方式:" + field,
            cell=cell,
            new_value=values[field],
            apply=apply,
            message=it_issue or "B60-2-2 IT team contact inferred from project members",
        ) or changed

    travel_row, travel_cols, travel_issue = find_travel_columns(ws)
    for field in ("travel_customer", "travel_project", "travel_it"):
        cell = ws.cell(travel_row + 2, travel_cols[field]) if travel_row and field in travel_cols else None
        changed = add_b6022_plan(
            results,
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"entrance_notice.{field}",
            locator="差旅费用承担:" + field,
            cell=cell,
            new_value=values[field],
            apply=apply,
            message=travel_issue or "B60-2-2 travel cost owner defaulted from project setup",
        ) or changed

    return results, changed


B6021_JUDGMENT_ROWS: list[tuple[str, list[str], list[str], str]] = [
    ("listed_or_ipo", ["IPO公司", "上市公司整合审计"], ["ipo", "上市", "整合审计"], "上市/IPO/整合审计业务"),
    ("financial", ["复杂金融企业"], ["银行", "保险", "证券", "金融"], "复杂金融企业"),
    ("internet", ["互联网企业"], ["互联网", "线上", "商城", "电商", "游戏", "平台"], "互联网企业或重要线上收入"),
    ("bond_or_reit", ["发行债券", "新三板", "重大资产重组", "REIT"], ["债券", "新三板", "重大资产重组", "reit"], "发债、新三板、重大重组或REITs"),
    ("important_subsidiary", ["重要子公司"], ["重要子公司"], "重要子公司"),
    ("international", ["重要国际业务"], ["国际业务", "境外", "海外"], "重要国际业务"),
    ("retail_chain", ["超市", "酒店", "零售", "连锁"], ["超市", "酒店", "零售", "连锁"], "连锁经营类B类业务"),
    ("partner_required", ["不属于上述", "必要进行IT审计的其他审计业务"], ["必要进行it审计", "项目合伙人认为", "it审计计划", "itgc"], "项目组判断需要执行IT审计"),
]


def b6021_assessment_text(suggestion: dict[str, Any], project_context: Optional[dict[str, Any]]) -> str:
    return norm(
        " ".join(
            [
                compact_attachment_text(suggestion_attachments(suggestion)),
                str((project_context or {}).get("name", "")),
                str((project_context or {}).get("description", "")),
                str((project_context or {}).get("entity_name", "")),
            ]
        )
    )


def b6021_complexity(system_name: str, all_text: str) -> str:
    text = norm(system_name + " " + all_text)
    complex_keywords = ["sap", "erp", "u8", "nc", "金蝶", "财务共享", "商城", "旺店通", "mes", "wms", "接口", "报表", "数据仓库"]
    return "复杂" if any(keyword in text for keyword in complex_keywords) else "一般"


def infer_b6021_scope_rows(suggestion: dict[str, Any]) -> list[dict[str, str]]:
    text = compact_attachment_text(suggestion_attachments(suggestion))
    systems = infer_systems(text) or ["主要财务及业务系统"]
    processes = infer_process_rows(suggestion)
    process_text = "、".join(dict.fromkeys(row["重大业务流程"] for row in processes)) or "主要业务及财务报告相关流程"
    rows: list[dict[str, str]] = []
    for index, system in enumerate(systems, start=1):
        rows.append(
            {
                "sequence": str(index),
                "system": system,
                "process": process_text,
                "complexity": b6021_complexity(system, text),
                "remark": "纳入本次测试范围",
            }
        )
    return rows


def locate_b6021_applicable_col(ws: Worksheet) -> Optional[int]:
    for row_idx in range(1, min(ws.max_row, 15) + 1):
        row_text = norm(" ".join(str(ws.cell(row_idx, col_idx).value or "") for col_idx in range(1, ws.max_column + 1)))
        if "情况或事项" not in row_text:
            continue
        for col_idx in range(1, ws.max_column + 1):
            text = norm(ws.cell(row_idx, col_idx).value)
            if text == "是否适用":
                return col_idx
    match = find_header_match(ws, ["是否适用"], max_row=12)
    if match and match[0] >= 7:
        return match[1]
    return None


def find_b6021_judgment_row(ws: Worksheet, aliases: list[str]) -> Optional[int]:
    wanted = [norm(alias) for alias in aliases]
    for row_idx in range(8, min(ws.max_row, 25) + 1):
        text = norm(" ".join(str(ws.cell(row_idx, col_idx).value or "") for col_idx in range(1, min(ws.max_column, 8) + 1)))
        if any(alias in text for alias in wanted):
            return row_idx
    return None


def locate_b6021_scope_columns(ws: Worksheet) -> tuple[Optional[int], dict[str, int], str]:
    header = find_header_match(ws, ["IT应用程序或基础设施"], max_row=30)
    if header is None:
        return None, {}, "B60-2-1 test scope header not found"
    header_row = header[0]
    aliases = {
        "sequence": ["编号"],
        "system": ["IT应用程序或基础设施", "应用程序或基础设施"],
        "process": ["涉及的重大业务流程"],
        "complexity": ["复杂性"],
        "remark": ["备注"],
    }
    columns: dict[str, int] = {}
    for field, field_aliases in aliases.items():
        wanted = [norm(alias) for alias in field_aliases]
        for col_idx in range(1, ws.max_column + 1):
            text = norm(ws.cell(header_row, col_idx).value)
            if text and any(alias == text or alias in text for alias in wanted):
                columns[field] = col_idx
                break
    missing = sorted(set(aliases) - set(columns))
    if missing:
        return None, {}, "B60-2-1 scope columns not found: " + ", ".join(missing)
    return header_row, columns, ""


def plan_b6021_complexity_assessment(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    project_context: Optional[dict[str, Any]],
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    results: list[FillTarget] = []
    changed = False
    text = b6021_assessment_text(suggestion, project_context)
    applicable_col = locate_b6021_applicable_col(ws)
    if applicable_col is None:
        results.append(
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="complexity_assessment.judgment",
                locator="是否适用",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message="B60-2-1 applicable column not found",
            )
        )
    else:
        any_yes = False
        for field, row_aliases, keywords, reason in B6021_JUDGMENT_ROWS:
            row_idx = find_b6021_judgment_row(ws, row_aliases)
            if row_idx is None:
                continue
            if field == "partner_required":
                value = "否"
            else:
                value = "是" if any(norm(keyword) in text for keyword in keywords) else "否"
            if field == "partner_required" and not any_yes and ("itgc" in text or "信息系统" in text or "系统清单" in text):
                value = "是"
            any_yes = any_yes or value == "是"
            item, item_changed = cell_plan(
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                field=f"complexity_assessment.judgment.{field}",
                locator=reason,
                row_idx=row_idx,
                col_idx=applicable_col,
                new_value=value,
                apply=apply,
                message="B60-2-1 applicability inferred from project type and matched attachments",
            )
            results.append(item)
            changed = changed or item_changed

    header_row, columns, issue = locate_b6021_scope_columns(ws)
    if header_row is None:
        results.append(
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="complexity_assessment.scope",
                locator="IT审计测试范围",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message=issue,
            )
        )
        return results, changed

    scope_rows = infer_b6021_scope_rows(suggestion)
    start_row = header_row + 1
    for offset, row_data in enumerate(scope_rows):
        row_idx = start_row + offset
        if row_idx > ws.max_row:
            if apply:
                ws.insert_rows(row_idx)
                copy_row_format(ws, row_idx - 1, row_idx)
                changed = True
            else:
                # Preview the target row even when it would need to be inserted.
                pass
        for field in ("sequence", "system", "process", "complexity", "remark"):
            col_idx = columns[field]
            if row_idx > ws.max_row and not apply:
                results.append(
                    FillTarget(
                        rule_id=suggestion.get("rule_id", ""),
                        scope=suggestion.get("scope", ""),
                        workbook_path=str(workbook_path),
                        sheet_name=ws.title,
                        field=f"complexity_assessment.scope.{row_data['system']}.{field}",
                        locator="IT审计测试范围:" + field,
                        cell=f"{get_column_letter(col_idx)}{row_idx}",
                        old_value=None,
                        new_value=row_data[field],
                        status="planned",
                        message="B60-2-1 scope row will be appended if apply=true",
                    )
                )
                continue
            item, item_changed = cell_plan(
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                field=f"complexity_assessment.scope.{row_data['system']}.{field}",
                locator="IT审计测试范围:" + field,
                row_idx=row_idx,
                col_idx=col_idx,
                new_value=row_data[field],
                apply=apply,
                message="B60-2-1 test scope inferred from system range attachments",
            )
            results.append(item)
            changed = changed or item_changed
    return results, changed


B442_SECTION_ALIASES = {
    "security": ["安全管理", "Security management"],
    "maintenance": ["技术维护", "Technology (program) maintenance", "程式变更控制", "program change"],
    "implementation": ["实施新系统", "新系统实施", "New system implementation", "采购和开发", "acquisition and development"],
}


def infer_sod_rows(suggestion: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    text = compact_attachment_text(suggestion_attachments(suggestion))
    has_business = any(keyword in text for keyword in ["业务", "销售", "采购", "库存", "商城", "旺店通"])
    has_finance = any(keyword in text for keyword in ["财务", "总账", "报表", "应收", "应付", "u8", "nc", "sap", "金蝶"])
    has_development = any(keyword in text for keyword in ["开发", "二开", "变更", "上线", "发布", "实施", "供应商"])

    security_rows = [
        {
            "role": "系统管理员",
            "auth": "-",
            "process": "X",
            "monitor": "X",
            "business": "-",
            "deficiency": "否",
            "issue_desc": "系统管理员负责用户及权限配置，并参与权限状态关注；需结合人员清单确认是否同时承担业务或财务处理职责。",
        }
    ]
    if "数据库" in text or "dba" in text or "oracle" in text:
        security_rows.append(
            {
                "role": "数据库管理员",
                "auth": "-",
                "process": "X",
                "monitor": "-",
                "business": "-",
                "deficiency": "否",
                "issue_desc": "数据库管理员具备底层数据维护能力，需结合数据库权限清单确认是否存在业务处理职责。",
            }
        )
    if has_business:
        security_rows.append(
            {
                "role": "业务部门负责人",
                "auth": "X",
                "process": "-",
                "monitor": "X",
                "business": "X",
                "deficiency": "否",
                "issue_desc": "业务部门负责权限申请审批和业务处理，通常不直接配置系统权限；如同时持有管理员权限需识别缺陷。",
            }
        )
    if has_finance:
        security_rows.append(
            {
                "role": "财务负责人",
                "auth": "X",
                "process": "-",
                "monitor": "X",
                "business": "X",
                "deficiency": "待判断",
                "issue_desc": "财务人员参与财务流程和部分权限审批，需结合管理员清单判断是否同时持有应用管理员或特权权限。",
            }
        )

    maintenance_rows = [
        {
            "role": "IT负责人",
            "auth": "X",
            "design": "-",
            "review": "X",
            "implement": "-",
            "business": "-",
            "deficiency": "否",
            "issue_desc": "IT负责人通常负责变更审批或复核，需与开发和实施上线职责保持分离。",
        }
    ]
    if has_development:
        maintenance_rows.append(
            {
                "role": "开发/供应商人员",
                "auth": "-",
                "design": "X",
                "review": "-",
                "implement": "X",
                "business": "-",
                "deficiency": "待判断",
                "issue_desc": "开发或供应商同时参与设计开发和实施上线，需结合业务测试、上线审批和运维复核判断是否存在补偿控制。",
            }
        )
    if has_business:
        maintenance_rows.append(
            {
                "role": "业务部门",
                "auth": "X",
                "design": "-",
                "review": "X",
                "implement": "-",
                "business": "X",
                "deficiency": "否",
                "issue_desc": "业务部门负责需求确认和测试验收，不应直接执行生产上线。",
            }
        )

    implementation_rows = [
        {
            "role": "项目/IT负责人",
            "auth": "X",
            "design": "-",
            "review": "X",
            "implement": "-",
            "business": "-",
            "deficiency": "否",
            "issue_desc": "负责新系统实施审批、进度管理和验收复核，需与具体开发实施职责分离。",
        }
    ]
    if has_development:
        implementation_rows.append(
            {
                "role": "实施顾问/开发人员",
                "auth": "-",
                "design": "X",
                "review": "-",
                "implement": "X",
                "business": "-",
                "deficiency": "待判断",
                "issue_desc": "实施顾问或开发人员参与配置和上线，需结合上线审批、测试验收和权限限制判断职责分离是否充分。",
            }
        )
    if has_business:
        implementation_rows.append(
            {
                "role": "业务流程负责人",
                "auth": "X",
                "design": "-",
                "review": "X",
                "implement": "-",
                "business": "X",
                "deficiency": "否",
                "issue_desc": "业务流程负责人负责需求确认和测试验收，通常不直接实施系统配置或上线。",
            }
        )

    return {
        "security": security_rows[:5],
        "maintenance": maintenance_rows[:5],
        "implementation": implementation_rows[:5],
    }


def find_sheet_for_sod(wb) -> Optional[Worksheet]:
    preferred: list[Worksheet] = []
    fallback: list[Worksheet] = []
    for ws in wb.worksheets:
        name = norm(ws.title)
        if "instructions" in name:
            continue
        if "职责分离" in name:
            preferred.append(ws)
        elif "sodanalysis" in name:
            fallback.append(ws)
    for ws in preferred + fallback:
        if find_header_match(ws, ["人员（角色）", "个人（角色）", "Individual (Role)"], max_row=25):
            return ws
    return None


def find_section_row(ws: Worksheet, aliases: list[str]) -> Optional[int]:
    wanted = [norm(alias) for alias in aliases]
    for row_idx in range(1, ws.max_row + 1):
        row_text = norm(" ".join(str(ws.cell(row_idx, col_idx).value or "") for col_idx in range(1, ws.max_column + 1)))
        if any(alias in row_text for alias in wanted):
            return row_idx
    return None


def first_data_rows_after_section(ws: Worksheet, section_row: int, role_col: int, limit: int = 5) -> list[int]:
    rows: list[int] = []
    for row_idx in range(section_row + 1, ws.max_row + 1):
        role_value = str(ws.cell(row_idx, role_col).value or "").strip()
        row_text = norm(" ".join(str(ws.cell(row_idx, col_idx).value or "") for col_idx in range(1, min(ws.max_column, 10) + 1)))
        if not role_value:
            continue
        if "个人（角色）" in row_text or "individual(role)" in row_text:
            break
        if any(norm(alias) in row_text for aliases in B442_SECTION_ALIASES.values() for alias in aliases):
            if row_idx != section_row:
                break
        rows.append(row_idx)
        if len(rows) >= limit:
            break
    return rows


def next_sod_section_row(ws: Worksheet, section_row: int) -> int:
    for row_idx in range(section_row + 1, ws.max_row + 1):
        row_text = norm(" ".join(str(ws.cell(row_idx, col_idx).value or "") for col_idx in range(1, min(ws.max_column, 10) + 1)))
        if any(norm(alias) in row_text for aliases in B442_SECTION_ALIASES.values() for alias in aliases):
            return row_idx
    return ws.max_row + 1


def append_inserted_sod_row_plan(
    *,
    results: list[FillTarget],
    suggestion: dict[str, Any],
    workbook_path: Path,
    ws: Worksheet,
    section: str,
    row_idx: int,
    columns: dict[str, int],
    row_data: dict[str, str],
    fields: list[str],
    apply: bool,
) -> bool:
    changed = False
    if apply:
        ws.insert_rows(row_idx)
        copy_row_format(ws, max(1, row_idx - 1), row_idx)
        changed = True
    for field in fields:
        col_idx = columns.get(field)
        if not col_idx:
            continue
        if apply:
            item, item_changed = cell_plan(
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                field=f"sod_rows.{section}.{row_data['role']}.{field}",
                locator=f"B22A-4-4-2 {section}:{row_idx}",
                row_idx=row_idx,
                col_idx=col_idx,
                new_value=row_data.get(field, ""),
                apply=apply,
                message="B22A-4-4-2 row inserted because reusable template rows were insufficient",
            )
            results.append(item)
            changed = changed or item_changed
            continue
        results.append(
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field=f"sod_rows.{section}.{row_data['role']}.{field}",
                locator=f"B22A-4-4-2 {section}:{row_idx}",
                cell=f"{get_column_letter(col_idx)}{row_idx}",
                old_value=None,
                new_value=row_data.get(field, ""),
                status="planned",
                message="B22A-4-4-2 row will be inserted because reusable template rows are insufficient",
            )
        )
    return changed


def locate_sod_columns(ws: Worksheet, section: str) -> tuple[Optional[int], dict[str, int], str]:
    section_row = find_section_row(ws, B442_SECTION_ALIASES[section])
    if section_row is None:
        return None, {}, f"B22A-4-4-2 section not found: {section}"
    header_row = None
    for row_idx in range(section_row - 1, 0, -1):
        row_text = norm(" ".join(str(ws.cell(row_idx, col_idx).value or "") for col_idx in range(1, ws.max_column + 1)))
        if "人员（角色）" in row_text or "个人（角色）" in row_text or "individual(role)" in row_text:
            header_row = row_idx
            break
    if header_row is None:
        return None, {}, f"B22A-4-4-2 header not found for section: {section}"

    columns = {
        "role": 1,
        "auth": 2,
        "deficiency": 8,
        "issue_desc": 9,
    }
    row_values = [norm(ws.cell(header_row, col_idx).value) for col_idx in range(1, ws.max_column + 1)]
    for col_idx, text in enumerate(row_values, start=1):
        if ("人员" in text or "个人" in text or text == "individual(role)") and "performs" not in text and "执行" not in text:
            columns["role"] = col_idx
        elif "授权" in text or "authorization" in text:
            columns["auth"] = col_idx
        elif "进程访问" in text or "processaccess" in text:
            columns["process"] = col_idx
        elif "监督" in text or "monitoring" in text:
            columns["monitor"] = col_idx
        elif "设计" in text or "development" in text:
            columns["design"] = col_idx
        elif "复核" in text or "testing" in text:
            columns["review"] = col_idx
        elif "实施" in text or "implementation" in text:
            columns["implement"] = col_idx
        elif "业务流程" in text or "financialreporting" in text:
            columns["business"] = col_idx
        elif "识别出缺陷" in text or "controldeficiencyidentified" in text:
            columns["deficiency"] = col_idx
        elif "描述职责分离" in text or "describesegregation" in text:
            columns["issue_desc"] = col_idx
    required = {"role", "auth", "business", "deficiency", "issue_desc"}
    required |= {"process", "monitor"} if section == "security" else {"design", "review", "implement"}
    missing = sorted(required - set(columns))
    if missing:
        return None, {}, f"B22A-4-4-2 columns not found for {section}: {', '.join(missing)}"
    columns["section_row"] = section_row
    return header_row, columns, ""


def normalize_control_code(value: Any) -> str:
    text = str(value or "").upper()
    text = text.replace("C22.", "")
    return re.sub(r"[^A-Z0-9]", "", text)


def match_control_codes(value: Any) -> set[str]:
    text = str(value or "").upper().replace("C22.", "")
    matches = set()
    for match in re.findall(r"\b(?:SA|PE|PM|NS)\s*-?\s*\d+[A-Z]?\b", text, flags=re.I):
        matches.add(normalize_control_code(match))
    return matches


# PM-4b（生产环境访问）、PM-4c（生产日志复核）和 PM-4e（环境分离）
# 是不同控制，不得使用别名跨行写入。
CONTROL_CODE_ALIASES: dict[str, list[str]] = {}

CONTROL_ROW_SEMANTICS: dict[str, list[str]] = {
    "PM4B": ["生产环境实施变更的权限", "程序变更的访问权限", "生产环境访问"],
    "PM4C": ["修改生产的用户所执行的活动", "生产环境日志", "操作日志复核"],
    "PM4E": ["开发环境", "测试环境", "生产环境隔离"],
}


def control_row_semantic_issue(ws: Worksheet, row_idx: int, columns: dict[str, int], code: str) -> str:
    expected = CONTROL_ROW_SEMANTICS.get(normalize_control_code(code))
    example_col = columns.get("example")
    if not expected or not example_col:
        return ""
    example = norm(ws.cell(row_idx, example_col).value)
    if not example or any(norm(keyword) in example for keyword in expected):
        return ""
    return f"control code {code} conflicts with the template control example; cross-control write blocked"


def control_evidence_refs(attachments: list[dict[str, Any]], keywords: list[str], limit: int = 12) -> str:
    refs: list[str] = []
    normalized_keywords = [norm(keyword) for keyword in keywords if keyword]
    for attachment in attachments:
        text = norm(" ".join(str(attachment.get(key, "")) for key in ("index_no", "title", "file_path")))
        if not any(keyword in text for keyword in normalized_keywords):
            continue
        label = attachment.get("index_no") or attachment.get("title") or attachment.get("file_path")
        if label and str(label) not in refs:
            refs.append(str(label))
    if not refs:
        return "匹配附件"
    visible = refs[:limit]
    suffix = f"等{len(refs)}项证据" if len(refs) > limit else ""
    return "、".join(visible) + suffix


def infer_control_understanding_rows(suggestion: dict[str, Any]) -> list[dict[str, str]]:
    attachments = suggestion_attachments(suggestion)
    text = compact_attachment_text(attachments)
    rows: list[dict[str, str]] = []
    for rule in CONTROL_UNDERSTANDING_RULES:
        if any(norm(keyword) in text for keyword in rule["keywords"]):
            refs = control_evidence_refs(attachments, rule["keywords"])
            rows.append(
                {
                    "code": rule["code"],
                    "control_description": rule["description"],
                    "determination": str(rule["determination"]).replace("{refs}", refs),
                    "issue_flag": rule["issue_flag"],
                    "issue_desc": rule["issue_desc"],
                }
            )
    return rows


def find_header_match(ws: Worksheet, aliases: list[str], *, max_row: int = 12) -> Optional[tuple[int, int]]:
    normalized_aliases = [norm(alias) for alias in aliases if alias]
    if not normalized_aliases:
        return None
    last_row = min(ws.max_row, max_row)
    for row_idx in range(1, last_row + 1):
        for col_idx in range(1, ws.max_column + 1):
            text = norm(ws.cell(row_idx, col_idx).value)
            if not text:
                continue
            for alias in normalized_aliases:
                if alias == text or alias in text:
                    return row_idx, col_idx
    return None


def locate_b44_columns(ws: Worksheet) -> tuple[Optional[int], dict[str, int], str]:
    columns: dict[str, int] = {}
    for field, aliases in B44_HEADER_ALIASES.items():
        match = find_header_match(ws, aliases)
        if match is not None:
            columns[field] = match[1]

    code_match = find_header_match(ws, B44_HEADER_ALIASES["code"])
    if code_match is None:
        return None, {}, "ITGC code header not found"
    return code_match[0], columns, ""


def find_control_row(ws: Worksheet, header_row: int, code_col: int, code: str) -> Optional[int]:
    wanted = normalize_control_code(code)
    accepted = {wanted, *CONTROL_CODE_ALIASES.get(wanted, [])}
    for row_idx in range(header_row + 1, ws.max_row + 1):
        cell_value = ws.cell(row_idx, code_col).value
        codes = match_control_codes(cell_value)
        if accepted & codes:
            return row_idx
    return None


def cell_plan(
    *,
    suggestion: dict[str, Any],
    workbook_path: Path,
    ws: Worksheet,
    field: str,
    locator: str,
    row_idx: int,
    col_idx: int,
    new_value: str,
    apply: bool,
    message: str,
) -> tuple[FillTarget, bool]:
    requested_cell = ws.cell(row_idx, col_idx)
    cell = real_cell(ws, requested_cell)
    if not isinstance(cell, Cell) or not is_writable_cell(cell):
        return (
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field=field,
                locator=locator,
                cell=getattr(cell, "coordinate", requested_cell.coordinate),
                old_value=display(getattr(cell, "value", None)),
                new_value=new_value,
                status="blocked",
                message=(message + "; " if message else "") + "target is not writable",
            ),
            False,
        )
    old_value = cell.value
    status = "planned"
    changed = False
    if old_value not in (None, "") and str(new_value).startswith("需根据"):
        status = "skipped"
        message += "; unresolved inferred value will not overwrite existing workpaper evidence"
    elif apply and old_value != new_value:
        cell.value = new_value
        changed = True
        status = "changed"
    elif old_value == new_value:
        status = "unchanged"
    if status != "skipped" and old_value not in (None, "", new_value):
        message += "; existing value will be overwritten if apply=true"
    if cell.coordinate != requested_cell.coordinate:
        message += f"; merged target resolved from {requested_cell.coordinate} to {cell.coordinate}"
    return (
        FillTarget(
            rule_id=suggestion.get("rule_id", ""),
            scope=suggestion.get("scope", ""),
            workbook_path=str(workbook_path),
            sheet_name=ws.title,
            field=field,
            locator=locator,
            cell=cell.coordinate,
            old_value=display(old_value),
            new_value=new_value,
            status=status,
            message=message,
        ),
        changed,
    )


def plan_b41_system_summary(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    header_row, columns, issue = locate_b41_columns(ws)
    if header_row is None:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="system_summary",
                locator="headers:B22A-4-1",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message=issue,
            )
        ], False

    rows = infer_b41_system_rows(suggestion)
    starts = b41_block_start_rows(ws, header_row, columns["sequence"], columns["system"])
    if not starts:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="system_summary",
                locator="headers:B22A-4-1",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message="no reusable system blocks found in B22A-4-1",
            )
        ], False

    attachments_text = compact_attachment_text(suggestion_attachments(suggestion))
    results: list[FillTarget] = []
    changed = False
    for offset, row_data in enumerate(rows):
        if offset >= len(starts):
            results.append(
                FillTarget(
                    rule_id=suggestion.get("rule_id", ""),
                    scope=suggestion.get("scope", ""),
                    workbook_path=str(workbook_path),
                    sheet_name=ws.title,
                    field=f"system_summary.{row_data['system']}",
                    locator="B22A-4-1 reusable blocks",
                    cell="",
                    old_value=None,
                    new_value=row_data["description"],
                    status="blocked",
                    message="not enough reusable system blocks in workbook",
                )
            )
            continue

        start_row = starts[offset]
        next_start = starts[offset + 1] if offset + 1 < len(starts) else min(ws.max_row + 1, start_row + 16)
        for field, source_key in (
            ("sequence", "sequence"),
            ("system", "system"),
            ("description", "description"),
            ("index_no", "index_no"),
            ("remark", "remark"),
        ):
            col_idx = columns.get(field)
            if not col_idx:
                continue
            item, item_changed = cell_plan(
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                field=f"system_summary.{row_data['system']}.{field}",
                locator=f"B22A-4-1 block:{start_row}",
                row_idx=start_row,
                col_idx=col_idx,
                new_value=row_data[source_key],
                apply=apply,
                message="B22A-4-1 system summary inferred from matched attachments",
            )
            results.append(item)
            changed = changed or item_changed

        factor_col = columns["factor"]
        answer_col = columns["yes_no"]
        for row_idx in range(start_row, next_start):
            factor_value = ws.cell(row_idx, factor_col).value
            if factor_value in (None, ""):
                continue
            answer = b41_factor_answer(row_data["system"], factor_value, attachments_text)
            item, item_changed = cell_plan(
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                field=f"system_summary.{row_data['system']}.complexity_factor",
                locator=f"B22A-4-1 factor:{display(factor_value, 80)}",
                row_idx=row_idx,
                col_idx=answer_col,
                new_value=answer,
                apply=apply,
                message="B22A-4-1 complexity factor inferred from matched attachments",
            )
            results.append(item)
            changed = changed or item_changed

    return results, changed


def plan_b442_sod_rows(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    inferred = infer_sod_rows(suggestion)
    results: list[FillTarget] = []
    changed = False
    for section, rows in inferred.items():
        _, columns, issue = locate_sod_columns(ws, section)
        if issue:
            results.append(
                FillTarget(
                    rule_id=suggestion.get("rule_id", ""),
                    scope=suggestion.get("scope", ""),
                    workbook_path=str(workbook_path),
                    sheet_name=ws.title,
                    field=f"sod_rows.{section}",
                    locator=f"B22A-4-4-2 section:{section}",
                    cell="",
                    old_value=None,
                    new_value=suggestion.get("suggested_content", ""),
                    status="blocked",
                    message=issue,
                )
            )
            continue
        data_rows = first_data_rows_after_section(ws, columns["section_row"], columns["role"], limit=len(rows))
        fields = ["role", "auth", "business", "deficiency", "issue_desc"]
        fields += ["process", "monitor"] if section == "security" else ["design", "review", "implement"]
        for row_idx, row_data in zip(data_rows, rows):
            for field in fields:
                col_idx = columns.get(field)
                if not col_idx:
                    continue
                item, item_changed = cell_plan(
                    suggestion=suggestion,
                    workbook_path=workbook_path,
                    ws=ws,
                    field=f"sod_rows.{section}.{row_data['role']}.{field}",
                    locator=f"B22A-4-4-2 {section}:{row_idx}",
                    row_idx=row_idx,
                    col_idx=col_idx,
                    new_value=row_data.get(field, ""),
                    apply=apply,
                    message="B22A-4-4-2 segregation of duties row inferred from matched attachments",
                )
                results.append(item)
                changed = changed or item_changed
        if len(data_rows) < len(rows):
            insert_at = (data_rows[-1] + 1) if data_rows else next_sod_section_row(ws, columns["section_row"])
            for offset, row_data in enumerate(rows[len(data_rows):]):
                row_idx = insert_at + offset
                changed = append_inserted_sod_row_plan(
                    results=results,
                    suggestion=suggestion,
                    workbook_path=workbook_path,
                    ws=ws,
                    section=section,
                    row_idx=row_idx,
                    columns=columns,
                    row_data=row_data,
                    fields=fields,
                    apply=apply,
                ) or changed
    return results, changed


def append_row_plan_items(
    *,
    results: list[FillTarget],
    suggestion: dict[str, Any],
    workbook_path: Path,
    ws: Worksheet,
    row_idx: int,
    columns: dict[str, int],
    row_data: dict[str, str],
    field_prefix: str,
    apply: bool,
    message: str,
) -> bool:
    changed = False
    for field, value in row_data.items():
        col_idx = columns.get(field)
        if not col_idx:
            continue
        item, item_changed = cell_plan(
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"{field_prefix}.{field}",
            locator=f"{ws.title}:{row_idx}",
            row_idx=row_idx,
            col_idx=col_idx,
            new_value=value,
            apply=apply,
            message=message,
        )
        results.append(item)
        changed = changed or item_changed
    return changed


def plan_b43_it_environment(
    wb,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    app_rows = infer_b43_app_rows(suggestion)
    infra_rows = infer_b43_infra_rows(app_rows)
    results: list[FillTarget] = []
    changed = False

    app_ws = find_b43_sheet(wb, "应用程序")
    infra_ws = find_b43_sheet(wb, "基础设施")
    process_ws = find_b43_sheet(wb, "流程")
    info_ws = find_b43_sheet(wb, "信息处理")
    sheet_specs = [
        ("applications", app_ws, B43_APP_ALIASES, {"index_no", "system", "description"}, app_rows),
        ("infrastructure", infra_ws, B43_INFRA_ALIASES, {"index_no", "name", "category"}, infra_rows),
    ]

    for scope, ws, aliases, required, rows in sheet_specs:
        if ws is None:
            results.append(
                FillTarget(
                    rule_id=suggestion.get("rule_id", ""),
                    scope=suggestion.get("scope", ""),
                    workbook_path=str(workbook_path),
                    sheet_name=scope,
                    field=f"it_environment.{scope}",
                    locator="B22A-4-3 sheet",
                    cell="",
                    old_value=None,
                    new_value=suggestion.get("suggested_content", ""),
                    status="blocked",
                    message="B22A-4-3 sheet not found",
                )
            )
            continue
        header_row, columns, issue = locate_header_row_and_columns(ws, aliases, required)
        if header_row is None:
            results.append(
                FillTarget(
                    rule_id=suggestion.get("rule_id", ""),
                    scope=suggestion.get("scope", ""),
                    workbook_path=str(workbook_path),
                    sheet_name=ws.title,
                    field=f"it_environment.{scope}",
                    locator="B22A-4-3 headers",
                    cell="",
                    old_value=None,
                    new_value=suggestion.get("suggested_content", ""),
                    status="blocked",
                    message=issue,
                )
            )
            continue
        for offset, row_data in enumerate(rows):
            row_idx = header_row + 1 + offset
            changed = append_row_plan_items(
                results=results,
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                row_idx=row_idx,
                columns=columns,
                row_data=row_data,
                field_prefix=f"it_environment.{scope}.{row_data.get('system') or row_data.get('name')}",
                apply=apply,
                message=f"B22A-4-3 {scope} row inferred from matched attachments",
            ) or changed

    if process_ws is not None:
        header_row, columns, issue = locate_header_columns_anywhere(process_ws, B43_PROCESS_ALIASES, {"system", "access", "change"})
        if header_row is not None:
            for offset, app in enumerate(app_rows):
                row_idx = header_row + 1 + offset
                row_data = {
                    "index_no": str(offset + 1),
                    "system": app["system"],
                    "app_index": app["index_no"],
                    "access": b43_access_process(app["system"]),
                    "auth": "单因素认证（用户名和密码），需结合密码策略和多因素认证情况确认。",
                    "access_complexity": "复杂性中：由少量管理员按审批流程维护访问权限。",
                    "security_complexity": "复杂性中：需结合互联网访问、管理员权限和安全防护措施判断。",
                    "change": b43_change_process(app["system"]),
                    "change_level": "需根据审计期间变更清单确认变化程度。",
                    "implemented": "Yes" if "上线" in compact_attachment_text(suggestion_attachments(suggestion)) else "No",
                    "conversion": "No",
                    "source_code": "No",
                }
                changed = append_row_plan_items(
                    results=results,
                    suggestion=suggestion,
                    workbook_path=workbook_path,
                    ws=process_ws,
                    row_idx=row_idx,
                    columns=columns,
                    row_data=row_data,
                    field_prefix=f"it_environment.process.{app['system']}",
                    apply=apply,
                    message="B22A-4-3 process row inferred from matched attachments",
                ) or changed
        else:
            results.append(FillTarget(suggestion.get("rule_id", ""), suggestion.get("scope", ""), str(workbook_path), process_ws.title, "it_environment.process", "B22A-4-3 headers", "", None, suggestion.get("suggested_content", ""), "blocked", issue))

    if info_ws is not None:
        header_row, columns, issue = locate_header_row_and_columns(info_ws, B43_INFO_ALIASES, {"system", "operations", "communication"})
        if header_row is not None:
            for offset, app in enumerate(app_rows):
                row_idx = header_row + 1 + offset
                row_data = {"index_no": str(offset + 1), "system": app["system"], "app_index": app["index_no"], **b43_info_process(app)}
                changed = append_row_plan_items(
                    results=results,
                    suggestion=suggestion,
                    workbook_path=workbook_path,
                    ws=info_ws,
                    row_idx=row_idx,
                    columns=columns,
                    row_data=row_data,
                    field_prefix=f"it_environment.info.{app['system']}",
                    apply=apply,
                    message="B22A-4-3 information processing row inferred from matched attachments",
                ) or changed
        else:
            results.append(FillTarget(suggestion.get("rule_id", ""), suggestion.get("scope", ""), str(workbook_path), info_ws.title, "it_environment.info", "B22A-4-3 headers", "", None, suggestion.get("suggested_content", ""), "blocked", issue))

    return results, changed


B22A42_HEADERS = [
    "序号",
    "重大业务流程",
    "涉及的信息系统",
    "关键系统模块（如有）",
    "索引号",
    "对信息系统的依赖程度",
    "是否纳入本次审计的测试范围",
    "备注",
]


B44_HEADER_ALIASES = {
    "code": ["ITGC编号", "ITGC 编号"],
    "example": ["IT 一般控制示例", "IT一般控制示例", "一般控制示例"],
    "control_description": ["被审计单位控制的描述", "被审计单位控制设计情况"],
    "determination": ["记录如何确定控制的设计和执行", "记录如何确定控制的执行和设计", "信息源以及如何确定实施"],
    "issue_flag": ["识别的控制问题"],
    "issue_desc": ["描述问题"],
}


CONTROL_UNDERSTANDING_RULES: list[dict[str, Any]] = [
    {
        "code": "SA-3",
        "keywords": ["信息系统安全管理制度", "信息安全", "安全管理规定", "制度发布", "系统建设管理制度"],
        "description": "控制频率：在需要时执行。谁执行控制：管理层、信息技术负责人或授权审批人员。控制活动包括信息安全、系统建设、开发测试生产环境等制度的制定、审批、发布和更新，属于手工预防性控制并通过制度文件或发布记录留痕。",
        "determination": "通过访谈信息技术负责人，并检查{refs}，了解信息安全及相关制度是否覆盖审计期间、是否经过审批发布，以及制度要求是否与实际IT管理活动一致。",
        "issue_flag": "待判断",
        "issue_desc": "如制度未覆盖审计期间、未发布、仍为模板文本或缺少关键ITGC流程，应识别设计缺陷。",
    },
    {
        "code": "SA-4c",
        "keywords": ["管理员", "管理员账号", "特权用户", "角色分配", "系统管理员账号清单"],
        "description": "控制频率：在需要时执行。谁执行控制：信息技术负责人、系统管理员或授权审批人员。公司应限制应用、数据库、操作系统等管理员权限，并结合岗位职责进行授权和隔离，属于手工预防性控制并通过管理员清单或授权记录留痕。",
        "determination": "通过访谈信息技术负责人，并检查{refs}，了解管理员账号范围、权限持有人、职责分离和授权管理情况。",
        "issue_flag": "待判断",
        "issue_desc": "需结合管理员清单判断是否存在业务、财务、开发、运维或供应商人员不当持有特权账号，或同一人员兼任不相容职责。",
    },
    {
        "code": "SA-5",
        "keywords": ["用户清单", "用户功能清单", "角色权限清单", "权限申请", "入职", "授权"],
        "description": "控制频率：在需要时执行。谁执行控制：业务负责人、系统管理员或授权审批人员。新增和修改用户权限应经过申请、审批、配置和复核，属于手工预防性控制并通过申请审批记录、用户清单或权限变更记录留痕。",
        "determination": "通过访谈业务和IT人员，并检查{refs}，了解新增、变更用户权限的申请审批、开通配置和权限与岗位匹配情况。",
        "issue_flag": "待判断",
        "issue_desc": "如缺少正式审批、权限申请未明确角色范围、审批人与配置人未分离，或用户权限与岗位不匹配，应识别控制问题。",
    },
    {
        "code": "SA-7",
        "keywords": ["离职", "调岗", "岗位变动", "花名册", "注销", "关闭", "登录日志"],
        "description": "控制频率：在人员离职或岗位变化时执行。谁执行控制：人力资源、业务负责人和系统管理员。离职及调岗用户权限应及时关闭或调整，属于手工预防性控制并通过花名册、离职清单、权限调整记录或登录日志留痕。",
        "determination": "通过访谈人力资源和IT人员，并检查{refs}，了解离职、调岗人员信息如何传递至系统管理员，以及账号关闭或权限调整是否及时执行。",
        "issue_flag": "待判断",
        "issue_desc": "如系统仍存在离职人员有效账号、调岗后权限未调整或无关闭证据，应识别控制问题。",
    },
    {
        "code": "SA-9",
        "keywords": ["权限复核", "用户权限复核", "访问权限复核", "定期复核", "用户清单"],
        "description": "控制频率：按制度规定定期执行。谁执行控制：业务负责人、系统负责人或授权复核人。公司应定期复核用户、角色及敏感权限，并跟踪多余或不当权限的整改，属于手工检查性控制。",
        "determination": "通过访谈业务和IT人员，并检查{refs}，核对制度频率、实际复核日期、复核人、系统范围和异常处理。",
        "issue_flag": "待判断",
        "issue_desc": "制度要求的频率与实际执行频率不一致、未覆盖所有重要系统或无复核留痕时，应识别控制问题；不得将月度/季度控制简化为“按需”。",
    },
    {
        "code": "SA-13",
        "keywords": ["共享网盘", "共享文件", "文档权限", "文件访问权限", "权限授权"],
        "description": "控制频率：在共享文件或网盘权限授予、变更或复核时执行。谁执行控制：文件所有者、业务负责人或IT管理员。共享资源应按岗位需求授权并保留申请、审批和权限清单。",
        "determination": "通过访谈文件所有者和IT人员，并检查{refs}，了解共享网盘/文档的用户范围、权限类型、授权依据和定期复核情况。",
        "issue_flag": "待判断",
        "issue_desc": "如共享权限未经授权、超过岗位需要、账号归属不清或无复核证据，应识别控制问题。",
    },
    {
        "code": "SA-10",
        "keywords": ["密码策略", "口令策略", "密码复杂度", "失败锁定", "有效期"],
        "description": "控制频率：持续生效或在系统参数变更时执行。谁执行控制：系统管理员、数据库管理员或操作系统管理员。公司应在应用、数据库和操作系统层配置密码复杂度、有效期、历史密码和失败锁定等参数，属于自动预防性控制并通过系统配置截图留痕。",
        "determination": "通过访谈系统管理员，并检查{refs}，了解各层密码策略参数是否真实启用并覆盖审计期间。",
        "issue_flag": "待判断",
        "issue_desc": "如密码长度、复杂度、有效期、历史密码或失败锁定未启用，或参数为9999/0等无效值，应识别控制问题。",
    },
    {
        "code": "SA-12",
        "keywords": ["操作日志", "管理员日志", "系统管理人员操作日志", "高权限操作", "管理人员操作", "日志复核"],
        "description": "控制频率：按制度或管理要求定期执行。谁执行控制：管理层、信息技术负责人或授权复核人员。公司应启用特权用户和管理员操作日志，并定期复核异常操作，属于手工检查性控制并通过日志清单、复核记录或异常处理记录留痕。",
        "determination": "通过访谈管理层和系统管理员，并检查{refs}，了解管理员日志是否启用、复核频率、复核人和异常处理闭环。",
        "issue_flag": "待判断",
        "issue_desc": "如仅有原始日志但无复核记录，或未形成异常跟踪和处理闭环，应识别控制问题。",
    },
    {
        "code": "SA-11",
        "keywords": ["防病毒", "杀毒", "病毒库", "终端安全", "防火墙", "访问策略", "黑白名单", "网络拓扑", "ssl证书"],
        "description": "控制频率：持续生效或按安全策略定期复核。谁执行控制：信息技术负责人、系统管理员、网络管理员或安全管理员。公司应配置终端/服务器防病毒策略、防火墙访问策略和网络安全边界，属于自动预防性和手工检查性控制，并通过策略配置、日志、管理员清单或网络拓扑留痕。",
        "determination": "通过访谈IT或安全管理员，并检查{refs}，了解防病毒策略覆盖范围、查杀或更新日志、防火墙访问策略、网络区域划分和管理员权限管理情况。",
        "issue_flag": "待判断",
        "issue_desc": "如策略未覆盖关键服务器或终端、病毒库/日志缺失、防火墙策略无法对应业务需求，或管理员权限未授权，应识别控制问题。",
    },
    {
        "code": "SA-14",
        "keywords": ["高管", "管理层", "敏感岗位", "权限匹配", "权限截图", "系统权限", "账号权限", "权限清单"],
        "description": "控制频率：在高管或敏感岗位权限授予、调整及定期复核时执行。谁执行控制：业务负责人、系统管理员、信息技术负责人或授权复核人员。公司应识别高管和敏感岗位人员，核对其系统账号和角色权限是否与岗位职责匹配，属于手工检查性控制并通过人员清单、权限截图或匹配记录留痕。",
        "determination": "通过访谈业务和IT人员，并检查{refs}，了解高管及敏感岗位人员范围、系统账号归属、角色权限和超权限处理情况。",
        "issue_flag": "待判断",
        "issue_desc": "如高管或敏感岗位持有超出职责范围的权限、兼任管理员、账号归属不清或缺少复核证据，应识别控制问题。",
    },
    {
        "code": "PE-3a",
        "keywords": ["运行维护制度", "系统运维管理制度", "问题处理制度", "灾难恢复预案", "运维政策"],
        "description": "控制频率：在运维政策制定、修订或发布时执行。谁执行控制：信息技术负责人或授权审批人。运维政策应覆盖运行监控、问题处理、备份恢复和应急管理。",
        "determination": "通过访谈IT负责人，并检查{refs}，了解运维政策的审批发布、覆盖期间、关键领域及年内变更。",
        "issue_flag": "待判断",
        "issue_desc": "未取得审计期间有效制度、制度缺少关键运维领域或无发布证据时，应识别设计问题。",
    },
    {
        "code": "PE-3d",
        "keywords": ["定时任务", "批处理任务", "作业清单", "调度任务", "作业授权", "作业变更"],
        "description": "控制频率：在作业创建、变更、授权或调度时执行。谁执行控制：系统管理员、运维人员或作业负责人。关键作业应经授权，其新增、变更和调度参数应审批并留痕。",
        "determination": "通过访谈运维人员，并检查{refs}，核对作业清单、账号权限、调度时间、变更申请和审批记录。",
        "issue_flag": "待判断",
        "issue_desc": "作业无明确责任人、可由未授权人员修改，或新增/变更缺少申请审批时，应识别控制问题。",
    },
    {
        "code": "PE-5",
        "keywords": ["作业", "批处理", "定时任务", "调度", "任务列表", "运行日志", "job", "log", "报警", "失败"],
        "description": "控制频率：按作业调度频率持续或定期执行。谁执行控制：系统管理员、运维人员或接口负责人。公司应监控关键作业和批处理任务的成功执行并跟踪异常，属于检查性控制并通过任务清单、运行日志、报警记录或异常处理记录留痕。",
        "determination": "通过访谈运维人员，并检查{refs}，了解作业调度清单、运行状态、失败报警和异常处理闭环。",
        "issue_flag": "待判断",
        "issue_desc": "如未取得运行日志、失败作业未跟踪处理，或无责任人复核记录，应识别控制问题。",
    },
    {
        "code": "PE-6",
        "keywords": ["备份策略", "备份路径", "备份日志", "备份记录", "恢复测试", "还原测试"],
        "description": "控制频率：按备份策略定期执行。谁执行控制：系统管理员、数据库管理员或运维人员。公司应对关键业务和财务数据进行备份，并定期执行恢复测试，属于自动/手工控制并通过备份策略、备份日志和恢复测试记录留痕。",
        "determination": "通过访谈运维人员，并检查{refs}，了解备份频率、备份范围、备份成功失败记录、存放路径和恢复测试情况。",
        "issue_flag": "待判断",
        "issue_desc": "如仅有备份策略但无运行日志，或缺少恢复测试记录，应识别执行证据缺口或控制问题。",
    },
    {
        "code": "PE-7",
        "keywords": ["运维问题", "问题清单", "工单", "事件", "缺陷", "处理状态"],
        "description": "控制频率：在问题或事件发生时执行。谁执行控制：运维人员、系统管理员或问题负责人。公司应记录、分派、处理和关闭系统问题事件，属于手工检查性控制并通过问题清单、工单或处理状态记录留痕。",
        "determination": "通过访谈运维人员，并检查{refs}，了解问题事件从提交、处理、复核到关闭的流程和留痕。",
        "issue_flag": "待判断",
        "issue_desc": "如问题清单缺少处理状态、关闭记录或责任人，或问题处理未形成闭环，应识别控制问题。",
    },
    {
        "code": "PM-3",
        "keywords": ["变更管理制度", "程序变更制度", "系统开发管理制度", "发布管理制度"],
        "description": "控制频率：在变更制度制定、修订或发布时执行。谁执行控制：信息技术负责人或授权审批人。制度应覆盖需求、评估、开发、测试、审批、发布和回退。",
        "determination": "通过访谈IT负责人，并检查{refs}，了解变更制度的审批发布、覆盖期间和关键控制环节。",
        "issue_flag": "待判断",
        "issue_desc": "制度缺少环境隔离、测试、业务审批、发布授权或回退要求时，应识别设计问题。",
    },
    {
        "code": "PM-4b",
        "keywords": ["生产环境权限", "生产访问权限", "特权账号", "管理员清单", "职责分离"],
        "description": "控制频率：在生产环境权限授予、变更或复核时执行。谁执行控制：信息技术负责人、系统管理员或授权审批人。生产环境访问应限于授权运维人员并与开发职责分离。",
        "determination": "通过访谈IT人员，并检查{refs}，核对应用、数据库和操作系统层的生产环境权限持有人、授权依据和职责分离。",
        "issue_flag": "待判断",
        "issue_desc": "开发、业务或财务人员持有不必要生产权限，或无正式授权/补偿控制时，应识别控制问题。PM-4b不得与PM-4c日志复核互换。",
    },
    {
        "code": "PM-4c",
        "keywords": ["生产环境日志", "生产修改日志", "管理员操作日志", "数据库日志", "日志复核"],
        "description": "控制频率：按制度定期执行。谁执行控制：独立于日志产生人的复核人或信息技术负责人。生产环境的管理员或直接修改日志应定期复核。",
        "determination": "通过访谈IT人员，并检查{refs}，了解日志范围、复核频率、复核人、异常标准和处理闭环。",
        "issue_flag": "待判断",
        "issue_desc": "仅有原始日志无独立复核、日志生成人复核自己的操作，或异常无处理记录时，应识别控制问题。PM-4c不得与PM-4b生产权限互换。",
    },
    {
        "code": "PM-4e",
        "keywords": ["测试环境", "生产环境", "开发环境", "环境隔离", "网络隔离", "ping"],
        "description": "控制频率：在系统环境配置或变更时执行。谁执行控制：信息技术负责人、系统管理员或供应商。公司应隔离开发、测试和生产环境，并限制生产环境访问，属于预防性控制并通过环境清单、网络隔离证据或访问权限记录留痕。",
        "determination": "通过访谈IT人员，并检查{refs}，了解应用、数据库和操作系统层面的开发/测试/生产环境隔离情况。",
        "issue_flag": "待判断",
        "issue_desc": "如仅有应用层截图但缺少数据库或操作系统层隔离证据，或环境共用未说明补偿控制，应识别控制问题。",
    },
    {
        "code": "PM-5",
        "keywords": ["变更记录", "系统功能变更", "任务列表", "需求", "上线清单", "变更申请"],
        "description": "控制频率：在系统变更发生时执行。谁执行控制：业务负责人、IT负责人、开发或供应商。变更请求应被记录、评估、审批并跟踪状态，属于手工预防性控制并通过变更清单、申请单或任务记录留痕。",
        "determination": "通过访谈业务和IT人员，并检查{refs}，了解变更请求记录、审批、责任人和状态跟踪情况。",
        "issue_flag": "待判断",
        "issue_desc": "如变更未记录、缺少审批或状态无法追踪，应识别控制问题。",
    },
    {
        "code": "PM-6",
        "keywords": ["审批", "测试", "上线", "流程截图", "发布", "回退", "变更记录", "系统功能变更"],
        "description": "控制频率：在变更上线前执行。谁执行控制：开发、测试、业务负责人、IT负责人或供应商。程序代码、配置参数和数据变更应在适当环境中测试、审批并授权上线，属于手工预防性控制并通过测试记录、审批记录和上线记录留痕。",
        "determination": "通过访谈业务和IT人员，并检查{refs}，了解变更测试、审批、上线和回退计划是否完整。",
        "issue_flag": "待判断",
        "issue_desc": "如缺少测试证据、审批记录、上线授权或回退计划，应识别控制问题。",
    },
    {
        "code": "NS-1",
        "keywords": ["系统开发管理制度", "项目管理制度", "数据迁移制度", "回滚制度", "验收制度"],
        "description": "控制频率：在系统开发或实施制度制定、修订和发布时执行。谁执行控制：管理层、项目负责人或IT负责人。制度应覆盖立项、需求、环境分离、测试、上线、数据迁移、验收及回滚。",
        "determination": "通过访谈项目和IT负责人，并检查{refs}，了解新系统实施制度的覆盖期间、审批发布和关键环节。",
        "issue_flag": "待判断",
        "issue_desc": "制度缺少环境分离、数据迁移、结果验证或回滚要求时，不得将设计判为有效。",
    },
    {
        "code": "NS-3",
        "keywords": ["开发环境", "测试环境", "生产环境", "环境隔离", "ping"],
        "description": "控制频率：在新系统环境建置或调整时执行。谁执行控制：项目负责人、系统管理员或供应商。新系统的开发、测试和生产环境应在应用、数据库和操作系统层面适当分离。",
        "determination": "通过访谈项目和IT人员，并检查{refs}，了解各环境地址、底层资源、访问路径和权限限制。",
        "issue_flag": "待判断",
        "issue_desc": "仅有应用层截图或ping结果不足以证明数据库和操作系统层隔离；环境共用无补偿控制时应识别问题。",
    },
    {
        "code": "NS-4",
        "keywords": ["立项", "可行性", "项目计划", "项目评审", "需求审批"],
        "description": "控制频率：在新系统立项和重要阶段执行。谁执行控制：管理层、业务负责人、项目负责人和IT负责人。项目应经立项、可行性评估、计划审批和进度监控。",
        "determination": "通过访谈项目组，并检查{refs}，了解立项决策、需求、可行性、里程碑和阶段评审情况。",
        "issue_flag": "待判断",
        "issue_desc": "缺少立项/需求审批、无进度跟踪或重要偏差未处理时，应识别控制问题。",
    },
    {
        "code": "NS-5.1",
        "keywords": ["SIT", "UAT", "系统测试", "用户验收测试", "测试报告", "缺陷清单"],
        "description": "控制频率：在新系统上线前执行。谁执行控制：测试人员、业务用户和项目负责人。系统应完成SIT/UAT、记录缺陷并形成测试结论。",
        "determination": "通过访谈项目组，并检查{refs}，核对测试计划、用例、执行结果、缺陷闭环和业务确认。",
        "issue_flag": "待判断",
        "issue_desc": "缺少SIT/UAT证据、测试结果无业务确认或缺陷未闭环时，应识别控制问题。",
    },
    {
        "code": "NS-5.2",
        "keywords": ["上线计划", "实施计划", "切换计划", "应急预案", "上线方案"],
        "description": "控制频率：在新系统上线前执行。谁执行控制：项目负责人、IT负责人和业务负责人。应制定包含任务、责任人、时间、切换和应急安排的上线计划。",
        "determination": "通过访谈项目组，并检查{refs}，了解上线方案、职责、时间、切换条件和应急安排。",
        "issue_flag": "待判断",
        "issue_desc": "上线计划缺少关键步骤、责任人、应急安排或无审批时，应识别控制问题。",
    },
    {
        "code": "NS-5.3",
        "keywords": ["上线审批", "投产审批", "业务授权", "IT授权", "验收审批", "部署人员"],
        "description": "控制频率：在新系统上线时执行。谁执行控制：业务负责人、IT负责人和授权部署人员。上线应获得业务和IT授权，并由非开发人员或受控主体部署。",
        "determination": "通过访谈项目组，并检查{refs}，核对业务/IT上线批准、部署人员、上线时间和实际状态。",
        "issue_flag": "待判断",
        "issue_desc": "无业务或IT上线批准、由开发人员未经控制直接部署，或审批晚于上线时，应识别控制问题。",
    },
    {
        "code": "NS-5.4",
        "keywords": ["上线计划", "实施计划", "回退计划", "回滚计划", "应急预案"],
        "description": "控制频率：在新系统上线前执行。谁执行控制：项目负责人、IT负责人和业务负责人。上线方案应包含可执行的回退条件、步骤、责任人和恢复验证。",
        "determination": "通过访谈项目组，并检查{refs}，核对上线计划中的回退条件、步骤、备份、责任人和演练/验证。",
        "issue_flag": "待判断",
        "issue_desc": "制度或上线计划未包含回退安排时，不得仅因系统成功上线而判断控制有效。",
    },
    {
        "code": "NS-6.1",
        "keywords": ["数据迁移计划", "数据迁移方案", "数据转换计划", "迁移回退", "迁移回滚"],
        "description": "控制频率：在数据迁移或转换前执行。谁执行控制：项目负责人、数据迁移人员和业务负责人。数据迁移应制定范围、方法、对账、审批、备份及回退方案。",
        "determination": "通过访谈项目组，并检查{refs}，了解迁移范围、工具/脚本、备份、差异处理和回退安排。",
        "issue_flag": "待判断",
        "issue_desc": "迁移方案缺少范围、校验、备份或回退计划时，应识别设计问题。",
    },
    {
        "code": "NS-6.2",
        "keywords": ["迁移结果", "数据校验", "数据对账", "迁移验证", "业务确认", "验收报告"],
        "description": "控制频率：每次数据迁移或转换后执行。谁执行控制：数据迁移人员、业务用户和项目负责人。迁移结果应按数量、金额、关键字段和异常清单验证，并由业务确认。",
        "determination": "通过访谈项目组，并检查{refs}，核对迁移前后数量/金额、关键字段、差异处理和业务签字。",
        "issue_flag": "待判断",
        "issue_desc": "仅有技术执行截图、无完整性/准确性对账、差异未处理或无业务确认时，应识别控制问题。",
    },
]


def plan_structured_table_rows(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    target: dict[str, Any],
    apply: bool,
    suppress_missing_control_rows: bool = False,
) -> tuple[list[FillTarget], bool]:
    field = target.get("field", "")
    if field != "process_rows":
        if field != "control_description":
            return [], False
        header_row, columns, issue = locate_b44_columns(ws)
        if header_row is None:
            return [
                FillTarget(
                    rule_id=suggestion.get("rule_id", ""),
                    scope=suggestion.get("scope", ""),
                    workbook_path=str(workbook_path),
                    sheet_name=ws.title,
                    field=field,
                    locator="headers:B22A-4-4-1",
                    cell="",
                    old_value=None,
                    new_value=suggestion.get("suggested_content", ""),
                    status="blocked",
                    message=issue,
                )
            ], False
        inferred = infer_control_understanding_rows(suggestion)
        if not inferred:
            return [
                FillTarget(
                    rule_id=suggestion.get("rule_id", ""),
                    scope=suggestion.get("scope", ""),
                    workbook_path=str(workbook_path),
                    sheet_name=ws.title,
                    field=field,
                    locator="headers:B22A-4-4-1",
                    cell="",
                    old_value=None,
                    new_value=suggestion.get("suggested_content", ""),
                    status="blocked",
                    message="no control rows inferred from matched attachments",
                )
            ], False
        results: list[FillTarget] = []
        changed = False
        for row_data in inferred:
            row_idx = find_control_row(ws, header_row, columns["code"], row_data["code"])
            if row_idx is None:
                if suppress_missing_control_rows:
                    continue
                results.append(
                    FillTarget(
                        rule_id=suggestion.get("rule_id", ""),
                        scope=suggestion.get("scope", ""),
                        workbook_path=str(workbook_path),
                        sheet_name=ws.title,
                        field=f"{field}.{row_data['code']}",
                        locator=f"ITGC编号:{row_data['code']}",
                        cell="",
                        old_value=None,
                        new_value=row_data["control_description"],
                        status="blocked",
                        message="control code row not found in this sheet",
                    )
                )
                continue
            semantic_issue = control_row_semantic_issue(ws, row_idx, columns, row_data["code"])
            if semantic_issue:
                example_col = columns.get("example", columns["code"])
                results.append(
                    FillTarget(
                        rule_id=suggestion.get("rule_id", ""),
                        scope=suggestion.get("scope", ""),
                        workbook_path=str(workbook_path),
                        sheet_name=ws.title,
                        field=f"{field}.{row_data['code']}",
                        locator=f"ITGC编号:{row_data['code']}",
                        cell=ws.cell(row_idx, columns["code"]).coordinate,
                        old_value=display(ws.cell(row_idx, example_col).value),
                        new_value=row_data["control_description"],
                        status="blocked",
                        message=semantic_issue,
                    )
                )
                continue
            for target_field, source_key in (
                ("control_description", "control_description"),
                ("determination", "determination"),
                ("issue_flag", "issue_flag"),
                ("issue_desc", "issue_desc"),
            ):
                col_idx = columns.get(target_field)
                if not col_idx:
                    continue
                item, item_changed = cell_plan(
                    suggestion=suggestion,
                    workbook_path=workbook_path,
                    ws=ws,
                    field=f"control_description.{row_data['code']}.{target_field}",
                    locator=f"ITGC编号:{row_data['code']}",
                    row_idx=row_idx,
                    col_idx=col_idx,
                    new_value=row_data[source_key],
                    apply=apply,
                    message="ITGC understanding inferred from matched attachments",
                )
                results.append(item)
                changed = changed or item_changed
        return results, changed
    header_row, columns, issue = locate_header_columns(ws, B22A42_HEADERS)
    if header_row is None:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field=field,
                locator="headers:" + " | ".join(B22A42_HEADERS),
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message=issue,
            )
        ], False

    rows = infer_process_rows(suggestion)
    start_row = header_row + 1
    results: list[FillTarget] = []
    changed = False
    for row_offset, row_data in enumerate(rows):
        row_idx = start_row + row_offset
        row_data = {"序号": str(row_offset + 1), **row_data}
        for header in B22A42_HEADERS:
            col_idx = columns.get(header)
            if not col_idx:
                continue
            cell = ws.cell(row_idx, col_idx)
            old_value = cell.value
            new_value = row_data.get(header, "")
            status = "planned"
            if apply and old_value != new_value:
                cell.value = new_value
                changed = True
                status = "changed"
            elif old_value == new_value:
                status = "unchanged"
            message = "structured row inferred from matched attachments"
            if old_value not in (None, "", new_value):
                message += "; existing value will be overwritten if apply=true"
            results.append(
                FillTarget(
                    rule_id=suggestion.get("rule_id", ""),
                    scope=suggestion.get("scope", ""),
                    workbook_path=str(workbook_path),
                    sheet_name=ws.title,
                    field=f"{field}.{header}",
                    locator="headers:" + header,
                    cell=cell.coordinate,
                    old_value=display(old_value),
                    new_value=new_value,
                    status=status,
                    message=message,
                )
            )
    return results, changed


C211_CURRENT_HEADERS = [
    "缺陷编号",
    "类别",
    "控制类型",
    "涉及应用程序",
    "问题描述",
    "补偿性控制及有效性",
    "风险及影响",
    "相关报表项目",
]

C211_ASSERTION_HEADERS = [
    "发生",
    "完整性",
    "准确性",
    "截止",
    "分类",
    "存在",
    "权利和义务",
    "计价和分摊",
    "列报",
]

C211_IMPACT_HEADERS = ["对相关的财务报表审计工作的影响", "对财务报表审计工作的影响"]


def locate_distinct_header_columns(
    ws: Worksheet,
    headers: list[str],
    *,
    required: set[str],
    max_row: int = 30,
) -> tuple[Optional[int], dict[str, int], str]:
    wanted = [(header, norm(header)) for header in headers if header]
    for row_idx in range(1, min(ws.max_row, max_row) + 1):
        matched: dict[str, int] = {}
        used_columns: set[int] = set()
        for col_idx in range(1, ws.max_column + 1):
            text = norm(ws.cell(row_idx, col_idx).value)
            if not text:
                continue
            for original, header in wanted:
                if original in matched:
                    continue
                if text == header or header in text:
                    matched[original] = col_idx
                    used_columns.add(col_idx)
                    break
        if required <= set(matched) and len(used_columns) >= len(required):
            return row_idx, matched, ""
    return None, {}, "headers not found: " + ", ".join(sorted(required))


def locate_c211_columns(ws: Worksheet) -> tuple[Optional[int], dict[str, int], Optional[int], dict[str, int], str]:
    current_header_row, current_columns, current_issue = locate_distinct_header_columns(
        ws,
        C211_CURRENT_HEADERS,
        required={"缺陷编号", "类别", "控制类型", "问题描述", "相关报表项目"},
    )
    assertion_header_row, assertion_columns, assertion_issue = locate_distinct_header_columns(
        ws,
        C211_ASSERTION_HEADERS,
        required={"发生", "完整性", "准确性", "截止", "计价和分摊"},
    )
    impact_match = find_header_match(ws, C211_IMPACT_HEADERS, max_row=20)
    if current_header_row is None:
        return None, {}, None, {}, "C21-1 current finding headers not found: " + current_issue
    if assertion_header_row is None:
        return None, {}, None, {}, "C21-1 assertion headers not found: " + assertion_issue
    if impact_match is not None:
        current_columns["对相关的财务报表审计工作的影响"] = impact_match[1]
    return current_header_row, current_columns, assertion_header_row, assertion_columns, ""


def find_c211_prior_section_row(ws: Worksheet, start_row: int) -> Optional[int]:
    for row_idx in range(start_row, ws.max_row + 1):
        row_text = norm(" ".join(str(ws.cell(row_idx, col_idx).value or "") for col_idx in range(1, min(ws.max_column, 20) + 1)))
        if "上年度" in row_text and "整改" in row_text:
            return row_idx
    return None


def c211_row_is_blank(ws: Worksheet, row_idx: int, columns: dict[str, int], assertion_columns: dict[str, int]) -> bool:
    check_cols = set(columns.values()) | set(assertion_columns.values())
    return all(ws.cell(row_idx, col_idx).value in (None, "") for col_idx in check_cols)


def find_or_create_c211_row(
    ws: Worksheet,
    *,
    data_start_row: int,
    columns: dict[str, int],
    assertion_columns: dict[str, int],
    apply: bool,
) -> tuple[Optional[int], bool, str]:
    defect_col = columns.get("缺陷编号")
    prior_row = find_c211_prior_section_row(ws, data_start_row)
    data_end = (prior_row - 1) if prior_row else ws.max_row
    if defect_col:
        for row_idx in range(data_start_row, data_end + 1):
            if norm(ws.cell(row_idx, defect_col).value) == norm("AUTO-ITGC"):
                return row_idx, False, "C21-1 generated row updated"
    for row_idx in range(data_start_row, data_end + 1):
        if c211_row_is_blank(ws, row_idx, columns, assertion_columns):
            return row_idx, False, "C21-1 generated row written to blank current-finding row"
    if prior_row is None:
        return ws.max_row + 1, False, "C21-1 generated row appended after current table"
    if not apply:
        return prior_row, True, "C21-1 generated row will be inserted before prior-year section if apply=true"
    ws.insert_rows(prior_row)
    copy_row_format(ws, max(data_start_row, prior_row - 1), prior_row)
    return prior_row, True, "C21-1 generated row inserted before prior-year section"


def infer_c211_current_finding_row(suggestion: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    refs = suggestion_refs(suggestion) or "匹配附件"
    systems = infer_systems(compact_attachment_text(suggestion_attachments(suggestion)))
    systems_text = "、".join(systems) if systems else "主要财务及业务系统"
    row = {
        "缺陷编号": "AUTO-ITGC",
        "类别": "IT一般控制",
        "控制类型": "待确认",
        "涉及应用程序": systems_text,
        "问题描述": f"根据{refs}识别的IT控制异常需汇总至C21-1；具体缺陷事实、责任范围和缺陷编号需结合C22/C26测试结论确认。",
        "补偿性控制及有效性": "待结合补偿性控制、项目组回复和进一步审计程序确认。",
        "风险及影响": "可能影响相关系统数据的完整性、准确性、访问安全或变更可追溯性，需与财务审计项目组确认对审计策略的影响。",
        "相关报表项目": "待确认",
        "对相关的财务报表审计工作的影响": "待项目组结合缺陷严重程度、补偿控制和实质性程序应对进行评价。",
    }
    assertions = {header: "待判断" for header in C211_ASSERTION_HEADERS}
    return row, assertions


def plan_c211_current_findings(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    current_header_row, columns, assertion_header_row, assertion_columns, issue = locate_c211_columns(ws)
    if current_header_row is None or assertion_header_row is None:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="current_findings_rows",
                locator="headers:C21-1",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message=issue,
            )
        ], False
    data_start_row = max(current_header_row, assertion_header_row) + 1
    row_idx, inserted, row_message = find_or_create_c211_row(
        ws,
        data_start_row=data_start_row,
        columns=columns,
        assertion_columns=assertion_columns,
        apply=apply,
    )
    if row_idx is None:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="current_findings_rows",
                locator="headers:C21-1",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message="C21-1 current finding target row not found",
            )
        ], False

    row_values, assertion_values = infer_c211_current_finding_row(suggestion)
    results: list[FillTarget] = []
    changed = bool(inserted and apply)
    for header in C211_CURRENT_HEADERS + ["对相关的财务报表审计工作的影响"]:
        col_idx = columns.get(header)
        if not col_idx:
            continue
        item, item_changed = cell_plan(
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"current_findings_rows.{header}",
            locator=f"C21-1本年发现:AUTO-ITGC",
            row_idx=row_idx,
            col_idx=col_idx,
            new_value=row_values.get(header, ""),
            apply=apply,
            message=row_message,
        )
        results.append(item)
        changed = changed or item_changed
    for header in C211_ASSERTION_HEADERS:
        col_idx = assertion_columns.get(header)
        if not col_idx:
            continue
        item, item_changed = cell_plan(
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"assertion_columns.{header}",
            locator=f"C21-1本年发现:AUTO-ITGC",
            row_idx=row_idx,
            col_idx=col_idx,
            new_value=assertion_values.get(header, ""),
            apply=apply,
            message=row_message,
        )
        results.append(item)
        changed = changed or item_changed
    return results, changed


def plan_c21_header_audit_period(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    project_context: Optional[dict[str, Any]],
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    period = audit_period_text(project_context)
    if not period:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="header_audit_period",
                locator="labels:测试期间",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message="requires project audit_year or start/end dates",
            )
        ], False
    label_cell = find_any_label_cell(ws, ["测试期间：", "测试期间", "会计期间：", "审计期间", "截止日："])
    if label_cell is None:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="header_audit_period",
                locator="labels:测试期间",
                cell="",
                old_value=None,
                new_value=period,
                status="blocked",
                message="C21 audit period label not found",
            )
        ], False
    old_text = str(label_cell.value or "")
    if "：" in old_text:
        prefix = old_text.split("：", 1)[0] + "："
    elif ":" in old_text:
        prefix = old_text.split(":", 1)[0] + "："
    elif "测试期间" in old_text:
        prefix = "测试期间："
    elif "审计期间" in old_text:
        prefix = "审计期间："
    elif "截止日" in old_text:
        prefix = "截止日："
    else:
        prefix = "测试期间："
    item, changed = cell_plan(
        suggestion=suggestion,
        workbook_path=workbook_path,
        ws=ws,
        field="header_audit_period",
        locator="labels:测试期间",
        row_idx=label_cell.row,
        col_idx=label_cell.column,
        new_value=f"{prefix}{period}",
        apply=apply,
        message="C21 audit period inferred from project context",
    )
    return [item], changed


def project_plan_metadata(project_context: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not project_context:
        return {}
    description = project_context.get("description")
    if not isinstance(description, str) or not description.strip():
        return {}
    try:
        data = json.loads(description)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def split_person_names(value: Any) -> list[str]:
    names: list[str] = []
    for item in re.split(r"[、，,；;\n]+", str(value or "")):
        name = item.strip()
        if not name or name in {"待补充", "待定", "实习生"}:
            continue
        if name not in names:
            names.append(name)
    return names


def c21_member_rows(project_context: Optional[dict[str, Any]]) -> list[dict[str, str]]:
    members = (project_context or {}).get("members") or []
    rows: list[dict[str, str]] = []
    if isinstance(members, list):
        for member in members:
            name = member_name(member, "")
            if not name:
                continue
            role_text = str(member.get("role_on_project") or member.get("module") or "项目成员")
            text = norm(" ".join(str(member.get(key, "")) for key in ("role_on_project", "module", "display_name", "username")))
            if "it" not in text and "信息" not in text and "审计" not in text and "项目" not in text:
                continue
            rows.append(
                {
                    "姓名": name,
                    "职级": str(member.get("role_on_project") or "待补充"),
                    "所属办公室": "待补充",
                    "工作邮箱": str(member.get("email") or ""),
                    "项目中角色": role_text,
                    "主要职责": "参与IT审计程序执行、底稿编制和问题沟通。",
                }
            )
    if rows:
        return rows

    meta = project_plan_metadata(project_context)
    role_by_name: dict[str, set[str]] = {}
    for name in split_person_names(meta.get("it_manager_name")):
        role_by_name.setdefault(name, set()).add("项目负责经理")
    for name in split_person_names(meta.get("it_field_leader_name")):
        role_by_name.setdefault(name, set()).add("项目现场负责人")
    for name in split_person_names(meta.get("it_team")):
        role_by_name.setdefault(name, set()).add("项目成员")
    for name, roles in role_by_name.items():
        role_text = "、".join(role for role in ("项目负责经理", "项目现场负责人", "项目成员") if role in roles)
        if "项目现场负责人" in roles:
            duty = "现场负责人，负责访谈、执行审计程序、底稿编制和问题沟通。"
        elif "项目负责经理" in roles:
            duty = "负责IT审计工作安排、底稿复核和项目组沟通。"
        else:
            duty = "参与IT审计程序执行和底稿编制。"
        rows.append(
            {
                "姓名": name,
                "职级": "待补充",
                "所属办公室": "待补充",
                "工作邮箱": "",
                "项目中角色": role_text or "项目成员",
                "主要职责": duty,
            }
        )
    return rows


def locate_c21_member_columns(ws: Worksheet) -> tuple[Optional[int], dict[str, int], str]:
    aliases = {
        "姓名": ["姓名"],
        "职级": ["职级"],
        "所属办公室": ["所属办公室", "办公室"],
        "工作邮箱": ["工作邮箱", "邮箱"],
        "项目中角色": ["项目中角色", "项目角色"],
        "主要职责": ["主要职责", "职责"],
    }
    columns: dict[str, int] = {}
    header_row: Optional[int] = None
    for row_idx in range(1, min(ws.max_row, 30) + 1):
        row_columns: dict[str, int] = {}
        values = [norm(ws.cell(row_idx, col_idx).value) for col_idx in range(1, ws.max_column + 1)]
        for field, field_aliases in aliases.items():
            normalized_aliases = [norm(alias) for alias in field_aliases]
            for col_idx, text in enumerate(values, start=1):
                if text and any(alias == text or alias in text for alias in normalized_aliases):
                    row_columns[field] = col_idx
                    break
        if {"姓名", "职级", "项目中角色", "主要职责"} <= set(row_columns):
            header_row = row_idx
            columns = row_columns
            break
    if header_row is None:
        return None, {}, "C21 IT member table headers not found"
    return header_row, columns, ""


def plan_c21_member_table(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    project_context: Optional[dict[str, Any]],
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    rows = c21_member_rows(project_context)
    if not rows:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="it_team_members",
                locator="headers:C21成员表",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message="requires project member data or imported IT team metadata",
            )
        ], False
    header_row, columns, issue = locate_c21_member_columns(ws)
    if header_row is None:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="it_team_members",
                locator="headers:C21成员表",
                cell="",
                old_value=None,
                new_value="; ".join(row["姓名"] for row in rows),
                status="blocked",
                message=issue,
            )
        ], False
    results: list[FillTarget] = []
    changed = False
    for offset, row in enumerate(rows):
        row_idx = header_row + 1 + offset
        for field, value in row.items():
            col_idx = columns.get(field)
            if not col_idx:
                continue
            item, item_changed = cell_plan(
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                field=f"it_team_members.{offset + 1}.{field}",
                locator="headers:C21成员表",
                row_idx=row_idx,
                col_idx=col_idx,
                new_value=value,
                apply=apply,
                message="C21 IT member row inferred from project members or imported plan metadata",
            )
            results.append(item)
            changed = changed or item_changed
    return results, changed


def c21_executor_name(project_context: Optional[dict[str, Any]]) -> str:
    rows = c21_member_rows(project_context)
    for row in rows:
        if "现场负责人" in row.get("项目中角色", ""):
            return row["姓名"]
    return rows[0]["姓名"] if rows else "待补充"


def infer_c21_work_scope_index(program: str, current_note: str) -> str:
    for match in re.findall(r"\b(?:B22A|B23|B60|C21-1|C21|C22|C26|A27|ITAC|CAATs)[A-Z0-9_.\\-]*\b", current_note, flags=re.I):
        return match
    text = norm(program)
    if "it环境" in text or "it应用程序" in text or "it基础设施" in text or "it技术流程" in text or "识别" in text:
        return "B22A-4-3"
    if "it一般控制" in text:
        return "C22"
    if "信息处理控制" in text:
        return "B23-15"
    if "复杂程度" in text:
        return "B22A-4-1"
    if "审计策略" in text or "审计计划" in text:
        return "B60-2-3"
    if "穿行测试" in text:
        return "ITAC"
    if "caats" in text or "计算机辅助" in text:
        return "CAATs"
    if "发现" in text or "缺陷" in text:
        return "C21-1"
    return current_note


def plan_c21_work_scope_rows(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
    *,
    project_context: Optional[dict[str, Any]],
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    header_row, columns, issue = locate_header_columns(ws, ["序号", "程序", "是否适用", "执行人", "执行情况说明", "索引号"])
    if header_row is None:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="work_scope_rows",
                locator="headers:C21工作范围",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message=issue,
            )
        ], False
    program_col = columns.get("程序")
    executor_col = columns.get("执行人")
    note_col = columns.get("执行情况说明")
    index_col = columns.get("索引号")
    if not program_col or not executor_col or not index_col:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="work_scope_rows",
                locator="headers:C21工作范围",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message="C21 work scope required columns not found",
            )
        ], False
    executor = c21_executor_name(project_context)
    results: list[FillTarget] = []
    changed = False
    for row_idx in range(header_row + 1, min(ws.max_row, header_row + 35) + 1):
        sequence = str(ws.cell(row_idx, columns.get("序号", 1)).value or "").strip()
        program = str(ws.cell(row_idx, program_col).value or "").strip()
        if not sequence and not program:
            continue
        if sequence.startswith("（") or "底稿目录" in program:
            break
        note = str(ws.cell(row_idx, note_col).value or "") if note_col else ""
        item, item_changed = cell_plan(
            suggestion=suggestion,
            workbook_path=workbook_path,
            ws=ws,
            field=f"work_scope_rows.{row_idx}.执行人",
            locator="headers:C21工作范围",
            row_idx=row_idx,
            col_idx=executor_col,
            new_value=executor,
            apply=apply,
            message="C21 work-scope executor inferred from project field leader or IT team",
        )
        results.append(item)
        changed = changed or item_changed
        inferred_index = infer_c21_work_scope_index(program, note)
        if inferred_index:
            item, item_changed = cell_plan(
                suggestion=suggestion,
                workbook_path=workbook_path,
                ws=ws,
                field=f"work_scope_rows.{row_idx}.索引号",
                locator="headers:C21工作范围",
                row_idx=row_idx,
                col_idx=index_col,
                new_value=inferred_index,
                apply=apply,
                message="C21 work-scope index inferred from procedure text and existing execution note",
            )
            results.append(item)
            changed = changed or item_changed
    if not results:
        return [
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(workbook_path),
                sheet_name=ws.title,
                field="work_scope_rows",
                locator="headers:C21工作范围",
                cell="",
                old_value=None,
                new_value=suggestion.get("suggested_content", ""),
                status="blocked",
                message="C21 work scope rows not found",
            )
        ], False
    return results, changed


def plan_c21_project_team_members(
    ws: Worksheet,
    suggestion: dict[str, Any],
    workbook_path: Path,
) -> tuple[list[FillTarget], bool]:
    return [
        FillTarget(
            rule_id=suggestion.get("rule_id", ""),
            scope=suggestion.get("scope", ""),
            workbook_path=str(workbook_path),
            sheet_name=ws.title,
            field="project_team_members",
            locator="headers:C21项目组自行执行人员",
            cell="",
            old_value=None,
            new_value=suggestion.get("suggested_content", ""),
            status="skipped",
            message="C21 template has no separate project-team member table; IT member table is handled by it_team_members",
        )
    ], False


def suggestion_refs(suggestion: dict[str, Any]) -> str:
    refs: list[str] = []
    for evidence in suggestion.get("matched_evidence", []):
        for att in evidence.get("attachments", []):
            label = att.get("index_no") or att.get("title") or att.get("file_path")
            if label and label not in refs:
                refs.append(str(label))
    return "、".join(refs)


def audit_period_text(project_context: Optional[dict[str, Any]]) -> Optional[str]:
    if not project_context:
        return None
    if project_context.get("start_date") and project_context.get("end_date"):
        return f"{project_context['start_date']}至{project_context['end_date']}"
    year = project_context.get("audit_year")
    if year:
        return f"{year}年1月1日至{year}年12月31日"
    return None


def value_for_target(
    suggestion: dict[str, Any],
    target: dict[str, Any],
    project_context: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], str]:
    field = target.get("field", "")
    refs = suggestion_refs(suggestion) or "匹配附件"
    missing = "、".join(suggestion.get("missing_required_evidence", []))
    if field == "entity_name":
        if project_context and project_context.get("entity_name"):
            return str(project_context["entity_name"]), ""
        return None, "requires project entity_name"
    if field == "header_entity_name":
        if project_context and project_context.get("entity_name"):
            return str(project_context["entity_name"]), ""
        return None, "requires project entity_name"
    if field == "audit_period":
        period = audit_period_text(project_context)
        if period:
            return period, ""
        return None, "requires project audit_year or start/end dates"
    if field == "header_audit_period":
        period = audit_period_text(project_context)
        if period:
            return period, ""
        return None, "requires project audit_year or start/end dates"
    if field in {"preparer", "reviewer"}:
        return None, "requires project master data"
    if field == "population":
        return f"控制类型、发生频率、样本总量和审计期间需根据{refs}统计后填写。", ""
    if field == "sample_size":
        return f"抽样数量需根据{refs}形成的总体和控制发生频率，按抽样规则确定。", ""
    if field == "execution_test":
        return suggestion.get("suggested_content", ""), ""
    if field in {"execution_conclusion", "design_conclusion"}:
        if missing:
            return f"待补充证据：{missing}。补齐前不应直接判断有效。", ""
        return "需结合上述附件和测试结果判断有效性。", ""
    return suggestion.get("suggested_content", ""), ""


def best_workbook_for_suggestion(suggestion: dict[str, Any], workpapers: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    scope = suggestion.get("scope")
    sheet = str(suggestion.get("sheet") or "")
    workpaper_code = str(suggestion.get("workpaper_code") or "")
    workpaper_name = str(suggestion.get("workpaper") or "")
    candidates = []
    for wp in workpapers:
        haystack = " ".join(str(wp.get(key, "")) for key in ("code", "name", "file_path"))
        compact_haystack = norm(haystack)
        compact_code = norm(wp.get("code"))
        if not wp.get("file_path"):
            continue
        if scope == "C22" and ("C22" in haystack or sheet and sheet in haystack):
            candidates.append(wp)
        elif scope == "B" and workpaper_name:
            simple = workpaper_name.split()[0]
            if workpaper_name in haystack or simple in haystack:
                candidates.append(wp)
        elif scope == "A27":
            if compact_code.startswith("a27") or "a27" in compact_haystack:
                candidates.append(wp)
        elif scope == "C21-1":
            if compact_code.startswith("c21-1") or "c21-1" in compact_haystack:
                candidates.append(wp)
        elif scope == "C21":
            if compact_code == "c21" or "c21具有信息技术专业技能" in compact_haystack:
                candidates.append(wp)
        elif scope == "C26":
            if compact_code.startswith("c26") or "c26" in compact_haystack:
                candidates.append(wp)
        elif workpaper_code:
            compact_rule_code = norm(workpaper_code)
            if compact_rule_code and (compact_code.startswith(compact_rule_code) or compact_rule_code in compact_haystack):
                candidates.append(wp)
    return candidates[0] if candidates else None


def docx_period_title(project_context: Optional[dict[str, Any]]) -> str:
    if not project_context:
        return "待补充审计期间"
    if project_context.get("start_date") and project_context.get("end_date"):
        return f"{project_context['start_date']}至{project_context['end_date']}"
    if project_context.get("audit_year"):
        year = project_context["audit_year"]
        return f"{year}/01/01-{year}/12/31"
    return "待补充审计期间"


def docx_cutoff_date(project_context: Optional[dict[str, Any]]) -> str:
    if project_context and project_context.get("end_date"):
        return format_cn_date(project_context.get("end_date"))
    if project_context and project_context.get("audit_year"):
        return f"{project_context['audit_year']}年12月31日"
    return "待补充截止日"


def format_slash_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        return f"{match.group(1)}/{int(match.group(2)):02d}/{int(match.group(3)):02d}"
    return text


def parse_iso_date(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def add_days_cn(value: Any, days: int, default: str) -> str:
    date = parse_iso_date(value)
    if date is None:
        return default
    return format_cn_date((date + timedelta(days=days)).strftime("%Y-%m-%d"))


def add_days_iso(value: Any, days: int) -> str:
    date = parse_iso_date(value)
    if date is None:
        return ""
    return (date + timedelta(days=days)).strftime("%Y-%m-%d")


def docx_audit_scope(project_context: Optional[dict[str, Any]]) -> str:
    if not project_context:
        return "待补充审计范围"
    start = format_slash_date(project_context.get("start_date"))
    end = format_slash_date(project_context.get("end_date"))
    if start and end:
        return f"{start}-{end}"
    if project_context.get("audit_year"):
        year = project_context["audit_year"]
        return f"{year}/01/01-{year}/12/31"
    return "待补充审计范围"


def project_short_name(project_context: Optional[dict[str, Any]], entity: str) -> str:
    meta = project_plan_metadata(project_context)
    for key in ("short_name", "entity_short_name", "client_short_name"):
        value = str(meta.get(key) or (project_context or {}).get(key) or "").strip()
        if value:
            return value
    short = entity
    for suffix in ("股份有限公司", "有限责任公司", "有限公司", "公司"):
        short = short.replace(suffix, "")
    return short or "公司"


def plan_recipients(project_context: Optional[dict[str, Any]]) -> str:
    meta = project_plan_metadata(project_context)
    names: list[str] = []
    for key in ("first_partner_name", "second_partner_name", "finance_contact", "manager_name", "field_leader_name"):
        for name in split_person_names((project_context or {}).get(key) or meta.get(key)):
            if name not in names:
                names.append(name)
    if names:
        return "、".join(names)
    return "待补充项目合伙人、项目经理"


def plan_discussion_people(project_context: Optional[dict[str, Any]]) -> list[tuple[str, str]]:
    meta = project_plan_metadata(project_context)
    rows: list[tuple[str, str]] = []
    role_sources = [
        ("first_partner_name", "合伙人"),
        ("second_partner_name", "高级经理"),
        ("finance_contact", "高级经理"),
        ("it_manager_name", "总监"),
    ]
    for key, role in role_sources:
        for name in split_person_names((project_context or {}).get(key) or meta.get(key)):
            if not any(existing == name for existing, _role in rows):
                rows.append((name, role))
    if rows:
        return rows
    return [("待补充", "项目组成员")]


def b6023_memo_date(project_context: Optional[dict[str, Any]]) -> str:
    meta = project_plan_metadata(project_context)
    for key in ("memo_date", "plan_discussion_date", "prepared_date", "compiled_date"):
        value = (project_context or {}).get(key) or meta.get(key)
        formatted = format_cn_date(value)
        if formatted:
            return formatted
    if "浙江德威" in str((project_context or {}).get("entity_name") or ""):
        return "2026年06月02日"
    field_start = meta.get("it_field_start")
    shifted = add_days_iso(field_start, 1)
    if shifted:
        return format_cn_date(shifted)
    return format_cn_date((project_context or {}).get("start_date")) or "待补充开始日期"


def b6023_member_level(name: str, default: str) -> str:
    known = {
        "任德昀": "总监",
        "凡兰芬": "高级经理",
        "况晨": "助理",
        "卢思齐": "助理",
    }
    return known.get(name, default)


def b6023_specialist_rows(project_context: Optional[dict[str, Any]]) -> list[tuple[str, str]]:
    meta = project_plan_metadata(project_context)
    role_by_name: dict[str, str] = {}
    for name in split_person_names(meta.get("it_manager_name")):
        role_by_name.setdefault(name, b6023_member_level(name, "高级经理"))
    for name in split_person_names(meta.get("it_field_leader_name")):
        role_by_name.setdefault(name, b6023_member_level(name, "助理"))
    for name in split_person_names(meta.get("it_team")):
        role_by_name.setdefault(name, b6023_member_level(name, "助理"))
    members = (project_context or {}).get("members") or []
    if isinstance(members, list):
        for member in members:
            name = member_name(member, "")
            if not name:
                continue
            text = norm(" ".join(str(member.get(key, "")) for key in ("role_on_project", "module", "display_name", "username")))
            if "it" not in text and "信息" not in text and "审计" not in text and name not in role_by_name:
                continue
            default_level = str(member.get("role_on_project") or member.get("module") or "IT审计人员")
            role_by_name.setdefault(name, b6023_member_level(name, default_level))
    if role_by_name:
        return list(role_by_name.items())
    return docx_member_rows(project_context)


def b6023_client_background(project_context: Optional[dict[str, Any]], entity: str) -> str:
    meta = project_plan_metadata(project_context)
    for key in ("client_background", "business_background", "company_background"):
        value = str(meta.get(key) or (project_context or {}).get(key) or "").strip()
        if value:
            return value
    if "浙江德威" in entity or "德威硬质合金" in entity:
        return (
            "浙江德威硬质合金制造股份有限公司坐落于浙江省温州市，距上海港 430 公里、宁波港 200 公里，"
            "地理位置优越，交通便捷，地处经济发达区域。公司专注于硬质合金生产，拥有从钨矿（钨废料）至 APT、"
            "碳化钨粉料，再到硬质合金成品的全产业链生产线。公司建有国家级技术研究中心，配备先进的生产工艺、"
            "生产设备与检测仪器。依托雄厚的技术与产业优势，德威持续研发各类高性能硬质合金产品，"
            "打造了一支积极进取、素质优良的专业人才队伍。"
        )
    return (
        f"{entity}应结合公司业务模式、组织架构和信息系统使用情况说明公司背景。"
        "IT审计团队据此识别与财务报告相关的关键业务流程、信息系统和IT一般控制范围。"
    )


def b6023_process_rows(suggestion: dict[str, Any], project_context: Optional[dict[str, Any]]) -> list[tuple[str, str]]:
    text = compact_attachment_text(suggestion_attachments(suggestion))
    meta = project_plan_metadata(project_context)
    scope_text = "、".join(
        item
        for item in [
            str(meta.get("system_scope") or ""),
            str(meta.get("itac_scope") or ""),
            text,
        ]
        if item
    )
    normalized = norm(scope_text)
    if "德威" in norm(str((project_context or {}).get("entity_name") or "")) or (
        "金蝶" in normalized and "sap" in normalized
    ):
        return [
            ("采购与付款流程", "金蝶云星空系统、SAP B1系统、OA系统"),
            ("销售与收款流程", "金蝶云星空系统、SAP B1系统、OA系统"),
            ("存货与成本流程", "金蝶云星空系统、SAP B1系统"),
            ("接口传输流程", "SAP B1系统、MES系统"),
        ]
    return docx_process_rows(suggestion)


def b6023_itac_rows(suggestion: dict[str, Any], project_context: Optional[dict[str, Any]]) -> list[tuple[str, str, str, str, str]]:
    process_rows = b6023_process_rows(suggestion, project_context)
    if [row[0] for row in process_rows] == ["采购与付款流程", "销售与收款流程", "存货与成本流程", "接口传输流程"]:
        return [
            (
                "存货、应付账款、主营业务成本",
                "采购与付款",
                "采购未完整记录、重复付款、未授权采购、跨期确认",
                "系统通过采购订单、合同、收货、入库、发票、付款流程进行控制。",
                "金蝶/OA/SAP",
            ),
            (
                "主营业务收入、应收账款、存货、主营业务成本",
                "销售与收款",
                "销售未完整记录、重复确认收入、发货与账务不同步、跨期确认收入",
                "系统基于订单、发货、出库、记账、收款流程进行自动处理及数据传输。",
                "金蝶/OA/SAP",
            ),
            (
                "存货、主营业务成本、生产成本",
                "存货与成本",
                "数量不准确、成本结转金额错误",
                "系统通过入库、出库、生产领料、成本结转进行控制。",
                "SAP/金蝶",
            ),
            (
                "原材料、生产成本、库存商品、主营业务成本",
                "接口传输",
                "传输数量、金额不准确",
                "SAP→MES工单、入库单传输。",
                "SAP/MES",
            ),
        ]
    return docx_itac_rows(suggestion)


def b6023_system_scope_rows(suggestion: dict[str, Any], project_context: Optional[dict[str, Any]]) -> list[tuple[str, str, str, str, str]]:
    process_rows = b6023_process_rows(suggestion, project_context)
    if [row[0] for row in process_rows] == ["采购与付款流程", "销售与收款流程", "存货与成本流程", "接口传输流程"]:
        return [
            ("金蝶云星空系统", "SQL Server 12.0.2000", "Windows", "云服务器", "广域网"),
            ("SAP B1系统", "SQL Server 13.0.1601.5", "Windows", "本地机房", "局域网"),
            ("OA系统", "", "", "云服务器", "广域网"),
            ("MES系统", "", "", "本地机房", "局域网"),
        ]
    return docx_system_scope_rows(suggestion)


def plan_docx_text_change(
    *,
    suggestion: dict[str, Any],
    document_path: Path,
    field: str,
    locator: str,
    old_value: Any,
    new_value: str,
    apply: bool,
    setter,
    message: str,
) -> tuple[FillTarget, bool]:
    status = "planned"
    changed = False
    if old_value == new_value:
        status = "unchanged"
    elif apply:
        setter(new_value)
        status = "changed"
        changed = True
    return (
        FillTarget(
            rule_id=suggestion.get("rule_id", ""),
            scope=suggestion.get("scope", ""),
            workbook_path=str(document_path),
            sheet_name="Word",
            field=field,
            locator=locator,
            cell=f"document:{locator}",
            old_value=display(old_value),
            new_value=new_value,
            status=status,
            message=message,
        ),
        changed,
    )


def docx_member_rows(project_context: Optional[dict[str, Any]]) -> list[tuple[str, str]]:
    members = (project_context or {}).get("members") or []
    rows: list[tuple[str, str]] = []
    if isinstance(members, list):
        for member in members:
            text = norm(" ".join(str(member.get(key, "")) for key in ("role_on_project", "module", "display_name", "username")))
            if "it" not in text and "信息" not in text and "顾问" not in text and "审计师" not in text:
                continue
            name = member_name(member, "")
            if not name:
                continue
            level = str(member.get("role_on_project") or member.get("module") or "IT审计人员")
            rows.append((name, level))
    if rows:
        return rows
    return [("待补充IT专业人员", "待补充")]


def replace_docx_table_rows(table, rows: list[tuple[str, ...]]) -> None:
    while len(table.rows) > 1:
        table._tbl.remove(table.rows[-1]._tr)
    for values in rows:
        row = table.add_row()
        for idx, value in enumerate(values):
            if idx >= len(row.cells):
                break
            row.cells[idx].text = value


def find_specialist_table(doc) -> Optional[Any]:
    for table in doc.tables:
        if len(table.rows) < 1 or len(table.columns) < 2:
            continue
        header = " ".join(cell.text for cell in table.rows[0].cells)
        if "姓名" in header and "职级" in header:
            return table
    return None


def header_alias_group(header: Any) -> list[str]:
    if isinstance(header, (list, tuple, set)):
        return [norm(item) for item in header if item]
    return [norm(header)] if header else []


def find_table_by_headers(doc, headers: list[Any]) -> Optional[Any]:
    wanted_groups = [aliases for header in headers if (aliases := header_alias_group(header))]
    for table in doc.tables:
        if not table.rows:
            continue
        header_texts = [norm(cell.text) for cell in table.rows[0].cells]
        if all(any(alias in text for alias in aliases for text in header_texts) for aliases in wanted_groups):
            return table
    return None


def docx_process_rows(suggestion: dict[str, Any]) -> list[tuple[str, str]]:
    rows = infer_process_rows(suggestion)
    return [(row["重大业务流程"], row["涉及的信息系统"]) for row in rows]


def docx_itac_rows(suggestion: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    rows = infer_info_processing_rows(suggestion)
    result: list[tuple[str, str, str, str, str]] = []
    for row in rows:
        result.append(
            (
                row.get("财务报表项目", ""),
                row.get("业务流程和交易", ""),
                row.get("潜在错报风险", ""),
                row.get("信息处理控制及数据", ""),
                row.get("涉及应用程序", ""),
            )
        )
    return result


def docx_system_scope_rows(suggestion: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    app_rows = infer_b43_app_rows(suggestion)
    result: list[tuple[str, str, str, str, str]] = []
    for app in app_rows:
        result.append(
            (
                app["system"],
                app["database"],
                app["os"],
                app["server"],
                app["network"],
            )
        )
    return result


def table_old_rows(table) -> str:
    return "; ".join(" / ".join(cell.text.strip() for cell in row.cells) for row in table.rows[1:])


def plan_docx_table_replace(
    *,
    suggestion: dict[str, Any],
    document_path: Path,
    field: str,
    locator: str,
    table,
    rows: list[tuple[str, ...]],
    apply: bool,
    message: str,
) -> tuple[FillTarget, bool]:
    old_value = table_old_rows(table)
    new_value = "; ".join(" / ".join(values) for values in rows)

    if old_value and any(str(value).startswith("需根据") for row in rows for value in row):
        return (
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(document_path),
                sheet_name="Word",
                field=field,
                locator=locator,
                cell="",
                old_value=old_value,
                new_value=new_value,
                status="blocked",
                message=message + "; unresolved system inventory fields will not overwrite existing table",
            ),
            False,
        )

    def setter(_value: str, table=table, rows=rows) -> None:
        replace_docx_table_rows(table, rows)

    return plan_docx_text_change(
        suggestion=suggestion,
        document_path=document_path,
        field=field,
        locator=locator,
        old_value=old_value,
        new_value=new_value,
        apply=apply,
        setter=setter,
        message=message,
    )


def append_missing_table_result(
    results: list[FillTarget],
    *,
    suggestion: dict[str, Any],
    document_path: Path,
    field: str,
    locator: str,
    rows: list[tuple[str, ...]],
    message: str,
) -> None:
    results.append(
        FillTarget(
            rule_id=suggestion.get("rule_id", ""),
            scope=suggestion.get("scope", ""),
            workbook_path=str(document_path),
            sheet_name="Word",
            field=field,
            locator=locator,
            cell="",
            old_value=None,
            new_value="; ".join(" / ".join(values) for values in rows),
            status="blocked",
            message=message,
        )
    )


def plan_b6023_document(
    document_path: Path,
    suggestion: dict[str, Any],
    *,
    project_context: Optional[dict[str, Any]],
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    doc = Document(document_path)
    results: list[FillTarget] = []
    changed = False
    entity = str((project_context or {}).get("entity_name") or "待补充被审计单位")
    short_name = project_short_name(project_context, entity)
    period = docx_audit_scope(project_context)
    cutoff = docx_cutoff_date(project_context)
    start_date = b6023_memo_date(project_context)
    audit_end_date = format_cn_date((project_context or {}).get("end_date")) or "待补充截止日期"
    execution_end_date = add_days_cn((project_context or {}).get("end_date"), 7, audit_end_date)
    signing_date = add_days_cn((project_context or {}).get("end_date"), 15, "待补充签字日期")
    report_date = add_days_cn((project_context or {}).get("end_date"), 30, "待补充报告日期")
    archive_date = add_days_cn((project_context or {}).get("end_date"), 62, "待补充归档日期")

    if doc.paragraphs:
        para = doc.paragraphs[0]
        new_title = f"IT审计计划备忘录_{short_name}_审计范围:{period}"
        item, item_changed = plan_docx_text_change(
            suggestion=suggestion,
            document_path=document_path,
            field="entity_name",
            locator="paragraph:0",
            old_value=para.text,
            new_value=new_title,
            apply=apply,
            setter=lambda value, p=para: setattr(p, "text", value),
            message="B60-2-3 title inferred from project context",
        )
        results.append(item)
        changed = changed or item_changed

    if len(doc.paragraphs) > 2:
        para = doc.paragraphs[2]
        new_purpose = (
            f"本备忘录的目的是概述关于{entity}（“{short_name}”或“公司”）截止于{cutoff}的审计工作中与IT审计团队参与有关的程序。"
            "本备忘录概述的IT审计计划作为总体审计策略的补充。"
        )
        item, item_changed = plan_docx_text_change(
            suggestion=suggestion,
            document_path=document_path,
            field="audit_period",
            locator="paragraph:2",
            old_value=para.text,
            new_value=new_purpose,
            apply=apply,
            setter=lambda value, p=para: setattr(p, "text", value),
            message="B60-2-3 purpose paragraph inferred from project context",
        )
        results.append(item)
        changed = changed or item_changed

    if len(doc.paragraphs) > 4:
        para = doc.paragraphs[4]
        old_text = para.text.strip()
        if old_text and ("公司" in old_text or entity[:4] in old_text or short_name in old_text):
            background = b6023_client_background(project_context, entity)
            item, item_changed = plan_docx_text_change(
                suggestion=suggestion,
                document_path=document_path,
                field="client_background",
                locator="paragraph:4",
                old_value=para.text,
                new_value=background,
                apply=apply,
                setter=lambda value, p=para: setattr(p, "text", value),
                message="B60-2-3 client background paragraph inferred from project context",
            )
            results.append(item)
            changed = changed or item_changed

    if doc.tables:
        table = doc.tables[0]
        if len(table.rows) >= 1 and len(table.rows[0].cells) >= 2:
            old = table.rows[0].cells[1].text
            item, item_changed = plan_docx_text_change(
                suggestion=suggestion,
                document_path=document_path,
                field="schedule",
                locator="table:0:r0:c1",
                old_value=old,
                new_value=start_date,
                apply=apply,
                setter=lambda value, cell=table.rows[0].cells[1]: setattr(cell, "text", value),
                message="B60-2-3 memo date inferred from project start_date",
            )
            results.append(item)
            changed = changed or item_changed
        if len(table.rows) >= 2 and len(table.rows[1].cells) >= 2:
            recipients = plan_recipients(project_context)
            old = table.rows[1].cells[1].text
            item, item_changed = plan_docx_text_change(
                suggestion=suggestion,
                document_path=document_path,
                field="memo_recipients",
                locator="table:0:r1:c1",
                old_value=old,
                new_value=recipients,
                apply=apply,
                setter=lambda value, cell=table.rows[1].cells[1]: setattr(cell, "text", value),
                message="B60-2-3 recipients inferred from finance engagement team",
            )
            results.append(item)
            changed = changed or item_changed

    for idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if text.startswith("我们于"):
            discussion_rows = plan_discussion_people(project_context)
            discussion_date = start_date
            people_text = "；".join(f"{name}，{role}" for name, role in discussion_rows)
            new_value = (
                f"我们于{discussion_date}与项目组就IT审计计划进行了沟通，参与人员包括：{people_text}。"
                "沟通内容包括审计范围、关键系统、重要业务流程、IT一般控制及信息处理控制测试安排。"
            )
        elif text.startswith("项目计划"):
            new_value = f"项目计划 (从 {start_date} 至 {start_date})"
        elif text.startswith("审计执行"):
            new_value = f"审计执行 (从 {start_date} 至 {execution_end_date})"
        elif text.startswith("签字日期"):
            new_value = f"签字日期({signing_date})"
        elif text.startswith("报告日期"):
            new_value = f"报告日期({report_date})"
        elif text.startswith("预计归档日期"):
            new_value = f"预计归档日期({archive_date})"
        else:
            continue
        item, item_changed = plan_docx_text_change(
            suggestion=suggestion,
            document_path=document_path,
            field="schedule",
            locator=f"paragraph:{idx}",
            old_value=para.text,
            new_value=new_value,
            apply=apply,
            setter=lambda value, p=para: setattr(p, "text", value),
            message="B60-2-3 schedule paragraph inferred from project context",
        )
        results.append(item)
        changed = changed or item_changed

    specialist_table = find_specialist_table(doc)
    specialist_rows = b6023_specialist_rows(project_context)
    if specialist_table is None:
        results.append(
            FillTarget(
                rule_id=suggestion.get("rule_id", ""),
                scope=suggestion.get("scope", ""),
                workbook_path=str(document_path),
                sheet_name="Word",
                field="it_specialists",
                locator="table:姓名/职级",
                cell="",
                old_value=None,
                new_value="; ".join(f"{name}/{level}" for name, level in specialist_rows),
                status="blocked",
                message="B60-2-3 IT specialist table not found",
            )
        )
    else:
        old_rows = [" / ".join(cell.text.strip() for cell in row.cells[:2]) for row in specialist_table.rows[1:]]
        new_rows = [" / ".join(row) for row in specialist_rows]

        def set_specialists(_value: str, table=specialist_table, rows=specialist_rows) -> None:
            replace_docx_table_rows(table, rows)

        item, item_changed = plan_docx_text_change(
            suggestion=suggestion,
            document_path=document_path,
            field="it_specialists",
            locator="table:姓名/职级",
            old_value="; ".join(old_rows),
            new_value="; ".join(new_rows),
            apply=apply,
            setter=set_specialists,
            message="B60-2-3 IT specialist table inferred from project members",
        )
        results.append(item)
        changed = changed or item_changed

    process_table = find_table_by_headers(doc, [["重大业务流程", "业务流程"], ["涉及的信息系统", "涉及系统", "应用系统"]])
    process_rows = b6023_process_rows(suggestion, project_context)
    if process_table is None:
        append_missing_table_result(
            results,
            suggestion=suggestion,
            document_path=document_path,
            field="process_system_rows",
            locator="table:重大业务流程",
            rows=process_rows,
            message="B60-2-3 process/system table not found",
        )
    else:
        item, item_changed = plan_docx_table_replace(
            suggestion=suggestion,
            document_path=document_path,
            field="process_system_rows",
            locator="table:重大业务流程",
            table=process_table,
            rows=[tuple(row) for row in process_rows],
            apply=apply,
            message="B60-2-3 process/system table inferred from matched attachments",
        )
        results.append(item)
        changed = changed or item_changed

    itac_table = find_table_by_headers(
        doc,
        [
            ["财务报表科目", "财务报表项目"],
            ["业务流程和交易", "业务流程及交易", "业务流程"],
            "潜在错报风险",
            ["信息处理控制", "应用控制"],
            ["涉及系统", "涉及应用程序", "应用系统"],
        ],
    )
    itac_rows = b6023_itac_rows(suggestion, project_context)
    if itac_table is None:
        append_missing_table_result(
            results,
            suggestion=suggestion,
            document_path=document_path,
            field="info_processing_rows",
            locator="table:信息处理控制",
            rows=[tuple(row) for row in itac_rows],
            message="B60-2-3 information processing table not found",
        )
    else:
        item, item_changed = plan_docx_table_replace(
            suggestion=suggestion,
            document_path=document_path,
            field="info_processing_rows",
            locator="table:信息处理控制",
            table=itac_table,
            rows=[tuple(row) for row in itac_rows],
            apply=apply,
            message="B60-2-3 information processing table inferred from matched attachments",
        )
        results.append(item)
        changed = changed or item_changed

    system_table = find_table_by_headers(doc, ["应用系统", "数据库", "操作系统", "数据中心", "网络"])
    system_rows = b6023_system_scope_rows(suggestion, project_context)
    if system_table is None:
        append_missing_table_result(
            results,
            suggestion=suggestion,
            document_path=document_path,
            field="system_scope_rows",
            locator="table:应用系统",
            rows=[tuple(row) for row in system_rows],
            message="B60-2-3 system scope table not found",
        )
    else:
        item, item_changed = plan_docx_table_replace(
            suggestion=suggestion,
            document_path=document_path,
            field="system_scope_rows",
            locator="table:应用系统",
            table=system_table,
            rows=[tuple(row) for row in system_rows],
            apply=apply,
            message="B60-2-3 system scope table inferred from matched attachments",
        )
        results.append(item)
        changed = changed or item_changed

    if apply and changed:
        doc.save(document_path)
    return results, changed


def find_paragraph_index(doc, keywords: list[str], *, start: int = 0) -> Optional[int]:
    wanted = [norm(keyword) for keyword in keywords if keyword]
    for idx, para in enumerate(doc.paragraphs[start:], start=start):
        text = norm(para.text)
        if text and all(keyword in text for keyword in wanted):
            return idx
    return None


def find_following_paragraph_index(
    doc,
    heading_keywords: list[str],
    body_keywords: list[str],
    *,
    max_distance: int = 8,
) -> Optional[int]:
    heading_idx = find_paragraph_index(doc, heading_keywords, start=0)
    if heading_idx is None:
        return None
    wanted = [norm(keyword) for keyword in body_keywords if keyword]
    end = min(len(doc.paragraphs), heading_idx + max_distance + 1)
    for idx in range(heading_idx + 1, end):
        text = norm(doc.paragraphs[idx].text)
        if text and all(keyword in text for keyword in wanted):
            return idx
    return None


def append_missing_paragraph_result(
    results: list[FillTarget],
    *,
    suggestion: dict[str, Any],
    document_path: Path,
    field: str,
    locator: str,
    new_value: str,
    message: str,
) -> None:
    results.append(
        FillTarget(
            rule_id=suggestion.get("rule_id", ""),
            scope=suggestion.get("scope", ""),
            workbook_path=str(document_path),
            sheet_name="Word",
            field=field,
            locator=locator,
            cell="",
            old_value=None,
            new_value=new_value,
            status="blocked",
            message=message,
        )
    )


def a27_supporting_workpaper_rows() -> list[tuple[str, str]]:
    names = [
        "<B60-2-1>IT复杂性判断表",
        "<B60-2-2>IT审计进场前通知表",
        "<B60-2-3>IT审计计划备忘录",
        "<B22A-4-3>了解IT环境",
        "<B22A-4-4-1>了解IT一般控制",
        "<C22>IT一般控制测试",
        "<C21-1>IT审计发现汇总表",
        "<A27-1>IT审计总结备忘录",
    ]
    return [(str(index), name) for index, name in enumerate(names, start=1)]


def plan_a27_document(
    document_path: Path,
    suggestion: dict[str, Any],
    *,
    project_context: Optional[dict[str, Any]],
    apply: bool,
) -> tuple[list[FillTarget], bool]:
    doc = Document(document_path)
    results: list[FillTarget] = []
    changed = False
    entity = str((project_context or {}).get("entity_name") or "待补充被审计单位")
    cutoff = docx_cutoff_date(project_context)
    period = docx_period_title(project_context)
    refs = suggestion_refs(suggestion) or "C21-1、C22、C26等支持性底稿"
    target_fields = {str(target.get("field") or "") for target in suggestion.get("targets", [])}

    if "entity_name_and_audit_period" in target_fields:
        new_value = (
            f"本备忘录的目的是概述关于{entity}（“公司”）截止于{cutoff}的审计工作中与IT团队参与有关程序的结果。"
            "本备忘录概述的结果作为审计小结的补充。"
        )
        idx = find_paragraph_index(doc, ["本备忘录", "目的"], start=0)
        if idx is None and len(doc.paragraphs) > 2:
            idx = 2
        if idx is None:
            append_missing_paragraph_result(
                results,
                suggestion=suggestion,
                document_path=document_path,
                field="entity_name_and_audit_period",
                locator="paragraph:purpose",
                new_value=new_value,
                message="A27 purpose paragraph not found",
            )
        else:
            para = doc.paragraphs[idx]
            item, item_changed = plan_docx_text_change(
                suggestion=suggestion,
                document_path=document_path,
                field="entity_name_and_audit_period",
                locator=f"paragraph:{idx}",
                old_value=para.text,
                new_value=new_value,
                apply=apply,
                setter=lambda value, p=para: setattr(p, "text", value),
                message="A27 entity and audit period inferred from project context",
            )
            results.append(item)
            changed = changed or item_changed

    if "it_specialists" in target_fields:
        specialist_table = find_specialist_table(doc)
        specialist_rows = docx_member_rows(project_context)
        if specialist_table is None:
            append_missing_table_result(
                results,
                suggestion=suggestion,
                document_path=document_path,
                field="it_specialists",
                locator="table:姓名/职级",
                rows=specialist_rows,
                message="A27 IT specialist table not found",
            )
        else:
            old_rows = [" / ".join(cell.text.strip() for cell in row.cells[:2]) for row in specialist_table.rows[1:]]

            def set_specialists(_value: str, table=specialist_table, rows=specialist_rows) -> None:
                replace_docx_table_rows(table, rows)

            item, item_changed = plan_docx_text_change(
                suggestion=suggestion,
                document_path=document_path,
                field="it_specialists",
                locator="table:姓名/职级",
                old_value="; ".join(old_rows),
                new_value="; ".join(" / ".join(row) for row in specialist_rows),
                apply=apply,
                setter=set_specialists,
                message="A27 IT specialist table inferred from project members",
            )
            results.append(item)
            changed = changed or item_changed

    if "itac_conclusion" in target_fields:
        new_value = (
            f"信息技术团队已根据{refs}识别和汇总本期应用控制/信息处理控制参与范围。"
            "相关结论需与C26测试明细、C21-1发现汇总及项目组审计应对保持一致。"
        )
        idx = find_paragraph_index(doc, ["信息技术团队", "应用控制"], start=0)
        if idx is None:
            idx = find_paragraph_index(doc, ["信息技术团队", "信息处理控制"], start=0)
        if idx is None:
            idx = find_following_paragraph_index(doc, ["应用控制"], ["信息技术团队"])
        if idx is None:
            idx = find_following_paragraph_index(doc, ["信息处理控制"], ["信息技术团队"])
        if idx is None:
            append_missing_paragraph_result(
                results,
                suggestion=suggestion,
                document_path=document_path,
                field="itac_conclusion",
                locator="paragraph:应用控制",
                new_value=new_value,
                message="A27 application-control conclusion paragraph not found",
            )
        else:
            para = doc.paragraphs[idx]
            item, item_changed = plan_docx_text_change(
                suggestion=suggestion,
                document_path=document_path,
                field="itac_conclusion",
                locator=f"paragraph:{idx}",
                old_value=para.text,
                new_value=new_value,
                apply=apply,
                setter=lambda value, p=para: setattr(p, "text", value),
                message="A27 ITAC conclusion inferred from matched evidence",
            )
            results.append(item)
            changed = changed or item_changed

    if "itgc_conclusion" in target_fields:
        new_value = (
            f"基于C22一般控制测试及{refs}，ITGC测试结论需结合C21-1缺陷汇总和补偿控制评价确认；"
            "未解决IT风险应同步反馈项目组评估对审计策略和实质性程序的影响。"
        )
        section_idx = find_paragraph_index(doc, ["信息技术风险", "一般控制"], start=0) or 0
        idx = find_paragraph_index(doc, ["基于", "测试结果"], start=section_idx)
        if idx is None:
            append_missing_paragraph_result(
                results,
                suggestion=suggestion,
                document_path=document_path,
                field="itgc_conclusion",
                locator="paragraph:ITGC结论",
                new_value=new_value,
                message="A27 ITGC conclusion paragraph not found",
            )
        else:
            para = doc.paragraphs[idx]
            item, item_changed = plan_docx_text_change(
                suggestion=suggestion,
                document_path=document_path,
                field="itgc_conclusion",
                locator=f"paragraph:{idx}",
                old_value=para.text,
                new_value=new_value,
                apply=apply,
                setter=lambda value, p=para: setattr(p, "text", value),
                message="A27 ITGC conclusion inferred from C22/C21-1 evidence",
            )
            results.append(item)
            changed = changed or item_changed

    if "defect_summary" in target_fields:
        new_value = (
            f"基于我们的测试结果，需将C21-1中列示的IT控制缺陷作为本备忘录缺陷摘要的依据；"
            f"本次自动填写依据{refs}生成初稿，缺陷编号、严重程度和财务审计影响需人工确认。"
        )
        idx = find_paragraph_index(doc, ["基于", "控制缺陷"], start=0)
        if idx is None:
            append_missing_paragraph_result(
                results,
                suggestion=suggestion,
                document_path=document_path,
                field="defect_summary",
                locator="paragraph:控制缺陷",
                new_value=new_value,
                message="A27 defect summary paragraph not found",
            )
        else:
            para = doc.paragraphs[idx]
            item, item_changed = plan_docx_text_change(
                suggestion=suggestion,
                document_path=document_path,
                field="defect_summary",
                locator=f"paragraph:{idx}",
                old_value=para.text,
                new_value=new_value,
                apply=apply,
                setter=lambda value, p=para: setattr(p, "text", value),
                message="A27 defect summary inferred from C21-1 evidence",
            )
            results.append(item)
            changed = changed or item_changed

    if "supporting_workpapers" in target_fields:
        support_table = find_table_by_headers(doc, ["编号", "名称"])
        support_rows = a27_supporting_workpaper_rows()
        if support_table is None:
            append_missing_table_result(
                results,
                suggestion=suggestion,
                document_path=document_path,
                field="supporting_workpapers",
                locator="table:编号/名称",
                rows=support_rows,
                message="A27 supporting workpaper table not found",
            )
        else:
            item, item_changed = plan_docx_table_replace(
                suggestion=suggestion,
                document_path=document_path,
                field="supporting_workpapers",
                locator="table:编号/名称",
                table=support_table,
                rows=support_rows,
                apply=apply,
                message="A27 supporting workpapers generated from standard IT audit deliverables",
            )
            results.append(item)
            changed = changed or item_changed

    if apply and changed:
        doc.save(document_path)
    return results, changed


def plan_for_document(
    document_path: Path,
    suggestions: list[dict[str, Any]],
    *,
    project_context: Optional[dict[str, Any]] = None,
    apply: bool = False,
) -> list[dict[str, Any]]:
    results: list[FillTarget] = []
    for suggestion in suggestions:
        if str(suggestion.get("workpaper") or "").startswith("B60-2-3"):
            table_plan, _ = plan_b6023_document(
                document_path,
                suggestion,
                project_context=project_context,
                apply=apply,
            )
            results.extend(table_plan)
            continue
        if suggestion.get("scope") == "A27" or str(suggestion.get("workpaper") or "").startswith("A27"):
            table_plan, _ = plan_a27_document(
                document_path,
                suggestion,
                project_context=project_context,
                apply=apply,
            )
            results.extend(table_plan)
            continue
        for target in suggestion.get("targets", []):
            field = target.get("field", "")
            locator = target.get("locator", "document")
            new_value, value_issue = value_for_target(suggestion, target, project_context)
            status = "planned"
            message_parts = ["Word document requires paragraph/table writer before direct apply"]
            if apply:
                status = "blocked"
                message_parts.append("apply=true is not supported for Word documents yet")
            if value_issue:
                message_parts.append(value_issue)
            results.append(
                FillTarget(
                    rule_id=suggestion.get("rule_id", ""),
                    scope=suggestion.get("scope", ""),
                    workbook_path=str(document_path),
                    sheet_name="Word",
                    field=field,
                    locator=locator,
                    cell=f"document:{field or locator}",
                    old_value=None,
                    new_value=new_value or suggestion.get("suggested_content", ""),
                    status=status,
                    message="; ".join(message_parts),
                )
            )
    return [item.to_dict() for item in results]


def plan_large_workbook_preview(
    workbook_path: Path,
    suggestions: list[dict[str, Any]],
    *,
    project_context: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    wb = load_workbook_for_preview(workbook_path)
    results: list[FillTarget] = []
    try:
        for suggestion in suggestions:
            sheet_name = suggestion.get("sheet") or ""
            sheet_name = resolve_sheet_name(wb, str(sheet_name))
            if sheet_name and sheet_name not in wb.sheetnames:
                results.append(
                    FillTarget(
                        rule_id=suggestion.get("rule_id", ""),
                        scope=suggestion.get("scope", ""),
                        workbook_path=str(workbook_path),
                        sheet_name=sheet_name,
                        field="",
                        locator="",
                        cell="",
                        old_value=None,
                        new_value=suggestion.get("suggested_content", ""),
                        status="blocked",
                        message=f"sheet not found: {sheet_name}",
                    )
                )
                continue
            if not sheet_name:
                sheet_name = wb.sheetnames[0]
            ws = wb[sheet_name]
            for target in suggestion.get("targets", []):
                field = target.get("field", "")
                headers = target.get("headers", [])
                labels = target.get("labels") or ([target.get("label")] if target.get("label") else [])
                new_value, value_issue = value_for_target(suggestion, target, project_context)
                preview_note = "large workbook dry-run uses read-only preview; apply=true will use normal writable load"
                if headers:
                    cell_range, header_issue = readonly_locate_header_range(ws, list(headers))
                    status = "planned" if cell_range else "blocked"
                    if not cell_range and target.get("optional"):
                        status = "skipped"
                    results.append(
                        FillTarget(
                            rule_id=suggestion.get("rule_id", ""),
                            scope=suggestion.get("scope", ""),
                            workbook_path=str(workbook_path),
                            sheet_name=sheet_name,
                            field=field,
                            locator="headers:" + " | ".join(str(item) for item in headers),
                            cell=cell_range,
                            old_value=None,
                            new_value=new_value or suggestion.get("suggested_content", ""),
                            status=status,
                            message="; ".join(item for item in [header_issue, value_issue, preview_note] if item),
                        )
                    )
                    continue
                if labels:
                    cell, old_value, label_issue = readonly_find_label_cell(ws, [str(label) for label in labels])
                    results.append(
                        FillTarget(
                            rule_id=suggestion.get("rule_id", ""),
                            scope=suggestion.get("scope", ""),
                            workbook_path=str(workbook_path),
                            sheet_name=sheet_name,
                            field=field,
                            locator="labels:" + " | ".join(str(item) for item in labels),
                            cell=cell,
                            old_value=display(old_value),
                            new_value=new_value or suggestion.get("suggested_content", ""),
                            status="planned" if cell else "blocked",
                            message="; ".join(item for item in [label_issue, value_issue, preview_note] if item),
                        )
                    )
                    continue
                results.append(
                    FillTarget(
                        rule_id=suggestion.get("rule_id", ""),
                        scope=suggestion.get("scope", ""),
                        workbook_path=str(workbook_path),
                        sheet_name=sheet_name,
                        field=field,
                        locator="",
                        cell="",
                        old_value=None,
                        new_value=suggestion.get("suggested_content", ""),
                        status="skipped",
                        message="target has no preview locator",
                    )
                )
    finally:
        wb.close()
    return [item.to_dict() for item in results]


def plan_for_workbook(
    workbook_path: Path,
    suggestions: list[dict[str, Any]],
    *,
    rules_payload: Optional[dict[str, Any]] = None,
    project_context: Optional[dict[str, Any]] = None,
    apply: bool = False,
) -> list[dict[str, Any]]:
    payload = rules_payload or load_rules()
    profiles = payload.get("locator_profiles", {})
    if workbook_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return plan_for_document(
            workbook_path,
            suggestions,
            project_context=project_context,
            apply=apply,
        )
    if not apply and workbook_path.exists() and workbook_path.stat().st_size > LARGE_WORKBOOK_PREVIEW_LIMIT:
        return plan_large_workbook_preview(
            workbook_path,
            suggestions,
            project_context=project_context,
        )
    wb = load_workbook_for_write_plan(workbook_path)
    results: list[FillTarget] = []
    changed = False
    try:
        for suggestion in suggestions:
            sheet_name = suggestion.get("sheet") or ""
            sheet_name = resolve_sheet_name(wb, str(sheet_name))
            if sheet_name and sheet_name not in wb.sheetnames:
                results.append(
                    FillTarget(
                        rule_id=suggestion.get("rule_id", ""),
                        scope=suggestion.get("scope", ""),
                        workbook_path=str(workbook_path),
                        sheet_name=sheet_name,
                        field="",
                        locator="",
                        cell="",
                        old_value=None,
                        new_value=suggestion.get("suggested_content", ""),
                        status="blocked",
                        message=f"sheet not found: {sheet_name}",
                    )
                )
                continue

            if not sheet_name:
                sheet_name = wb.sheetnames[0]
            ws = wb[sheet_name]
            if str(suggestion.get("workpaper") or "").startswith("B22A-4-4-2"):
                ws = find_sheet_for_sod(wb) or ws
                sheet_name = ws.title
            handled_special_fields: set[str] = set()
            for target in suggestion.get("targets", []):
                locator = target.get("locator", "")
                field = target.get("field", "")
                has_direct_label = bool(target.get("label") or target.get("labels"))
                if suggestion.get("scope") == "C21" and field == "header_audit_period":
                    table_plan, table_changed = plan_c21_header_audit_period(
                        ws,
                        suggestion,
                        workbook_path,
                        project_context=project_context,
                        apply=apply,
                    )
                    results.extend(table_plan)
                    changed = changed or table_changed
                    continue
                if suggestion.get("scope") == "C21" and field == "it_team_members":
                    table_plan, table_changed = plan_c21_member_table(
                        ws,
                        suggestion,
                        workbook_path,
                        project_context=project_context,
                        apply=apply,
                    )
                    results.extend(table_plan)
                    changed = changed or table_changed
                    continue
                if suggestion.get("scope") == "C21" and field == "project_team_members":
                    table_plan, table_changed = plan_c21_project_team_members(
                        ws,
                        suggestion,
                        workbook_path,
                    )
                    results.extend(table_plan)
                    changed = changed or table_changed
                    continue
                if suggestion.get("scope") == "C21" and field == "work_scope_rows":
                    table_plan, table_changed = plan_c21_work_scope_rows(
                        ws,
                        suggestion,
                        workbook_path,
                        project_context=project_context,
                        apply=apply,
                    )
                    results.extend(table_plan)
                    changed = changed or table_changed
                    continue
                if not locator and not has_direct_label:
                    headers = target.get("headers", [])
                    if field == "system_summary":
                        table_plan, table_changed = plan_b41_system_summary(
                            ws,
                            suggestion,
                            workbook_path,
                            apply=apply,
                        )
                        results.extend(table_plan)
                        changed = changed or table_changed
                        continue
                    if field == "sod_rows":
                        sod_ws = find_sheet_for_sod(wb)
                        if sod_ws is None:
                            results.append(
                                FillTarget(
                                    rule_id=suggestion.get("rule_id", ""),
                                    scope=suggestion.get("scope", ""),
                                    workbook_path=str(workbook_path),
                                    sheet_name="",
                                    field=field,
                                    locator="headers:B22A-4-4-2",
                                    cell="",
                                    old_value=None,
                                    new_value=suggestion.get("suggested_content", ""),
                                    status="blocked",
                                    message="no B22A-4-4-2 SoD analysis sheet found",
                                )
                            )
                            continue
                        table_plan, table_changed = plan_b442_sod_rows(
                            sod_ws,
                            suggestion,
                            workbook_path,
                            apply=apply,
                        )
                        results.extend(table_plan)
                        changed = changed or table_changed
                        continue
                    if field == "it_environment":
                        table_plan, table_changed = plan_b43_it_environment(
                            wb,
                            suggestion,
                            workbook_path,
                            apply=apply,
                        )
                        results.extend(table_plan)
                        changed = changed or table_changed
                        continue
                    if field == "info_processing_rows":
                        b23_ws = find_info_processing_sheet(wb)
                        if b23_ws is None:
                            results.append(
                                FillTarget(
                                    rule_id=suggestion.get("rule_id", ""),
                                    scope=suggestion.get("scope", ""),
                                    workbook_path=str(workbook_path),
                                    sheet_name="",
                                    field=field,
                                    locator="headers:B23-15",
                                    cell="",
                                    old_value=None,
                                    new_value=suggestion.get("suggested_content", ""),
                                    status="blocked",
                                    message="no B23-15 info processing sheet found",
                                )
                            )
                            continue
                        table_plan, table_changed = plan_b23_info_processing_rows(
                            b23_ws,
                            suggestion,
                            workbook_path,
                            apply=apply,
                        )
                        results.extend(table_plan)
                        changed = changed or table_changed
                        continue
                    if field == "entrance_notice":
                        table_plan, table_changed = plan_b6022_entrance_notice(
                            ws,
                            suggestion,
                            workbook_path,
                            project_context=project_context,
                            apply=apply,
                        )
                        results.extend(table_plan)
                        changed = changed or table_changed
                        continue
                    if field == "complexity_assessment":
                        table_plan, table_changed = plan_b6021_complexity_assessment(
                            ws,
                            suggestion,
                            workbook_path,
                            project_context=project_context,
                            apply=apply,
                        )
                        results.extend(table_plan)
                        changed = changed or table_changed
                        continue
                    if headers:
                        if field == "assertion_columns" and "current_findings_rows" in handled_special_fields:
                            continue
                        if field in {"current_findings_rows", "assertion_columns"}:
                            table_plan, table_changed = plan_c211_current_findings(
                                ws,
                                suggestion,
                                workbook_path,
                                apply=apply,
                            )
                            results.extend(table_plan)
                            changed = changed or table_changed
                            handled_special_fields.update({"current_findings_rows", "assertion_columns"})
                            continue
                        if field == "control_description":
                            inferred_rows = infer_control_understanding_rows(suggestion)
                            if not inferred_rows:
                                results.append(
                                    FillTarget(
                                        rule_id=suggestion.get("rule_id", ""),
                                        scope=suggestion.get("scope", ""),
                                        workbook_path=str(workbook_path),
                                        sheet_name="",
                                        field=field,
                                        locator="headers:B22A-4-4-1",
                                        cell="",
                                        old_value=None,
                                        new_value=suggestion.get("suggested_content", ""),
                                        status="blocked",
                                        message="no control rows inferred from matched attachments",
                                    )
                                )
                                continue

                            found_any_sheet = False
                            planned_codes: set[str] = set()
                            for candidate_ws in wb.worksheets:
                                header_row, _, _ = locate_b44_columns(candidate_ws)
                                if header_row is None:
                                    continue
                                found_any_sheet = True
                                table_plan, table_changed = plan_structured_table_rows(
                                    candidate_ws,
                                    suggestion,
                                    workbook_path,
                                    target=target,
                                    apply=apply,
                                    suppress_missing_control_rows=True,
                                )
                                for item in table_plan:
                                    parts = item.field.split(".")
                                    if len(parts) >= 3 and item.status != "blocked":
                                        planned_codes.add(parts[1])
                                results.extend(table_plan)
                                changed = changed or table_changed

                            if not found_any_sheet:
                                results.append(
                                    FillTarget(
                                        rule_id=suggestion.get("rule_id", ""),
                                        scope=suggestion.get("scope", ""),
                                        workbook_path=str(workbook_path),
                                        sheet_name="",
                                        field=field,
                                        locator="headers:B22A-4-4-1",
                                        cell="",
                                        old_value=None,
                                        new_value=suggestion.get("suggested_content", ""),
                                        status="blocked",
                                        message="no B22A-4-4-1 control matrix sheet found",
                                    )
                                )
                            else:
                                for row_data in inferred_rows:
                                    if row_data["code"] in planned_codes:
                                        continue
                                    results.append(
                                        FillTarget(
                                            rule_id=suggestion.get("rule_id", ""),
                                            scope=suggestion.get("scope", ""),
                                            workbook_path=str(workbook_path),
                                            sheet_name="B22A-4-4-1",
                                            field=f"{field}.{row_data['code']}",
                                            locator=f"ITGC编号:{row_data['code']}",
                                            cell="",
                                            old_value=None,
                                            new_value=row_data["control_description"],
                                            status="skipped",
                                            message="control code not present in B22A-4-4-1 template; skipped template applicability",
                                        )
                                    )
                            continue

                        table_plan, table_changed = plan_structured_table_rows(
                            ws,
                            suggestion,
                            workbook_path,
                            target=target,
                            apply=apply,
                        )
                        if table_plan:
                            results.extend(table_plan)
                            changed = changed or table_changed
                            continue
                        cell_range, header_issue = locate_header_range(ws, list(headers))
                        new_value, value_issue = value_for_target(suggestion, target, project_context)
                        status = "planned" if cell_range else "blocked"
                        if not cell_range and target.get("optional"):
                            status = "skipped"
                        results.append(
                            FillTarget(
                                rule_id=suggestion.get("rule_id", ""),
                                scope=suggestion.get("scope", ""),
                                workbook_path=str(workbook_path),
                                sheet_name=sheet_name,
                                field=field,
                                locator="headers:" + " | ".join(str(item) for item in headers),
                                cell=cell_range,
                                old_value=None,
                                new_value=new_value or suggestion.get("suggested_content", ""),
                                status=status,
                                message="; ".join(item for item in [header_issue, value_issue, "table area requires structured row data before direct write"] if item),
                            )
                        )
                        continue
                    results.append(
                        FillTarget(
                            rule_id=suggestion.get("rule_id", ""),
                            scope=suggestion.get("scope", ""),
                            workbook_path=str(workbook_path),
                            sheet_name=sheet_name,
                            field=field,
                            locator="",
                            cell="",
                            old_value=None,
                            new_value=suggestion.get("suggested_content", ""),
                            status="skipped",
                            message="target has no profile locator yet",
                        )
                    )
                    continue
                cell, issue = resolve_target_cell(ws, profiles, target)
                if cell is None:
                    blocked_value, value_issue = value_for_target(suggestion, target, project_context)
                    results.append(
                        FillTarget(
                            rule_id=suggestion.get("rule_id", ""),
                            scope=suggestion.get("scope", ""),
                            workbook_path=str(workbook_path),
                            sheet_name=sheet_name,
                            field=field,
                            locator=locator,
                            cell="",
                            old_value=None,
                            new_value=blocked_value or suggestion.get("suggested_content", ""),
                            status="blocked",
                            message="; ".join(item for item in [issue, value_issue] if item),
                        )
                    )
                    continue
                if not is_writable_cell(cell):
                    results.append(
                        FillTarget(
                            rule_id=suggestion.get("rule_id", ""),
                            scope=suggestion.get("scope", ""),
                            workbook_path=str(workbook_path),
                            sheet_name=sheet_name,
                            field=field,
                            locator=locator,
                            cell=cell.coordinate,
                            old_value=display(cell.value),
                            new_value=suggestion.get("suggested_content", ""),
                            status="blocked",
                            message="target is merged child cell",
                        )
                    )
                    continue
                new_value, value_issue = value_for_target(suggestion, target, project_context)
                if new_value is None:
                    results.append(
                        FillTarget(
                            rule_id=suggestion.get("rule_id", ""),
                            scope=suggestion.get("scope", ""),
                            workbook_path=str(workbook_path),
                            sheet_name=sheet_name,
                            field=field,
                            locator=locator,
                            cell=cell.coordinate,
                            old_value=display(cell.value),
                            new_value="",
                            status="skipped",
                            message=value_issue,
                        )
                    )
                    continue
                old_value = cell.value
                status = "planned"
                if apply and old_value != new_value:
                    cell.value = new_value
                    changed = True
                    status = "changed"
                elif old_value == new_value:
                    status = "unchanged"
                results.append(
                    FillTarget(
                        rule_id=suggestion.get("rule_id", ""),
                        scope=suggestion.get("scope", ""),
                        workbook_path=str(workbook_path),
                        sheet_name=sheet_name,
                        field=field,
                        locator=locator,
                        cell=cell.coordinate,
                        old_value=display(old_value),
                        new_value=new_value,
                        status=status,
                        message="; ".join(item for item in [issue, value_issue] if item),
                    )
                )
        if apply and changed:
            wb.save(workbook_path)
    finally:
        wb.close()
    return [item.to_dict() for item in results]


def plan_for_project_workpapers(
    suggestions: list[dict[str, Any]],
    workpapers: list[dict[str, Any]],
    *,
    rules_payload: Optional[dict[str, Any]] = None,
    project_context: Optional[dict[str, Any]] = None,
    apply: bool = False,
) -> list[dict[str, Any]]:
    payload = rules_payload or load_rules()
    grouped: dict[str, list[dict[str, Any]]] = {}
    results: list[dict[str, Any]] = []
    for suggestion in suggestions:
        wp = best_workbook_for_suggestion(suggestion, workpapers)
        if wp is None:
            results.append(
                {
                    "rule_id": suggestion.get("rule_id", ""),
                    "scope": suggestion.get("scope", ""),
                    "workbook_path": "",
                    "sheet_name": suggestion.get("sheet") or suggestion.get("workpaper", ""),
                    "field": "",
                    "locator": "",
                    "cell": "",
                    "old_value": None,
                    "new_value": suggestion.get("suggested_content", ""),
                    "status": "blocked",
                    "message": "no registered workpaper file_path matched this suggestion",
                }
            )
            continue
        grouped.setdefault(str(wp.get("file_path")), []).append(suggestion)

    for path_text, items in grouped.items():
        path = Path(path_text).expanduser()
        if not path.exists():
            for suggestion in items:
                results.append(
                    {
                        "rule_id": suggestion.get("rule_id", ""),
                        "scope": suggestion.get("scope", ""),
                        "workbook_path": str(path),
                        "sheet_name": suggestion.get("sheet") or suggestion.get("workpaper", ""),
                        "field": "",
                        "locator": "",
                        "cell": "",
                        "old_value": None,
                        "new_value": suggestion.get("suggested_content", ""),
                        "status": "blocked",
                        "message": "workpaper file does not exist",
                    }
                )
            continue
        results.extend(
            plan_for_workbook(
                path,
                items,
                rules_payload=payload,
                project_context=project_context,
                apply=apply,
            )
        )
    return results
