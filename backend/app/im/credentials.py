"""IM 频道凭证的加解密边界。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken


class CredentialKeyError(RuntimeError):
    pass


def _fernet() -> Fernet:
    raw = os.environ.get("IM_CREDENTIAL_KEY", "").strip()
    if not raw:
        raise CredentialKeyError("启用外部 IM 前必须配置独立的 IM_CREDENTIAL_KEY")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise CredentialKeyError("IM_CREDENTIAL_KEY 必须是有效的 Fernet 密钥") from exc


def encrypt_secret(value: str) -> str:
    if not value:
        raise ValueError("凭证不能为空")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialKeyError("IM 凭证无法解密，请检查密钥是否匹配") from exc


@dataclass(frozen=True, slots=True)
class ChannelCredential:
    channel_id: str
    app_id: str
    tenant_key: str
    app_secret: str = field(repr=False)
    verification_token: str | None = field(default=None, repr=False)
    encrypt_key: str | None = field(default=None, repr=False)
