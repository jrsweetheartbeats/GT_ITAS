from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.engine import URL, make_url

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = BASE_DIR.parent
DEEPSEEK_LOCAL_CONFIG_PATH = BASE_DIR / "deepseek.local.json"
PROJECTS_ROOT = Path(
    os.getenv("AUDIT_FLOW_PROJECTS_ROOT", str(WORKSPACE_ROOT / "项目文件"))
).expanduser()
TRAINING_SUBMISSIONS_ROOT = BASE_DIR / "data" / "training_submissions"


def is_production_environment() -> bool:
    return os.getenv("AUDIT_FLOW_ENV", "development").strip().lower() in {"production", "prod"}


def initial_admin_password(*, required: bool = False) -> str:
    password = os.getenv("AUDIT_FLOW_INITIAL_ADMIN_PASSWORD", "")
    if required and not password:
        raise RuntimeError("生产环境必须设置 AUDIT_FLOW_INITIAL_ADMIN_PASSWORD")
    return password


def session_ttl_minutes() -> int:
    raw = os.getenv("AUDIT_FLOW_SESSION_TTL_MINUTES", "480")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("AUDIT_FLOW_SESSION_TTL_MINUTES 必须是整数") from exc
    if not 5 <= value <= 10080:
        raise RuntimeError("AUDIT_FLOW_SESSION_TTL_MINUTES 必须在 5 至 10080 分钟之间")
    return value


def cors_settings() -> tuple[list[str], str | None]:
    """Use local origins by default; deployments must list trusted origins explicitly."""
    configured = os.getenv("AUDIT_FLOW_CORS_ORIGINS", "").strip()
    if not configured:
        return [], r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$"
    origins = [item.strip().rstrip("/") for item in configured.split(",") if item.strip()]
    if not origins or "*" in origins:
        raise RuntimeError("AUDIT_FLOW_CORS_ORIGINS 必须列出明确的可信来源，不能使用 *")
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
            raise RuntimeError("AUDIT_FLOW_CORS_ORIGINS 必须是以逗号分隔的 HTTP(S) 来源")
    return origins, None


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    api_url: str
    model: str
    timeout_seconds: int = 120
    max_input_chars: int = 60000
    max_output_tokens: int = 4096


def _positive_int(payload: dict[str, Any], key: str, default: int) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"DeepSeek 配置项 {key} 必须是正整数") from exc
    if value <= 0:
        raise RuntimeError(f"DeepSeek 配置项 {key} 必须是正整数")
    return value


def load_deepseek_config(*, required: bool = True) -> DeepSeekConfig | None:
    """Read the local DeepSeek config without placing secrets in the database."""
    path = Path(os.getenv("AUDIT_FLOW_DEEPSEEK_CONFIG", str(DEEPSEEK_LOCAL_CONFIG_PATH))).expanduser()
    if not path.is_file():
        if required:
            raise RuntimeError(f"DeepSeek 尚未配置，请创建本地配置文件：{path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DeepSeek 本地配置不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("DeepSeek 本地配置必须是 JSON 对象")
    api_key = str(payload.get("api_key") or "").strip()
    api_url = str(payload.get("api_url") or "https://api.deepseek.com/chat/completions").strip()
    model = str(payload.get("model") or "deepseek-v4-flash").strip()
    parsed_url = urlparse(api_url)
    if not api_key:
        raise RuntimeError("DeepSeek 本地配置缺少 api_key")
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise RuntimeError("DeepSeek api_url 必须是有效的 HTTPS 地址")
    if not model:
        raise RuntimeError("DeepSeek 本地配置缺少 model")
    return DeepSeekConfig(
        api_key=api_key,
        api_url=api_url,
        model=model,
        timeout_seconds=_positive_int(payload, "timeout_seconds", 120),
        max_input_chars=_positive_int(payload, "max_input_chars", 60000),
        max_output_tokens=_positive_int(payload, "max_output_tokens", 4096),
    )


def deepseek_config_status() -> dict[str, Any]:
    """Return non-secret configuration metadata suitable for an API response."""
    try:
        config = load_deepseek_config(required=False)
    except RuntimeError as exc:
        return {"configured": False, "error": str(exc)}
    if config is None:
        return {"configured": False, "error": "尚未创建本地配置文件"}
    return {
        "configured": True,
        "model": config.model,
        "api_host": urlparse(config.api_url).hostname or "",
    }


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
        username=os.getenv("AUDIT_FLOW_DB_USER", "root"),
        password=os.getenv("AUDIT_FLOW_DB_PASSWORD", "") or None,
        host=os.getenv("AUDIT_FLOW_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("AUDIT_FLOW_DB_PORT", "3306")),
        database=os.getenv("AUDIT_FLOW_DB_NAME", "ITAS"),
        query=query,
    )
    return require_mariadb_url(url.render_as_string(hide_password=False))


DATABASE_URL = build_database_url()
