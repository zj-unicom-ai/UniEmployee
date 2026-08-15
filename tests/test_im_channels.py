"""IM 频道第一批：频道存储、员工挂载、频道会话与普通会话隔离。"""

from app import conversations


def test_create_channel_with_members():
    ch = conversations.create_channel(
        "测试频道",
        description="用于 IM 测试",
        kind="web",
        employee_ids=["emp_a", "emp_b"],
    )
    assert ch["id"].startswith("chan_")
    assert ch["name"] == "测试频道"
    assert conversations.get_channel(ch["id"])["kind"] == "web"
    assert conversations.list_employee_ids_for_channel(ch["id"]) == ["emp_a", "emp_b"]
    members = conversations.list_channel_members(ch["id"])
    assert members[0]["is_default"] == 1


def test_channel_conversation_isolated_from_normal_history():
    ch = conversations.create_channel("隔离频道", employee_ids=["emp_x"])
    conv_id = "c_im_test"
    conversations.create(conv_id, "emp_x", title="频道首条", preview="频道预览",
                         count=1, user_id="u1", channel_id=ch["id"])
    assert len(conversations.list_for_channel(ch["id"], user_id="u1")) == 1
    # 普通历史列表不应出现频道会话
    assert conversations.list_for(user_id="u1") == []
    meta = conversations.get(conv_id)
    assert meta["channel_id"] == ch["id"]
    assert meta["employee_id"] == "emp_x"


def test_ensure_default_channel_is_idempotent():
    first = conversations.ensure_default_channel(["emp_1", "emp_2"])
    second = conversations.ensure_default_channel(["emp_1", "emp_2"])
    assert first["id"] == second["id"]
    assert conversations.get_channel(first["id"])


def test_channel_config_columns_persisted():
    ch = conversations.create_channel(
        "外部频道", provider="generic", enabled=False,
        config={"secret": "abc", "outbound_webhook": "https://example.com/hook"},
        employee_ids=["emp_x"],
    )
    got = conversations.get_channel(ch["id"])
    assert got["provider"] == "generic"
    assert got["enabled"] is False
    assert got["config"]["secret"] == "abc"
    assert got["config"]["outbound_webhook"] == "https://example.com/hook"


def test_channel_update_and_soft_delete():
    ch = conversations.create_channel("待改频道", provider="generic", employee_ids=["emp_a"])
    updated = conversations.update_channel(ch["id"], name="改名", enabled=False, employee_ids=["emp_b"])
    assert updated["name"] == "改名"
    assert updated["enabled"] is False
    assert conversations.list_employee_ids_for_channel(ch["id"]) == ["emp_b"]
    assert conversations.delete_channel(ch["id"]) is True
    assert conversations.get_channel(ch["id"]) is None


def test_find_channel_conversation_filters_by_employee():
    ch = conversations.create_channel("查找频道")
    conversations.create("conv_find", "emp_x", user_id="im:chan:s1", channel_id=ch["id"])
    found = conversations.find_channel_conversation(ch["id"], "im:chan:s1", "emp_x")
    assert found and found["conv_id"] == "conv_find"
    assert conversations.find_channel_conversation(ch["id"], "im:chan:s1", "emp_y") is None
