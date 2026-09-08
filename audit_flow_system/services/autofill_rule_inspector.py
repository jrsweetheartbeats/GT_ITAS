from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re
from typing import Any

from openpyxl import load_workbook

from ..autofill_rules import build_suggestion, load_rules, match_evidence, missing_required, rule_applies
from ..autofill_writer import find_control_row, infer_control_understanding_rows, locate_b44_columns
from .template_rule_scanner import scan_workpaper_templates


READY = "ready"
MISSING_LOCATOR = "missing_locator"
MISSING_TARGET = "missing_target"
MISSING_EVIDENCE = "missing_evidence"
CONFLICT = "conflict"
DISABLED = "disabled"

STATUS_ORDER = [READY, MISSING_TARGET, MISSING_LOCATOR, MISSING_EVIDENCE, CONFLICT, DISABLED]

PROJECT_STATUS_ORDER = [READY, MISSING_TARGET, MISSING_LOCATOR, MISSING_EVIDENCE, CONFLICT, DISABLED, "not_checked"]

SCOPE_CATALOG = {
    "A27": {"label": "A27", "stage": "reporting", "reserved": True},
    "B22A": {"label": "B22A", "stage": "planning", "reserved": False},
    "B23": {"label": "B23", "stage": "planning", "reserved": False},
    "B60": {"label": "B60", "stage": "planning", "reserved": False},
    "C21": {"label": "C21", "stage": "execution", "reserved": True},
    "C21-1": {"label": "C21-1", "stage": "execution", "reserved": True},
    "C22": {"label": "C22", "stage": "execution", "reserved": False},
    "C26": {"label": "C26", "stage": "execution", "reserved": True},
}

B_COVERAGE_NOTES = {
    "B22A-4-1": ("writable", "IT概要系统、接口和复杂性判断已支持结构化写入；复杂性公式列不直接覆盖。"),
    "B22A-4-2": ("writable", "重大业务流程与信息系统映射已支持按表头写入。"),
    "B22A-4-3": ("writable", "IT环境应用程序、基础设施、流程和信息处理页签已支持结构化写入。"),
    "B22A-4-4-1": ("writable_with_gap", "ITGC了解矩阵可写入；K/L问题标识必须后续与C22和C21-1交叉校验。"),
    "B22A-4-4-2": ("writable", "职责分离分析已支持按分区和表头写入。"),
    "B23-15": ("writable", "了解信息处理控制已支持表格行写入，必要时插入预留行。"),
    "B60-2-1": ("writable_with_gap", "Excel复杂性判断表可写入；Word版本仍偏建议级。"),
    "B60-2-2": ("writable", "进场前通知表已支持项目上下文和附件范围写入。"),
    "B60-2-3": ("writable", "计划备忘录Word标题、段落和关键表格已支持写入。"),
}

C_EXPECTED = [
    ("C21", "具有信息技术专业技能的项目组成员", "covered", "已补IT项目组成员和具体工作范围规则；需与项目成员配置、B类、C22/C26和C21-1/A27引用保持一致。"),
    ("C21-1", "IT审计发现汇总表", "covered", "已补本年度问题汇总和上年度整改跟踪规则，并作为B22A-4-4-1 K/L交叉校验来源。"),
    ("C22", "IT一般控制测试", "covered", "31条规则已覆盖标准C22测试页签，当前主要依赖c22_common locator；PE-8.1图像化物理环境附表仍通过PE-8规则和人工复核处理。"),
    ("C26", "ITAC/信息处理控制测试", "covered", "已补测试汇总和明细页签字段规则；接口/自动控制的差异分析仍需按项目证据验证。"),
]

