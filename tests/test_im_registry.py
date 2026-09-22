import asyncio

from app.im.credentials import ChannelCredential
from app.im import providers as providers_module
from app.im import registry as registry_module


class FakeProvider:
    def __init__(self, credential, *, on_message, on_status=None):
        self.credential = credential
        self.on_message = on_message
        self.on_status = on_status
        self.channel = None

    async def connect(self, timeout=30):
        self.channel = object()
        if self.on_status:
            self.on_status("connecting", None)
        if self.credential.app_id == "bad":
            raise RuntimeError("credential rejected")
        if self.on_status:
            self.on_status("connected", None)

    async def disconnect(self):
        self.channel = None

    async def send(self, message):
        return None


def _configure(monkeypatch, channels, credentials):
    monkeypatch.setenv("FEISHU_ENABLED", "0")
    # Provider 现在通过注册表分派；测试替换注册表条目而不是 Registry 里的类引用。
    monkeypatch.setitem(providers_module.PROVIDERS, "feishu", FakeProvider)
    monkeypatch.setitem(providers_module.PROVIDERS, "dingtalk", FakeProvider)
    monkeypatch.setattr(
        registry_module.conversations, "list_channels", lambda: list(channels)
    )
    monkeypatch.setattr(
        registry_module.conversations,
        "list_employee_ids_for_channel",
        lambda channel_id: ["employee_1"],
    )
    monkeypatch.setattr(
        registry_module.jobs,
        "get_credential",
        lambda channel_id: credentials.get(channel_id),
    )
    monkeypatch.setattr(
        registry_module.jobs,
        "credential_summary",
        lambda channel_id: {
            "configured": channel_id in credentials,
            "updated_at": credentials.get(channel_id).app_id
            if channel_id in credentials
            else None,
        },
    )


def test_registry_isolates_failed_channel_from_healthy_channel(monkeypatch):
    channels = [
        {"id": "good", "provider": "feishu", "enabled": True, "updated_at": "1"},
        {"id": "bad", "provider": "feishu", "enabled": True, "updated_at": "1"},
    ]
    credentials = {
        "good": ChannelCredential("good", "good", "", "secret"),
        "bad": ChannelCredential("bad", "bad", "", "secret"),
    }
    _configure(monkeypatch, channels, credentials)

    async def scenario():
        registry = registry_module.SupervisorRegistry()
        await registry.start()
        await asyncio.sleep(0.05)
        states = registry.status("good"), registry.status("bad")
        await registry.stop()
        return states

    good, bad = asyncio.run(scenario())
    assert good["status"] == "connected"
    assert bad["status"] == "failed"
    assert "credential rejected" in bad["last_error"]


def test_registry_reconcile_stops_disabled_channel(monkeypatch):
    channels = [
        {"id": "ch", "provider": "feishu", "enabled": True, "updated_at": "1"}
    ]
    credentials = {
        "ch": ChannelCredential("ch", "good", "", "secret"),
    }
    _configure(monkeypatch, channels, credentials)

    async def scenario():
        registry = registry_module.SupervisorRegistry()
        await registry.start()
        await asyncio.sleep(0.02)
        assert registry.status("ch")["status"] == "connected"
        channels[0] = {**channels[0], "enabled": False, "updated_at": "2"}
        await registry.reconcile()
        state = registry.status("ch")
        await registry.stop()
        return state

    state = asyncio.run(scenario())
    assert state["status"] == "disabled"


def test_database_channel_suppresses_legacy_environment_fallback(monkeypatch):
    channels = [
        {"id": "db-channel", "provider": "feishu", "enabled": True, "updated_at": "1"}
    ]
    credentials = {
        "db-channel": ChannelCredential("db-channel", "db-app", "", "secret"),
    }
    _configure(monkeypatch, channels, credentials)
    monkeypatch.setenv("FEISHU_ENABLED", "1")
    monkeypatch.setenv("FEISHU_CHANNEL_ID", "legacy-channel")
    monkeypatch.setenv("FEISHU_EMPLOYEE_ID", "legacy-employee")
    monkeypatch.setenv("FEISHU_APP_ID", "legacy-app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "legacy-secret")

    registry = registry_module.SupervisorRegistry()
    assert set(registry._desired_specs()) == {"db-channel"}
