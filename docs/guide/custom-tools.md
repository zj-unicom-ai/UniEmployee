# 自定义工具开发指南

工具是员工的手脚。本篇讲怎么写一个本地工具并接进平台：从 `@tool` 装饰到登记注册、审批标记、运行时上下文与产物文件推送。

两种给员工加能力的方式先分清：

| | 本地工具（本篇） | MCP 连接器 |
|---|---|---|
| 适用 | 平台内闭环能力：查库、搜文档、生成文件、调内部服务 | 外部标准服务/复用现成 MCP server |
| 实现 | `backend/app/tools/` 下的 Python 函数 | `CONNECTOR_SEEDS` 里登记 stdio/http 配置 |
| 审批 | `needs_approval` 一行配置 | 由连接器侧/护栏配置 |
| 参考 | `bocha_search`、`publish_briefing` | `newsnow`、`playwright`、`crm` |

## 最小可用工具

```python
# backend/app/tools/time_tools.py
from langchain.tools import tool

@tool
def get_current_time() -> str:
    """【获取当前时间】返回当前真实日期时间（东八区）。"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
```

要点：

- **docstring 就是给模型看的工具说明书**——第一行概括用途，参数说明写清格式与示例。模型靠它决定何时调用、怎么传参，按"模型的说明书"标准写，不是给程序员看的注释；
- 工具函数保持**幂等、可重试、失败返回可读文本**而不是抛裸异常（异常会中断 run；返回"检索失败，请……"让模型能自行调整策略）。

## 三处登记，缺一不可

1. **`backend/app/compiler.py` → `ALL_LOCAL_TOOLS`**：全量本地工具注册表，员工按 id 从这里挑：

```python
from app.tools.publish_tools import publish_briefing
ALL_LOCAL_TOOLS = { ..., "publish_briefing": publish_briefing, }
```

2. **`backend/app/catalog/seeds.py` → tools 表种子**（员工选择列表与资源中心展示）：

```python
("publish_briefing", "发布市场简报", "把生成的市场简报看板提交发布（需人工审批……）", "local",
 json.dumps(["approve", "reject"])),   # 第四列 needs_approval
```

3. **指派给员工**：`EMPLOYEE_SEEDS[emp]["tools"]` 加 id（老库用 backfill 幂等补，见下）。

## 需要人工审批的工具

在 tools 表种子里给 `needs_approval` 配决策列表（通常是 `["approve", "reject"]`），编译层 `_build_interrupt_on()` 会自动把它派生进员工的 `interrupt_on`——模型调用该工具时整个 run **挂起**，会话出审批卡，管理员批准后才真正执行：

- 适用于一切**对外/不可逆**动作：发通知、发工单、退款、发布简报；
- 拒绝时模型会收到"审批人已拒绝该请求"，应引导它在后续回答里说明取消原因；
- 参考实现：`app/tools/publish_tools.py`（发布归档 + 可选 webhook）、`app/tools/kb.py` 的 `create_ticket`。

## 运行时上下文：知道"我是谁、在哪个会话"

工具执行在 LangGraph 运行时里，通过 `get_config()` 拿上下文：

```python
from langgraph.config import get_config

cfg = get_config() or {}
user_id  = (cfg.get("configurable") or {}).get("user_id")    # 当前登录用户
conv_id  = (cfg.get("configurable") or {}).get("thread_id")  # 会话 id
```

**纪律**：需要按用户落盘/落库的工具，取不到 `user_id` 必须**显式报错拒绝**，不能静默回退共享目录——参考 `generate_solution_doc` 与 `publish_briefing` 的防御式写法。

## 产物文件：让用户"看得见、下得了"

写真实文件的工具（Word 文档、HTML 归档），遵守两条约定即可自动获得前端文件卡片：

1. 文件写到 `app.paths.WORKSPACE_DATA`（即 `workspace/data/`）**按用户隔离的子目录**：`WORKSPACE_DATA / user_id / <业务目录>/`；
2. 在 `streaming.py` 的产物探测工具列表（`write_file/execute/edit_file/run_python/publish_briefing`）加上你的工具名——流会自动 diff 出新增文件、推 `file` 事件并落库 `conversation_files`，前端渲染成可下载卡片，历史会话恢复同样可见。

注意 `backend=state` 的员工**没有** `write_file`，写盘只能由工具函数本身完成（工具跑在服务端，与员工后端无关）。

## 老库补缺（backfill）

新工具对老库要在 `seeds.py` 加一个幂等 backfill（`INSERT OR IGNORE`，不覆盖管理员改动），并在 `main.py` lifespan 调用：

```python
def backfill_market_intel_v2():
    con = _conn(); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO tools(id,name,description,source,needs_approval) VALUES(?,?,?,?,?)",
                ("publish_briefing", "发布市场简报", "……", "local", json.dumps(["approve", "reject"])))
    if cur.execute("SELECT 1 FROM employees WHERE id='market-intel' AND deleted_at IS NULL").fetchone():
        cur.execute("INSERT OR IGNORE INTO employee_tools VALUES('market-intel','publish_briefing')")
    con.commit(); con.close()
```

完整实例见 `backend/app/catalog/seeds.py`。

## 测试要点

- 目录库层面：工具登记、员工指派、`_build_interrupt_on` 派生出 `{"allowed_decisions": [...]}`（参考 `tests/test_catalog.py::test_backfill_market_intel_publish_tool`）；
- 纯函数逻辑（文件名清洗、HTML 包装等）抽成模块级函数直接单测，不依赖运行时；
- 带 `get_config` 的工具函数体较难直测——把可测逻辑抽出来，配置读取留薄壳。

## 相关文档

- [新增数字员工指南](./add-employee.md)——工具指派进员工
- [配置参考](./configuration.md)
- 原理深读：[一个数字员工是如何被"编译"出来的](../articles/02-how-a-digital-employee-is-compiled.md)
