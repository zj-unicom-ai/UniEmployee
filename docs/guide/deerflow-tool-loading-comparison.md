# DeerFlow 工具加载机制与 UniEmployee 借鉴评估

> 源码基线：UniEmployee `0951e32`；本地 DeerFlow `fc9fb2de`。核对时间：2026-09-27。DeerFlow 源码目录：`/Users/wrg/mystudy/deer-flow`。本文重点是源码和当前本地配置，不把仓库中存在的所有实现误当成默认启用能力。

## 1. 结论摘要

DeerFlow 的工具不是一个“默认全量工具包”。它把工具分成了几层：

1. **Harness 自带的流程工具**：例如向用户展示产物、请求澄清、技能包审核；少量固定进入普通 Agent，其他的按子代理、上传、视觉、任务运行环境等条件装配。
2. **配置选择的工具实现**：`config.yaml -> tools[] -> use` 用 Python 类路径选择一个实现。社区目录里有很多搜索、抓取、知识库、浏览器实现，但只有配置启用的工具进入 Agent。
3. **MCP 外部工具**：启动/构建时读取已启用 MCP server 并发现其工具；可选的 `tool_search` 会把 MCP 工具 schema 延后暴露，避免一次把所有 schema 放进模型上下文。它不是下载或安装工具。
4. **插件工具**：从安装的 DeerFlow extension/plugin 注册表加载，经过管理员启用、分组和 schema 校验后进入普通工具链。
5. **沙箱能力**：`ls/read_file/write_file/bash` 等按配置选择并受 sandbox 条件限制；它们不是“业务集成工具”，执行后端另由 Sandbox Provider 配置。

因此最值得 UniEmployee 学的是**工具目录/来源元数据、按业务授权过滤、工具 schema 延迟发现、外部 MCP 生命周期与状态诊断**，不是照搬 DeerFlow 的搜索 provider 数量。当前 UniEmployee 已有按员工配置工具、MCP connector 和统一授权；当前主要差距是工具实现注册仍需改代码、MCP schema 在员工编译时整批发现、Agent 缓存使改动生效边界不直观，也缺少面向管理员的“本次员工最终工具清单及未加载原因”诊断。

## 2. DeerFlow 内置工具清单

### 2.1 固定与条件装配的 Harness 工具

| 工具 | 装配条件/用途 | 是否所有 Agent 默认可用 |
|---|---|---|
| `present_files` | 让用户看到输出目录中的文件 | 是，普通工具组默认项 |
| `ask_clarification` | 向用户请求补充信息；交互策略可将其关闭 | 常见交互 Agent 有；非交互/调度任务可移除 |
| `review_skill_package` | 审核技能包内容 | 是，普通工具组默认项 |
| `list_uploaded_files` | 列出本轮已上传文件 | 通常包含；调用方可关闭，子代理需先获得父任务上传状态快照 |
| `view_image` | 读取图片供视觉模型使用 | 仅模型配置支持 vision 时加入 |
| `task` | 将任务委派给子代理 | 仅开启 subagent 后加入 |
| `batch_task` / `batch_status` / `cancel_batch` | 子代理持久化批量任务管理 | 子代理已启用且 SQL-backed batch runtime 已安装时加入 |
| `list_background_tasks` / `cancel_background_task` | 管理当前会话的长时 MCP 任务 | 仅安装了 MCP task runtime 时加入 |
| `skill_manage` | 技能进化/管理 | 仅 `skill_evolution.enabled` 时加入 |
| `invoke_acp_agent` | 调用配置好的外部 ACP Agent | 只有配置了 ACP Agent 才生成 |
| `setup_agent` | 创建自定义 Agent 的引导阶段持久化配置 | 只在 bootstrap 构建路径加入 |
| `update_agent` | 自定义 Agent 持久化更新自身配置 | 仅自定义 Agent 正常会话加入；webhook 会移除 |
| `tool_search` | 搜索并提升延迟暴露的 MCP 工具 schema | 仅 `tool_search.enabled=true` 且存在 MCP 工具时加入 |

依据：DeerFlow `tools/tools.py` 的 `BUILTIN_TOOLS`、`SUBAGENT_TOOLS` 与 `get_available_tools()` 条件分支；lead-agent 在自身 build path 另外装配 `setup_agent` 和条件式 `update_agent`。注意工具文件存在不等于该工具必然进入某个 Agent。

### 2.2 配置选中的本地/社区工具

DeerFlow 的 `config.yaml` 把每个工具定义为 `name/group/use` 等参数；运行时用 `resolve_variable(cfg.use, BaseTool)` 解析 Python 类路径。当前本地 `config.yaml` 配置的业务/平台工具为：

