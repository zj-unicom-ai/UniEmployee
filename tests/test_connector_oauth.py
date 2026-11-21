"""OAuth MCP connector flow and request-time bearer auth regression tests."""

import asyncio
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet

from app import catalog
from app.connectors import oauth


def test_oauth_authorization_registration_storage_refresh_and_disconnect(monkeypatch):
    monkeypatch.setenv("CONNECTOR_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    config = {
        "transport": "http",
        "url": "https://mcp.example.test/mcp",
        "auth_type": "oauth2",
        "oauth_issuer": "https://auth.example.test",
        "oauth_resource": "https://mcp.example.test/mcp",
        "oauth_scopes": "documents.read",
    }
    catalog.create_connector("oauth_test", "OAuth test", config=config)

    async def fake_resolve(url, *, field, allow_private):
        parsed = urlparse(url)
        return parsed.hostname, "93.184.216.34", 443, parsed

    monkeypatch.setattr(oauth, "_resolve_target", fake_resolve)
    calls = []

    def response(method, url, body, status=200):
        return httpx.Response(
            status,
            json=body,
            request=httpx.Request(method, url),
        )

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return response(method, url, {
                "authorization_endpoint": "https://auth.example.test/authorize",
                "token_endpoint": "https://auth.example.test/token",
                "registration_endpoint": "https://auth.example.test/register",
                "token_endpoint_auth_methods_supported": ["none"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
            })
        if url.endswith("/register"):
            return response(method, url, {"client_id": "dynamic-client"})
        form = kwargs.get("form") or {}
        if form.get("grant_type") == "authorization_code":
            return response(method, url, {
                "access_token": "access-initial",
                "refresh_token": "refresh-initial",
                "expires_in": 3600,
                "scope": "documents.read",
                "token_type": "Bearer",
            })
        if form.get("grant_type") == "refresh_token":
            return response(method, url, {
                "access_token": "access-refreshed",
                "refresh_token": "refresh-rotated",
                "expires_in": 3600,
                "token_type": "Bearer",
            })
        raise AssertionError(f"Unexpected OAuth request: {method} {url}")

    monkeypatch.setattr(oauth, "_request", fake_request)

    authorization_url = asyncio.run(oauth.begin_authorization(
        "oauth_test", "user-1", "tenant-1",
        "https://app.example.test/api/connectors/oauth/callback",
    ))
    query = parse_qs(urlparse(authorization_url).query)
    assert query["client_id"] == ["dynamic-client"]
    assert query["code_challenge_method"] == ["S256"]
    state = query["state"][0]

    details = asyncio.run(oauth.finish_authorization("auth-code", state))
    assert details == {
        "connector_id": "oauth_test",
        "user_id": "user-1",
        "tenant_id": "tenant-1",
    }
    assert oauth.connection_status("oauth_test", "user-1", "tenant-1")["status"] == "connected"
    assert oauth.connection_status("oauth_test", "user-2", "tenant-1")["status"] == "disconnected"
    assert oauth.connection_status("oauth_test", "user-1", "tenant-2")["status"] == "disconnected"

    credentials, _ = oauth._connection_credentials("oauth_test", "user-1", "tenant-1")
    credentials["expires_at"] = int(time.time()) - 1
    oauth._save_refreshed_credentials("oauth_test", "user-1", "tenant-1", credentials)
    refreshed = asyncio.run(oauth._refresh_credentials("oauth_test", "user-1", "tenant-1"))
    assert refreshed == "access-refreshed"
    credentials, _ = oauth._connection_credentials("oauth_test", "user-1", "tenant-1")
    assert credentials["refresh_token"] == "refresh-rotated"
    assert any((call[2].get("form") or {}).get("grant_type") == "refresh_token" for call in calls)

    with pytest.raises(oauth.OAuthError, match="已失效或已使用"):
        asyncio.run(oauth.finish_authorization("auth-code", state))

    assert oauth.disconnect("oauth_test", "user-1", "tenant-1") is True
    assert oauth.connection_status("oauth_test", "user-1", "tenant-1")["status"] == "disconnected"


def test_oauth_bearer_auth_retries_401_with_replayable_request_body(monkeypatch):
    token_calls = []

    async def fake_refresh(connector_id, user_id, tenant_id, *, force=False,
                           previous_access_token=None):
        token_calls.append((force, previous_access_token))
        return "access-refreshed" if force else "access-old"

    monkeypatch.setattr(oauth, "_refresh_credentials", fake_refresh)
    attempts = []

    async def handler(request):
        attempts.append((request.headers["Authorization"], request.content))
        if len(attempts) == 1:
            return httpx.Response(401, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            auth=oauth.runtime_auth("oauth_test", "user-1", "tenant-1"),
        ) as client:
            return await client.post(
                "https://mcp.example.test/mcp",
                json={"jsonrpc": "2.0", "method": "tools/call"},
            )

    result = asyncio.run(call())
    assert result.status_code == 200
    assert [item[0] for item in attempts] == [
        "Bearer access-old", "Bearer access-refreshed",
    ]
    assert attempts[0][1] == attempts[1][1]
    assert token_calls == [(False, None), (True, "access-old")]


def test_connector_config_rejects_plaintext_client_secret():
    with pytest.raises(oauth.OAuthError, match="不能保存 client secret 原文"):
        oauth.validate_connector_config({
            "transport": "http",
            "auth_type": "oauth2",
            "client_secret": "do-not-store-me",
        })
