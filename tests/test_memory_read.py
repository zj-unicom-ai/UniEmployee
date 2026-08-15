"""回归：记忆按 (user_id, emp_id) 隔离，且新会话能读到该用户记忆。

根因：早期实现在 _mem_namespace 里**运行时**调
get_config()["configurable"]["user_id"] 取 user_id。abefore_agent（加载记忆）
阶段 langgraph 的 config 上下文尚未就绪，get_config() 取不到 → 回退
"default" → 新会话读不到该用户记忆；但工具调用「写记忆」时
get_config() 可取 → 能写入，造成「写进、读不出」。

修复：get_agent 本就按 (emp_id, user_id) 缓存 agent，编译期 user_id 已知，
直接闭包捕获进命名空间（与技能路由同款写法）。本测试锁定该契约。
"""
import asyncio

from app.compiler import build_backends, memory_namespace, EmployeeSpec
from deepagents.backends.utils import create_file_data
from langgraph.store.sqlite import AsyncSqliteStore


def _spec() -> EmployeeSpec:
    return EmployeeSpec(
        id="xiaoshu", name="小数", model="openai:deepseek-v4-flash",
        persona="你是数据分析助手",
    )


def test_memory_namespace_closure_captures_user_id():
    # 闭包捕获 user_id，不依赖 get_config()
    assert memory_namespace("u_1", "xiaoshu") == ("u_1", "xiaoshu")
    # 管理员/模板路径 user_id=None → "default"
    assert memory_namespace(None, "xiaoshu") == ("default", "xiaoshu")


def test_build_backends_memory_namespace_uses_user_id():
    spec = _spec()
    # 不同用户 → 记忆命名空间不同（隔离）
    ns_a = build_backends(spec, None, user_id="u_A").routes["/memories/"]._namespace(None)
    ns_b = build_backends(spec, None, user_id="u_B").routes["/memories/"]._namespace(None)
    assert ns_a == ("u_A", "xiaoshu")
    assert ns_b == ("u_B", "xiaoshu")
    assert ns_a != ns_b
    # 技能命名空间也按用户隔离：#72 允许用户覆盖各自技能集合
    assert build_backends(spec, None, user_id="u_A").routes["/skills/"]._namespace(None) == ("u_A", "xiaoshu")


def test_memory_read_resolves_per_user_namespace(tmp_path):
    # 用 build_backends 产出的命名空间直接读 store，验证「新会话读得到该用户记忆」
    db = tmp_path / "store.db"

    async def go():
        async with AsyncSqliteStore.from_conn_string(str(db)) as store:
            await store.aput(
                ("u_X", "xiaoshu"), "/AGENTS.md",
                create_file_data("## 用户档案\n- 测试名字：张三\n"),
            )
            # 与运行时（abefore_agent）完全一致：build_backends 决定命名空间
            ns = build_backends(_spec(), store, user_id="u_X").routes["/memories/"]._namespace(None)
            assert ns == ("u_X", "xiaoshu")
            item = await store.aget(ns, "/AGENTS.md")
            assert item is not None
            assert "张三" in item.value["content"]
            # 另一个用户读不到 u_X 的记忆
            other = await store.aget(("u_OTHER", "xiaoshu"), "/AGENTS.md")
            assert other is None

    asyncio.run(go())
