"""安全护栏：敏感词引擎 + 工具白名单 + 拦截日志回归测试。"""
from app import guard


def test_sensitive_words_crud_and_check():
    guard.add_word("测试敏感词甲", category="测试")
    hit = guard.check_text("这句话里有测试敏感词甲出现")
    assert hit and hit["word"] == "测试敏感词甲" and hit["category"] == "测试"
    assert guard.check_text("正常内容不命中") is None

    words = guard.list_words()
    target = next(w for w in words if w["word"] == "测试敏感词甲")
    guard.delete_word(target["id"])
    assert guard.check_text("测试敏感词甲又出现了") is None  # 软删后不再命中


def test_settings_and_tool_whitelist():
    guard.set_setting("admin_only_tools", "tool_x, tool_y")
    s = guard.get_settings()
    assert "tool_x" in s["admin_only_tools"]
    # 普通用户受限，admin 不受限
    assert not guard.tool_allowed("tool_x", "user")
    assert guard.tool_allowed("tool_x", "admin")
    assert guard.tool_allowed("tool_z", "user")  # 白名单外不限制
    # 清空白名单 = 不限制
    guard.set_setting("admin_only_tools", "")
    assert guard.tool_allowed("tool_x", "user")


def test_guard_logs():
    guard.log("input_blocked", "测试拦截记录", user_id="u1",
              extra={"word": "x"})
    logs = guard.list_logs(event_type="input_blocked")
    assert any("测试拦截记录" in l["detail"] for l in logs)
