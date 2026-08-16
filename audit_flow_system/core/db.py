from __future__ import annotations

import os
from typing import Any, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL


engine_args: dict[str, Any] = {
    "future": True,
    "pool_pre_ping": True,
    "pool_size": int(os.getenv("AUDIT_FLOW_DB_POOL_SIZE", "5")),
    "max_overflow": int(os.getenv("AUDIT_FLOW_DB_MAX_OVERFLOW", "10")),
    "pool_recycle": int(os.getenv("AUDIT_FLOW_DB_POOL_RECYCLE", "26600")),
}

engine = create_engine(DATABASE_URL, **engine_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_database_exists() -> None:
    url = make_url(DATABASE_URL)
    if url.get_backend_name() != "mariadb" or not url.database:
        raise RuntimeError("本系统只支持 MariaDB，请使用 mariadb+pymysql 数据库 URL")
    server_url = URL.create(
        drivername=url.drivername,
        username=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        query=dict(url.query),
    )
    server_engine = create_engine(server_url, future=True, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    database_name = "`" + url.database.replace("`", "``") + "`"
    try:
        with server_engine.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS {database_name} "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        server_engine.dispose()


def safe_database_label() -> str:
    try:
        return make_url(DATABASE_URL).render_as_string(hide_password=True)
    except Exception:
        return DATABASE_URL
