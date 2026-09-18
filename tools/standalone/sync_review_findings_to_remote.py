#!/usr/bin/env python3
"""将本地 ITAS 项目的复核问题同步到远端 MariaDB。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
import sys
import unicodedata
from typing import Any, Iterable, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url


LOCAL_URL_ENV = "AUDIT_FLOW_LOCAL_DB_URL"
REMOTE_URL_ENV = "AUDIT_FLOW_REMOTE_DB_URL"


class SyncError(RuntimeError):
    """可预期的同步校验错误。"""


@dataclass(frozen=True)
class SyncResult:
    source_rows: int
    inserted: int
    would_insert: int
    skipped_duplicates: int
    dry_run: bool
    project_code: str


def normalize_text(value: Any) -> str:
    """归一化业务文本，避免全半角、大小写和空白差异造成重复。"""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.split()).casefold()


def finding_fingerprint(row: Mapping[str, Any]) -> str:
    """生成项目内问题的稳定业务指纹。"""
    parts = (
        "c22" if bool(row.get("c22_related")) else "non-c22",
        normalize_text(row.get("workpaper_code")),
        normalize_text(row.get("issue_step")),
        normalize_text(row.get("finding_type")),
        normalize_text(row.get("issue")),
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def require_mariadb_url(value: str, env_name: str) -> str:
    if not value:
        raise SyncError(f"请设置 {env_name}")
    url = make_url(value)
    if url.get_backend_name() != "mariadb" or not url.database:
        raise SyncError(f"{env_name} 必须是包含数据库名的 mariadb+pymysql URL")
    return value


def _one_project(conn: Connection, code: str) -> Mapping[str, Any]:
    rows = conn.execute(
        text("SELECT id, code, name FROM projects WHERE code = :code ORDER BY id"),
        {"code": code},
    ).mappings().all()
    if not rows:
        raise SyncError(f"未找到项目编号：{code}")
    if len(rows) != 1:
        raise SyncError(f"项目编号 {code} 对应 {len(rows)} 个项目，无法安全同步")
    return rows[0]


def _load_findings(conn: Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT rf.*, w.code AS workpaper_code,
                   creator.username AS creator_username,
                   assignee.username AS assignee_username
            FROM review_findings AS rf
            JOIN review_runs AS rr ON rr.id = rf.run_id
            LEFT JOIN workpapers AS w ON w.id = rf.workpaper_id
            LEFT JOIN users AS creator ON creator.id = rf.created_by_user_id
            LEFT JOIN users AS assignee ON assignee.id = rf.assignee_user_id
            WHERE rr.project_id = :project_id
            ORDER BY rf.id
            """
        ),
        {"project_id": project_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _unique_code_map(conn: Connection, table: str, key: str, where_sql: str, params: Mapping[str, Any]) -> dict[str, int]:
    rows = conn.execute(text(f"SELECT id, {key} AS business_key FROM {table} WHERE {where_sql}"), params).mappings()
    result: dict[str, int] = {}
    for row in rows:
        business_key = str(row["business_key"] or "")
        if business_key in result:
            raise SyncError(f"远端 {table}.{key} 业务键重复：{business_key}")
        result[business_key] = int(row["id"])
    return result


def _validate_source_rows(rows: Iterable[Mapping[str, Any]]) -> None:
    seen_fingerprints: dict[str, str] = {}
    seen_issue_nos: dict[str, str] = {}
    for row in rows:
        fingerprint = finding_fingerprint(row)
        issue_no = str(row.get("issue_no") or "").strip()
        if fingerprint in seen_fingerprints:
            raise SyncError(
                f"本地项目已存在重复问题：{seen_fingerprints[fingerprint]} 与 {issue_no or '[空编号]'}"
            )
        seen_fingerprints[fingerprint] = issue_no or "[空编号]"
        if issue_no:
            previous = seen_issue_nos.get(issue_no)
            if previous and previous != fingerprint:
                raise SyncError(f"本地项目问题编号重复且内容不同：{issue_no}")
            seen_issue_nos[issue_no] = fingerprint


def _manual_run_id(conn: Connection, project_id: int) -> int:
    existing = conn.execute(
        text(
            "SELECT id FROM review_runs "
            "WHERE project_id = :project_id AND mode = 'manual' ORDER BY id DESC LIMIT 1"
        ),
        {"project_id": project_id},
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    now = datetime.utcnow()
    conn.execute(
        text(
            """
            INSERT INTO review_runs
                (project_id, workpaper_id, mode, status, started_at, finished_at,
                 summary, report_path, created_at, updated_at)
            VALUES
                (:project_id, NULL, 'manual', 'completed', :now, :now,
                 '本地问题清单同步', '', :now, :now)
            """
        ),
        {"project_id": project_id, "now": now},
    )
    return int(conn.execute(text("SELECT LAST_INSERT_ID()" )).scalar_one())


FINDING_COLUMNS = (
    "issue_no", "standard_index_code", "source", "rule_code", "audit_stage",
    "finding_type", "issue_step", "issue_category", "severity", "c22_related",
    "workpaper_file", "location", "target", "issue", "evidence", "recommendation",
    "project_reply", "resolution_confirmed", "review_stage", "field_lead",
    "project_reviewer", "note", "status", "due_date", "review_comment",
)


INSERT_FINDING_SQL = text(
    """
    INSERT IGNORE INTO review_findings
        (run_id, workpaper_id, workpaper_version_id, resolved_workpaper_version_id,
         review_step_id, created_by_user_id, assignee_user_id,
         issue_no, standard_index_code, source, rule_code, audit_stage,
         finding_type, issue_step, issue_category, severity, c22_related,
         workpaper_file, location, target, issue, evidence, recommendation,
         project_reply, resolution_confirmed, review_stage, field_lead,
         project_reviewer, note, status, due_date, review_comment,
         created_at, updated_at)
    VALUES
        (:run_id, :workpaper_id, NULL, NULL, NULL, :created_by_user_id, :assignee_user_id,
         :issue_no, :standard_index_code, :source, :rule_code, :audit_stage,
         :finding_type, :issue_step, :issue_category, :severity, :c22_related,
         :workpaper_file, :location, :target, :issue, :evidence, :recommendation,
         :project_reply, :resolution_confirmed, :review_stage, :field_lead,
         :project_reviewer, :note, :status, :due_date, :review_comment,
         :created_at, :updated_at)
    """
)


def _prepare_params(
    row: Mapping[str, Any], run_id: int, workpapers: Mapping[str, int], users: Mapping[str, int]
) -> dict[str, Any]:
    workpaper_code = str(row.get("workpaper_code") or "")
    if row.get("workpaper_id") is not None and workpaper_code not in workpapers:
        raise SyncError(f"远端项目缺少底稿 {workpaper_code!r}，已停止以避免错误关联")
    params = {column: row.get(column) for column in FINDING_COLUMNS}
    params.update(
        run_id=run_id,
        workpaper_id=workpapers.get(workpaper_code),
        created_by_user_id=users.get(str(row.get("creator_username") or "")),
        assignee_user_id=users.get(str(row.get("assignee_username") or "")),
        created_at=row.get("created_at") or datetime.utcnow(),
        updated_at=row.get("updated_at") or datetime.utcnow(),
    )
    return params


def _sync_locked(
    conn: Connection,
    source_rows: list[dict[str, Any]],
    remote_project: Mapping[str, Any],
    *,
    apply: bool,
) -> SyncResult:
    remote_rows = _load_findings(conn, int(remote_project["id"]))
    remote_fingerprints = {finding_fingerprint(row) for row in remote_rows}
    remote_issue_nos = {
        str(row.get("issue_no") or "").strip(): finding_fingerprint(row)
        for row in remote_rows if str(row.get("issue_no") or "").strip()
    }
    pending: list[dict[str, Any]] = []
    skipped = 0
    for row in source_rows:
        fingerprint = finding_fingerprint(row)
        if fingerprint in remote_fingerprints:
            skipped += 1
            continue
        issue_no = str(row.get("issue_no") or "").strip()
        if issue_no and issue_no in remote_issue_nos and remote_issue_nos[issue_no] != fingerprint:
            raise SyncError(f"远端项目中编号 {issue_no} 已被另一个问题使用，未写入任何数据")
        pending.append(row)

    if not apply:
        return SyncResult(len(source_rows), 0, len(pending), skipped, True, str(remote_project["code"]))

    if not pending:
        return SyncResult(len(source_rows), 0, 0, skipped, False, str(remote_project["code"]))

    workpapers = _unique_code_map(
        conn, "workpapers", "code", "project_id = :project_id", {"project_id": remote_project["id"]}
    )
    users = _unique_code_map(conn, "users", "username", "1 = 1", {})
    run_id = _manual_run_id(conn, int(remote_project["id"]))
    inserted = 0
    for row in pending:
        result = conn.execute(INSERT_FINDING_SQL, _prepare_params(row, run_id, workpapers, users))
        if result.rowcount != 1:
            raise SyncError(f"INSERT IGNORE 未写入问题 {row.get('issue_no') or '[空编号]'}")
        inserted += 1
    total = conn.execute(
        text("SELECT COUNT(*) FROM review_findings WHERE run_id = :run_id"), {"run_id": run_id}
    ).scalar_one()
    conn.execute(
        text(
            "UPDATE review_runs SET status='completed', finished_at=:now, updated_at=:now, "
            "summary=:summary WHERE id=:run_id"
        ),
        {"now": datetime.utcnow(), "summary": f"本地问题清单同步，累计 {total} 项", "run_id": run_id},
    )
    return SyncResult(len(source_rows), inserted, inserted, skipped, False, str(remote_project["code"]))


def sync_findings(local_engine: Engine, remote_engine: Engine, project_code: str, *, apply: bool) -> SyncResult:
    with local_engine.connect() as local_conn:
        local_project = _one_project(local_conn, project_code)
        source_rows = _load_findings(local_conn, int(local_project["id"]))
    _validate_source_rows(source_rows)

    if not apply:
        with remote_engine.connect() as remote_conn:
            remote_project = _one_project(remote_conn, project_code)
            return _sync_locked(remote_conn, source_rows, remote_project, apply=False)

    with remote_engine.connect() as remote_conn:
        remote_project = _one_project(remote_conn, project_code)
        remote_conn.commit()
        lock_name = f"itas:review-findings:{remote_project['id']}"
        acquired = remote_conn.execute(text("SELECT GET_LOCK(:name, 10)"), {"name": lock_name}).scalar_one()
        remote_conn.commit()
        if acquired != 1:
            raise SyncError("无法获取远端项目同步锁，请稍后重试")
        try:
            with remote_conn.begin():
                result = _sync_locked(remote_conn, source_rows, remote_project, apply=True)
            return result
        finally:
            remote_conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
            remote_conn.commit()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将本地 ITAS 项目问题清单去重同步到远端 MariaDB")
    parser.add_argument("--project-code", required=True, help="本地与远端共用的项目编号")
    parser.add_argument("--apply", action="store_true", help="实际写入；不加此参数时只做预演")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    local_url = require_mariadb_url(
        os.getenv(LOCAL_URL_ENV, "") or os.getenv("AUDIT_FLOW_DB_URL", ""), LOCAL_URL_ENV
    )
    remote_url = require_mariadb_url(os.getenv(REMOTE_URL_ENV, ""), REMOTE_URL_ENV)
    local_engine = create_engine(local_url, future=True, pool_pre_ping=True)
    remote_engine = create_engine(remote_url, future=True, pool_pre_ping=True)
    try:
        result = sync_findings(local_engine, remote_engine, args.project_code, apply=args.apply)
    except SyncError as exc:
        print(f"同步终止：{exc}", file=sys.stderr)
        return 2
    finally:
        local_engine.dispose()
        remote_engine.dispose()
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
