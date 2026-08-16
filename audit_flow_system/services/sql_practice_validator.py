from __future__ import annotations

import re
from typing import Any, Optional


ALLOWED_START = {"select", "show", "describe", "desc", "explain", "with"}
FORBIDDEN_WORDS = {
    "alter", "analyze", "call", "create", "delete", "do", "drop", "grant",
    "handler", "insert", "kill", "load", "lock", "optimize", "rename",
    "repair", "replace", "revoke", "set", "truncate", "unlock", "update", "use",
}


def _mask_literals(sql: str) -> tuple[str, list[str]]:
    output: list[str] = []
    errors: list[str] = []
    index = 0
    quote = ""
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == "\\" and index + 1 < len(sql):
                output.extend("  ")
                index += 2
                continue
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.extend("  ")
                    index += 2
                    continue
                quote = ""
            output.append(" ")
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            output.append(" ")
        else:
            output.append(char)
        index += 1
    if quote:
        errors.append("字符串引号未闭合")
    return "".join(output), errors


def _balanced_parentheses(masked_sql: str) -> bool:
    depth = 0
    for char in masked_sql:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def validate_practice_sql(sql: str, rules: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    rules = rules or {}
    raw = (sql or "").strip()
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    if not raw:
        return {"passed": False, "errors": ["SQL不能为空"], "warnings": [], "checks": []}
    if len(raw) > 50000:
        errors.append("SQL超过50000字符限制")

    comment_tokens = [token for token in ("--", "#", "/*", "*/") if token in raw]
    if comment_tokens:
        errors.append("练习SQL不允许包含注释，以防止隐藏或绕过校验")
    masked, literal_errors = _mask_literals(raw)
    errors.extend(literal_errors)
    normalized = re.sub(r"\s+", " ", masked).strip().lower()
    if not _balanced_parentheses(masked):
        errors.append("括号不配对")

    semicolons = [match.start() for match in re.finditer(r";", masked)]
    if len(semicolons) > 1 or (semicolons and masked[semicolons[0] + 1 :].strip()):
        errors.append("一次只能提交一条SQL语句")
    normalized = normalized.rstrip(";").strip()
    first = (re.match(r"([a-z]+)", normalized) or [None, ""])[1]
    if first not in ALLOWED_START:
        errors.append("只允许SELECT、WITH、SHOW、DESCRIBE/DESC或EXPLAIN只读语句")
    if first == "with" and not re.search(r"\bselect\b", normalized):
        errors.append("WITH语句必须以SELECT查询为主体")

    words = set(re.findall(r"\b[a-z_]+\b", normalized))
    found_forbidden = sorted(words & FORBIDDEN_WORDS)
    if found_forbidden:
        errors.append("包含禁止关键字：" + "、".join(found_forbidden))
    if re.search(r"\binto\s+(out|dump)file\b", normalized):
        errors.append("禁止使用INTO OUTFILE或INTO DUMPFILE")
    if re.search(r"\bselect\s+.*\binto\b", normalized):
        errors.append("禁止使用SELECT INTO写出数据")

    allowed_databases = [str(item).lower() for item in rules.get("allowed_databases", [])]
    if allowed_databases:
        references = {
            match.lower()
            for match in re.findall(
                r"(?:\bfrom|\bjoin|\bdescribe|\bdesc)\s+`?([a-zA-Z_][\w]*)`?\s*\.\s*`?[\w\u4e00-\u9fff]+`?",
                masked,
                flags=re.IGNORECASE,
            )
        }
        outside = sorted(ref for ref in references if ref not in allowed_databases)
        if outside:
            errors.append("引用了题目范围外的数据库：" + "、".join(outside))
        checks.append({"name": "数据库范围", "passed": not outside, "detail": "允许：" + "、".join(allowed_databases)})

    required_keywords = [str(item).lower() for item in rules.get("required_keywords", [])]
    missing_keywords = [item for item in required_keywords if not re.search(rf"\b{re.escape(item)}\b", normalized)]
    if missing_keywords:
        errors.append("缺少题目要求的关键字：" + "、".join(missing_keywords))

    required_tables = [str(item).lower() for item in rules.get("required_tables", [])]
    missing_tables = [item for item in required_tables if item not in normalized.replace("`", "")]
    if missing_tables:
        errors.append("缺少题目要求的表：" + "、".join(missing_tables))

    if rules.get("require_where") and not re.search(r"\bwhere\b", normalized):
        errors.append("本题要求使用WHERE限定范围")
    if rules.get("forbid_select_star") and re.search(r"\bselect\s+(?:distinct\s+)?\*", normalized):
        errors.append("本题禁止SELECT *，请明确列出所需字段")

    required_select_columns = [str(item).strip().lower() for item in rules.get("required_select_columns", []) if str(item).strip()]
    if required_select_columns:
        select_match = re.search(r"\bselect\s+(.*?)\s+\bfrom\b", masked.lower().replace("`", ""), flags=re.DOTALL)
        select_clause = select_match.group(1) if select_match else ""
        missing_columns = [item for item in required_select_columns if item not in select_clause]
        if missing_columns:
            errors.append("SELECT缺少题目要求的字段：" + "、".join(missing_columns))
        checks.append({"name": "指定返回字段", "passed": not missing_columns, "detail": "、".join(required_select_columns)})

    required_equalities = rules.get("required_equalities", {})
    missing_equalities = []
    for field, expected in required_equalities.items():
        pattern = rf"`?{re.escape(str(field).lower())}`?\s*=\s*{re.escape(str(expected).lower())}(?![\w.])"
        if not re.search(pattern, normalized):
            missing_equalities.append(f"{field}={expected}")
    if missing_equalities:
        errors.append("WHERE缺少指定条件：" + "、".join(missing_equalities))
    if required_equalities:
        checks.append({"name": "指定筛选条件", "passed": not missing_equalities, "detail": "、".join(f"{key}={value}" for key, value in required_equalities.items())})

    if rules.get("require_limit"):
        limit_match = re.search(r"\blimit\s+(?:(\d+)\s*,\s*)?(\d+)\b", normalized)
        if not limit_match:
            errors.append("本题明细查询必须包含数值LIMIT")
        else:
            limit_value = int(limit_match.group(2))
            max_limit = int(rules.get("max_limit", 1000))
            if limit_value > max_limit:
                errors.append(f"LIMIT不得超过{max_limit}")
            exact_limit = rules.get("exact_limit")
            if exact_limit is not None and limit_value != int(exact_limit):
                errors.append(f"本题要求使用LIMIT {int(exact_limit)}")
            checks.append({"name": "结果行数限制", "passed": limit_value <= max_limit and (exact_limit is None or limit_value == int(exact_limit)), "detail": f"LIMIT {limit_value}"})

    if first in {"select", "with"} and not re.search(r"\bfrom\b", normalized):
        warnings.append("未发现FROM，请确认是否为题目所需的常量查询")
    passed = not errors
    checks.insert(0, {"name": "只读与单语句", "passed": not any("只允许" in item or "禁止" in item or "一条" in item for item in errors), "detail": "不会连接或执行SQL"})
    return {"passed": passed, "errors": errors, "warnings": warnings, "checks": checks}


def validate_practice_result(result: dict[str, Any], rules: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    rules = rules or {}
    columns = [str(item) for item in result.get("columns", [])]
    rows = result.get("rows", []) or []
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    expected_values = rules.get("expected_result_values", {})
    missing_columns = [str(item) for item in expected_values if str(item) not in columns]
    if missing_columns:
        errors.append("查询结果缺少校验字段：" + "、".join(missing_columns))
    checks.append({"name": "结果字段", "passed": not missing_columns, "detail": "、".join(columns)})
    if rules.get("require_nonempty_result") and not rows:
        errors.append("查询结果为空，请检查筛选条件")
    checks.append({"name": "结果非空", "passed": bool(rows) or not rules.get("require_nonempty_result"), "detail": f"返回{len(rows)}行"})
    mismatches: list[str] = []
    if not missing_columns:
        for field, expected in expected_values.items():
            index = columns.index(str(field))
            if any(str(row[index]) != str(expected) for row in rows):
                mismatches.append(f"{field}应全部等于{expected}")
    if mismatches:
        errors.append("查询结果不符合题目条件：" + "、".join(mismatches))
    if expected_values:
        checks.append({"name": "结果值核对", "passed": not mismatches and not missing_columns, "detail": "、".join(f"{key}={value}" for key, value in expected_values.items())})
    return {"passed": not errors, "errors": errors, "warnings": [], "checks": checks}
