"""自动化任务回归测试：cron 解析 / next_fire 计算 / CRUD / 抢占 / 模板渲染。"""
from datetime import datetime

from app import automations


# ---- cron 解析与匹配 ----

def test_cron_every_minute():
    parsed = automations.parse_cron("* * * * *")
    assert automations.cron_match(parsed, datetime(2026, 9, 2, 10, 30, 5))


def test_cron_daily_at_9():
    parsed = automations.parse_cron("0 9 * * *")
    assert automations.cron_match(parsed, datetime(2026, 9, 2, 9, 0))
    assert not automations.cron_match(parsed, datetime(2026, 9, 2, 9, 1))
    assert not automations.cron_match(parsed, datetime(2026, 9, 2, 10, 0))


def test_cron_step_and_range_and_list():
    parsed = automations.parse_cron("*/15 9-11 1,15 * *")
    assert automations.cron_match(parsed, datetime(2026, 9, 1, 10, 45))
    assert not automations.cron_match(parsed, datetime(2026, 9, 1, 10, 40))  # 分钟不在 */15
    assert not automations.cron_match(parsed, datetime(2026, 9, 2, 10, 45))  # 日不在 1,15
    assert not automations.cron_match(parsed, datetime(2026, 9, 1, 12, 45))  # 时不在 9-11


def test_cron_dow_sunday_is_0_or_7():
    # 2026-09-06 是周日
    for expr in ("* * * * 0", "* * * * 7"):
        parsed = automations.parse_cron(expr)
        assert automations.cron_match(parsed, datetime(2026, 9, 6, 8, 0))
        assert not automations.cron_match(parsed, datetime(2026, 9, 7, 8, 0))  # 周一


def test_cron_dom_dow_union_semantics():
    # 日与周同时受限 -> 并集：1 号或每个周一（2026-09-07 是周一）
    parsed = automations.parse_cron("0 0 1 * 1")
    assert automations.cron_match(parsed, datetime(2026, 9, 7, 0, 0))   # 周一但非 1 号
    assert automations.cron_match(parsed, datetime(2026, 10, 1, 0, 0))  # 1 号但非周一
    assert not automations.cron_match(parsed, datetime(2026, 9, 8, 0, 0))


def test_cron_invalid_expressions():
    for bad in ("* * * *", "61 * * * *", "* 24 * * *", "* * 0 * *",
                "*/0 * * * *", "5-2 * * * *", "a * * * *", "* * 31 2 *"):
        assert automations.validate_cron(bad) != "", f"应判定非法: {bad}"
    assert automations.validate_cron("*/5 * * * *") == ""
    assert automations.validate_cron("0 9 * * 1-5") == ""


def test_next_fire_basic():
    after = datetime(2026, 9, 2, 10, 30)
    nxt = automations.next_fire("0 9 * * *", after)
    assert (nxt.year, nxt.month, nxt.day, nxt.hour, nxt.minute) == (2026, 9, 3, 9, 0)
    # 紧随其后的分钟也能算（after 所在分钟不算，从下一分钟开始）
    assert automations.next_fire("* * * * *", after) == datetime(2026, 9, 2, 10, 31)


def test_next_fire_impossible_returns_none():
    # 2 月 30 日不存在
    assert automations.next_fire("0 0 30 2 *", datetime(2026, 1, 1)) is None


# ---- CRUD 与调度语义 ----

def _mk_cron(**kw):
    base = dict(name="每日报表", trigger_type="cron", employee_id="xiaoshu",
                prompt="汇总今日经营数据并输出简报", cron_expr="0 9 * * *")
    base.update(kw)
    return automations.create(**base)


def test_create_cron_sets_next_fire():
    auto = _mk_cron()
    assert auto["trigger_type"] == "cron"
    assert auto["next_fire_at"]  # 启用中的 cron 任务创建即排期
    nxt = automations.next_fire("0 9 * * *", datetime.now())
    assert auto["next_fire_at"] == nxt.strftime(automations.TS)


