from __future__ import annotations

import os
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from ..core.db import engine
from ..core.security import hash_password, validate_password_policy
from ..models import LoginSession, User


PROTECTED_DB_USERS = {"root", "mysql", "mariadb.sys", "itas_practice", "sa"}
_IDENT_RE = re.compile(r"^[A-Za-z0-9_.:%-]+$")
SQL_LOGIN_ALIASES = {
    "ita_cyx": ("chenyixi",),
    "ita_kzj": ("kezhijiang",),
    "ita_wyx": ("wangyongxuan",),
}


def _safe_ident(value: str, *, label: str) -> str:
    ident = str(value or "").strip()
    if not _IDENT_RE.fullmatch(ident):
        raise HTTPException(status_code=400, detail=f"{label}格式无效")
    return ident


def _sql_literal(value: str) -> str:
    return "N'" + str(value).replace("'", "''") + "'"


def _bracket(value: str) -> str:
    return "[" + str(value).replace("]", "]]") + "]"


def _mysql_quote(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def sync_mariadb_password(username: str, password: str) -> list[str]:
    """Update matching MariaDB accounts so personal/practice databases keep the same password."""
    account = _safe_ident(username, label="账号")
    if account.lower() in PROTECTED_DB_USERS:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT User, Host FROM mysql.user WHERE User = :username"),
            {"username": account},
        ).all()
    if not rows:
        return []

    synced: list[str] = []
    quoted_password = _mysql_quote(password)
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            for user, host in rows:
                safe_user = _safe_ident(user, label="数据库账号")
                safe_host = _safe_ident(host, label="数据库主机")
                cursor.execute(
                    f"ALTER USER `{safe_user}`@`{safe_host}` IDENTIFIED BY {quoted_password}"
                )
                synced.append(f"MariaDB {safe_user}@{safe_host}")
            cursor.execute("FLUSH PRIVILEGES")
        finally:
            cursor.close()
        raw.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步 MariaDB 账号密码失败：{exc}") from exc
    finally:
        raw.close()
    return synced


def _mssql_logins_to_update(username: str) -> list[str]:
    names = [username, *SQL_LOGIN_ALIASES.get(username, ())]
    unique: list[str] = []
    for name in names:
        ident = _safe_ident(name, label="SQL Server 账号")
        if ident.lower() in PROTECTED_DB_USERS:
            continue
        if ident not in unique:
            unique.append(ident)
    return unique


def sync_sqlserver_password(username: str, password: str) -> list[str]:
    """Update matching SQL Server logins used for practice and personal databases."""
    if os.getenv("AUDIT_FLOW_MSSQL_SYNC", "1").strip().lower() in {"0", "false", "no", "off"}:
        return []
    candidates = _mssql_logins_to_update(username)
    if not candidates:
        return []
    try:
        import pyodbc
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="未安装 pyodbc，无法同步 SQL Server 账号密码") from exc

    server = os.getenv("AUDIT_FLOW_MSSQL_SERVER", "127.0.0.1").strip() or "127.0.0.1"
    driver = os.getenv("AUDIT_FLOW_MSSQL_DRIVER", "SQL Server").strip() or "SQL Server"
    conn_str = f"DRIVER={{{driver}}};SERVER={server};Trusted_Connection=yes;"
    try:
        conn = pyodbc.connect(conn_str, autocommit=True, timeout=8)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"连接 SQL Server 失败：{exc}") from exc

    synced: list[str] = []
    try:
        cursor = conn.cursor()
        try:
            existing = {
                str(row[0])
                for row in cursor.execute("SELECT name FROM sys.sql_logins").fetchall()
            }
            for login_name in candidates:
                if login_name not in existing:
                    continue
                cursor.execute(
                    f"ALTER LOGIN {_bracket(login_name)} WITH PASSWORD = {_sql_literal(password)}"
                )
                synced.append(f"SQL Server {login_name}")
        finally:
            cursor.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步 SQL Server 账号密码失败：{exc}") from exc
    finally:
        conn.close()
    return synced


def set_user_password(
    db: Session,
    user: User,
    password: str,
    *,
    policy: dict[str, Any],
    invalidate_sessions: bool = True,
) -> list[str]:
    validate_password_policy(password, policy)
    synced = sync_mariadb_password(user.username, password)
    synced.extend(sync_sqlserver_password(user.username, password))
    user.password_hash = hash_password(password)
    if invalidate_sessions:
        db.execute(update(LoginSession).where(LoginSession.user_id == user.id).values(active=False))
    return synced


def find_active_user(db: Session, username: str) -> User | None:
    account = str(username or "").strip()
    if not account:
        return None
    return db.execute(select(User).where(User.username == account)).scalar_one_or_none()


def password_sync_message(synced: list[str]) -> str:
    if not synced:
        return "ITAS 密码已更新"
    return "ITAS 密码已更新，并已同步：" + "、".join(synced)