A_EXPECTED = [
    ("A27", "IT审计总结备忘录", "covered", "已补范围、结论、问题汇总和支持性底稿清单规则；实际写回需结合C21-1和C22/C26结论验证。"),
    ("A14", "项目计划/审计策略相关底稿", "missing_rule", "缺少规则。"),
    ("A17", "重要性/范围相关底稿", "missing_rule", "缺少规则。"),
    ("A21", "风险评估/项目执行相关底稿", "missing_rule", "缺少规则。"),
    ("A53", "归档/报告支持相关底稿", "missing_rule", "缺少规则。"),
]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def split_workpaper(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    parts = text.split(maxsplit=1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def infer_workpaper_code(rule: dict[str, Any]) -> str:
    explicit = str(rule.get("workpaper_code") or "").strip()
    if explicit:
        return explicit
    workpaper_code, _ = split_workpaper(str(rule.get("workpaper") or ""))
    if workpaper_code:
        return workpaper_code
    scope = str(rule.get("scope") or "").strip()
    sheet = str(rule.get("sheet") or "").strip()
    if scope == "C22":
        return "C22"
    return sheet or scope


def infer_workpaper_name(rule: dict[str, Any]) -> str:
    explicit = str(rule.get("workpaper_name") or "").strip()
    if explicit:
        return explicit
    _, workpaper_name = split_workpaper(str(rule.get("workpaper") or ""))
    if workpaper_name:
        return workpaper_name
    if rule.get("scope") == "C22":
        return "IT一般控制测试"
    return str(rule.get("workpaper") or rule.get("scope") or "")


def infer_stage(rule: dict[str, Any]) -> str:
    if rule.get("stage"):
        return str(rule["stage"])
    code = infer_workpaper_code(rule)
    if code.startswith(("B22A", "B23", "B60")) or rule.get("scope") == "B":
        return "planning"
    if code.startswith("A"):
        return "reporting"
    return "execution"


def infer_section(rule: dict[str, Any]) -> str:
    return str(rule.get("section") or rule.get("sheet") or infer_workpaper_code(rule) or "")


def resolve_locator(locator_profiles: dict[str, Any], locator: str) -> dict[str, Any]:
    current: Any = locator_profiles
    for part in str(locator or "").split("."):
        if not isinstance(current, dict) or part not in current:
            return {}
        current = current[part]
    return current if isinstance(current, dict) else {}


def evidence_requirements(rule: dict[str, Any]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for item in safe_list(rule.get("evidence")):
        if not isinstance(item, dict):
            continue
        requirements.append(
            {
                "name": item.get("name", ""),
                "required": bool(item.get("required", False)),
                "any_keywords": safe_list(item.get("any_keywords")),
                "purpose": item.get("purpose", ""),
                "evidence_type": item.get("type") or "attachment",
            }
        )
    return requirements


def evidence_logic(requirements: list[dict[str, Any]], applies_when: str) -> str:
    if not requirements:
        return "未配置证据匹配要求"
    required_names = [item["name"] for item in requirements if item.get("required")]
    if applies_when == "all_required":
        policy = "必须匹配全部必需证据"
    elif applies_when == "all_evidence":
        policy = "必须匹配全部证据项"
    elif required_names:
        policy = "至少匹配一个必需证据"
    else:
        policy = "至少匹配一个证据项"
    return f"{policy}；按附件索引号、名称、路径、类型和引用字段中的关键词匹配"


def locator_label(profile: dict[str, Any], target: dict[str, Any]) -> str:
    if target.get("target_cell") or target.get("cell"):
        return str(target.get("target_cell") or target.get("cell"))
    if target.get("locator"):
        return str(target.get("locator"))
    headers = safe_list(target.get("headers"))
    if headers:
        return "headers:" + " | ".join(str(item) for item in headers)
    labels = safe_list(target.get("labels") or profile.get("labels"))
    if labels:
        return "labels:" + " | ".join(str(item) for item in labels)
    label = target.get("label") or profile.get("label")
    if label:
        return "label:" + str(label)
    keywords = safe_list(target.get("label_keywords"))
    if keywords:
        return "label_keywords:" + " | ".join(str(item) for item in keywords)
    return ""


def target_has_field_or_cell(target: dict[str, Any], profile: dict[str, Any]) -> bool:
    return bool(
        target.get("field")
        or target.get("target_field")
        or target.get("cell")
        or target.get("target_cell")
        or target.get("headers")
        or target.get("label")
        or target.get("labels")
        or profile.get("label")
        or profile.get("labels")
    )


def locator_method(locator: str, target: dict[str, Any], profile: dict[str, Any]) -> str:
    if target.get("target_cell") or target.get("cell"):
        return "fixed_cell"
    if profile:
        return "locator_profile"
    if target.get("headers"):
        return "header_match"
    if target.get("label") or target.get("labels") or target.get("label_keywords"):
        return "label_match"
    if locator.startswith("document."):
        return "document_strategy"
    if locator:
        return "named_strategy"
    return ""


def target_has_locator(locator: str, target: dict[str, Any], profile: dict[str, Any]) -> bool:
    method = locator_method(locator, target, profile)
    if not method:
        return False
    if method == "named_strategy" and "." in locator:
        return False
    return True


def inspect_target(locator_profiles: dict[str, Any], target: dict[str, Any], index: int) -> dict[str, Any]:
    locator = str(target.get("locator") or "")
    profile = resolve_locator(locator_profiles, locator) if locator else {}
    method = locator_method(locator, target, profile)
    target_cell = str(target.get("cell") or target.get("target_cell") or "")
    target_field = str(target.get("field") or target.get("target_field") or "")
    risks: list[str] = []
    status = READY
    if not target_has_field_or_cell(target, profile):
        status = MISSING_TARGET
        risks.append("目标字段、固定单元格、表头或标签未配置")
    elif not target_has_locator(locator, target, profile):
        status = MISSING_LOCATOR
        if locator:
            risks.append(f"locator 未在 locator_profiles 中定义：{locator}")
        else:
            risks.append("缺少 locator、固定单元格、表头或标签定位方式")
    elif method in {"header_match", "document_strategy", "label_match"} and not profile:
        risks.append("定位依赖表头/标签/文档专项策略，建议后续沉淀为 locator_profiles")
    return {
        "index": index,
        "target_field": target_field,
        "field": target_field,
        "target_cell": target_cell,
        "cell": target_cell,
        "locator": locator,
        "locator_display": locator_label(profile, target),
        "locator_method": method or "missing",
        "locator_profile_found": bool(profile),
        "locator_profile": profile,
        "headers": safe_list(target.get("headers")),
        "labels": safe_list(target.get("labels") or profile.get("labels")),
        "label": target.get("label") or profile.get("label") or "",
        "write_mode": target.get("write") or profile.get("write") or "",
        "status": status,
        "risks": risks,
    }


def rule_status(targets: list[dict[str, Any]], evidence: list[dict[str, Any]], conflicts: list[str], enabled: bool) -> str:
    if not enabled:
        return DISABLED
    if conflicts:
        return CONFLICT
    if not evidence:
        return MISSING_EVIDENCE
    if not targets or any(target["status"] == MISSING_TARGET for target in targets):
        return MISSING_TARGET
    if any(target["status"] == MISSING_LOCATOR for target in targets):
        return MISSING_LOCATOR
    return READY


def rule_status_summary(inspections: list[dict[str, Any]], field: str) -> dict[str, Any]:
    by_status = Counter(item.get(field) or "not_checked" for item in inspections)
    return {
        "ready": by_status.get(READY, 0),
        "missing_target": by_status.get(MISSING_TARGET, 0),
        "missing_locator": by_status.get(MISSING_LOCATOR, 0),
        "missing_evidence": by_status.get(MISSING_EVIDENCE, 0),
        "conflict": by_status.get(CONFLICT, 0),
        "disabled": by_status.get(DISABLED, 0),
        "not_checked": by_status.get("not_checked", 0),
        "by_status": {status: by_status.get(status, 0) for status in PROJECT_STATUS_ORDER},
    }


def required_evidence_count(requirements: list[dict[str, Any]]) -> int:
    return sum(1 for item in requirements if item.get("required"))


def missing_reason_for_status(status: str, risks: list[str]) -> str:
    if status in {READY, "not_checked", ""}:
        return ""
    if risks:
        return "；".join(risks)
    return {
        MISSING_TARGET: "缺少目标底稿、字段或单元格",
        MISSING_LOCATOR: "缺少稳定 locator 或固定单元格",
        MISSING_EVIDENCE: "缺少 evidence/source 或项目证据",
        CONFLICT: "规则存在冲突",
        DISABLED: "规则已停用",
    }.get(status, "")


def infer_source_type(rule: dict[str, Any], targets: list[dict[str, Any]]) -> str:
    if rule.get("source_type"):
        return str(rule["source_type"])
    fields = " ".join(target.get("target_field", "") for target in targets)
    if infer_workpaper_code(rule).startswith("B60") or any(key in fields for key in ["entity_name", "audit_period", "schedule"]):
        return "attachments_and_project_context"
    return "attachments"


def inspect_rule(rule: dict[str, Any], locator_profiles: dict[str, Any], duplicate_ids: set[str]) -> dict[str, Any]:
    raw_targets = [target for target in safe_list(rule.get("targets")) if isinstance(target, dict)]
    if rule.get("target_cell") or rule.get("locator"):
        raw_targets.append(
            {
                "field": rule.get("field") or rule.get("target_field") or rule.get("name") or rule.get("id"),
                "target_cell": rule.get("target_cell", ""),
                "locator": rule.get("locator", ""),
            }
        )
    targets = [inspect_target(locator_profiles, target, index) for index, target in enumerate(raw_targets, start=1)]
    evidence = evidence_requirements(rule)
    conflicts: list[str] = []
    rule_id = str(rule.get("id") or "")
    if rule_id in duplicate_ids:
        conflicts.append("规则 ID 重复")
    seen_fields: set[str] = set()
    for target in targets:
        field = str(target.get("target_field") or "")
        if field and field in seen_fields:
            conflicts.append(f"同一规则内目标字段重复：{field}")
        seen_fields.add(field)
    enabled = bool(rule.get("enabled", True))
    definition_status = rule_status(targets, evidence, conflicts, enabled)
    risks = list(conflicts)
    if not enabled:
        risks.append("规则已停用")
    if definition_status == MISSING_EVIDENCE:
        risks.append("未配置 evidence/source，无法判断填充来源")
    if definition_status == MISSING_TARGET:
        risks.append("缺少明确目标字段或目标单元格")
    if definition_status == MISSING_LOCATOR:
        risks.append("至少一个目标缺少稳定定位方式")
    for target in targets:
        risks.extend(target.get("risks", []))
    workpaper_code = infer_workpaper_code(rule)
    workpaper_name = infer_workpaper_name(rule)
    stage = infer_stage(rule)
    section = infer_section(rule)
    source_type = infer_source_type(rule, targets)
    applies_when = str(rule.get("applies_when") or "any_required")
    target_fields = [target["target_field"] for target in targets if target.get("target_field")]
    target_locators = [target["locator_display"] for target in targets if target.get("locator_display")]
    return {
        "id": rule_id,
        "rule_id": rule_id,
        "name": rule.get("name", ""),
        "scope": rule.get("scope", ""),
        "workpaper_code": workpaper_code,
        "workpaper_name": workpaper_name,
        "workpaper": rule.get("workpaper") or f"{workpaper_code} {workpaper_name}".strip(),
        "stage": stage,
        "sheet": rule.get("sheet") or "",
        "section": section,
        "target_field": "、".join(target_fields),
        "target_cell": "、".join(target["target_cell"] for target in targets if target.get("target_cell")),
        "locator": "、".join(target_locators),
        "targets": targets,
        "source_type": source_type,
        "evidence_requirements": evidence,
        "sources": evidence,
        "content_template": rule.get("content_template", ""),
        "matching_logic": evidence_logic(evidence, applies_when),
        "preconditions": [
            "规则启用" if enabled else "规则停用",
            "项目中存在可匹配底稿",
            "必需证据按关键词匹配成功",
            "目标字段可通过固定单元格、locator、表头或标签定位",
        ],
        "validation": {
            "pre_write": [
                "确认底稿文件存在且可打开",
                "确认目标页签或章节存在",
                "确认目标单元格、表头、标签或文档结构可定位",
                "确认必需证据已匹配",
            ],
            "post_write": [
                "重新读取目标位置并比对写入值",
                "记录旧值、新值、单元格/章节和写入状态",
                "blocked 项不得写入",
            ],
            "status": definition_status,
            "definition_status": definition_status,
            "project_status": "not_checked",
            "risks": list(dict.fromkeys(risks)),
            "checks": {
                "has_scope": bool(rule.get("scope")),
                "has_sheet_or_workpaper": bool(rule.get("sheet") or rule.get("workpaper") or workpaper_code),
                "has_target": bool(targets) and all(target["status"] != MISSING_TARGET for target in targets),
                "has_locator": bool(targets) and all(target["status"] != MISSING_LOCATOR for target in targets),
                "has_evidence": bool(evidence),
                "has_content_template": bool(rule.get("content_template")),
                "enabled": enabled,
            },
        },
        "validation_steps": [
            "写入前：底稿存在、页签/章节存在、目标可定位、证据已匹配",
            "写入后：读取目标位置，确认新值与计划一致并保留状态记录",
        ],
        "severity": rule.get("severity") or ("high" if definition_status in {CONFLICT, MISSING_TARGET} else "medium"),
        "enabled": enabled,
        "definition_status": definition_status,
        "project_status": "not_checked",
        "missing_reason": missing_reason_for_status(definition_status, list(dict.fromkeys(risks))),
        "evidence_required_count": required_evidence_count(evidence),
        "evidence_matched_count": None,
        "matched_workpaper_count": None,
        "status": definition_status,
        "current_status": definition_status,
        "risk_gaps": list(dict.fromkeys(risks)),
        "definition_gaps": list(dict.fromkeys(risks)),
        "project_gaps": [],
        "_raw": rule,
    }


def target_conflict_key(rule: dict[str, Any], target: dict[str, Any]) -> str:
    locator = target.get("target_cell") or target.get("locator_display") or target.get("locator")
    field = target.get("target_field") or ""
    if not locator and not field:
        return ""
    return "|".join(
        [
            str(rule.get("workpaper_code") or ""),
            str(rule.get("sheet") or rule.get("section") or ""),
            str(field),
            str(locator),
        ]
    )


def add_cross_rule_conflicts(inspections: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[str]] = defaultdict(list)
    for rule in inspections:
        for target in rule.get("targets", []):
            key = target_conflict_key(rule, target)
            if key:
                grouped[key].append(rule.get("rule_id", ""))
    conflicts = {key: ids for key, ids in grouped.items() if len(set(ids)) > 1}
    if not conflicts:
        return
    for rule in inspections:
        messages: list[str] = []
        for target in rule.get("targets", []):
            key = target_conflict_key(rule, target)
            ids = conflicts.get(key)
            if ids:
                messages.append("目标与其他规则重复：" + "、".join(sorted(set(ids))))
        if messages:
            rule["definition_status"] = CONFLICT
            rule["status"] = CONFLICT
            rule["current_status"] = CONFLICT
            rule["validation"]["definition_status"] = CONFLICT
            rule["validation"]["status"] = CONFLICT
            rule["validation"]["risks"] = list(dict.fromkeys(rule["validation"]["risks"] + messages))
            rule["risk_gaps"] = list(dict.fromkeys(rule["risk_gaps"] + messages))
            rule["definition_gaps"] = list(dict.fromkeys(rule["definition_gaps"] + messages))
            rule["missing_reason"] = missing_reason_for_status(CONFLICT, rule["definition_gaps"])


def summarize_rules(inspections: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = Counter(item["status"] for item in inspections)
    by_scope = Counter(item.get("scope") or "unknown" for item in inspections)
    by_stage = Counter(item.get("stage") or "unknown" for item in inspections)
    definition = rule_status_summary(inspections, "definition_status")
    project = rule_status_summary(inspections, "project_status")
    return {
        "total_rules": len(inspections),
        "ready": by_status.get(READY, 0),
        "missing_target": by_status.get(MISSING_TARGET, 0),
        "missing_locator": by_status.get(MISSING_LOCATOR, 0),
        "missing_evidence": by_status.get(MISSING_EVIDENCE, 0),
        "conflict": by_status.get(CONFLICT, 0),
        "disabled": by_status.get(DISABLED, 0),
        "by_status": {status: by_status.get(status, 0) for status in STATUS_ORDER},
        "by_scope": dict(by_scope),
        "by_stage": dict(by_stage),
        "definition": definition,
        "project": project,
    }


def build_scopes(inspections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in inspections:
        code = str(rule.get("workpaper_code") or "")
        family = "B22A" if code.startswith("B22A") else "B23" if code.startswith("B23") else "B60" if code.startswith("B60") else str(rule.get("scope") or code)
        by_family[family].append(rule)
    scopes: list[dict[str, Any]] = []
    for family, meta in SCOPE_CATALOG.items():
        rules = by_family.get(family, [])
        status_counter = Counter(rule["status"] for rule in rules)
        definition_counter = Counter(rule.get("definition_status") for rule in rules)
        project_counter = Counter(rule.get("project_status") for rule in rules)
        scopes.append(
            {
                "scope": family,
                "label": meta["label"],
                "stage": meta["stage"],
                "reserved": bool(meta["reserved"] and not rules),
                "rule_count": len(rules),
                "ready": status_counter.get(READY, 0),
                "missing_target": status_counter.get(MISSING_TARGET, 0),
                "missing_locator": status_counter.get(MISSING_LOCATOR, 0),
                "missing_evidence": status_counter.get(MISSING_EVIDENCE, 0),
                "conflict": status_counter.get(CONFLICT, 0),
                "disabled": status_counter.get(DISABLED, 0),
                "definition_status": dict(definition_counter),
                "project_status": dict(project_counter),
            }
        )
    for family, rules in sorted(by_family.items()):
        if family in SCOPE_CATALOG:
            continue
        status_counter = Counter(rule["status"] for rule in rules)
        definition_counter = Counter(rule.get("definition_status") for rule in rules)
        project_counter = Counter(rule.get("project_status") for rule in rules)
        scopes.append(
            {
                "scope": family,
                "label": family,
                "stage": rules[0].get("stage", ""),
                "reserved": False,
                "rule_count": len(rules),
                "ready": status_counter.get(READY, 0),
                "missing_target": status_counter.get(MISSING_TARGET, 0),
                "missing_locator": status_counter.get(MISSING_LOCATOR, 0),
                "missing_evidence": status_counter.get(MISSING_EVIDENCE, 0),
                "conflict": status_counter.get(CONFLICT, 0),
                "disabled": status_counter.get(DISABLED, 0),
                "definition_status": dict(definition_counter),
                "project_status": dict(project_counter),
            }
        )
    return scopes


def group_for_visualization(inspections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for rule in inspections:
        workpaper_key = rule.get("workpaper_code") or rule.get("workpaper") or "未指定底稿"
        sheet_key = rule.get("sheet") or rule.get("section") or "默认区域"
        workpaper = grouped.setdefault(
            workpaper_key,
            {
                "workpaper_code": rule.get("workpaper_code", ""),
                "workpaper_name": rule.get("workpaper_name", ""),
                "workpaper": rule.get("workpaper", ""),
                "scope": rule.get("scope", ""),
                "stage": rule.get("stage", ""),
                "rule_count": 0,
                "ready": 0,
                "sheets": {},
            },
        )
        workpaper["rule_count"] += 1
        if rule.get("definition_status") == READY:
            workpaper["ready"] += 1
        sheet = workpaper["sheets"].setdefault(sheet_key, {"sheet": sheet_key, "section": rule.get("section", ""), "fields": []})
        for target in rule.get("targets", []):
            sheet["fields"].append(
                {
                    "target_field": target.get("target_field", ""),
                    "target_cell": target.get("target_cell", ""),
                    "locator": target.get("locator_display", ""),
                    "locator_method": target.get("locator_method", ""),
                    "source_type": rule.get("source_type", ""),
                    "evidence_requirements": rule.get("evidence_requirements", []),
                    "rule": {
                        "rule_id": rule.get("rule_id", ""),
                        "name": rule.get("name", ""),
                        "content_template": rule.get("content_template", ""),
                    },
                    "validation": rule.get("validation", {}),
                    "definition_status": target.get("status") if target.get("status") != READY else rule.get("definition_status"),
                    "project_status": rule.get("project_status"),
                    "status": target.get("status") if target.get("status") != READY else rule.get("status"),
                }
            )
    result: list[dict[str, Any]] = []
    for workpaper in grouped.values():
        result.append(
            {
                **{key: value for key, value in workpaper.items() if key != "sheets"},
                "sheets": list(workpaper["sheets"].values()),
            }
        )
    return result


def deficiency_lists(inspections: list[dict[str, Any]], *, status_field: str = "status", gap_field: str = "risk_gaps") -> dict[str, list[dict[str, Any]]]:
    result = {
        "conflicts": [],
        "missing_targets": [],
        "missing_locators": [],
        "missing_evidence": [],
    }
    for rule in inspections:
        base = {
            "rule_id": rule.get("rule_id", ""),
            "name": rule.get("name", ""),
            "scope": rule.get("scope", ""),
            "workpaper_code": rule.get("workpaper_code", ""),
            "workpaper_name": rule.get("workpaper_name", ""),
            "stage": rule.get("stage", ""),
            "sheet": rule.get("sheet", ""),
            "section": rule.get("section", ""),
            "risks": rule.get(gap_field, []),
        }
        status = rule.get(status_field)
        if status == CONFLICT:
            result["conflicts"].append(base)
        if status == MISSING_EVIDENCE or (status_field == "project_status" and rule.get("missing_required_evidence")):
            result["missing_evidence"].append(base)
        project_validation = rule.get("project_validation") or {}
        if (
            status == MISSING_TARGET
            or (status_field == "definition_status" and any(target.get("status") == MISSING_TARGET for target in rule.get("targets", [])))
            or (status_field == "project_status" and project_validation.get("matched_workpaper_count") == 0)
        ):
            result["missing_targets"].append(base)
        if status == MISSING_LOCATOR or (status_field == "definition_status" and any(target.get("status") == MISSING_LOCATOR for target in rule.get("targets", []))):
            result["missing_locators"].append(base)
    return result


def public_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in rule.items() if key != "_raw"}


def target_statistics(inspections: list[dict[str, Any]]) -> dict[str, int]:
    targets = [target for rule in inspections for target in rule.get("targets", [])]
    return {
        "total_targets": len(targets),
        "targets_with_locator": sum(1 for target in targets if target.get("locator")),
        "targets_with_stable_locator": sum(1 for target in targets if target.get("locator") or target.get("locator_display")),
        "targets_with_fixed_cell": sum(1 for target in targets if target.get("target_cell")),
    }


def workpaper_presence(workpapers: list[dict[str, Any]] | None, code: str) -> dict[str, Any]:
    if workpapers is None:
        return {"project_present": None, "matched_workpaper_count": None}
    token = normalize_text(code)
    matches = [
        item for item in workpapers
        if token and token in normalize_text(" ".join(str(item.get(key, "")) for key in ("code", "name", "file_path")))
    ]
    return {
        "project_present": bool(matches),
        "matched_workpaper_count": len(matches),
    }


def coverage_matrix(inspections: list[dict[str, Any]], workpapers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in inspections:
        by_code[str(rule.get("workpaper_code") or "")].append(rule)

    b_rows: list[dict[str, Any]] = []
    for code, (coverage_status, note) in B_COVERAGE_NOTES.items():
        rules = by_code.get(code, [])
        b_rows.append(
            {
                "class": "B",
                "workpaper_code": code,
                "workpaper_name": rules[0].get("workpaper_name", "") if rules else "",
                "rule_count": len(rules),
                "covered": bool(rules),
                "coverage_status": coverage_status if rules else "missing_rule",
                "write_level": coverage_status,
                "definition_ready": all(rule.get("definition_status") == READY for rule in rules) if rules else False,
                "project_ready": all(rule.get("project_status") == READY for rule in rules) if rules else False,
                "note": note,
                **workpaper_presence(workpapers, code),
            }
        )

    c_rows: list[dict[str, Any]] = []
    for code, name, expected_status, note in C_EXPECTED:
        rules = by_code.get(code, [])
        c_rows.append(
            {
                "class": "C",
                "workpaper_code": code,
                "workpaper_name": name,
                "rule_count": len(rules),
                "covered": bool(rules),
                "coverage_status": "covered" if rules else expected_status,
                "write_level": "writable" if rules else "missing_rule",
                "definition_ready": all(rule.get("definition_status") == READY for rule in rules) if rules else False,
                "project_ready": all(rule.get("project_status") == READY for rule in rules) if rules else False,
                "note": note,
                **workpaper_presence(workpapers, code),
            }
        )

    a_rows: list[dict[str, Any]] = []
    for code, name, expected_status, note in A_EXPECTED:
        rules = by_code.get(code, [])
        a_rows.append(
            {
                "class": "A",
                "workpaper_code": code,
                "workpaper_name": name,
                "rule_count": len(rules),
                "covered": bool(rules),
                "coverage_status": "covered" if rules else expected_status,
                "write_level": "writable" if rules else "missing_rule",
                "definition_ready": all(rule.get("definition_status") == READY for rule in rules) if rules else False,
                "project_ready": all(rule.get("project_status") == READY for rule in rules) if rules else False,
                "note": note,
                **workpaper_presence(workpapers, code),
            }
        )

    all_rows = b_rows + c_rows + a_rows
    return {
        "B": b_rows,
        "C": c_rows,
        "A": a_rows,
        "summary": {
            "covered_workpapers": sum(1 for row in all_rows if row["covered"]),
            "missing_rule_workpapers": sum(1 for row in all_rows if not row["covered"]),
            "writable_or_partial": sum(1 for row in all_rows if str(row["write_level"]).startswith("writable")),
            "priority_missing": [row["workpaper_code"] for row in all_rows if row["coverage_status"] in {"missing_rule_priority", "missing_rule"}],
        },
    }


def next_rule_todos() -> list[dict[str, Any]]:
    return [
        {
            "priority": 1,
            "workpaper_code": "B22A-4-4-1",
            "title": "K/L 与 C22/C21-1 一致性规则",
            "reason": "B22A K/L不能只依赖附件或B22A自身判断，必须交叉校验C22测试结论和C21-1问题清单。",
            "definition_needed": ["C22控制编号结论读取", "C21-1问题编号和控制点读取", "K列是否存在问题", "L列问题描述一致性"],
        },
        {
            "priority": 2,
            "workpaper_code": "A14/A17/A21/A53",
            "title": "A类报告和归档类底稿规则",
            "reason": "A27已补规则，但其他A类底稿仍未形成默认字段和校验规则。",
            "definition_needed": ["默认字段", "引用底稿", "复核状态", "归档检查项"],
        },
    ]


def build_payload(
    inspections: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
    workpapers: list[dict[str, Any]] | None = None,
    include_template_scan: bool = False,
) -> dict[str, Any]:
    public_rules = [public_rule(rule) for rule in inspections]
    deficiencies = deficiency_lists(public_rules)
    definition_deficiencies = deficiency_lists(public_rules, status_field="definition_status", gap_field="definition_gaps")
    project_deficiencies = deficiency_lists(public_rules, status_field="project_status", gap_field="project_gaps")
    template_scan = scan_workpaper_templates(workpapers or []) if include_template_scan and workpapers is not None else None
    return {
        **(extra or {}),
        "summary": summarize_rules(public_rules),
        "definition_summary": {
            "total_rules": len(public_rules),
            **rule_status_summary(public_rules, "definition_status"),
        },
        "project_summary": {
            "total_rules": len(public_rules),
            **rule_status_summary(public_rules, "project_status"),
        },
        "target_statistics": target_statistics(public_rules),
        "scopes": build_scopes(public_rules),
        "workpapers": group_for_visualization(public_rules),
        "coverage_matrix": coverage_matrix(public_rules, workpapers),
        "template_scan": template_scan,
        "next_rule_todos": next_rule_todos(),
        "rules": public_rules,
        "definition_gaps": definition_deficiencies,
        "project_gaps": project_deficiencies,
        **deficiencies,
    }


def inspect_autofill_rules() -> dict[str, Any]:
    payload = load_rules()
    rule_ids = [rule.get("id", "") for rule in payload.get("rules", [])]
    duplicate_ids = {rule_id for rule_id, count in Counter(rule_ids).items() if rule_id and count > 1}
    inspections = [
        inspect_rule(rule, payload.get("locator_profiles", {}), duplicate_ids)
        for rule in payload.get("rules", [])
    ]
    add_cross_rule_conflicts(inspections)
    return build_payload(
        inspections,
        extra={
            "version": payload.get("version"),
            "basis": payload.get("basis", ""),
        },
    )


def match_workpapers(rule: dict[str, Any], workpapers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = [
        rule.get("workpaper_code", ""),
        rule.get("workpaper_name", ""),
        rule.get("sheet", ""),
    ]
    normalized_tokens = [normalize_text(token) for token in tokens if token]
    matches: list[dict[str, Any]] = []
    for workpaper in workpapers:
        text = normalize_text(" ".join(str(workpaper.get(key, "")) for key in ("code", "name", "file_path")))
        if any(token and token in text for token in normalized_tokens):
            matches.append(workpaper)
    return matches


def b44_control_template_gaps(
    rule: dict[str, Any],
    evidence_matches: list[Any],
    matched_workpapers: list[dict[str, Any]],
) -> list[str]:
    if str(rule.get("id") or "") != "B-B22A-4-4-1-ITGC-UNDERSTANDING":
        return []
    if not rule_applies(rule, evidence_matches):
        return []
    suggestion = build_suggestion(rule, evidence_matches)
    inferred = infer_control_understanding_rows(suggestion)
    if not inferred:
        return []

    found_codes: set[str] = set()
    checked_files: list[str] = []
    errors: list[str] = []
    for workpaper in matched_workpapers:
        path = Path(str(workpaper.get("file_path") or "")).expanduser()
        if path.suffix.lower() not in {".xlsx", ".xlsm"} or not path.exists():
            continue
        checked_files.append(path.name)
        try:
            wb = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        except Exception as exc:  # pragma: no cover - defensive for damaged user workbooks
            errors.append(f"{path.name} 无法打开：{exc}")
            continue
        try:
            for ws in wb.worksheets:
                header_row, columns, _ = locate_b44_columns(ws)
                code_col = columns.get("code")
                if header_row is None or not code_col:
                    continue
                for row_data in inferred:
                    code = row_data.get("code", "")
                    if code and code not in found_codes and find_control_row(ws, header_row, code_col, code):
                        found_codes.add(code)
        finally:
            wb.close()

    missing_codes = [row["code"] for row in inferred if row.get("code") and row["code"] not in found_codes]
    gaps: list[str] = []
    if missing_codes:
        gaps.append(
            "B22A-4-4-1 了解矩阵缺少控制编号行："
            + "、".join(missing_codes)
            + "；C22/附件触发了这些控制点，但当前 B22A 模板未提供可写入行"
        )
    gaps.extend(errors)
    if not checked_files and inferred:
        gaps.append("未找到可打开的 B22A-4-4-1 Excel 底稿，无法校验控制编号行")
    return gaps


def apply_project_context(
    inspections: list[dict[str, Any]],
    workpapers: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    project_items: list[dict[str, Any]] = []
    for item in inspections:
        rule = item["_raw"]
        evidence_matches = match_evidence(rule, attachments)
        missing = missing_required(evidence_matches)
        matched_workpapers = match_workpapers(item, workpapers)
        definition_status = item["definition_status"]
        project_status = READY if definition_status == READY else definition_status
        project_gaps: list[str] = []
        if definition_status != READY:
            project_gaps.append("规则定义未达到 ready，项目层不能进入写入验证")
        if not matched_workpapers:
            project_status = MISSING_TARGET
            project_gaps.append("当前项目未匹配到适用底稿")
        if missing:
            if project_status == READY:
                project_status = MISSING_EVIDENCE
            if not attachments:
                project_gaps.append("当前项目附件数为 0，无法匹配必需证据：" + "、".join(missing))
            else:
                project_gaps.append("当前项目缺少必需证据：" + "、".join(missing))
        template_gaps = b44_control_template_gaps(rule, evidence_matches, matched_workpapers)
        if template_gaps:
            if project_status == READY:
                project_status = MISSING_TARGET
            project_gaps.extend(template_gaps)
        evidence_required_count = item.get("evidence_required_count")
        if evidence_required_count is None:
            evidence_required_count = required_evidence_count(item.get("evidence_requirements", []))
        evidence_matched_count = sum(1 for match in evidence_matches if match.matched)
        project_validation = {
            "status": project_status,
            "definition_status": definition_status,
            "project_status": project_status,
            "missing_reason": missing_reason_for_status(project_status, list(dict.fromkeys(project_gaps))),
            "risks": list(dict.fromkeys(project_gaps)),
            "matched_workpaper_count": len(matched_workpapers),
            "attachment_count": len(attachments),
            "missing_required_evidence": missing,
            "evidence_required_count": evidence_required_count,
            "evidence_matched_count": evidence_matched_count,
            "template_gaps": template_gaps,
        }
        definition_gaps = list(item.get("definition_gaps", []))
        combined_gaps = list(dict.fromkeys(definition_gaps + project_gaps))
        project_items.append(
            {
                **item,
                "matched_workpapers": [
                    {
                        "id": workpaper.get("id"),
                        "code": workpaper.get("code", ""),
                        "name": workpaper.get("name", ""),
                        "stage": workpaper.get("stage", ""),
                        "file_path": workpaper.get("file_path", ""),
                    }
                    for workpaper in matched_workpapers
                ],
                "evidence_matches": [
                    {
                        "name": match.name,
                        "required": match.required,
                        "matched": match.matched,
                        "attachment_count": len(match.attachments),
                        "attachments": [
                            {
                                "id": attachment.get("id"),
                                "index_no": attachment.get("index_no", ""),
                                "title": attachment.get("title", ""),
                                "file_path": attachment.get("file_path", ""),
                            }
                            for attachment in match.attachments
                        ],
                    }
                    for match in evidence_matches
                ],
                "missing_required_evidence": missing,
                "template_gaps": template_gaps,
                "project_validation": project_validation,
                "definition_status": definition_status,
                "project_status": project_status,
                "missing_reason": missing_reason_for_status(project_status, list(dict.fromkeys(project_gaps))),
                "evidence_required_count": evidence_required_count,
                "evidence_matched_count": evidence_matched_count,
                "matched_workpaper_count": len(matched_workpapers),
                "status": project_status,
                "current_status": project_status,
                "project_gaps": list(dict.fromkeys(project_gaps)),
                "risk_gaps": combined_gaps,
                "validation": {
                    **item.get("validation", {}),
                    "status": project_status,
                    "definition_status": definition_status,
                    "project_status": project_status,
                    "risks": combined_gaps,
                },
            }
        )
    return project_items


def inspect_project_autofill_rules(
    workpapers: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    *,
    include_template_scan: bool = True,
) -> dict[str, Any]:
    payload = load_rules()
    rule_ids = [rule.get("id", "") for rule in payload.get("rules", [])]
    duplicate_ids = {rule_id for rule_id, count in Counter(rule_ids).items() if rule_id and count > 1}
    base_rules = [
        inspect_rule(rule, payload.get("locator_profiles", {}), duplicate_ids)
        for rule in payload.get("rules", [])
    ]
    add_cross_rule_conflicts(base_rules)
    project_rules = apply_project_context(base_rules, workpapers, attachments)
    return build_payload(
        project_rules,
        extra={
            "version": payload.get("version"),
            "basis": payload.get("basis", ""),
            "project_context": {
                "workpaper_count": len(workpapers),
                "attachment_count": len(attachments),
            },
        },
        workpapers=workpapers,
        include_template_scan=include_template_scan,
    )
