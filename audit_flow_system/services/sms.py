"""Send login/reset verification codes to a staff mobile number."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

logger = logging.getLogger(__name__)

MOBILE_RE = re.compile(r"^1[3-9]\d{9}$")


class SmsError(RuntimeError):
    """Raised when a verification SMS cannot be delivered."""


@dataclass(frozen=True)
class SmsResult:
    provider: str
    debug_code: str = ""


def normalize_cn_mobile(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits


def mask_mobile(value: str) -> str:
    phone = normalize_cn_mobile(value)
    if not MOBILE_RE.fullmatch(phone):
        return ""
    return f"{phone[:3]}****{phone[-4:]}"


def sms_provider() -> str:
    return (os.getenv("AUDIT_FLOW_SMS_PROVIDER") or "console").strip().lower()


def send_verification_sms(phone: str, code: str) -> SmsResult:
    provider = sms_provider()
    mobile = normalize_cn_mobile(phone)
    if not MOBILE_RE.fullmatch(mobile):
        raise SmsError("手机号格式不正确")
    if provider in {"console", "log", "dev"}:
        logger.warning("password reset code for %s is %s (console SMS provider)", mask_mobile(mobile), code)
        return SmsResult(provider="console", debug_code=code)
    if provider == "aliyun":
        _send_aliyun_sms(mobile, code)
        return SmsResult(provider="aliyun")
    raise SmsError("未配置可用的短信服务")


def _percent_encode(value: str) -> str:
    return quote(str(value), safe="-_.~")


def _send_aliyun_sms(phone: str, code: str) -> None:
    access_key = os.getenv("ALIYUN_ACCESS_KEY_ID") or os.getenv("AUDIT_FLOW_ALIYUN_ACCESS_KEY_ID") or ""
    secret = os.getenv("ALIYUN_ACCESS_KEY_SECRET") or os.getenv("AUDIT_FLOW_ALIYUN_ACCESS_KEY_SECRET") or ""
    sign_name = os.getenv("AUDIT_FLOW_ALIYUN_SMS_SIGN_NAME") or ""
    template_code = os.getenv("AUDIT_FLOW_ALIYUN_SMS_TEMPLATE_CODE") or ""
    if not access_key or not secret or not sign_name or not template_code:
        raise SmsError("阿里云短信未配置完整：需要 AccessKey、签名和模板编号")
    params: dict[str, Any] = {
        "AccessKeyId": access_key,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone,
        "RegionId": os.getenv("AUDIT_FLOW_ALIYUN_SMS_REGION", "cn-hangzhou"),
        "SignName": sign_name,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid4().hex,
        "SignatureVersion": "1.0",
        "TemplateCode": template_code,
        "TemplateParam": json.dumps({"code": code}, ensure_ascii=False),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    canonical = "&".join(f"{_percent_encode(key)}={_percent_encode(params[key])}" for key in sorted(params))
    string_to_sign = f"GET&{_percent_encode('/')}&{_percent_encode(canonical)}"
    signature = hmac.new(f"{secret}&".encode("utf-8"), string_to_sign.encode("utf-8"), sha1).digest()
    params["Signature"] = base64.b64encode(signature).decode("ascii")
    url = "https://dysmsapi.aliyuncs.com/?" + urlencode(params)
    request = Request(url, method="GET")
    with urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if str(payload.get("Code") or "") != "OK":
        raise SmsError(str(payload.get("Message") or "短信发送失败"))
