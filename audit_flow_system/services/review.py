from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import BASE_DIR, WORKSPACE_ROOT
from ..core.utils import get_or_404
from ..models import Attachment, Project, ReviewFinding, ReviewRun, ReviewStep, Workpaper
from .privacy import project_redaction_terms, redact_payload, redact_text
from .workpaper_metadata import workpaper_preparer_text


def _matched_workpaper_for_finding(db: Session, run: ReviewRun, target: str, issue: str) -> Workpaper | None:
    if run.workpaper_id:
        item = db.get(Workpaper, run.workpaper_id)
        if item:
            return item
    text = f"{target or ''} {issue or ''}".lower()
    if not text.strip():
        return None
    attachments = db.execute(
        select(Attachment).where(Attachment.project_id == run.project_id).order_by(Attachment.index_no)
    ).scalars().all()
    for attachment in attachments:
        if attachment.workpaper_id and attachment.index_no and attachment.index_no.lower() in text:
            item = db.get(Workpaper, attachment.workpaper_id)
            if item:
                return item
    workpapers = db.execute(
        select(Workpaper).where(Workpaper.project_id == run.project_id).order_by(Workpaper.code)
    ).scalars().all()
    for item in sorted(workpapers, key=lambda row: len(row.code or ""), reverse=True):
        code = (item.code or "").lower()
        name = (item.name or "").lower()
        if (code and code in text) or (name and name in text):
            return item
    return None


def add_finding(
    db: Session,
    run: ReviewRun,
    rule_code: str,
    severity: str,
    target: str,
    issue: str,
    evidence: str = "",
) -> None:
    workpaper = _matched_workpaper_for_finding(db, run, target, issue)
    db.add(
        ReviewFinding(
            run_id=run.id,
            rule_code=rule_code,
            severity=severity,
            target=target,
            issue=issue,
            evidence=evidence,
            assignee_user_id=workpaper.preparer_user_id if workpaper and workpaper.preparer_user_id else None,
        )
    )


def run_internal_review(db: Session, run: ReviewRun) -> int:
    project = get_or_404(db, Project, run.project_id, "项目")
    workpapers = db.execute(select(Workpaper).where(Workpaper.project_id == project.id)).scalars().all()
    attachments = db.execute(select(Attachment).where(Attachment.project_id == project.id)).scalars().all()
    count = 0

    if not project.audit_year:
        add_finding(db, run, "GLOBAL-001", "high", project.name, "项目未维护审计年度")
        count += 1

    seen_codes: dict[str, int] = {}
    for wp in workpapers:
        if wp.code in seen_codes:
            add_finding(db, run, "GLOBAL-002", "medium", wp.code, "同一项目存在重复底稿编码")
            count += 1
        seen_codes[wp.code] = wp.id
        if not wp.preparer_user_id and not workpaper_preparer_text(wp):
            add_finding(db, run, "GLOBAL-001", "medium", wp.code, "底稿未维护编制人")
            count += 1
        if wp.file_path and not Path(wp.file_path).expanduser().exists():
            add_finding(db, run, "GLOBAL-003", "medium", wp.code, "底稿文件路径不存在", wp.file_path)
            count += 1
        if wp.status in {"submitted", "in_review"}:
            steps = db.execute(select(ReviewStep).where(ReviewStep.workpaper_id == wp.id)).scalars().all()
            if not steps:
                add_finding(db, run, "FLOW-001", "medium", wp.code, "已提交底稿未建立复核流转")
                count += 1

    seen_indexes: dict[str, int] = {}
    for att in attachments:
        if not att.index_no:
            add_finding(db, run, "ATT-001", "high", att.title, "附件未维护索引号")
            count += 1
        elif att.index_no in seen_indexes:
            add_finding(db, run, "ATT-001", "high", att.index_no, "同一项目存在重复附件索引号")
            count += 1
        seen_indexes[att.index_no] = att.id
        if att.referenced_in and att.index_no and att.index_no not in att.referenced_in:
            add_finding(db, run, "ATT-002", "medium", att.index_no, "附件引用说明未包含附件索引号", att.referenced_in)
            count += 1
        if att.file_path and not Path(att.file_path).expanduser().exists():
            add_finding(db, run, "ATT-003", "medium", att.index_no, "附件文件路径不存在", att.file_path)
            count += 1

    return count


def run_external_rules(db: Session, run: ReviewRun) -> int:
    project = get_or_404(db, Project, run.project_id, "项目")
    if not project.project_root:
        add_finding(db, run, "EXT-000", "medium", project.name, "未配置项目底稿根目录，无法调用现有复核规则脚本")
        return 1

    rules_dir = WORKSPACE_ROOT / "复核规则"
    script = rules_dir / "run_project_rules.py"
    if not script.exists():
        add_finding(db, run, "EXT-000", "high", str(script), "现有复核规则入口不存在")
        return 1

    report_dir = BASE_DIR / "review_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"review_run_{run.id}.json"
    run.report_path = str(report_path)
    cmd = [
        sys.executable,
        str(script),
        "--project-root",
        project.project_root,
        "--report",
        str(report_path),
    ]
    proc = subprocess.run(cmd, cwd=str(rules_dir), text=True, capture_output=True, timeout=180)
    if proc.returncode != 0:
        add_finding(db, run, "EXT-001", "high", project.project_root, "现有复核规则执行失败", proc.stderr[-2000:])
        return 1

    if not report_path.exists():
        add_finding(db, run, "EXT-002", "high", project.project_root, "现有复核规则未生成报告", proc.stdout[-2000:])
        return 1

    raw_payload = json.loads(report_path.read_text(encoding="utf-8"))
    redaction_terms = project_redaction_terms(db, project)
    payload, redaction_stats = redact_payload(raw_payload, redaction_terms)
    redacted_report_path = report_dir / f"review_run_{run.id}.redacted.json"
    redacted_report_path.write_text(json.dumps({"redaction": redaction_stats, **payload}, ensure_ascii=False, indent=2), encoding="utf-8")
    run.report_path = str(redacted_report_path)
    count = 0
    for item in payload.get("findings", []):
        add_finding(
            db,
            run,
            item.get("rule_id", "EXT"),
            item.get("severity", "medium"),
            item.get("target", ""),
            item.get("issue", ""),
            item.get("evidence", ""),
        )
        count += 1
    for item in payload.get("changes", []):
        if item.get("status") in {"blocked", "partial"}:
            add_finding(
                db,
                run,
                item.get("rule_id", "EXT"),
                "medium",
                item.get("target", ""),
                item.get("message", ""),
                json.dumps({"old": item.get("old"), "new": item.get("new")}, ensure_ascii=False),
            )
            count += 1
    if redaction_stats:
        summary, _ = redact_text(run.summary or "", redaction_terms)
        run.summary = summary
    return count
