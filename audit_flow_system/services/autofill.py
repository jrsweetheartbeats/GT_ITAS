from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from ..autofill_rules import generate_suggestions, load_rules, summarize_rules
from ..autofill_writer import plan_for_project_workpapers

DEFAULT_AUTOFILL_FIELD_GROUPS = [
    {
        "key": "entity_name",
        "label": "公司名称",
        "fields": ["entity_name", "header_entity_name", "client_name", "entity_name_and_audit_period"],
    },
    {
        "key": "preparer",
        "label": "编制人",
        "fields": ["preparer", "prepared_by", "prepared_by_name", "compiler"],
    },
    {
        "key": "prepared_date",
        "label": "编制日期",
        "fields": ["prepared_date", "prepared_at", "compile_date"],
    },
    {
        "key": "reviewer",
        "label": "复核人",
        "fields": ["reviewer", "reviewed_by", "reviewer_name"],
    },
    {
        "key": "reviewed_date",
        "label": "复核日期",
        "fields": ["reviewed_date", "reviewed_at", "review_date"],
    },
    {
        "key": "audit_period",
        "label": "审计期间",
        "fields": ["audit_period", "header_audit_period", "entity_name_and_audit_period"],
    },
    {
        "key": "audit_plan_period",
        "label": "审计计划时间周期",
        "fields": ["schedule", "audit_plan_period", "plan_period", "project_schedule"],
    },
]

DEFAULT_AUTOFILL_ALLOWED_FIELD_KEYS = [group["key"] for group in DEFAULT_AUTOFILL_FIELD_GROUPS]


def normalize_autofill_allowed_keys(value: Any) -> list[str]:
    valid = {group["key"] for group in DEFAULT_AUTOFILL_FIELD_GROUPS}
    if not isinstance(value, list):
        return DEFAULT_AUTOFILL_ALLOWED_FIELD_KEYS.copy()
    return [str(item) for item in value if str(item) in valid]


def autofill_scope_config(value: Any) -> dict[str, Any]:
    enabled_keys = set(normalize_autofill_allowed_keys(value))
    return {
        "field_groups": [
            {
                **group,
                "enabled": group["key"] in enabled_keys,
            }
            for group in DEFAULT_AUTOFILL_FIELD_GROUPS
        ],
        "enabled_keys": [group["key"] for group in DEFAULT_AUTOFILL_FIELD_GROUPS if group["key"] in enabled_keys],
    }


def allowed_field_names(value: Any) -> set[str]:
    enabled = set(normalize_autofill_allowed_keys(value))
    fields: set[str] = set()
    for group in DEFAULT_AUTOFILL_FIELD_GROUPS:
        if group["key"] in enabled:
            fields.update(group["fields"])
    return fields


def target_field(target: dict[str, Any]) -> str:
    return str(target.get("field") or target.get("target_field") or "")


def filter_suggestions_by_allowed_fields(suggestions: list[dict[str, Any]], allowed_keys: Any) -> list[dict[str, Any]]:
    allowed = allowed_field_names(allowed_keys)
    filtered: list[dict[str, Any]] = []
    for suggestion in suggestions:
        targets = [target for target in suggestion.get("targets", []) if target_field(target) in allowed]
        if not targets:
            continue
        item = deepcopy(suggestion)
        item["targets"] = targets
        item["scope_filtered"] = True
        filtered.append(item)
    return filtered


def filter_plan_by_allowed_fields(plan: list[dict[str, Any]], allowed_keys: Any) -> list[dict[str, Any]]:
    allowed = allowed_field_names(allowed_keys)
    return [item for item in plan if str(item.get("field") or "") in allowed]


def autofill_rules_payload() -> dict[str, Any]:
    payload = load_rules()
    return {
        "summary": summarize_rules(payload),
        "basis": payload.get("basis", ""),
        "source_projects": payload.get("source_projects", []),
        "locator_profiles": payload.get("locator_profiles", {}),
        "rules": payload.get("rules", []),
    }


def autofill_suggestions(attachments: list[dict[str, Any]], scope: Optional[str] = None) -> list[dict[str, Any]]:
    suggestions = generate_suggestions(attachments)
    if scope:
        suggestions = [item for item in suggestions if item.get("scope") == scope]
    return suggestions


def autofill_plan(
    suggestions: list[dict[str, Any]],
    workpapers: list[dict[str, Any]],
    project_context: dict[str, Any],
    apply: bool = False,
) -> list[dict[str, Any]]:
    return plan_for_project_workpapers(
        suggestions,
        workpapers,
        project_context=project_context,
        apply=apply,
    )
