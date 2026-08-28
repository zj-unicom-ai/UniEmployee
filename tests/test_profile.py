"""个人画像（user_profiles）+ system_prompt 注入回归测试。"""
from app import catalog
from app.compiler import _build_user_context


def test_profile_upsert_and_partial_update():
    uid = catalog.create_user("prof_user", "x")
    # 无记录 → 全空结构
    assert catalog.get_profile(uid) == {
        "display_name": "", "position": "", "duties": "", "preferences": ""}

    # 首次保存
    assert catalog.upsert_profile(uid, {
        "display_name": "王工", "position": "后端工程师",
        "duties": "负责平台服务端", "preferences": "回复简洁"})
    p = catalog.get_profile(uid)
    assert p["display_name"] == "王工" and p["position"] == "后端工程师"

    # 部分更新：只改称呼，其余沿用
    assert catalog.upsert_profile(uid, {"display_name": "老王"})
    p2 = catalog.get_profile(uid)
    assert p2["display_name"] == "老王"
    assert p2["position"] == "后端工程师"
    assert p2["duties"] == "负责平台服务端"

    # 不存在的用户
    assert not catalog.upsert_profile("ghost", {"display_name": "x"})


def test_build_user_context_injection():
    uid = catalog.create_user("prof_user2", "x")
    # 无画像 → 不注入
    assert _build_user_context(uid) == ""
    assert _build_user_context(None) == ""

    catalog.upsert_profile(uid, {
        "display_name": "王工", "position": "后端工程师",
        "duties": "", "preferences": "回复简洁"})
    ctx = _build_user_context(uid)
    assert "当前用户信息" in ctx
    assert "称呼：王工" in ctx
    assert "职位：后端工程师" in ctx
    assert "偏好与沟通风格：回复简洁" in ctx
    assert "职责背景" not in ctx  # 空字段不出现
