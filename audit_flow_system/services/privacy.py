from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client, ClientITContact, EnterpriseContact, Project, ProjectMember, User


@dataclass(frozen=True)
class RedactionTerm:
    value: str
    label: str


PATTERN_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[邮箱]"),
    ("mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[电话]"),
    ("phone", re.compile(r"(?<!\d)(?:0\d{2,3}[- ]?)?\d{7,8}(?:[- ]?\d{1,6})?(?!\d)"), "[电话]"),
    ("id_card", re.compile(r"(?<![0-9A-Za-z])\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?![0-9A-Za-z])"), "[身份证号]"),
    ("bank_card", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), "[银行卡号]"),
    ("credit_code", re.compile(r"(?<![0-9A-Za-z])[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}(?![0-9A-Za-z])", re.I), "[统一社会信用代码]"),
    ("ip", re.compile(r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"), "[IP地址]"),
]


def _clean_term(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _term_pattern(value: str) -> re.Pattern[str]:
    if re.search(r"[\u4e00-\u9fff]", value):
        return re.compile(re.escape(value))
    return re.compile(rf"(?<![0-9A-Za-z]){re.escape(value)}(?![0-9A-Za-z])", re.I)


def project_redaction_terms(db: Session, project: Project) -> list[RedactionTerm]:
    terms: list[RedactionTerm] = []

    def add(value: Any, label: str) -> None:
        text = _clean_term(value)
        if len(text) >= 2:
            terms.append(RedactionTerm(text, label))

    add(project.entity_name, "[客户名称]")
    add(project.name, "[项目名称]")
    add(project.code, "[项目编号]")
    add(project.oa_project_no, "[OA项目号]")
    add(project.ims_project_no, "[IMS项目号]")
    add(project.first_partner_name, "[项目人员]")
    add(project.first_partner_email, "[邮箱]")
    add(project.first_partner_phone, "[电话]")
    add(project.second_partner_name, "[项目人员]")
    add(project.second_partner_email, "[邮箱]")
    add(project.second_partner_phone, "[电话]")

    if project.client_id:
        client = db.get(Client, project.client_id)
        if client:
            add(client.entity_name, "[客户名称]")
            add(client.finance_director_name, "[客户联系人]")
            add(client.finance_director_phone, "[电话]")
            add(client.finance_director_email, "[邮箱]")
            for contact in db.execute(select(ClientITContact).where(ClientITContact.client_id == client.id)).scalars():
                add(contact.name, "[客户联系人]")
                add(contact.phone, "[电话]")
                add(contact.email, "[邮箱]")

    for contact in db.execute(select(EnterpriseContact).where(EnterpriseContact.project_id == project.id)).scalars():
        add(contact.name, "[客户联系人]")
        add(contact.phone, "[电话]")
        add(contact.email, "[邮箱]")

    for member in db.execute(select(ProjectMember).where(ProjectMember.project_id == project.id)).scalars():
        if member.user:
            add(member.user.display_name, "[项目人员]")
            add(member.user.username, "[项目人员]")
            add(member.user.email, "[邮箱]")
            add(member.user.phone, "[电话]")

    for user_id in [
        project.creator_user_id,
        project.project_leader_user_id,
        project.manager_user_id,
        project.quality_reviewer_user_id,
        project.field_leader_user_id,
    ]:
        if not user_id:
            continue
        user = db.get(User, user_id)
        if user:
            add(user.display_name, "[项目人员]")
            add(user.username, "[项目人员]")
            add(user.email, "[邮箱]")
            add(user.phone, "[电话]")

    dedup: dict[str, RedactionTerm] = {}
    for term in terms:
        dedup.setdefault(term.value, term)
    return sorted(dedup.values(), key=lambda item: len(item.value), reverse=True)


def redact_text(value: Any, terms: list[RedactionTerm] | None = None) -> tuple[str, dict[str, int]]:
    text = str(value or "")
    stats: dict[str, int] = {}
    for term in terms or []:
        pattern = _term_pattern(term.value)
        text, count = pattern.subn(term.label, text)
        if count:
            stats[term.label] = stats.get(term.label, 0) + count
    for key, pattern, replacement in PATTERN_RULES:
        text, count = pattern.subn(replacement, text)
        if count:
            stats[key] = stats.get(key, 0) + count
    return text, stats


def redact_payload(value: Any, terms: list[RedactionTerm] | None = None) -> tuple[Any, dict[str, int]]:
    stats: dict[str, int] = {}

    def merge(extra: dict[str, int]) -> None:
        for key, count in extra.items():
            stats[key] = stats.get(key, 0) + count

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            redacted, item_stats = redact_text(item, terms)
            merge(item_stats)
            return redacted
        if isinstance(item, list):
            return [walk(child) for child in item]
        if isinstance(item, dict):
            return {key: walk(child) for key, child in item.items()}
        return item

    return walk(value), stats
