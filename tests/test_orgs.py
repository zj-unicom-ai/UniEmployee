"""组织（部门树）+ 用户归属回归测试（离线，用临时 sqlite 库）。"""
import pytest

from app import catalog
from app.catalog import orgs


@pytest.fixture()
def seeded():
    """建一棵测试树：总部 > (华东, 华北)；华东 > 销售部。"""
    root = orgs.create_org("总部")
    east = orgs.create_org("华东大区", parent_id=root)
    north = orgs.create_org("华北大区", parent_id=root)
    sales = orgs.create_org("销售部", parent_id=east)
    return {"root": root, "east": east, "north": north, "sales": sales}


def test_create_and_list(seeded):
    lst = {o["name"]: o for o in orgs.list_orgs()}
    assert set(lst) == {"总部", "华东大区", "华北大区", "销售部"}
    assert lst["销售部"]["parent_id"] == seeded["east"]


def test_create_with_bad_parent():
    assert orgs.create_org("孤儿", parent_id="org_not_exist") is None


def test_descendants_include_subtree(seeded):
    ids = orgs.descendant_ids(seeded["root"])
    assert set(ids) == set(seeded.values())
    # 不含自身
    assert orgs.descendant_ids(seeded["east"], include_self=False) == [seeded["sales"]]


def test_update_rename_without_move(seeded):
    # 不带 move：改名不影响 parent_id
    assert orgs.update_org(seeded["sales"], name="销售一部") is None
    o = orgs.get_org(seeded["sales"])
    assert o["name"] == "销售一部"
    assert o["parent_id"] == seeded["east"]


def test_update_move_cycle_rejected(seeded):
    # 把父部门挂到子部门下 → cycle
    assert orgs.update_org(seeded["east"], parent_id=seeded["sales"], move=True) == "cycle"
    # 挂到自己 → cycle
    assert orgs.update_org(seeded["east"], parent_id=seeded["east"], move=True) == "cycle"


def test_update_move_to_bad_parent(seeded):
    assert orgs.update_org(seeded["sales"], parent_id="org_not_exist", move=True) == "bad_parent"


def test_update_move_ok(seeded):
    assert orgs.update_org(seeded["sales"], parent_id=seeded["north"], move=True) is None
    assert orgs.get_org(seeded["sales"])["parent_id"] == seeded["north"]
    # 挂到顶级
    assert orgs.update_org(seeded["sales"], parent_id=None, move=True) is None
    assert orgs.get_org(seeded["sales"])["parent_id"] is None


def test_delete_protection(seeded):
    uid = catalog.create_user("org_user_1", "x", org_id=seeded["sales"])
    assert orgs.delete_org(seeded["sales"]) == "has_members"
    assert orgs.delete_org(seeded["root"]) == "has_children"
    # 移出成员后可删
    catalog.update_user(uid, org_id=None, set_org=True)
    assert orgs.delete_org(seeded["sales"]) is None
    assert orgs.get_org(seeded["sales"]) is None


def test_delete_not_found():
    assert orgs.delete_org("org_not_exist") == "not_found"


def test_user_org_and_filter(seeded):
    uid1 = catalog.create_user("org_user_a", "x", org_id=seeded["sales"])
    uid2 = catalog.create_user("org_user_b", "x", org_id=seeded["north"])
    uid3 = catalog.create_user("org_user_c", "x")  # 无部门

    # 列表带部门名
    rows = {u["username"]: u for u in catalog.list_users()}
    assert rows["org_user_a"]["org_name"] == "销售部"
    assert rows["org_user_b"]["org_name"] == "华北大区"
    assert rows["org_user_c"]["org_name"] is None

    # 父部门筛选含子部门成员
    names = {u["username"] for u in catalog.list_users(org_id=seeded["east"])}
    assert names == {"org_user_a"}
    names = {u["username"] for u in catalog.list_users(org_id=seeded["root"])}
    assert names == {"org_user_a", "org_user_b"}

    # 分页筛选
    paged = catalog.list_users_paged(1, 10, org_id=seeded["east"])
    assert paged["total"] == 1 and paged["items"][0]["username"] == "org_user_a"

    # 调部门
    catalog.update_user(uid1, org_id=seeded["north"], set_org=True)
    assert {u["username"] for u in catalog.list_users(org_id=seeded["north"])} == \
        {"org_user_a", "org_user_b"}
    # set_org=False 不影响归属
    catalog.update_user(uid2, role="admin")
    assert catalog.get_user(uid2)["org_id"] == seeded["north"]


def test_user_org_name_after_org_renamed(seeded):
    uid = catalog.create_user("org_user_d", "x", org_id=seeded["east"])
    orgs.update_org(seeded["east"], name="华东区")
    rows = {u["username"]: u for u in catalog.list_users()}
    assert rows["org_user_d"]["org_name"] == "华东区"