| 工具名 | 当前选中的实现 | 能力类别 |
|---|---|---|
| `web_search` | `deerflow.community.ddg_search.tools:web_search_tool` | DuckDuckGo 网页搜索 |
| `web_fetch` | `deerflow.community.jina_ai.tools:web_fetch_tool` | Jina Reader 网页正文提取 |
| `image_search` | `deerflow.community.image_search.tools:image_search_tool` | DuckDuckGo 图片搜索 |
| `ls`, `read_file`, `glob`, `grep` | `deerflow.sandbox.tools:*` | 沙箱文件读取/查找 |
| `write_file`, `str_replace` | `deerflow.sandbox.tools:*` | 沙箱文件写入 |
| `bash` | `deerflow.sandbox.tools:bash_tool` | 命令执行；LocalSandbox 下默认不暴露 host bash |

**对当前这份 DeerFlow 配置做了运行时核验**：用其 backend venv 调用 `get_available_tools(include_mcp=False, app_config=get_app_config())`，实际返回 14 个工具：`web_search, web_fetch, image_search, ls, read_file, glob, grep, write_file, str_replace, present_files, ask_clarification, review_skill_package, list_uploaded_files, view_image`；`tool_search_enabled=False`。`bash` 未出现是因为本地 sandbox 配置默认不允许 host bash；`task` 未出现是因为这次核验显式使用默认 `subagent_enabled=False`。核验没有初始化 MCP 外部服务，故结果不包含 MCP 工具；仓库根目录也没有 `extensions_config.json`。

源码内可选社区 provider 远多于当前激活项，按用途归纳如下：

| 用途 | 可选实现（仓库已有代码） |
|---|---|
| 网页搜索 | `ddg_search`, `searxng`, `serper`, `serply`, `brave`, `tavily`, `infoquest`, `tencent_wsa`, `exa`, `firecrawl`, `groundroute`, `fastcrw`, `sofya` |
| 网页抓取/读取 | `jina_ai`, `exa`, `infoquest`, `firecrawl`, `groundroute`, `fastcrw`, `sofya`, `browserless`, `crawl4ai` |
| 图片搜索 | `image_search`, `infoquest`, `serper`, `brave` |
| 知识检索 | `ragflow`, `lightrag` |
| 浏览器交互 | `browser_automation`：`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_back`, `browser_screenshot`, `browser_close` |

上述是“实现选项”，有些要求 API key，有些要求可选依赖或独立服务。很多配置示例是注释状态；配置时同名 provider 应选一个（例如一个 `web_search` 对应一个 provider），不能据此推断所有实现都被同时加载。`community/` 里还包括沙箱 provider/适配器（如 BoxLite、E2B、AIO Sandbox、Tenki），它们配置的是执行后端，不应计入默认业务工具数量。

## 3. DeerFlow 的动态加载具体指什么

| 装载机制 | 实际行为 | “动态”的边界 |
|---|---|---|
| `config.yaml -> tools[]` | 读取配置中的 `use` 类路径并实例化工具，按 `groups`、知识 capability、sandbox 条件裁剪 | 可通过换配置选择不同 provider；不是 Agent 自行发现整个 `community/` |
| MCP 初始化与缓存 | 根据 `extensions_config.json` 中 enabled server 调用 MCP adapter 发现工具；工具列表带 MCP provenance，缓存按有效配置变化检查/刷新 | 新工具来源在外部 MCP server；服务配置要先存在且启用 |
| `tool_search` 延迟 schema | 编译 Agent 时先拿到 MCP 工具候选目录；仅向模型显示工具名，模型查询后返回至多 5 个完整 schema 并记录 thread 内 promotion；中间件再控制 schema 可见与执行 | 延迟的是模型上下文中的 schema 暴露；工具实现及连接早已通过 MCP discover 加载，非现场安装/下载 |
| MCP routing auto-promote | `routing.mode=prefer` 和关键词配置可在模型调用前自动提升部分 deferred schema，默认 `top_k=3`、限制 1–5 | 只影响候选 schema 暴露，不代表授权；skill policy 仍过滤可见与执行 |
| Extension plugin registry | 启动时从配置的已安装插件中加载 `PluginContribution`；工具做命名空间前缀、schema 校验、管理员 enabled 检查、输入/输出大小限制和 30 秒执行限制 | 插件代码需要部署/安装，配置启用后加载；不是任意模型文本就能注册代码 |
| 运行环境条件注入 | 根据视觉模型、subagent、上传状态、ACP 配置、长任务 runtime 添加对应工具 | 条件式装配，构建出来的 Agent 工具清单仍是明确集合 |

此次本地源码配置 `tool_search.enabled=false`，且没有根级 `extensions_config.json`；因此不能说此工作副本当前启用了 MCP 延迟发现或 MCP 工具。`tool_search` 的功能代码存在，但当前配置并未让它工作。

## 4. UniEmployee 当前工具加载链路

