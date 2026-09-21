"""Send password-reset verification codes by company email."""
from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import logging
import os
import re
import smtplib
import ssl

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailError(RuntimeError):
    """Raised when a verification email cannot be delivered."""


@dataclass(frozen=True)
class MailResult:
    provider: str
    debug_code: str = ""


def normalize_email(value: str) -> str:
    return str(value or "").strip()


def mask_email(value: str) -> str:
    text = normalize_email(value)
    if "@" not in text:
        return ""
    local, _, domain = text.partition("@")
    if len(local) <= 2:
        shown = f"{local[:1]}*"
    else:
        shown = f"{local[:2]}***"
    return f"{shown}@{domain}"


def smtp_configured() -> bool:
    return bool(os.getenv("AUDIT_FLOW_SMTP_HOST") and os.getenv("AUDIT_FLOW_SMTP_USER") and os.getenv("AUDIT_FLOW_SMTP_PASSWORD"))


def send_verification_email(to_address: str, code: str, *, display_name: str = "") -> MailResult:
    recipient = normalize_email(to_address)
    if not EMAIL_RE.fullmatch(recipient):
        raise MailError("邮箱地址格式不正确")
    if not smtp_configured():
        logger.warning("password reset code for %s is %s (SMTP not configured)", mask_email(recipient), code)
        return MailResult(provider="console", debug_code=code)
    host = os.getenv("AUDIT_FLOW_SMTP_HOST", "").strip()
    port = int(os.getenv("AUDIT_FLOW_SMTP_PORT", "587"))
    user = os.getenv("AUDIT_FLOW_SMTP_USER", "").strip()
    password = os.getenv("AUDIT_FLOW_SMTP_PASSWORD", "")
    sender = os.getenv("AUDIT_FLOW_SMTP_FROM", user).strip() or user
    starttls = os.getenv("AUDIT_FLOW_SMTP_STARTTLS", "1") not in {"0", "false", "FALSE", "no"}
    verify = os.getenv("AUDIT_FLOW_SMTP_TLS_VERIFY", "0") not in {"0", "false", "FALSE", "no"}
    greeting = display_name.strip() or "同事"
    message = EmailMessage()
    message["Subject"] = "ITAS 密码重置验证码"
    message["From"] = f"ITAS <{sender}>"
    message["To"] = recipient
    message.set_content(
        f"{greeting}，您好：\n\n"
        f"您正在重置 ITAS 登录密码。验证码为：{code}\n"
        "5 分钟内有效，请勿转发给他人。\n"
        "如非本人操作，请忽略本邮件。\n"
    )
    context = ssl.create_default_context() if verify else ssl._create_unverified_context()
    try:
        with smtplib.SMTP(host, port, timeout=20) as client:
            client.ehlo()
            if starttls:
                client.starttls(context=context)
                client.ehlo()
            client.login(user, password)
            client.send_message(message)
    except Exception as exc:
        raise MailError(f"验证码邮件发送失败：{exc}") from exc
    return MailResult(provider="smtp")
