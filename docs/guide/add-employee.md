# 新增数字员工指南

本篇是**动手手册**：从零把一个新数字员工接入平台。原理与设计动机见 [docs/articles/02](../articles/02-how-a-digital-employee-is-compiled.md)。

平台支持两条路径，先想清楚走哪条：

| 路径 | 适用场景 | 改动 |
|---|---|---|
| **A. 资源中心页面化创建** | 单一部署里试一个新员工，不想动代码 | 纯页面操作，管理员账号即可 |
| **B. 代码种子（内置员工）** | 希望新员工随平台分发、所有部署开箱即得 | yaml + seeds.py 注册 + 技能目录 |

两条路径产出的员工能力等价——页面化创建的本质就是把路径 B 的内容在管理页里配置一遍。下面以第七个内置员工 **小察（market-intel，市场情报分析师）** 为贯穿实例讲路径 B。

## 前置概念：员工是一份"岗位说明书"

一个 composed（编排型）员工 = 人设 + 技能规程 + 工具 + 知识库 + 连接器 + 审批策略的**编排**，运行时编译成一个 deepagents agent。所有字段定义在 `backend/app/spec.py` 的 `EmployeeSpec`：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 全局唯一标识（也是目录库主键），小写中划线，如 `market-intel` |
| `name` / `role` | ✅ | 展示名与岗位名（对话页下拉显示 role） |
| `model` | ✅ | 通常写 `${MODEL_NAME}` 占位符，播种时替换为环境变量值 |
| `persona` | ✅ | 人设与工作纪律（追加进 system_prompt） |
| `kind` | — | `composed`（编排型，默认） / `custom`（定制型，如 xiaoshu 有专属工作台模块） |
| `backend` | — | `state`（无文件系统，默认）/ `local_shell`（宿主机 shell 与真实文件）/ `sandbox`（OpenSandbox 容器）。**选型见下表** |
| `skills` | — | 技能 id 列表（对应 `backend/skills/<id>/SKILL.md`） |
| `tools` | — | 本地工具 id 列表（须已登记进 `ALL_LOCAL_TOOLS`） |
| `kbs` / `sops` / `connectors` | — | 知识库 / SOP / MCP 连接器 id |
| `subagents` / `subagent_policy` | — | 内联子代理配置与委派策略（追加进 system_prompt） |
| `interrupt_on` | — | 人工审批策略；**一般留空 `{}`**——配置了 `needs_approval` 的工具会自动推导 |

**backend 选型决策**：

- 默认 `state`：产出走对话内输出（如小察的 HTML 看板）、不需要跑代码 → 选它，最小攻击面；
- `local_shell`：需要 `execute`/`write_file` 真实写盘跑数（如 biz-analyzer 跑 pandas）；
- `sandbox`：执行不可信/重代码，需要容器隔离（如 net-ops）。

## 路径 B：五步接入一个内置员工

### 第 1 步：写员工 yaml

新建 `backend/employees/market-intel.yaml`（真实文件可对照）。骨架与关键写法：

```yaml
id: market-intel
name: 小察
role: 市场情报分析师
kind: composed
model: ${MODEL_NAME}
backend: state   # 看板走对话内输出，无需文件系统
persona: |
  你是小察，……（人设 + 工作纪律 + 技能路由说明）

  ## 技能路由
  当用户消息满足某技能的触发条件时，必须先 read_file 查阅完整规程再执行：

  ### market-daily-brief
  触发条件：……
  规程路径：/skills/market-daily-brief/SKILL.md
skills:
  - market-daily-brief
tools:
  - kb_search
  - bocha_search
  - get_current_time
mcp_servers: {}     # MCP 能力走连接器指派（cons），此处保持空
interrupt_on: {}    # 需审批工具由 needs_approval 自动推导，此处保持空
subagents:
  - name: intel-scouter
    description: 负责联网采集的多轮检索
    system_prompt: |
      你是情报采集员。只负责执行检索并归纳……
    tools:
      - bocha_search
    model: ${MODEL_NAME}
subagent_policy: |
  当任务需要 3 次以上联网检索时，先委派 intel-scouter 子代理……
```

**persona 里最重要的一段是"技能路由"**：平台不会把技能全文塞进 system_prompt（成本高且不可控），而是注入技能摘要，要求模型在命中触发条件时用 `read_file` 去读 `/skills/<id>/SKILL.md`。触发条件写法见[技能规程编写规范](./skill-authoring.md)。

