from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine import URL, make_url

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = BASE_DIR.parent


def require_mariadb_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() != "mariadb":
        raise RuntimeError("本系统只支持 MariaDB，请使用 mariadb+pymysql 数据库 URL")
    return database_url


def build_database_url() -> str:
    explicit = os.getenv("AUDIT_FLOW_DB_URL")
    if explicit:
        return require_mariadb_url(explicit)
    query = {
        "charset": os.getenv("AUDIT_FLOW_DB_CHARSET", "utf8mb4"),
        "connect_timeout": os.getenv("AUDIT_FLOW_DB_CONNECT_TIMEOUT", "10"),
        "read_timeout": os.getenv("AUDIT_FLOW_DB_READ_TIMEOUT", "30000"),
        "write_timeout": os.getenv("AUDIT_FLOW_DB_WRITE_TIMEOUT", "30000"),
    }
    url = URL.create(
        drivername=os.getenv("AUDIT_FLOW_DB_DRIVER", "mariadb+pymysql"),
        username=os.getenv("AUDIT_FLOW_DB_USER", "itas_user"),
        password=os.getenv("AUDIT_FLOW_DB_PASSWORD") or None,
        host=os.getenv("AUDIT_FLOW_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("AUDIT_FLOW_DB_PORT", "3306")),
        database=os.getenv("AUDIT_FLOW_DB_NAME", "ITA"),
        query=query,
    )
    return require_mariadb_url(url.render_as_string(hide_password=False))


DATABASE_URL = build_database_url()