UniEmployee 采用“员工配置 → 编译器装配 → Agent 缓存”的路径：

1. Catalog 的 `employee_tools`、`employee_connectors` 关系形成员工的 `spec.tools` 与 `spec.mcp_servers`。
2. `compiler.ALL_LOCAL_TOOLS` 静态登记本地工具；`_assemble_tools()` 依据 `spec.tools` 按名选择。
3. `kb_search`、退款工具、ontology 工具由闭包/工厂按员工、用户、checkpointer 运行时构造，不全在静态表内。
4. MCP 在编译 Agent 时按已绑定 connector 启动 MultiServerMCPClient 并 `get_tools()`；所有发现到的工具再经过 guard policy。
5. DeepAgents 的 `FilesystemMiddleware` 单独提供文件系统工具；非 admin 通过白名单限制只读。随后把 tool list 传入 `create_deep_agent()`。
6. `runtime.get_agent` 按员工/用户/模型缓存编译 Agent；员工工具/连接器权限变更需要使相关缓存失效或重启，单改 Python 注册表也不等于运行中的 Agent 自动热加载。

与 DeerFlow 相同点：都将 LangChain `BaseTool` 接入 LangGraph/DeepAgents Agent；MCP 都使用 LangChain 生态适配。不同点：UniEmployee 的工具授权主轴是 catalog 中“员工绑定 + 用户/角色 guard + connector grant”，DeerFlow 还有技能激活后的 tool policy、MCP schema promotion、中间件过滤/审计和 extension contribution 路径。

## 5. 值得借鉴的点及收益判断

| 借鉴项 | UniEmployee 当前不足 | 做好后的具体价值 | 建议优先级与边界 |
|---|---|---|---|
| **工具清单诊断**：返回员工最终工具、来源（local/closure/MCP/filesystem）、授权结果、未加载原因、配置快照/版本 | 现在主要从资源配置、后端日志和运行回答侧面确认；员工最终装配结果不够集中、可解释 | 管理员能回答“为什么这个员工看不到 CRM 查询？”；缩短联调和权限排查时间，降低误以为能力已授权的风险 | **P0，低风险高收益**。先只读展示/诊断，不碰 Agent 权限决策 |
| **工具 provenance/稳定 ID**：记录工具来自哪个 connector/provider、版本及调用来源 | MCP 工具调用留有来源参数做 guard，但工具清单/Trace 层的来源描述有限；同名工具在跨 connector 的呈现需强化 | 审计能回溯实际数据来源、责任连接器及耗时/失败归属；连接器同名工具歧义更容易发现 | **P1**。和清单诊断合并设计；名称冲突策略需确定（禁止或 namespace） |
| **对大型 MCP 工具集延迟 schema**：先列工具目录，选中后才加入模型 schema | UniEmployee 在 Agent compile 时把连接器返回的 MCP 工具全部装配；没有 DeerFlow 式按 query 找 schema 的能力 | MCP server 工具多时减少每轮模型输入 token、降低工具误选；增加工具时避免 prompt/context 持续膨胀 | **条件式 P2**。CRM Lab 目前小工具集没有足够收益；先采集单 Agent MCP 工具数和 schema token 体积，达到可证阈值再做。发现 schema 不应放宽现有 connector/role/employee 授权 |
| **统一工具 Provider/扩展接口**：以声明式清单包装可插拔 provider，带 schema、配置、依赖和授权元数据 | 新本地工具需要改 `compiler.py` 注册表与资源播种；MCP 独立走 connector path；两条路径没有统一的管理员诊断视图 | 新增集成能复用校验、授权、生命周期、诊断，而不是新增多个特例；降低后续 CRM/工单/文档等 connector 接入成本 | **P2，需求触发**。不要为了“插件化”重写现在的小型注册表；等待第二/第三个同类业务 connector 后判断抽象收益 |
| **MCP/Agent 缓存刷新与健康状态** | DeerFlow 有工具缓存失效/重建，UniEmployee 编译缓存和 MCP client 生命周期更多依赖服务重启/显式 invalidation | 管理员调整 connector 后能看到待生效、已生效、失败状态，避免旧 schema 持续服务或盲目重启 | **P1**。优先清晰展示 reload 边界 + 主动失效和失败回滚；跨进程实时热加载需后续证据 |
| **以场景裁剪的工具 capability** | UniEmployee 已能按员工勾选并做 guard，filesystem 和 ontology 也有粒度约束 | 避免所有员工都看到或承担无关工具 schema；缩小误操作/误选范围 | **保留并补诊断**。现有模型已经适合业务员工，不需照搬 DeerFlow skill middleware |

## 6. 可行性及不建议照搬的内容

