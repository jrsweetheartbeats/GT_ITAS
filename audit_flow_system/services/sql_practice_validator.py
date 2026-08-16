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

    if rules.get("require_limit"):
        limit_match = re.search(r"\blimit\s+(?:(\d+)\s*,\s*)?(\d+)\b", normalized)
        if not limit_match:
            errors.append("本题明细查询必须包含数值LIMIT")
        else:
            limit_value = int(limit_match.group(2))
            max_limit = int(rules.get("max_limit", 1000))
            if limit_value > max_limit:
                errors.append(f"LIMIT不得超过{max_limit}")
            checks.append({"name": "结果行数限制", "passed": limit_value <= max_limit, "detail": f"LIMIT {limit_value}"})

    if first in {"select", "with"} and not re.search(r"\bfrom\b", normalized):
        warnings.append("未发现FROM，请确认是否为题目所需的常量查询")
    passed = not errors
    checks.insert(0, {"name": "只读与单语句", "passed": not any("只允许" in item or "禁止" in item or "一条" in item for item in errors), "detail": "不会连接或执行SQL"})
    return {"passed": passed, "errors": errors, "warnings": warnings, "checks": checks}
