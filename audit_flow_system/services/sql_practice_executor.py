from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import os
import re
import time
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import create_engine

from ..core.config import require_mariadb_url
from .sql_practice_validator import _mask_literals, validate_practice_sql


DEFAULT_RESULT_LIMIT = 50
MAX_RESULT_LIMIT = 1000
MAX_QUERY_SECONDS = 8
_practice_engine = None


def _engine():
    global _practice_engine
    database_url = os.getenv("AUDIT_FLOW_PRACTICE_DB_URL", "").strip()
    if not database_url:
        raise HTTPException(status_code=503, detail="练习查询连接尚未配置，请联系管理员")
    if _practice_engine is None:
        _practice_engine = create_engine(
            require_mariadb_url(database_url),
            future=True,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            pool_recycle=1800,
        )
    return _practice_engine


def _normalized_sql(sql: str) -> tuple[str, str]:
    raw = (sql or "").strip().rstrip(";").strip()
    masked, _errors = _mask_literals(raw)
    normalized = re.sub(r"\s+", " ", masked).strip().lower()
    return raw, normalized


def _ensure_database_scope(sql: str, rules: dict[str, Any]) -> None:
    raw, normalized = _normalized_sql(sql)
    allowed = {str(item).strip().lower() for item in rules.get("allowed_databases", []) if str(item).strip()}
    if not allowed:
        raise HTTPException(status_code=400, detail="本题未配置可查询数据库，不能在线运行")
    if re.search(r"\b(information_schema|performance_schema|mysql|sys)\s*\.", normalized):
        raise HTTPException(status_code=400, detail="禁止查询系统数据库")
    if re.search(r"\b(load_file|sleep|benchmark|get_lock|release_lock)\s*\(", normalized) or "@@" in normalized:
        raise HTTPException(status_code=400, detail="查询包含练习环境禁止使用的函数或变量")

    qualified = {
        match.lower()
        for match in re.findall(r"`?([a-zA-Z_][\w]*)`?\s*\.\s*`?[a-zA-Z_\u4e00-\u9fff][\w\u4e00-\u9fff]*`?", raw)
    }
    outside = sorted(qualified - allowed)
    if outside:
        raise HTTPException(status_code=400, detail="引用了题目范围外的数据库：" + "、".join(outside))

    cte_names = {
        item.lower()
        for item in re.findall(r"(?:\bwith|,)\s*`?([a-zA-Z_][\w]*)`?\s+as\s*\(", normalized)
    }
    first = (re.match(r"([a-z]+)", normalized) or [None, ""])[1]
    if first != "show":
        for token in re.findall(r"\b(?:from|join)\s+([^\s,()]+)", normalized):
            clean = token.replace("`", "").strip()
            if clean in cte_names:
                continue
            if "." not in clean:
                raise HTTPException(status_code=400, detail=f"在线查询必须使用 数据库.表名，未限定：{clean}")
            database = clean.split(".", 1)[0]
            if database not in allowed:
                raise HTTPException(status_code=400, detail=f"数据库 {database} 不在本题范围内")
    if first in {"describe", "desc"}:
        target = re.match(r"(?:describe|desc)\s+([^\s]+)", normalized)
        if not target or "." not in target.group(1).replace("`", ""):
            raise HTTPException(status_code=400, detail="DESCRIBE在线查询必须使用 数据库.表名")
    if first == "show":
        show_match = re.match(r"show\s+tables\s+(?:from|in)\s+`?([a-zA-Z_][\w]*)`?", normalized)
        if not show_match or show_match.group(1).lower() not in allowed:
            raise HTTPException(status_code=400, detail="SHOW仅支持 SHOW TABLES FROM 题目数据库")


def _limit_value(normalized: str) -> Optional[int]:
    match = re.search(r"\blimit\s+(?:\d+\s*,\s*)?(\d+)\s*$", normalized)
    return int(match.group(1)) if match else None


def _execution_sql(sql: str, rules: dict[str, Any]) -> tuple[str, int, bool]:
    raw, normalized = _normalized_sql(sql)
    configured = rules.get("default_limit", DEFAULT_RESULT_LIMIT)
    default_limit = DEFAULT_RESULT_LIMIT if configured is None else int(configured)
    default_limit = max(1, min(default_limit, MAX_RESULT_LIMIT))
    explicit_limit = _limit_value(normalized)
    first = (re.match(r"([a-z]+)", normalized) or [None, ""])[1]
    append_limit = explicit_limit is None and first in {"select", "with", "explain"}
    executed_sql = f"{raw} LIMIT {default_limit}" if append_limit else raw
    row_limit = explicit_limit if explicit_limit is not None else default_limit
    row_limit = max(1, min(row_limit, MAX_RESULT_LIMIT))
    return executed_sql, row_limit, append_limit


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 5000 else value[:5000] + "…[已截断]"
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def execute_practice_sql(sql: str, rules: dict[str, Any]) -> dict[str, Any]:
    if rules.get("query_enabled") is not True:
        raise HTTPException(status_code=400, detail="本题未开放在线查询")
    validation = validate_practice_sql(sql, rules)
    if not validation["passed"]:
        raise HTTPException(status_code=400, detail={"message": "SQL静态校验未通过", "validation": validation})
    _ensure_database_scope(sql, rules)
    executed_sql, row_limit, limit_applied = _execution_sql(sql, rules)
    started = time.monotonic()
    raw_connection = None
    cursor = None
    try:
        raw_connection = _engine().raw_connection()
        cursor = raw_connection.cursor()
        cursor.execute(f"SET SESSION max_statement_time = {MAX_QUERY_SECONDS}")
        cursor.execute("START TRANSACTION READ ONLY")
        cursor.execute(executed_sql)
        columns = [str(item[0]) for item in (cursor.description or [])]
        values = cursor.fetchmany(row_limit + 1) if cursor.description else []
        truncated = len(values) > row_limit
        values = values[:row_limit]
        rows = [[_json_value(value) for value in row] for row in values]
        raw_connection.rollback()
    except HTTPException:
        if raw_connection is not None:
            raw_connection.rollback()
        raise
    except Exception as exc:
        if raw_connection is not None:
            raw_connection.rollback()
        message = str(exc).replace(os.getenv("AUDIT_FLOW_PRACTICE_DB_URL", ""), "[练习数据库]")
        raise HTTPException(status_code=400, detail=f"查询失败：{message[:500]}") from exc
    finally:
        if cursor is not None:
            cursor.close()
        if raw_connection is not None:
            raw_connection.close()
    return {
        "executedSql": executed_sql,
        "limitApplied": limit_applied,
        "rowLimit": row_limit,
        "columns": columns,
        "rows": rows,
        "rowCount": len(rows),
        "truncated": truncated,
        "durationMs": round((time.monotonic() - started) * 1000),
    }
