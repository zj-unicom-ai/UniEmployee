"""User-scoped OAuth 2.0 for remote MCP connectors.

The public interface is deliberately small: start an authorization, consume its
callback, expose connection status, disconnect, and provide a request-time
Bearer auth object to the MCP adapter. Protocol discovery follows the MCP
Protected Resource Metadata / OAuth Authorization Server Metadata flow used by
Octop, adapted to UniEmployee's catalog and per-user runtime.
"""

# The DNS-pinned HTTP transport is adapted from Octop's MIT-licensed
# ``src/octop/infra/utils/ssrf_guard.py`` (Copyright (c) 2026 Octop).
# See ``backend/app/connectors/OCTOP_SOURCE_LICENSE.txt``.

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from httpcore._backends.auto import AutoBackend
from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkStream

from app.catalog.db import _conn
from app.catalog import resources


class OAuthError(ValueError):
    """Safe, user-displayable OAuth setup or authorization error."""


class OAuthReauthorizationRequired(OAuthError):
    """Stored authorization can no longer be refreshed."""


_STATE_TTL_SECONDS = 600
_REFRESH_SKEW_SECONDS = 60
_PRIVATE_HOST_SUFFIXES = (".localhost", ".local", ".internal")
_WWW_RESOURCE_METADATA = re.compile(
    r'resource_metadata\s*=\s*"([^"]+)"', re.IGNORECASE
)
_refresh_locks: dict[tuple[str, str, str], asyncio.Lock] = {}


def is_oauth_config(config: dict[str, Any] | None) -> bool:
    cfg = config or {}
    return str(cfg.get("auth_type") or "").strip().lower() == "oauth2"


def validate_connector_config(config: Any) -> None:
    """Reject malformed configs and secrets that would otherwise be stored in plaintext."""
    if not isinstance(config, dict):
        raise OAuthError("连接器 config 必须是 JSON 对象。")
    if config.get("oauth_client_secret") or config.get("client_secret"):
        raise OAuthError(
            "连接器配置不能保存 client secret 原文；请使用 CONNECTOR_OAUTH_CLIENT_SECRET_ 环境变量引用。"
        )


