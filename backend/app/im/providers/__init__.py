"""第三方 IM Provider 实现与 provider 注册表。

新增渠道时只需在这里登记一个实现类，Registry、路由和 Worker 都不需要改动。
"""

from __future__ import annotations

from typing import Any

from app.im.credentials import ChannelCredential
from .dingtalk import DingtalkProvider
from .feishu import FeishuProvider
from .wecom import WecomProvider

# provider 标识 -> 实现类。三个方法（connect / disconnect / send）语义统一。
PROVIDERS: dict[str, type] = {
    "feishu": FeishuProvider,
    "dingtalk": DingtalkProvider,
    "wecom": WecomProvider,
}

# 展示名，仅用于面向管理员的状态与错误文案。
PROVIDER_LABELS: dict[str, str] = {
    "feishu": "飞书",
    "dingtalk": "钉钉",
    "wecom": "企业微信",
}

# 页面与错误文案里展示的凭证字段名；三者字段语义相同（应用标识 + 密钥），
# 只是平台叫法不同。
CREDENTIAL_LABELS: dict[str, str] = {
    "feishu": "App ID/App Secret",
    "dingtalk": "Client ID/Client Secret",
    # 企微的「Bot ID / Secret」来自工作台「智能机器人 → 手工创建 → API 模式 → 长连接」，
    # 与「设置接收消息回调地址」模式下的 Token/EncodingAESKey 不是一回事。
    "wecom": "Bot ID/Secret",
}


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider)


def credential_label(provider: str) -> str:
    return CREDENTIAL_LABELS.get(provider, "凭证")


def supported_providers() -> frozenset[str]:
    """已实现凭证配置与长连接的 provider 集合。"""
    return frozenset(PROVIDERS)


def create_provider(
    provider: str,
    credential: ChannelCredential,
    *,
    on_message: Any,
    on_status: Any = None,
) -> Any:
    """按 provider 标识构造实现类；未登记的 provider 直接拒绝。"""
    try:
        factory = PROVIDERS[provider]
    except KeyError as exc:
        raise RuntimeError(f"尚未实现 {provider_label(provider)} 渠道的运行时长连接") from exc
    return factory(credential, on_message=on_message, on_status=on_status)


__all__ = [
    "CREDENTIAL_LABELS",
    "PROVIDERS",
    "PROVIDER_LABELS",
    "DingtalkProvider",
    "FeishuProvider",
    "create_provider",
    "credential_label",
    "provider_label",
    "supported_providers",
]
