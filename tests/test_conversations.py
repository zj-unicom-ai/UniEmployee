"""会话管理回归测试：创建/分页/标题/删除/用户隔离。"""
from app import conversations


def test_create_and_get():
    conversations.create("c1", "xiaosu", title="嗨", preview="嗨你好", count=1, user_id="u1")
    m = conversations.get("c1")
    assert m is not None
    assert m["title"] == "嗨"
    assert m["employee_id"] == "xiaosu"
    assert m["user_id"] == "u1"


def test_list_for_with_limit():
    for i in range(5):
        conversations.create(f"c{i}", "xiaosu", user_id="u1")
    assert len(conversations.list_for(user_id="u1")) == 5
    assert len(conversations.list_for(user_id="u1", limit=2)) == 2


def test_list_paged_pagination():
    for i in range(12):
        conversations.create(f"p{i}", "xiaosu", user_id="u1")
    d1 = conversations.list_paged(user_id="u1", page=1, page_size=5)
    assert d1["total"] == 12 and d1["pages"] == 3 and len(d1["items"]) == 5
    d3 = conversations.list_paged(user_id="u1", page=3, page_size=5)
    assert len(d3["items"]) == 2  # 最后一页只剩 2 条


def test_set_title_overrides():
    conversations.create("c", "xiaosu", title="首句截断", user_id="u1")
    conversations.set_title("c", "AI提炼的标题")
    assert conversations.get("c")["title"] == "AI提炼的标题"


def test_user_isolation_in_list():
    conversations.create("a1", "xiaosu", user_id="ua")
    conversations.create("b1", "xiaosu", user_id="ub")
    assert len(conversations.list_for(user_id="ua")) == 1
    assert len(conversations.list_for(user_id="ub")) == 1
    # 分页也按 user 隔离
    assert conversations.list_paged(user_id="ua", page=1)["total"] == 1


def test_delete():
    conversations.create("c", "xiaosu", user_id="u1")
    assert conversations.delete("c") is True
    assert conversations.get("c") is None
    assert conversations.delete("不存在") is False
