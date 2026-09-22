"""将会话/记忆主体与平台授权主体明确分离。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActorContext:
    """一次外部消息执行时使用的身份上下文。

    ``subject_id`` 决定会话与长期记忆归属；``authorization_user_id`` 决定
    UniEmployee 平台权限。首版外部身份的后者必须为 ``None``。
    """

    subject_id: str
    authorization_user_id: str | None
    provider: str
    app_id: str
    tenant_key: str
    sender_open_id: str
    chat_id: str
    chat_type: str

    @classmethod
    def isolated(
        cls,
        *,
        provider: str,
        app_id: str,
        tenant_key: str,
        sender_open_id: str,
        chat_id: str,
        chat_type: str,
    ) -> "ActorContext":
        """构造不做平台账号映射的外部身份上下文（任意 IM Provider 通用）。"""
        if not all((provider, app_id, tenant_key, sender_open_id, chat_id)):
            raise ValueError("外部身份字段不能为空")
        if chat_type not in {"p2p", "group"}:
            raise ValueError(f"不支持的 chat_type: {chat_type!r}")
        # 单聊和群聊都以 chat_id 为记忆边界；群聊因此天然全群共享。
        # subject_id 会被运行时用于 Store namespace 和本地工作目录。
        # 使用不可逆、确定且跨平台安全的标识，避免 Windows 路径中的冒号，
        # 同时不把 IM 组织、应用和会话标识暴露到文件系统目录名中。
        scope_material = "\0".join((provider, app_id, tenant_key, chat_id))
        subject_id = f"im_{provider}_" + hashlib.sha256(
            scope_material.encode("utf-8")
        ).hexdigest()
        return cls(
            subject_id=subject_id,
            authorization_user_id=None,
            provider=provider,
            app_id=app_id,
            tenant_key=tenant_key,
            sender_open_id=sender_open_id,
            chat_id=chat_id,
            chat_type=chat_type,
        )

    @classmethod
    def isolated_feishu(
        cls,
        *,
        app_id: str,
        tenant_key: str,
        sender_open_id: str,
        chat_id: str,
        chat_type: str,
    ) -> "ActorContext":
        return cls.isolated(
            provider="feishu",
            app_id=app_id,
            tenant_key=tenant_key,
            sender_open_id=sender_open_id,
            chat_id=chat_id,
            chat_type=chat_type,
        )