def configuration_signature(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    names = (
        "transport", "url", "auth_type", "oauth_issuer", "oauth_resource",
        "oauth_scopes", "oauth_client_id", "oauth_client_secret_env",
        "oauth_token_endpoint_auth_method", "oauth_allowed_hosts",
        "oauth_allow_private_hosts",
    )
    selected = {name: cfg.get(name) for name in names}
    payload = json.dumps(selected, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clear_connector(connector_id: str) -> None:
    """Remove OAuth client registrations, pending flows, and user grants."""
    con = _conn()
    con.execute("DELETE FROM connector_oauth_clients WHERE connector_id=?", (connector_id,))
    con.execute("DELETE FROM connector_oauth_states WHERE connector_id=?", (connector_id,))
    con.execute("DELETE FROM connector_oauth_connections WHERE connector_id=?", (connector_id,))
    con.commit()
    con.close()


def _fernet() -> Fernet:
    raw = os.environ.get("CONNECTOR_OAUTH_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise OAuthError(
            "尚未配置 CONNECTOR_OAUTH_ENCRYPTION_KEY；请生成并配置 Fernet 密钥后重试。"
        )
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise OAuthError("CONNECTOR_OAUTH_ENCRYPTION_KEY 格式无效。") from exc


def _seal(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(raw).decode("ascii")


def _unseal(value: str | bytes) -> dict[str, Any]:
    try:
        raw = value.encode("ascii") if isinstance(value, str) else value
        result = json.loads(_fernet().decrypt(raw).decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeEncodeError, json.JSONDecodeError) as exc:
        raise OAuthError("连接器授权数据无法解密；请检查加密密钥是否与写入时一致。") from exc
    if not isinstance(result, dict):
        raise OAuthError("连接器授权数据格式无效。")
    return result


def _private_ip(ip_text: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return not addr.is_global


def _parse_https_url(url: str, field: str) -> tuple[str, int, Any]:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() != "https":
        raise OAuthError(f"{field} 必须使用 HTTPS。")
    if not parsed.hostname or parsed.username or parsed.password:
        raise OAuthError(f"{field} 不是有效的 HTTPS 地址。")
    if parsed.fragment:
        raise OAuthError(f"{field} 不能包含 URL fragment。")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise OAuthError(f"{field} 端口无效。") from exc
    return parsed.hostname.lower().rstrip("."), port, parsed


async def _resolve_target(url: str, *, field: str, allow_private: bool) -> tuple[str, str, int, Any]:
    host, port, parsed = _parse_https_url(url, field)
    if not allow_private:
        if host in {"localhost", "host.docker.internal", "gateway.docker.internal"}:
            raise OAuthError(f"{field} 指向本机或私有网络；仅管理员显式允许后才能使用。")
        if host.endswith(_PRIVATE_HOST_SUFFIXES):
            raise OAuthError(f"{field} 指向本机或私有网络；仅管理员显式允许后才能使用。")
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        raise OAuthError(f"{field} 主机名无法解析。") from exc
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise OAuthError(f"{field} 主机名无法解析。")
    if not allow_private and any(_private_ip(address) for address in addresses):
        raise OAuthError(f"{field} 解析到了私有或保留 IP；仅管理员显式允许后才能使用。")
    return host, addresses[0], port, parsed


class _PinnedBackend(AutoBackend):
    """Pin the validated DNS result for one HTTPS request (prevents rebinding)."""

    def __init__(self, target_host: str, pinned_ip: str) -> None:
        super().__init__()
        self._target_host = target_host
        self._pinned_ip = pinned_ip

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        return await super().connect_tcp(
            self._pinned_ip if host == self._target_host else host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class _PinnedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, host: str, pinned_ip: str) -> None:
        super().__init__()
        # httpcore retains the original hostname for TLS SNI while the socket
        # connects to the address checked above.
        self._pool._network_backend = _PinnedBackend(host, pinned_ip)


async def _request(
    method: str,
    url: str,
    *,
    field: str,
    allow_private: bool,
    json_body: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
) -> httpx.Response:
    host, pinned_ip, port, parsed = await _resolve_target(
        url, field=field, allow_private=allow_private
    )
    netloc = f"{host}:{port}" if port != 443 else host
    normalized_url = urlunparse(("https", netloc, parsed.path or "/", "", parsed.query, ""))
    transport = _PinnedTransport(host, pinned_ip)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=20.0,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            return await client.request(
                method,
                normalized_url,
                json=json_body,
                data=form,
                headers=headers,
                auth=auth,
            )
    except OAuthError:
        raise
    except Exception as exc:
        raise OAuthError(f"访问 {field} 失败，请检查连接器地址和网络。") from exc


def _metadata_urls(issuer: str) -> list[str]:
    parsed = urlparse(issuer.rstrip("/"))
    base = f"https://{parsed.netloc}"
    issuer_path = parsed.path.strip("/")
    candidates = [
        urljoin(base, "/.well-known/oauth-authorization-server"
                + (f"/{issuer_path}" if issuer_path else "")),
        urljoin(base, "/.well-known/openid-configuration"
                + (f"/{issuer_path}" if issuer_path else "")),
        issuer.rstrip("/") + "/.well-known/openid-configuration",
    ]
    return list(dict.fromkeys(candidates))


def _oauth_endpoint_host_allowed(
    endpoint: str, issuer: str, allowed_hosts: Iterable[str]
) -> bool:
    host = (urlparse(endpoint).hostname or "").lower().rstrip(".")
    issuer_host = (urlparse(issuer).hostname or "").lower().rstrip(".")
    explicit = {str(item).strip().lower().rstrip(".") for item in allowed_hosts if str(item).strip()}
    return bool(host and issuer_host and (
        host == issuer_host or host.endswith("." + issuer_host) or host in explicit
    ))


async def _authorization_metadata(
    issuer: str, *, allow_private: bool, allowed_hosts: Iterable[str]
) -> dict[str, Any]:
    _parse_https_url(issuer, "oauth_issuer")
    last_error: Exception | None = None
    for url in _metadata_urls(issuer):
        try:
            response = await _request(
                "GET", url, field="OAuth metadata", allow_private=allow_private
            )
            if response.status_code >= 400:
                continue
            body = response.json()
            if (isinstance(body, dict) and body.get("authorization_endpoint")
                    and body.get("token_endpoint")):
                endpoints = [
                    ("authorization_endpoint", body["authorization_endpoint"]),
                    ("token_endpoint", body["token_endpoint"]),
                ]
                if body.get("registration_endpoint"):
                    endpoints.append(("registration_endpoint", body["registration_endpoint"]))
                for field, endpoint in endpoints:
                    _parse_https_url(endpoint, field)
                    if not _oauth_endpoint_host_allowed(endpoint, issuer, allowed_hosts):
                        raise OAuthError(
                            f"{field} 主机不属于 OAuth issuer；如服务商使用独立域名，请配置 oauth_allowed_hosts。"
                        )
                    await _resolve_target(
                        endpoint, field=field, allow_private=allow_private
                    )
                return body
        except Exception as exc:
            last_error = exc
    if last_error:
        raise OAuthError("无法读取 OAuth authorization-server metadata。") from last_error
    raise OAuthError("OAuth authorization-server metadata 缺少必需端点。")


def _protected_resource_urls(mcp_url: str, advertised: str | None = None) -> list[str]:
    parsed = urlparse(mcp_url)
    origin = f"https://{parsed.netloc}"
    urls = [advertised] if advertised else []
    if parsed.path and parsed.path != "/":
        urls.append(urljoin(origin, f"/.well-known/oauth-protected-resource{parsed.path}"))
    urls.append(urljoin(origin, "/.well-known/oauth-protected-resource"))
    return list(dict.fromkeys(str(item).strip() for item in urls if item))


async def _discover_resource_metadata(
    mcp_url: str, *, allow_private: bool
) -> dict[str, Any]:
    advertised = None
    try:
        response = await _request(
            "POST",
            mcp_url,
            field="MCP endpoint",
            allow_private=allow_private,
            json_body={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "UniEmployee", "version": "0.1"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        match = _WWW_RESOURCE_METADATA.search(response.headers.get("WWW-Authenticate", ""))
        advertised = match.group(1).strip() if match else None
    except OAuthError:
        # Resource metadata endpoints are still tried; some servers only expose
        # the well-known document and do not challenge unauthenticated initialize.
        pass

    for candidate in _protected_resource_urls(mcp_url, advertised):
        try:
            response = await _request(
                "GET", candidate, field="protected-resource metadata",
                allow_private=allow_private,
            )
            if response.status_code >= 400:
                continue
            body = response.json()
            if isinstance(body, dict) and body.get("authorization_servers"):
                return body
        except Exception:
            continue
    raise OAuthError("MCP 服务没有提供 OAuth protected-resource metadata，请配置 oauth_issuer。")


async def _discover_oauth(
    config: dict[str, Any], mcp_url: str
) -> tuple[str, str, dict[str, Any]]:
    allow_private = config.get("oauth_allow_private_hosts") is True
    issuer = str(config.get("oauth_issuer") or "").strip().rstrip("/")
    configured_resource = str(config.get("oauth_resource") or "").strip()
    resource = configured_resource or mcp_url
    if not issuer:
        resource_metadata = await _discover_resource_metadata(
            mcp_url, allow_private=allow_private
        )
        servers = resource_metadata.get("authorization_servers")
        if not isinstance(servers, list) or not servers:
            raise OAuthError("OAuth protected-resource metadata 缺少 authorization_servers。")
        issuer = str(servers[0]).strip().rstrip("/")
        resource = configured_resource or str(resource_metadata.get("resource") or resource).strip()
    allowed_hosts = config.get("oauth_allowed_hosts") or []
    if not isinstance(allowed_hosts, list):
        raise OAuthError("oauth_allowed_hosts 必须是域名数组。")
    metadata = await _authorization_metadata(
        issuer, allow_private=allow_private, allowed_hosts=allowed_hosts
    )
    return issuer, resource, metadata


def _scopes(config: dict[str, Any]) -> str:
    value = config.get("oauth_scopes") or ""
    if isinstance(value, list):
        return " ".join(str(scope).strip() for scope in value if str(scope).strip())
    return " ".join(str(value).split())


def _client_secret_from_env(config: dict[str, Any]) -> str | None:
    env_name = str(config.get("oauth_client_secret_env") or "").strip()
    if not env_name:
        return None
    if not env_name.startswith("CONNECTOR_OAUTH_CLIENT_SECRET_"):
        raise OAuthError(
            "oauth_client_secret_env 必须使用 CONNECTOR_OAUTH_CLIENT_SECRET_ 前缀。"
        )
    secret = os.environ.get(env_name, "").strip()
    if not secret:
        raise OAuthError(f"服务端环境变量 {env_name} 尚未配置。")
    return secret


def _get_registered_client(connector_id: str) -> dict[str, Any] | None:
    con = _conn()
    row = con.execute(
        "SELECT issuer,resource,metadata_json,client_id,client_secret_ciphertext "
        "FROM connector_oauth_clients WHERE connector_id=?", (connector_id,)
    ).fetchone()
    con.close()
    if not row:
        return None
    data = dict(row)
    try:
        data["metadata"] = json.loads(data.pop("metadata_json"))
    except (json.JSONDecodeError, TypeError):
        return None
    secret_blob = data.pop("client_secret_ciphertext")
    data["client_secret"] = _unseal(secret_blob).get("secret") if secret_blob else None
    return data


def _save_registered_client(
    connector_id: str,
    *,
    issuer: str,
    resource: str,
    metadata: dict[str, Any],
    client_id: str,
    client_secret: str | None,
) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    secret_blob = _seal({"secret": client_secret}) if client_secret else None
    con = _conn()
    con.execute(
        "INSERT INTO connector_oauth_clients(connector_id,issuer,resource,metadata_json,client_id,"
        "client_secret_ciphertext,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(connector_id) DO UPDATE SET issuer=excluded.issuer,resource=excluded.resource,"
        "metadata_json=excluded.metadata_json,client_id=excluded.client_id,"
        "client_secret_ciphertext=excluded.client_secret_ciphertext,updated_at=excluded.updated_at",
        (connector_id, issuer, resource, json.dumps(metadata, ensure_ascii=False), client_id,
         secret_blob, now, now),
    )
    con.commit()
    con.close()


async def _register_client(
    connector_id: str,
    config: dict[str, Any],
    *,
    issuer: str,
    resource: str,
    metadata: dict[str, Any],
    redirect_uri: str,
) -> tuple[str, str | None, str]:
    configured_id = str(config.get("oauth_client_id") or "").strip()
    auth_method = str(config.get("oauth_token_endpoint_auth_method") or "").strip()
    if configured_id:
        secret = _client_secret_from_env(config)
        if not auth_method:
            auth_method = "client_secret_post" if secret else "none"
        if auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
            raise OAuthError("oauth_token_endpoint_auth_method 不受支持。")
        if auth_method in {"client_secret_post", "client_secret_basic"} and not secret:
            raise OAuthError(
                f"{auth_method} 需要配置 oauth_client_secret_env 和对应服务端环境变量。"
            )
        return configured_id, secret, auth_method

    old = _get_registered_client(connector_id)
    if old and old.get("issuer") == issuer and old.get("resource") == resource:
        methods = metadata.get("token_endpoint_auth_methods_supported") or []
        if "none" in methods:
            method = "none"
        elif "client_secret_post" in methods or not methods:
            method = "client_secret_post"
        elif "client_secret_basic" in methods:
            method = "client_secret_basic"
        else:
            raise OAuthError("OAuth 服务端没有支持的 token endpoint client auth method。")
        return str(old["client_id"]), old.get("client_secret"), method

    endpoint = str(metadata.get("registration_endpoint") or "").strip()
    if not endpoint:
        raise OAuthError(
            "OAuth 服务未开放动态客户端注册；请在连接器配置 oauth_client_id，"
            "并按需配置 oauth_client_secret_env。"
        )
    methods = metadata.get("token_endpoint_auth_methods_supported") or []
    if "none" in methods:
        method = "none"
    elif "client_secret_post" in methods or not methods:
        method = "client_secret_post"
    elif "client_secret_basic" in methods:
        method = "client_secret_basic"
    else:
        raise OAuthError("OAuth 服务端没有支持的 token endpoint client auth method。")
    supported_grants = metadata.get("grant_types_supported") or []
    grant_types = ["authorization_code"]
    if not supported_grants or "refresh_token" in supported_grants:
        grant_types.append("refresh_token")
    response = await _request(
        "POST", endpoint, field="dynamic client registration",
        allow_private=config.get("oauth_allow_private_hosts") is True,
        json_body={
            "client_name": "UniEmployee Connector",
            "redirect_uris": [redirect_uri],
            "grant_types": grant_types,
            "response_types": ["code"],
            "token_endpoint_auth_method": method,
        },
    )
    if response.status_code >= 400:
        raise OAuthError(f"OAuth 动态客户端注册失败（HTTP {response.status_code}）。")
    body = response.json()
    if not isinstance(body, dict) or not body.get("client_id"):
        raise OAuthError("OAuth 动态客户端注册没有返回 client_id。")
    client_id = str(body["client_id"])
    client_secret = str(body.get("client_secret") or "") or None
    _save_registered_client(
        connector_id, issuer=issuer, resource=resource, metadata=metadata,
        client_id=client_id, client_secret=client_secret,
    )
    return client_id, client_secret, method


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _store_state(
    state: str,
    connector_id: str,
    user_id: str,
    tenant_id: str,
    context: dict[str, Any],
) -> None:
    now = int(time.time())
    con = _conn()
    con.execute("DELETE FROM connector_oauth_states WHERE expires_at<=?", (now,))
    con.execute(
        "INSERT INTO connector_oauth_states(state_hash,connector_id,user_id,tenant_id,"
        "context_ciphertext,expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
        (hashlib.sha256(state.encode("ascii")).hexdigest(), connector_id, user_id,
         tenant_id, _seal(context), now + _STATE_TTL_SECONDS,
         time.strftime("%Y-%m-%d %H:%M:%S")),
    )
    con.commit()
    con.close()


def _consume_state(state: str) -> dict[str, Any]:
    if not state or len(state) > 256:
        raise OAuthError("OAuth state 缺失或无效，请重新发起授权。")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    now = int(time.time())
    con = _conn()
    row = con.execute(
        "SELECT connector_id,user_id,tenant_id,context_ciphertext FROM connector_oauth_states "
        "WHERE state_hash=? AND expires_at>?", (state_hash, now)
    ).fetchone()
    if not row:
        con.close()
        raise OAuthError("OAuth state 已失效或已使用，请重新发起授权。")
    deleted = con.execute(
        "DELETE FROM connector_oauth_states WHERE state_hash=? AND expires_at>?",
        (state_hash, now),
    )
    if getattr(deleted, "rowcount", 0) != 1:
        con.commit()
        con.close()
        raise OAuthError("OAuth state 已被使用，请重新发起授权。")
    con.commit()
    con.close()
    context = _unseal(row["context_ciphertext"])
    context.update({
        "connector_id": row["connector_id"],
        "user_id": row["user_id"],
        "tenant_id": row["tenant_id"],
    })
    return context


async def begin_authorization(
    connector_id: str,
    user_id: str,
    tenant_id: str,
    redirect_uri: str,
) -> str:
    connector = resources.get_connector(connector_id)
    if not connector:
        raise OAuthError("连接器不存在或已停用。")
    _fernet()  # Fail before metadata lookup or dynamic client registration.
    config = connector.get("config") or {}
    if not is_oauth_config(config):
        raise OAuthError("该连接器没有启用 OAuth 2.0。")
    validate_connector_config(config)
    transport = str(config.get("transport") or "").lower().replace("-", "_")
    if transport not in {"http", "streamable_http", "sse"}:
        raise OAuthError("OAuth 连接器必须使用 HTTP、Streamable HTTP 或 SSE。")
    mcp_url = str(config.get("url") or "").strip()
    if not mcp_url:
        raise OAuthError("OAuth 连接器缺少 MCP url。")
    _parse_https_url(mcp_url, "MCP url")
    issuer, resource, metadata = await _discover_oauth(config, mcp_url)
    client_id, client_secret, auth_method = await _register_client(
        connector_id, config, issuer=issuer, resource=resource,
        metadata=metadata, redirect_uri=redirect_uri,
    )
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    scope = _scopes(config)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if scope:
        params["scope"] = scope
    if resource:
        params["resource"] = resource
    _store_state(state, connector_id, user_id, tenant_id, {
        "issuer": issuer,
        "resource": resource,
        "metadata": metadata,
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_method": auth_method,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "scope": scope,
        "allow_private": config.get("oauth_allow_private_hosts") is True,
        "config_signature": configuration_signature(config),
    })
    separator = "&" if "?" in metadata["authorization_endpoint"] else "?"
    return str(metadata["authorization_endpoint"]) + separator + urlencode(params)


def _save_connection(context: dict[str, Any], tokens: dict[str, Any]) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = tokens.get("expires_at")
    credential_data = {
        **tokens,
        "issuer": context["issuer"],
        "resource": context.get("resource"),
        "metadata": context["metadata"],
        "client_id": context["client_id"],
        "client_secret": context.get("client_secret"),
        "auth_method": context.get("auth_method") or "none",
        "allow_private": bool(context.get("allow_private")),
    }
    con = _conn()
    con.execute(
        "INSERT INTO connector_oauth_connections(connector_id,user_id,tenant_id,"
        "credentials_ciphertext,status,expires_at,scopes,connected_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(connector_id,user_id,tenant_id) DO UPDATE SET "
        "credentials_ciphertext=excluded.credentials_ciphertext,status='connected',"
        "expires_at=excluded.expires_at,scopes=excluded.scopes,connected_at=excluded.connected_at,"
        "updated_at=excluded.updated_at",
        (context["connector_id"], context["user_id"], context["tenant_id"],
         _seal(credential_data), "connected", expires_at,
         str(tokens.get("scope") or context.get("scope") or ""), now, now),
    )
    con.commit()
    con.close()


async def finish_authorization(code: str, state: str) -> dict[str, str]:
    context = _consume_state(state)
    connector = resources.get_connector(str(context["connector_id"]))
    if (not connector or not is_oauth_config(connector.get("config"))
            or configuration_signature(connector.get("config")) != context.get("config_signature")):
        raise OAuthError("OAuth 连接器配置已变更，请重新发起授权。")
    if not code or len(code) > 4096:
        raise OAuthError("OAuth provider 没有返回有效授权码。")
    metadata = context["metadata"]
    endpoint = str(metadata["token_endpoint"])
    form: dict[str, Any] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": context["redirect_uri"],
        "client_id": context["client_id"],
        "code_verifier": context["code_verifier"],
    }
    if context.get("resource"):
        form["resource"] = context["resource"]
    secret = context.get("client_secret")
    auth = None
    if secret and context.get("auth_method") == "client_secret_basic":
        auth = (str(context["client_id"]), str(secret))
    elif secret and context.get("auth_method") == "client_secret_post":
        form["client_secret"] = secret
    response = await _request(
        "POST", endpoint, field="token endpoint",
        allow_private=bool(context.get("allow_private")),
        form=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=auth,
    )
    if response.status_code >= 400:
        raise OAuthError(f"OAuth token exchange 失败（HTTP {response.status_code}）。")
    body = response.json()
    if not isinstance(body, dict) or not body.get("access_token"):
        raise OAuthError("OAuth token endpoint 没有返回 access_token。")
    expires_in = max(0, int(body.get("expires_in") or 0))
    tokens = {
        "access_token": str(body["access_token"]),
        "refresh_token": str(body.get("refresh_token") or ""),
        "expires_at": int(time.time()) + expires_in if expires_in else None,
        "token_type": str(body.get("token_type") or "Bearer"),
        "scope": str(body.get("scope") or context.get("scope") or ""),
    }
    _save_connection(context, tokens)
    return {
        "connector_id": str(context["connector_id"]),
        "user_id": str(context["user_id"]),
        "tenant_id": str(context["tenant_id"]),
    }


def consume_denied_authorization(state: str) -> dict[str, str]:
    context = _consume_state(state)
    return {
        "connector_id": str(context["connector_id"]),
        "user_id": str(context["user_id"]),
        "tenant_id": str(context["tenant_id"]),
    }


def connection_status(connector_id: str, user_id: str, tenant_id: str) -> dict[str, Any]:
    con = _conn()
    row = con.execute(
        "SELECT status,expires_at,scopes,connected_at,updated_at "
        "FROM connector_oauth_connections WHERE connector_id=? AND user_id=? AND tenant_id=?",
        (connector_id, user_id, tenant_id),
    ).fetchone()
    con.close()
    if not row:
        return {"status": "disconnected", "expires_at": None, "scopes": "", "connected_at": None}
    out = dict(row)
    if out.get("status") == "connected" and out.get("expires_at"):
        if int(out["expires_at"]) <= int(time.time()):
            out["status"] = "refresh_required"
    return out


def disconnect(connector_id: str, user_id: str, tenant_id: str) -> bool:
    con = _conn()
    result = con.execute(
        "DELETE FROM connector_oauth_connections WHERE connector_id=? AND user_id=? AND tenant_id=?",
        (connector_id, user_id, tenant_id),
    )
    con.commit()
    con.close()
    return getattr(result, "rowcount", 0) > 0


def _connection_credentials(connector_id: str, user_id: str, tenant_id: str) -> tuple[dict[str, Any], str]:
    con = _conn()
    row = con.execute(
        "SELECT credentials_ciphertext,status FROM connector_oauth_connections "
        "WHERE connector_id=? AND user_id=? AND tenant_id=?",
        (connector_id, user_id, tenant_id),
    ).fetchone()
    con.close()
    if not row:
        raise OAuthReauthorizationRequired("请先在“我的连接器”中完成授权。")
    if row["status"] != "connected":
        raise OAuthReauthorizationRequired("连接器授权已失效，请重新授权。")
    return _unseal(row["credentials_ciphertext"]), str(row["credentials_ciphertext"])


def _save_refreshed_credentials(
    connector_id: str, user_id: str, tenant_id: str,
    credentials: dict[str, Any], status: str = "connected",
) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    con.execute(
        "UPDATE connector_oauth_connections SET credentials_ciphertext=?,status=?,expires_at=?,"
        "scopes=?,updated_at=? WHERE connector_id=? AND user_id=? AND tenant_id=?",
        (_seal(credentials), status, credentials.get("expires_at"),
         str(credentials.get("scope") or ""), now, connector_id, user_id, tenant_id),
    )
    con.commit()
    con.close()


async def _refresh_credentials(
    connector_id: str,
    user_id: str,
    tenant_id: str,
    *,
    force: bool = False,
    previous_access_token: str | None = None,
) -> str:
    key = (tenant_id, user_id, connector_id)
    lock = _refresh_locks.setdefault(key, asyncio.Lock())
    async with lock:
        credentials, _ = _connection_credentials(connector_id, user_id, tenant_id)
        access = str(credentials.get("access_token") or "")
        expires_at = credentials.get("expires_at")
        still_valid = not expires_at or int(expires_at) > int(time.time()) + _REFRESH_SKEW_SECONDS
        if still_valid and (not force or access != previous_access_token):
            return access
        refresh_token = str(credentials.get("refresh_token") or "")
        if not refresh_token:
            _save_refreshed_credentials(
                connector_id, user_id, tenant_id, credentials, "reauthorization_required"
            )
            raise OAuthReauthorizationRequired("授权已过期且没有 refresh token，请重新授权。")
        metadata = credentials.get("metadata") or {}
        token_endpoint = str(metadata.get("token_endpoint") or "")
        form: dict[str, Any] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": credentials["client_id"],
        }
        if credentials.get("resource"):
            form["resource"] = credentials["resource"]
        secret = credentials.get("client_secret")
        auth = None
        if secret and credentials.get("auth_method") == "client_secret_basic":
            auth = (str(credentials["client_id"]), str(secret))
        elif secret and credentials.get("auth_method") == "client_secret_post":
            form["client_secret"] = secret
        response = await _request(
            "POST", token_endpoint, field="token endpoint",
            allow_private=bool(credentials.get("allow_private")), form=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"}, auth=auth,
        )
        if response.status_code >= 400:
            error_code = ""
            try:
                error_code = str(response.json().get("error") or "")
            except Exception:
                pass
            if error_code in {"invalid_grant", "invalid_token"}:
                _save_refreshed_credentials(
                    connector_id, user_id, tenant_id, credentials, "reauthorization_required"
                )
                raise OAuthReauthorizationRequired("授权已被服务端撤销，请重新授权。")
            raise OAuthError(f"刷新 OAuth token 失败（HTTP {response.status_code}）。")
        body = response.json()
        if not isinstance(body, dict) or not body.get("access_token"):
            raise OAuthError("OAuth refresh endpoint 没有返回 access_token。")
        expires_in = max(0, int(body.get("expires_in") or 0))
        credentials["access_token"] = str(body["access_token"])
        credentials["refresh_token"] = str(body.get("refresh_token") or refresh_token)
        credentials["expires_at"] = int(time.time()) + expires_in if expires_in else None
        credentials["token_type"] = str(body.get("token_type") or credentials.get("token_type") or "Bearer")
        credentials["scope"] = str(body.get("scope") or credentials.get("scope") or "")
        _save_refreshed_credentials(connector_id, user_id, tenant_id, credentials)
        return str(credentials["access_token"])


class _ConnectorBearerAuth(httpx.Auth):
    # Buffer request bodies so a POST can be replayed after a 401. Do not buffer
    # successful response bodies: SSE MCP responses can stay open indefinitely.
    requires_request_body = True

    def __init__(self, connector_id: str, user_id: str, tenant_id: str) -> None:
        self.connector_id = connector_id
        self.user_id = user_id
        self.tenant_id = tenant_id

    async def async_auth_flow(self, request: httpx.Request):
        token = await _refresh_credentials(
            self.connector_id, self.user_id, self.tenant_id
        )
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            await response.aread()
            token = await _refresh_credentials(
                self.connector_id, self.user_id, self.tenant_id,
                force=True, previous_access_token=token,
            )
            request.headers["Authorization"] = f"Bearer {token}"
            yield request


def runtime_auth(connector_id: str, user_id: str, tenant_id: str) -> httpx.Auth:
    """Create a request-time auth adapter for one user's MCP HTTP connection."""
    return _ConnectorBearerAuth(connector_id, user_id, tenant_id)
