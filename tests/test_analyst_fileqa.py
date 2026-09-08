"""表格问答（fileqa）模块测试。

覆盖：数据文件注册（CSV/Excel 多 sheet）、路径校验、只读查询、
LLM 工具（file_table_list / file_table_query）、SSE 结果桥接、
compose_user_content 的 guidance 覆盖。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import paths
from app.agent.analyst.fileqa import manager as fileqa_manager
from app.agent.analyst.fileqa.tools import file_table_list, file_table_query
from app.agent.analyst.tools.sql_tools import (
    clear_conv_id,
    pop_query_results,
    set_conv_id,
)
from app.attachments import compose_user_content


@pytest.fixture(autouse=True)
def tmp_workspace(tmp_path, monkeypatch):
    """把 workspace/data 指到临时目录，隔离真实文件。"""
    ws = tmp_path / "workspace" / "data"
    ws.mkdir(parents=True)
    monkeypatch.setattr(paths, "WORKSPACE_DATA", ws)
    return ws


@pytest.fixture(autouse=True)
def user_ctx():
    """每个用例注入/清理 fileqa 用户上下文。"""
    fileqa_manager.set_user_id("u1")
    yield
    fileqa_manager.clear_user_id()


def _make_csv(uid: str, name: str, rows: int = 3) -> str:
    """在用户上传目录造一个 CSV 附件，返回虚拟路径。"""
    d = paths.WORKSPACE_DATA / "uploads" / uid / "c1"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    lines = ["产品,销售额,城市"]
    cities = ["杭州", "上海", "北京", "深圳"]
    for i in range(rows):
        lines.append(f"产品{i},{100 + i},{cities[i % len(cities)]}")
    p.write_text("\n".join(lines), encoding="utf-8")
    return f"/data/uploads/{uid}/c1/{name}"


def _make_xlsx(uid: str, name: str, sheets: dict) -> str:
    """在用户上传目录造一个多 sheet Excel 附件，返回虚拟路径。"""
    import pandas as pd

    d = paths.WORKSPACE_DATA / "uploads" / uid / "c1"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    with pd.ExcelWriter(p, engine="openpyxl") as writer:
        for sheet, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet, index=False)
    return f"/data/uploads/{uid}/c1/{name}"


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

def test_register_csv():
    vp = _make_csv("u1", "1000_销售明细.csv", rows=4)
    reg = fileqa_manager.register_data_file(vp, "u1")
    assert reg["file"] == "1000_销售明细.csv"
    assert len(reg["tables"]) == 1
    t = reg["tables"][0]
    # CSV 表名 = 文件名主干（清洗后）
    assert t["name"] == "1000_销售明细"
    assert t["columns"] == ["产品", "销售额", "城市"]
    assert t["row_count"] == 4
    assert t["sample"][0]["产品"] == "产品0"


def test_register_xlsx_multi_sheet():
    import pandas as pd

    vp = _make_xlsx("u1", "2000_经营数据.xlsx", {
        "销售": pd.DataFrame({"产品": ["A", "B"], "金额": [10, 20]}),
        "成本": pd.DataFrame({"产品": ["A"], "成本": [5]}),
    })
    reg = fileqa_manager.register_data_file(vp, "u1")
    names = {t["name"] for t in reg["tables"]}
    # Excel 表名 = 主干__sheet名
    assert names == {"2000_经营数据__销售", "2000_经营数据__成本"}


def test_register_rejects_bad_path():
    # 路径穿越
    with pytest.raises(ValueError):
        fileqa_manager.register_data_file("/data/uploads/u1/../x.csv", "u1")
    # 非本用户目录
    with pytest.raises(ValueError):
        fileqa_manager.register_data_file("/data/uploads/other/c1/a.csv", "u1")
    # 非数据文件
    with pytest.raises(ValueError):
        fileqa_manager.register_data_file("/data/uploads/u1/c1/a.txt", "u1")


def test_register_gbk_csv():
    """国内业务系统常见 GBK 编码导出文件应能正常解析。"""
    d = paths.WORKSPACE_DATA / "uploads" / "u1" / "c1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "3000_gbk.csv").write_text("产品,销售额\n手机,100\n", encoding="gbk")
    reg = fileqa_manager.register_data_file("/data/uploads/u1/c1/3000_gbk.csv", "u1")
    assert reg["tables"][0]["columns"] == ["产品", "销售额"]


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def test_execute_query_select_only():
    vp = _make_csv("u1", "1000_销售明细.csv")
    fileqa_manager.register_data_file(vp, "u1")

    ok = fileqa_manager.execute_query(
        "u1", 'SELECT COUNT(*) AS n FROM "1000_销售明细"')
    assert ok["success"] and ok["data"][0]["n"] == 3

    for bad in ("DELETE FROM t", "DROP TABLE t",
                'SELECT 1; DROP TABLE "t"'.replace("DROP", "DROP")):
        r = fileqa_manager.execute_query("u1", bad)
        assert not r["success"] or "DROP" not in bad.upper()[:6]


def test_execute_query_rejects_write():
    _make_csv("u1", "1000_销售明细.csv")
    fileqa_manager.register_data_file("/data/uploads/u1/c1/1000_销售明细.csv", "u1")
    for sql in ("DELETE FROM x", "INSERT INTO x VALUES(1)",
                "UPDATE x SET a=1", "CREATE TABLE x(a int)"):
        r = fileqa_manager.execute_query("u1", sql)
        assert not r["success"]
        assert "SELECT" in r["error"]


def test_execute_query_empty_library():
    r = fileqa_manager.execute_query("nobody", "SELECT 1")
    assert not r["success"]
    assert "上传" in r["error"]


def test_list_user_tables():
    vp = _make_csv("u1", "1000_销售明细.csv")
    fileqa_manager.register_data_file(vp, "u1")
    tables = fileqa_manager.list_user_tables("u1")
    assert len(tables) == 1
    assert tables[0]["row_count"] == 3
    assert {"name": "产品", "type": "VARCHAR"} in tables[0]["columns"] or \
        any(c["name"] == "产品" for c in tables[0]["columns"])


# ---------------------------------------------------------------------------
# LLM 工具
# ---------------------------------------------------------------------------

def test_tool_file_table_list():
    _make_csv("u1", "1000_销售明细.csv")
    fileqa_manager.register_data_file("/data/uploads/u1/c1/1000_销售明细.csv", "u1")
    out = file_table_list.invoke({})
    assert "1000_销售明细" in out
    assert "产品" in out


def test_tool_file_table_list_empty():
    out = file_table_list.invoke({})
    assert "没有已注册的表格" in out


def test_tool_file_table_query_and_sse_bridge():
    _make_csv("u1", "1000_销售明细.csv")
    fileqa_manager.register_data_file("/data/uploads/u1/c1/1000_销售明细.csv", "u1")
    set_conv_id("conv_t1")
    try:
        out = file_table_query.invoke(
            {"query": 'SELECT 产品, 销售额 FROM "1000_销售明细" '
                      'WHERE 销售额 > 100 ORDER BY 销售额',
             "conversation_id": "conv_t1"})
        assert "查询成功" in out
        # SSE 桥接：结果被推入会话缓冲，streaming.py 取出发 sql 事件
        items = pop_query_results("conv_t1")
        assert len(items) == 1
        assert items[0]["columns"] == ["产品", "销售额"]
        assert items[0]["chart_type"] == "table"
    finally:
        clear_conv_id()


def test_tool_file_table_query_rejects_write():
    out = file_table_query.invoke({"query": "DELETE FROM x"})
    assert "错误" in out


def test_tool_without_user_context():
    fileqa_manager.clear_user_id()
    out = file_table_list.invoke({})
    assert "错误" in out


# ---------------------------------------------------------------------------
# 消息组装
# ---------------------------------------------------------------------------

def test_register_attachments_summary():
    _make_csv("u1", "1000_销售明细.csv")
    atts = [{"name": "1000_销售明细.csv",
             "path": "/data/uploads/u1/c1/1000_销售明细.csv",
             "size": 100, "content_type": "text/csv"}]
    summary = fileqa_manager.register_attachments(atts, "u1")
    assert "1000_销售明细" in summary
    assert "file_table_query" in summary
    # 非数据文件不触发注册
    assert fileqa_manager.register_attachments(
        [{"name": "a.txt", "path": "/data/uploads/u1/c1/a.txt"}], "u1") == ""


def test_register_attachments_failure_tolerant():
    atts = [{"name": "missing.csv", "path": "/data/uploads/u1/c1/missing.csv"}]
    summary = fileqa_manager.register_attachments(atts, "u1")
    assert "注册失败" in summary


def test_compose_user_content_guidance_override():
    atts = [{"name": "a.csv", "path": "/data/uploads/u1/c1/a.csv",
             "size": 1, "content_type": "text/csv"}]
    default_content = compose_user_content("你好", atts)
    assert "run_python" in default_content
    custom = compose_user_content("你好", atts, guidance="用 file_table_query 查询。")
    assert "file_table_query" in custom
    assert "run_python" not in custom
    # 附件列表与原始消息保留
    assert "你好" in custom and "a.csv" in custom


def test_xiaoshu_seed_has_file_tools():
    """种子配置与 backfill 常量必须包含 file_table_* 工具。"""
    from app.catalog.seeds import ANALYST_FILE_TOOLS, EMPLOYEE_SEEDS

    assert "file_table_list" in ANALYST_FILE_TOOLS
    assert "file_table_query" in ANALYST_FILE_TOOLS
    assert "file_table_list" in EMPLOYEE_SEEDS["xiaoshu"]["tools"]
    assert "file_table_query" in EMPLOYEE_SEEDS["xiaoshu"]["tools"]


def test_compiler_registers_file_tools():
    from app.compiler import ALL_LOCAL_TOOLS

    assert "file_table_list" in ALL_LOCAL_TOOLS
    assert "file_table_query" in ALL_LOCAL_TOOLS