def test_disable_clears_next_fire_and_enable_reschedules():
    auto = _mk_cron()
    off = automations.update(auto["id"], enabled=False)
    assert off["enabled"] is False and off["next_fire_at"] is None
    on = automations.update(auto["id"], enabled=True)
    assert on["next_fire_at"]


def test_update_cron_expr_reschedules():
    auto = _mk_cron()
    upd = automations.update(auto["id"], cron_expr="*/10 * * * *")
    assert upd["cron_expr"] == "*/10 * * * *"
    nxt = automations.next_fire("*/10 * * * *", datetime.now())
    assert upd["next_fire_at"] == nxt.strftime(automations.TS)


def test_due_crons_only_enabled_and_past():
    past = _mk_cron(name="过期任务")
    future = _mk_cron(name="未来任务", cron_expr="0 3 * * *")  # 明天凌晨 3 点
    disabled = _mk_cron(name="停用任务", enabled=False)
    # 把 past 的触发点手动拨到 1 小时前（模拟停机错过）
    with automations._conn() as con:
        con.execute("UPDATE automations SET next_fire_at=? WHERE id=?",
                    (datetime.now().strftime(automations.TS), past["id"]))
        con.commit()
    due = automations.due_crons(datetime.now().strftime(automations.TS))
    ids = {a["id"] for a in due}
    assert past["id"] in ids
    assert future["id"] not in ids
    assert disabled["id"] not in ids


def test_claim_next_cas_prevents_double_run():
    auto = _mk_cron()
    old = auto["next_fire_at"]
    # 期望值不对（已被别人抢走）-> 抢占失败
    assert automations.claim_next(auto["id"], "2099-01-01T00:00", "2099-01-02T00:00") is False
    assert automations.get(auto["id"])["next_fire_at"] == old
    # 期望值正确 -> 成功并写入新触发点
    new_next = "2099-01-02T00:00"
    assert automations.claim_next(auto["id"], old, new_next) is True
    cur = automations.get(auto["id"])
    assert cur["next_fire_at"] == new_next
    assert cur["last_status"] == "running"


def test_mark_result_updates_counters():
    auto = _mk_cron()
    automations.mark_result(auto["id"], "ok", "", "c_test_1")
    cur = automations.get(auto["id"])
    assert cur["last_status"] == "ok"
    assert cur["last_conv_id"] == "c_test_1"
    assert cur["run_count"] == 1


def test_list_by_event_filters_enabled():
    automations.create(name="退款事件", trigger_type="event", employee_id="xiaoshu",
                       prompt="处理退款事件", event_key="order.refunded", secret="s1")
    automations.create(name="退款事件停用", trigger_type="event", employee_id="xiaoshu",
                       prompt="处理退款事件", event_key="order.refunded", enabled=False)
    hits = automations.list_by_event("order.refunded")
    assert len(hits) == 1 and hits[0]["name"] == "退款事件"
    assert automations.list_by_event("no.such.event") == []


def test_delete():
    auto = _mk_cron()
    assert automations.delete(auto["id"]) is True
    assert automations.delete(auto["id"]) is False
    assert automations.get(auto["id"]) is None


# ---- 模板渲染 ----

def test_render_prompt_placeholders():
    out = automations.render_prompt("现在是 {{now}}，事件：{{payload}}",
                                    payload={"order_id": "A1", "amount": 99})
    assert "{{now}}" not in out and "{{payload}}" not in out
    assert "A1" in out and "99" in out


def test_render_prompt_appends_payload_when_no_placeholder():
    out = automations.render_prompt("处理该事件", payload={"k": "v"})
    assert "处理该事件" in out and "[事件数据]" in out and '"k": "v"' in out


def test_render_prompt_without_payload():
    out = automations.render_prompt("生成 {{now}} 的日报")
    assert "{{now}}" not in out
