#!/usr/bin/env python3
"""把远端 ITAS 的通讯录和项目主数据同步到本地 MariaDB。

同步范围：
- 通讯录：roles（补齐通讯录角色）、users（联系方式）、personnel_profiles、ims_contacts
- 项目信息：clients、client_it_contacts、projects、project_members、enterprise_contacts

本地已有用户的 password_hash 默认保留，避免把本机登录密码冲掉。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import os
import re
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url


LOCAL_URL_ENV = "AUDIT_FLOW_LOCAL_DB_URL"
REMOTE_URL_ENV = "AUDIT_FLOW_REMOTE_DB_URL"
DEFAULT_REMOTE_HOST = "10.141.1.49"
DEFAULT_DB_NAME = "ITAS"

UPSERT_TABLES = ("roles", "users", "clients", "projects")
REPLACE_TABLES = ("personnel_profiles", "ims_contacts", "client_it_contacts", "enterprise_contacts")
UNIQUE_REALIGN = {
    "roles": "code",
    "users": "username",
    "clients": "normalized_entity_name",
    "personnel_profiles": "name",
}
PRESERVE_EXISTING = {"users": ("password_hash",)}
CHILD_REPLACE = {
    "project_members": "project_id",
}
ALLOWED_TABLES = frozenset((*UPSERT_TABLES, *REPLACE_TABLES, *CHILD_REPLACE))
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SyncError(RuntimeError):
    """可预期的同步校验错误。"""


@dataclass
class TableResult:
    table: str
    source_rows: int
    inserted: int = 0
    updated: int = 0
    replaced: int = 0
    realigned: int = 0


@dataclass
class SyncReport:
    dry_run: bool
    tables: list[TableResult] = field(default_factory=list)

    def add(self, result: TableResult) -> TableResult:
        self.tables.append(result)
        return result


def require_mariadb_url(value: str, env_name: str) -> str:
    if not value:
        raise SyncError(f"请设置 {env_name}")
    url = make_url(value)
    if url.get_backend_name() != "mariadb" or not url.database:
        raise SyncError(f"{env_name} 必须是包含数据库名的 mariadb+pymysql URL")
    return value


def build_url_from_parts(*, host: str, user: str, password: str, port: int, database: str) -> str:
    return (
        f"mariadb+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/"
        f"{database}?charset=utf8mb4"
    )


def default_local_url() -> str:
    explicit = os.getenv(LOCAL_URL_ENV) or os.getenv("AUDIT_FLOW_DB_URL")
    if explicit:
        return require_mariadb_url(explicit, LOCAL_URL_ENV)
    return build_url_from_parts(
        host=os.getenv("AUDIT_FLOW_DB_HOST", "127.0.0.1"),
        user=os.getenv("AUDIT_FLOW_DB_USER", "root"),
        password=os.getenv("AUDIT_FLOW_DB_PASSWORD", ""),
        port=int(os.getenv("AUDIT_FLOW_DB_PORT", "3306")),
        database=os.getenv("AUDIT_FLOW_DB_NAME", DEFAULT_DB_NAME),
    )


def default_remote_url() -> str:
    explicit = os.getenv(REMOTE_URL_ENV)
    if explicit:
        return require_mariadb_url(explicit, REMOTE_URL_ENV)
    password = os.getenv("AUDIT_FLOW_REMOTE_DB_PASSWORD") or os.getenv("AUDIT_FLOW_DB_PASSWORD", "")
    return build_url_from_parts(
        host=os.getenv("AUDIT_FLOW_REMOTE_DB_HOST", DEFAULT_REMOTE_HOST),
        user=os.getenv("AUDIT_FLOW_REMOTE_DB_USER", os.getenv("AUDIT_FLOW_DB_USER", "root")),
        password=password,
        port=int(os.getenv("AUDIT_FLOW_REMOTE_DB_PORT", "3306")),
        database=os.getenv("AUDIT_FLOW_REMOTE_DB_NAME", os.getenv("AUDIT_FLOW_DB_NAME", DEFAULT_DB_NAME)),
    )


def quote_ident(name: str) -> str:
    if not _IDENT_RE.fullmatch(name):
        raise SyncError(f"非法标识符: {name}")
    return f"`{name}`"


def require_table(table: str) -> str:
    if table not in ALLOWED_TABLES:
        raise SyncError(f"拒绝操作未登记的表: {table}")
    return quote_ident(table)


def table_names(conn: Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute(text("SHOW TABLES")).all()}


def table_columns(conn: Connection, table: str) -> list[str]:
    quoted = require_table(table)
    return [str(row[0]) for row in conn.execute(text(f"SHOW COLUMNS FROM {quoted}")).all()]


def fetch_rows(conn: Connection, table: str) -> list[dict[str, Any]]:
    quoted = require_table(table)
    return [dict(row) for row in conn.execute(text(f"SELECT * FROM {quoted} ORDER BY id")).mappings()]


def bump_autoincrement(conn: Connection, table: str) -> None:
    quoted = require_table(table)
    max_id = conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {quoted}")).scalar_one()
    conn.execute(text(f"ALTER TABLE {quoted} AUTO_INCREMENT = :value"), {"value": int(max_id) + 1})


def shared_columns(local_cols: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    keys = set(rows[0].keys())
    cols = [col for col in local_cols if col in keys]
    if "id" not in cols:
        raise SyncError("同步表必须包含 id 列")
    return cols


def realign_unique_values(
    conn: Connection,
    table: str,
    unique_col: str,
    rows: Sequence[Mapping[str, Any]],
) -> int:
    """If a local unique value belongs to a different id than remote, rename the local row."""
    remote_by_value = {
        str(row.get(unique_col) or ""): int(row["id"])
        for row in rows
        if str(row.get(unique_col) or "")
    }
    if not remote_by_value:
        return 0
    quoted_table = require_table(table)
    quoted_col = quote_ident(unique_col)
    local_rows = conn.execute(text(f"SELECT id, {quoted_col} AS uk FROM {quoted_table}")).mappings().all()
    changed = 0
    for local in local_rows:
        value = str(local["uk"] or "")
        remote_id = remote_by_value.get(value)
        if remote_id is None or remote_id == int(local["id"]):
            continue
        new_value = f"{value}__local{int(local['id'])}"
        conn.execute(
            text(f"UPDATE {quoted_table} SET {quoted_col} = :new_value WHERE id = :id"),
            {"new_value": new_value, "id": int(local["id"])},
        )
        changed += 1
    return changed


def quoted_columns(cols: Sequence[str]) -> str:
    return ", ".join(quote_ident(col) for col in cols)


def existing_ids(conn: Connection, table: str, ids: Iterable[int]) -> set[int]:
    id_list = sorted({int(item) for item in ids})
    if not id_list:
        return set()
    quoted = require_table(table)
    rows = conn.execute(
        text(f"SELECT id FROM {quoted} WHERE id IN ({', '.join(str(item) for item in id_list)})")
    ).all()
    return {int(row[0]) for row in rows}


def upsert_rows(
    conn: Connection,
    table: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    preserve: Sequence[str] = (),
) -> tuple[int, int]:
    if not rows:
        return 0, 0
    quoted = require_table(table)
    cols = shared_columns(table_columns(conn, table), rows)
    present = existing_ids(conn, table, (int(row["id"]) for row in rows))
    insert_sql = (
        f"INSERT INTO {quoted} ({quoted_columns(cols)}) "
        f"VALUES ({', '.join(f':{col}' for col in cols)})"
    )
    update_cols = [col for col in cols if col != "id"]
    inserted = 0
    updated = 0
    for row in rows:
        payload = {col: row.get(col) for col in cols}
        row_id = int(row["id"])
        if row_id in present:
            assignments = []
            params = {"id": row_id}
            for col in update_cols:
                if col in preserve:
                    continue
                assignments.append(f"{quote_ident(col)} = :{col}")
                params[col] = payload[col]
            if assignments:
                conn.execute(text(f"UPDATE {quoted} SET {', '.join(assignments)} WHERE id = :id"), params)
            updated += 1
            continue
        conn.execute(text(insert_sql), payload)
        inserted += 1
    return inserted, updated


def replace_table(conn: Connection, table: str, rows: Sequence[Mapping[str, Any]]) -> int:
    quoted = require_table(table)
    conn.execute(text(f"DELETE FROM {quoted}"))
    if not rows:
        return 0
    cols = shared_columns(table_columns(conn, table), rows)
    insert_sql = (
        f"INSERT INTO {quoted} ({quoted_columns(cols)}) "
        f"VALUES ({', '.join(f':{col}' for col in cols)})"
    )
    for start in range(0, len(rows), 200):
        chunk = rows[start:start + 200]
        conn.execute(text(insert_sql), [{col: row.get(col) for col in cols} for row in chunk])
    return len(rows)


def replace_children(
    conn: Connection,
    table: str,
    parent_col: str,
    rows: Sequence[Mapping[str, Any]],
    parent_ids: Sequence[int],
) -> int:
    quoted = require_table(table)
    quoted_parent = quote_ident(parent_col)
    if parent_ids:
        id_sql = ", ".join(str(int(item)) for item in parent_ids)
        conn.execute(text(f"DELETE FROM {quoted} WHERE {quoted_parent} IN ({id_sql})"))
    if not rows:
        return 0
    cols = shared_columns(table_columns(conn, table), rows)
    insert_sql = (
        f"INSERT INTO {quoted} ({quoted_columns(cols)}) "
        f"VALUES ({', '.join(f':{col}' for col in cols)})"
    )
    for start in range(0, len(rows), 200):
        chunk = rows[start:start + 200]
        conn.execute(text(insert_sql), [{col: row.get(col) for col in cols} for row in chunk])
    return len(rows)


def ensure_ims_contacts_table(local_conn: Connection, remote_conn: Connection) -> None:
    if "ims_contacts" in table_names(local_conn):
        return
    ddl = remote_conn.execute(text("SHOW CREATE TABLE `ims_contacts`")).first()
    if not ddl:
        raise SyncError("远端缺少 ims_contacts 表")
    local_conn.execute(text(str(ddl[1])))


def sync_master_data(local_engine: Engine, remote_engine: Engine, *, dry_run: bool) -> SyncReport:
    report = SyncReport(dry_run=dry_run)
    with remote_engine.connect() as remote_conn:
        remote_tables = table_names(remote_conn)
        required = set(UPSERT_TABLES) | set(REPLACE_TABLES) | set(CHILD_REPLACE)
        missing = sorted(table for table in required if table != "ims_contacts" and table not in remote_tables)
        if missing:
            raise SyncError(f"远端缺少表：{', '.join(missing)}")
        source = {table: fetch_rows(remote_conn, table) for table in required if table in remote_tables}
        ims_ddl_needed = "ims_contacts" in remote_tables

    if dry_run:
        with local_engine.connect() as local_conn:
            local_tables = table_names(local_conn)
            for table, rows in source.items():
                result = TableResult(table=table, source_rows=len(rows))
                if table not in local_tables:
                    result.inserted = len(rows)
                    report.add(result)
                    continue
                present = existing_ids(local_conn, table, (int(row["id"]) for row in rows)) if table in UPSERT_TABLES else set()
                if table in UPSERT_TABLES:
                    result.inserted = sum(1 for row in rows if int(row["id"]) not in present)
                    result.updated = len(rows) - result.inserted
                else:
                    result.replaced = len(rows)
                report.add(result)
        return report

    with local_engine.begin() as local_conn:
        with remote_engine.connect() as remote_conn:
            if ims_ddl_needed:
                ensure_ims_contacts_table(local_conn, remote_conn)
        try:
            local_conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table in UPSERT_TABLES:
                rows = source.get(table, [])
                unique_col = UNIQUE_REALIGN.get(table)
                realigned = realign_unique_values(local_conn, table, unique_col, rows) if unique_col else 0
                inserted, updated = upsert_rows(
                    local_conn,
                    table,
                    rows,
                    preserve=PRESERVE_EXISTING.get(table, ()),
                )
                bump_autoincrement(local_conn, table)
                report.add(TableResult(table, len(rows), inserted, updated, realigned=realigned))
            for table in REPLACE_TABLES:
                rows = source.get(table, [])
                if table not in table_names(local_conn):
                    continue
                unique_col = UNIQUE_REALIGN.get(table)
                realigned = realign_unique_values(local_conn, table, unique_col, rows) if unique_col else 0
                replaced = replace_table(local_conn, table, rows)
                if table != "ims_contacts":
                    bump_autoincrement(local_conn, table)
                report.add(TableResult(table, len(rows), replaced=replaced, realigned=realigned))
            project_ids = [int(row["id"]) for row in source.get("projects", [])]
            for table, parent_col in CHILD_REPLACE.items():
                rows = source.get(table, [])
                replaced = replace_children(local_conn, table, parent_col, rows, project_ids)
                bump_autoincrement(local_conn, table)
                report.add(TableResult(table, len(rows), replaced=replaced))
            local_conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        except Exception:
            local_conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            raise
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从远端 MariaDB 同步通讯录和项目信息到本地")
    parser.add_argument("--apply", action="store_true", help="实际写入本地；默认只预演")
    parser.add_argument("--local-url", default="", help="本地 mariadb+pymysql URL")
    parser.add_argument("--remote-url", default="", help="远端 mariadb+pymysql URL")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    local_url = require_mariadb_url(args.local_url or default_local_url(), LOCAL_URL_ENV)
    remote_url = require_mariadb_url(args.remote_url or default_remote_url(), REMOTE_URL_ENV)
    local_engine = create_engine(local_url, future=True, pool_pre_ping=True)
    remote_engine = create_engine(remote_url, future=True, pool_pre_ping=True)
    report = sync_master_data(local_engine, remote_engine, dry_run=not args.apply)
    mode = "预演" if report.dry_run else "已写入"
    print(f"{mode} 通讯录/项目主数据同步")
    for item in report.tables:
        print(
            f"  {item.table}: 远端 {item.source_rows} 行，"
            f"新增 {item.inserted}，更新 {item.updated}，替换 {item.replaced}，改名 {item.realigned}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