### 第 2 步：写技能目录

新建 `backend/skills/market-daily-brief/SKILL.md`（一个技能一个目录，frontmatter + 正文，详见[编写规范](./skill-authoring.md)）。技能目录是**全局共享**的：所有员工从同一池子里选，所以技能内容里不要写死某个员工的专属信息。

### 第 3 步：注册进种子表

`backend/app/catalog/seeds.py` 的 `EMPLOYEE_SEEDS` dict 追加一项（yaml 之外**必须**注册这里，员工才会播种）：

```python
"market-intel": dict(
    skills=["market-daily-brief", "competitor-deep-dive", "market-alert-triage"],
    tools=_tools_with_ontology(["kb_search", "bocha_search", "get_current_time"]),
    kbs=[], sops=[], cons=["newsnow", "playwright"]),
```

- `tools`：只能填已登记进 `ALL_LOCAL_TOOLS`（`backend/app/compiler.py`）的 id；`_tools_with_ontology()` 是内置员工的统一包装，追加两个本体查询工具；
- `cons`：MCP 连接器 id，必须在 `CONNECTOR_SEEDS` 里存在；
- `sops`：刚性 SOP 的 id（内容定义在同一文件的 `NETOPS_SOPS` 式列表里）。

如果员工要用新连接器，同步更新 `CONNECTOR_ASSIGN`（老库幂等回填指派用）：

```python
CONNECTOR_ASSIGN = {"crm": ["xiaoxiao", "hrbp"], "newsnow": ["xiaoshu", "market-intel"], ...}
```

### 第 4 步：老库幂等补缺（已有部署的升级路径）

播种规则：`seed_if_empty()` **只对空库全量播种**；老库升级靠各 `backfill_*` 函数（`main.py` lifespan 启动时调用）：

- **员工本身不用写 backfill**——`backfill_employees_if_missing()` 会自动把 `EMPLOYEE_SEEDS` 里缺失的员工补种进老库（含技能目录扫描、授权给全部现有用户）；
- 只有员工**新增工具/新审批标记**等字段级补缺才需要写 backfill（参考 `backfill_market_intel_v2()`：`INSERT OR IGNORE` 工具表与指派表，不覆盖管理员改动）。

### 第 5 步：测试与验证

在 `tests/test_catalog.py` 仿 `test_backfill_employees_if_missing_adds_market_intel` 加用例：断言新员工名称/技能/工具/连接器指派，并模拟老库删除后 backfill 补回、幂等重跑。然后：

```bash
PYTHONPATH=backend .venv/bin/python -m pytest tests/ -q   # 项目根目录跑
```

重启服务（`--reload` 下改后端代码也会清缓存），对话页下拉即出现新员工。

## 必须知道的四个坑位

1. **改 yaml 的 persona 对已有库不生效**——persona 播种进 catalog 库后以库为准。改内置员工人设：清库重播种，或资源中心改，或 SQL 更新。
2. **改工具/人设/连接器后不热生效**——`get_agent` 按"员工+用户+模型"缓存编译结果，需重启服务（`--reload` 下改后端代码也会顺带清缓存）。
3. **SKILL.md 是例外，可以热改**——技能内容运行时同步进 Store（`sync_skills_to_store`），编辑后刷新 Store 即可，不必重编译。
4. **技能目录全局共享**——为一个员工改 SKILL.md 会影响所有引用它的员工；员工间要差异化时复制目录改 id。

## 端到端实例：小察的完整文件清单

```
backend/employees/market-intel.yaml            # 员工定义
backend/skills/market-daily-brief/SKILL.md     # 技能 ×3
backend/skills/competitor-deep-dive/SKILL.md
backend/skills/market-alert-triage/SKILL.md
backend/app/catalog/seeds.py                   # EMPLOYEE_SEEDS + CONNECTOR_ASSIGN 注册
backend/app/tools/publish_tools.py             # （可选）该员工的新工具
tests/test_catalog.py                          # 补种回归用例
```

一个不含新工具的纯编排员工，净新增只有 yaml + 技能目录 + seeds 三处——这也是"编排型"设计的意图：员工是配置和规程，不是代码。

## 相关文档

- [技能规程编写规范](./skill-authoring.md)
- [自定义工具开发](./custom-tools.md)
- [配置参考](./configuration.md)
- 原理深读：[一个数字员工是如何被"编译"出来的](../articles/02-how-a-digital-employee-is-compiled.md)
