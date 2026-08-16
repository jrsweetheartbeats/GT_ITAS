from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Optional


RULES_PATH = Path(
    os.getenv(
        "AUDIT_FLOW_AUTOFILL_RULES_PATH",
        str(Path(__file__).resolve().parent / "data" / "autofill_rules.example.json"),
    )
).expanduser()


@dataclass
class EvidenceMatch:
    name: str
    required: bool
    matched: bool
    attachments: list[dict[str, Any]]


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    return re.sub(r"\s+", "", text)


def attachment_text(item: dict[str, Any]) -> str:
    return normalize_text(
        " ".join(
            [
                str(item.get("index_no", "")),
                str(item.get("title", "")),
                str(item.get("file_path", "")),
                str(item.get("file_type", "")),
                str(item.get("referenced_in", "")),
            ]
        )
    )


def match_evidence(rule: dict[str, Any], attachments: list[dict[str, Any]]) -> list[EvidenceMatch]:
    results: list[EvidenceMatch] = []
    prepared = [(item, attachment_text(item)) for item in attachments]
    for evidence in rule.get("evidence", []):
        keywords = [normalize_text(word) for word in evidence.get("any_keywords", [])]
        matched = [
            item
            for item, text in prepared
            if any(keyword and keyword in text for keyword in keywords)
        ]
        results.append(
            EvidenceMatch(
                name=evidence.get("name", ""),
                required=bool(evidence.get("required", False)),
                matched=bool(matched),
                attachments=matched,
            )
        )
    return results


def evidence_refs(matches: list[EvidenceMatch]) -> str:
    refs: list[str] = []
    for match in matches:
        for item in match.attachments:
            label = item.get("index_no") or item.get("title") or item.get("file_path")
            if label and label not in refs:
                refs.append(str(label))
    return "、".join(refs) if refs else "已取得附件"


def rule_applies(rule: dict[str, Any], matches: list[EvidenceMatch]) -> bool:
    policy = rule.get("applies_when", "any_required")
    required = [item for item in matches if item.required]
    if policy == "all_required":
        return bool(required) and all(item.matched for item in required)
    if policy == "all_evidence":
        return bool(matches) and all(item.matched for item in matches)
    if required:
        return any(item.matched for item in required)
    return any(item.matched for item in matches)


def missing_required(matches: list[EvidenceMatch]) -> list[str]:
    return [item.name for item in matches if item.required and not item.matched]


def build_suggestion(rule: dict[str, Any], matches: list[EvidenceMatch]) -> dict[str, Any]:
    refs = evidence_refs(matches)
    template = rule.get("content_template", "")
    return {
        "rule_id": rule.get("id"),
        "scope": rule.get("scope"),
        "sheet": rule.get("sheet", ""),
        "workpaper_code": rule.get("workpaper_code", ""),
        "workpaper": rule.get("workpaper", ""),
        "workpaper_name": rule.get("workpaper", ""),
        "stage": rule.get("stage", ""),
        "section": rule.get("section", ""),
        "name": rule.get("name"),
        "source_projects": rule.get("source_projects", []),
        "targets": rule.get("targets", []),
        "matched_evidence": [
            {
                "name": item.name,
                "required": item.required,
                "matched": item.matched,
                "attachments": [
                    {
                        "id": att.get("id"),
                        "index_no": att.get("index_no"),
                        "title": att.get("title"),
                        "file_path": att.get("file_path"),
                    }
                    for att in item.attachments
                ],
            }
            for item in matches
        ],
        "missing_required_evidence": missing_required(matches),
        "suggested_content": template.replace("{evidence_refs}", refs),
    }


def generate_suggestions(attachments: list[dict[str, Any]], rules_payload: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    payload = rules_payload or load_rules()
    suggestions = []
    for rule in payload.get("rules", []):
        matches = match_evidence(rule, attachments)
        if rule_applies(rule, matches):
            suggestions.append(build_suggestion(rule, matches))
    return suggestions


def summarize_rules(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    data = payload or load_rules()
    rules = data.get("rules", [])
    by_scope: dict[str, int] = {}
    for rule in rules:
        scope = rule.get("scope", "unknown")
        by_scope[scope] = by_scope.get(scope, 0) + 1
    return {
        "version": data.get("version"),
        "source_project_count": len(data.get("source_projects", [])),
        "rule_count": len(rules),
        "rule_count_by_scope": by_scope,
    }