- **兼容性高**：工具目录诊断、source/provenance 字段、工具清单版本；不改变 LangChain `BaseTool` 或 `create_deep_agent` 接口，可以在 `_assemble_tools()` 返回之前/之后组织只读元数据。
- **兼容性中**：MCP 工具缓存刷新和 health status；需与当前 `runtime.get_agent` 缓存、持有中的 MCP client 关闭、会话执行中的工具对象生命周期对齐。应定义“旧会话继续用旧工具，新会话使用新版本”或明确要求重启，避免半路替换。
- **兼容性中低/仅按需**：deferred schema discovery；需要新增 per-thread promotion state、中间件拦截和重试提示，还要验证 deepagents 版本下工具 schema bind/执行可见性同步。DeerFlow 实现不能直接复制，因为它依赖自己的 state middleware、tool policy 和 build sites。
- **不建议现阶段迁移整套 DeerFlow tool middleware、Community providers 或 plugin host**：UniEmployee 已有资源中心、员工授权、工具护栏、MCP 与本体工具；整体搬迁重复实现，会扩大运行边界而没有验证过的使用者收益。
- **LangChain/LangGraph 基础相似不等于组件可直接搬运**：`BaseTool` 和 MCP adapter 提供可复用的接口概念；具体工具装配、状态模型、Agent 生命周期和权限策略依赖不同 harness。建议按接口语义借鉴，在 UniEmployee 侧做适配层。

## 7. 建议的迭代顺序与验收

1. **P0：做工具装配诊断**。对一个员工返回最终工具名称、来源、绑定 connector、授权/裁剪原因、生效配置版本；CRM Lab 做正反用例：已授权存在、未授权不存在、connector 离线/配置错误时状态明确。验收：不调用模型即可定位为何工具可见/不可见，诊断接口不能泄露密钥。
2. **P1：补 MCP 生命周期反馈**。展示 connector 健康/最后发现时间/发现到的工具名/错误与缓存版本；配置改变后明确显示“需要重新编译/已刷新/刷新失败”。验收：编辑 connector 配置后能够证明下一次 Agent compile 使用新工具集，失败不丢失旧可用状态或清楚提示不可用。
3. **P1：补工具调用来源 Trace**。把工具名映射到本地工具 ID 或 MCP connector/tool ID，日志记录成功、拒绝、失败，不记录凭据。验收：从一次 CRM 查询 Trace 可还原员工、工具、connector、耗时与拒绝理由。
4. **P2 条件项：延迟 schema discovery**。先采集 1–2 个 MCP 服务的工具数量、模型工具 schema token 占比和误选率。只有当工具规模/context 成本或选错率带来具体问题时，再实现 query/search → schema promotion；在 promotion 与执行两层都应用同一授权策略并加回归验收。
5. **P2 条件项：Provider 插件化**。当连续接入多个本地工具适配器、重复的注册/配置代码可以被量化时，再抽象 Provider contract；否则保持现有清晰注册表，避免先造扩展平台。

## 8. 源码与核验记录

UniEmployee 关键代码：

- `backend/app/compiler.py`：`ALL_LOCAL_TOOLS`、`GLOBAL_TOOL_NAMES`、`_assemble_tools()`、MCP `get_tools()` 与 guard 处理、`create_deep_agent()`。
- `backend/app/catalog/employees.py`：从 catalog 读员工工具/connector 绑定，构造 spec。
- `backend/app/runtime.py`：员工/用户 Agent 与 MCP client 缓存及失效入口。
- `backend/app/catalog/seeds.py`：当前默认工具/connector 种子及员工绑定。

DeerFlow 关键代码（本机源码 commit `fc9fb2de`）：

- [`tools/tools.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/tools/tools.py:34>)：`BUILTIN_TOOLS`、`get_available_tools()`、配置工具解析、MCP 与 ACP、插件汇总。
- [`tool_search.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/tools/builtins/tool_search.py:142>)：deferred MCP catalog、schema 搜索和 promotion。
- [`tool_search_config.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/config/tool_search_config.py:10>)：延迟发现开关，默认 `false`。
- [`lead_agent/agent.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py:1087>)：lead Agent build path 追加 bootstrap/self-update 工具及 tool_search 装配。
- [`plugin_tools.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/extensions/plugin_tools.py:96>)：插件工具 schema、namespace、settings 和执行限制。
- [`tools/AGENTS.md`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/tools/AGENTS.md:25>)：Harness 工具语义和可选 Community/ACP 工具概览。

**运行时核验范围**：DeerFlow backend venv + 仓库当前 `config.yaml`；执行 `get_available_tools(include_mcp=False, app_config=get_app_config())`。它确认了本地配置实际生效的 14 个工具及 `tool_search=false`，没有连接外部 MCP 服务，也没有验证 MCP server 在线行为或扩展插件安装行为。此边界避免把静态源码存在性说成动态服务已经运行。
