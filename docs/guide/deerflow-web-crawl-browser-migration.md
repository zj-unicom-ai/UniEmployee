# DeerFlow 网页抓取与浏览器交付：源码对比和迁移决策

> 源码基线：UniEmployee `0951e32`；本机 DeerFlow `fc9fb2de`。核对日期：2026-09-27。DeerFlow 本地目录：`/Users/wrg/mystudy/deer-flow`。这是代码架构评估，不代表抓取成功率、业务采纳率或 ROI 已在真实业务中验证。

## 1. 决策摘要

**可迁移，但不应该把 DeerFlow 的整套浏览器子系统搬进来。** 应当把“网页抓取”和“浏览器交付”作为两个独立能力决策：

1. **网页正文抓取（建议近期优先评估）**：UniEmployee 已有搜索摘要和 Playwright MCP，但没有面向“读取搜索结果 URL、提取正文、返回来源”的一等工具。小范围增加只读 `web_fetch` 能补齐“搜索 → 阅读原文 → 有来源地回答”链路。它可限制在需要调研的员工，通过现有工具授权、Trace、SSE 和文件/消息结果承载，无需改 Agent 主框架。
2. **浏览器操作工具（已有基础，先核验配置和真实可用性）**：UniEmployee 的 catalog 已播种官方 Playwright MCP connector，并分配给 `net-ops`、`market-intel`。这能让 Agent 通过 MCP 工具操作 headless 浏览器；工具 schema 在员工编译时发现并纳入 Agent。DeerFlow 的稳定引用、动作后快照、SSRF 和会话治理值得借鉴，不能从“配置存在”推断每个员工当前都能使用或运行时服务一定在线。
3. **浏览器实时交付（暂不优先移植）**：DeerFlow 的 Live Browser 是一套额外产品能力：服务端保存有状态浏览器、REST/WS 按会话授权、JPEG 实时帧、前端远程鼠标键盘、地址栏/Tab 同步，并与 Agent 工具共享会话。UniEmployee 当前没有浏览器页面路由、浏览器会话服务或实时画面面板。除非真实任务需要用户看页面、登录后接管或人机协作，否则这一大块会带来明显的安全、运维和前端成本，当前合成 CRM 场景还无法证明它值回投入。

建议：先补 **P0 网页读取闭环设计/核验**（在评测任务中确认缺失确实影响结果，并估测来源读取需求）；若成立，再做有边界的只读抓取；浏览器 Live 作为有真实流程样本后启动的 **P2 选项**。已有 Playwright MCP 则作为现阶段浏览器自动化验证入口，不重复造轮子。

## 2. DeerFlow 具体怎么实现

### 2.1 网页搜索后的只读抓取

当前本地 `config.yaml` 激活的 `web_fetch` 指向 `deerflow.community.jina_ai.tools:web_fetch_tool`。实现步骤是：

1. 模型只能提交用户给过或搜索工具返回的**精确 URL**，工具说明明确禁止补 `www`，要求完整 scheme，并说明不能读需要认证的页面。
2. `JinaClient` 将页面请求交给 Jina Reader（`https://r.jina.ai/`），可配置 timeout、proxy、`trust_env` 和可选 API key。
3. 返回 HTML 后由 `ReadabilityExtractor` 提取正文，再转成 Markdown，最多交给模型 4096 个字符。

因此它是一条简单、可替换的“远端抓取服务 + 正文抽取”链路，不维护浏览器状态，也不执行点击、登录或表单提交。DeerFlow 仓库还有 Crawl4AI、Browserless 等可选实现：Crawl4AI 指向独立服务，可配置过滤模式；Browserless 可渲染动态页面并提供截图/正文工具。这些是 provider 备选实现，不代表当前 `config.yaml` 同时启用了它们。

**设计价值**：搜索摘要常常不足以支持核实或归纳，读取原文能补上下文和引用依据；使用 provider 抽正文比每次启动完整浏览器更轻。**局限**：依赖第三方服务或单独部署服务；受站点反爬、地区、动态页面、版权/访问条款影响；固定 4096 字符可能截掉后文；不能读取登录墙内的内容。

### 2.2 Agent 的有状态浏览器工具

DeerFlow `browser_automation` 暴露 8 个工具：

| 工具 | 用途 |
|---|---|
| `browser_navigate` | 打开 http(s) 页面并返回标题、URL、交互元素快照 |
| `browser_snapshot` | 重新观察当前页面和可交互元素 |
| `browser_click` | 根据最近快照中的 `[ref]` 编号点击 |
| `browser_type` | 向指定元素输入/填充内容，可选提交 |
| `browser_get_text` | 获取当前页面文本（有长度限制） |
| `browser_back` | 浏览器后退 |
| `browser_screenshot` | 截图并作为可交付 artifact 保存 |
| `browser_close` | 关闭该 thread 的会话 |

关键实现不是“提示模型猜 CSS 选择器”，而是每次 snapshot 给可见控件生成临时 `[ref]`，点击/输入后再返回新快照。过期引用会失败并促使模型重新观察。Playwright 放在一个私有 daemon asyncio loop 线程中，因为 Playwright 对象绑定创建它的事件循环，而 Agent/Gateway 调用方可能处于不同 loop。会话按 `thread_id` 保存，缺省上限 32 个，30 分钟空闲清理；满载时优先淘汰未 pin 会话，全部占用则拒绝新会话。浏览器依赖按可选依赖延迟导入。

安全和运行边界包括：默认只允许 public HTTP(S) URL；对导航/重定向/子资源都做 SSRF 检查；访问私网地址必须显式配置。CDP 连接到已有 Chrome 时无法安装相同请求拦截器，所以除非显式开启 `allow_unguarded_cdp`，默认拒绝此不安全模式。浏览器会话进程内存储，不支持多个 Uvicorn worker；源码明确要求 `GATEWAY_WORKERS=1` 或禁用浏览器工具。会话容量、单 viewer 限制和清理属于功能本身，不是部署后可以忽略的细节。

### 2.3 “浏览器交付”具体交付了什么

DeerFlow 同时把浏览器能力交付给 Agent 和用户：

- **Agent 侧进展与产物**：每次工具动作尝试保存一张压缩 JPEG；快照文本和 `browser_view` 元数据一起进入 ToolMessage；图片作为 thread artifact 供工作区查看。中间进度帧放在隐藏 `.browser-frames` 下，避免污染用户的正式文件变更清单。显式 `browser_screenshot` 则可作为正式交付物。
- **用户侧 Live 面板**：前端 `BrowserViewPanel` 显示 JPEG，地址栏可导航；鼠标点击、键盘、文本、滚轮、后退/前进、tab 操作通过 WebSocket 发回服务端。后端通过有界队列在慢客户端时丢旧画面，帧可用二进制传输；URL/Tab 信息另用 JSON 更新。连接失败有限次数退避重连。用户操作和 Agent 操作指向**相同 thread 的浏览器 session**，所以用户能观察和接管 Agent 所在页面。
- **边界授权**：REST 导航和 WS 都要求登录、thread 写权限与 thread 明确归属当前用户；WS 单独验证 Origin，因为常规 HTTP auth/CSRF middleware 不覆盖 WS 升级；跨用户 thread 或工具未启用时 fail closed。实时浏览器可能包含登录态 cookie 和页面隐私，所以不能按普通截图查看器处理。

这不是把截图嵌入聊天这么简单，而是一个**远程、有状态、双向控制的浏览器工作台**。仅添加图片 Artifact 预览不能替代它；反过来，也不应为了预览普通截图就引入整个 Live Browser 系统。

## 3. UniEmployee 对照：已有、缺少、未核验

| 能力 | UniEmployee 当前状态 | 差距及判断 |
|---|---|---|
| 网页搜索 | `backend/app/tools/search.py` 提供 `bocha_search`，返回最多 6 条标题/摘要/URL | 能发现页面，但不主动读取页面正文；搜索摘要不等于原文核验 |
| 网页正文抓取 | 没有 `web_fetch` 一等本地工具 | 属于明确功能缺口。可用性高，且能只给小察/市场情报员工授权 |
| 浏览器自动化 | `catalog/seeds.py` 配置 `@playwright/mcp@latest --headless --isolated`，connector 种子分配给 `net-ops`、`market-intel` | 是通过外部 MCP server 提供的浏览器工具，不是本地 session manager。实际发现到的工具、Chromium 可用性、connector 健康情况取决于运行环境；需看运行时工具清单/Trace 验证，不能只看 seed |
| 工具加载/授权 | `compiler.py` 在编译员工 Agent 时，通过 `MultiServerMCPClient.get_tools()` 发现配置 connector 的工具，走 guard，再放入 Agent；Agent 有缓存 | 适合复用的既有入口；配置更改的生效边界和 MCP 生命周期状态仍需显示清楚。不能假设 MCP schema 会按每个用户问题动态发现 |
| 浏览器会话可复用 | 当前 browser connector 使用 `--isolated`；应用层没有 DeerFlow 式 thread → BrowserSession 生命周期管理 | 当前设计更像 MCP 工具服务器控制浏览器；不能假设 session 与 DeerFlow 一样跨 Agent 工具/前端共用，须以 MCP server 实际行为确认 |
| 浏览器图像交付 | 普通 Artifact/聊天文件已经可显示图片（近期修复的 `FileCard.vue`）；聊天 Trace 展示工具调用状态 | 静态截图可以作为文件交付，但没有 Agent 动作时的浏览器步骤帧、共享 session 面板或鼠标键盘接管 |
| 浏览器 Live API/前端 | 未找到按会话控制浏览器的 REST/WS 服务或 BrowserView 页面组件 | 若要迁移，需要新后端会话服务、权限模型、WS 帧协议、前端面板和运行治理，绝不是单独改 `FileCard.vue` |

**源码基线限制**：以上判断是 repo 与种子配置审阅，没有在本轮启动 Playwright MCP 子进程、安装 Chromium 或执行真实浏览器动作。因此“配置了 connector”是代码事实，“当前环境真实运行正常”尚未在本轮证明。之前 CRM 的端到端验证不能替代浏览器 connector 验收。

## 4. 为什么值得改 / 为什么不应直接全量照搬

### 网页抓取值得做的前提

若一个目标工作任务经常要“搜索近期信息并阅读原文”，只靠 `bocha_search` 摘要可能导致关键限定条件、发布日期、正文证据遗漏。加抓取能力之后，Agent 能读取来源页面并引用，评测可直接比较事实核验完整度、来源有效率、任务完成率及成本。这是能用用例验证的价值。

如果 UniEmployee 当前没有任何获批的外网检索场景，抓取工具不会自动产生 ROI，还会引入 SSRF、服务费用、反爬与不稳定性。因此先从员工授权和评测集开始，不能默认暴露给所有数字员工。

### 浏览器实时交付值得做的前提

只有当任务需要以下一项或多项时，Live 面板才有额外价值：Agent 需要用户已经登录的业务页面；页面无法从 API/HTML 抓取；用户需要实时监督、纠正或接管；或者人工审批必须核对当时屏幕状态。做好之后的收益是减少“Agent 看不见页面”的中断和重复描述，用户可以确认当前页面并直接操作；可用指标是人工接管率、任务完成率、重试次数和单任务耗时。

若浏览器只是后台抓取公开网页，Live 面板会增加 Chromium 资源、WebSocket 并发、会话清理、身份隔离、SSRF/CSRF、部署单 worker 限制和前端交互复杂度，却没有被证明的用户收益。现阶段先使用现有 Playwright MCP 工具和静态截图交付做场景验证。

### LangChain / LangGraph 可行性

- **高可行性**：将 `web_fetch` 包装为 UniEmployee 的 LangChain `@tool`，交由现有 `ALL_LOCAL_TOOLS` / employee_tools / guard / Trace 管线；或以独立 MCP server 方式接入。模型、工具 schema、消息及调用接口都能对齐，不必更换 deepagents/LangGraph。
- **中可行性**：把 DeerFlow 的“浏览器动作返回快照/图片 artifact”语义映射到 UniEmployee 的 tool result、Trace 与 artifact 存储。工具定义能对齐，`Command`/ToolMessage metadata、SSE 事件以及 artifact 生命周期是各自 harness 的实现，不能直接复制。
- **中低可行性**：复刻共享实时 session。LangChain 只负责调用工具，不能替代 HTTP/WS 会话服务、Playwright loop-affinity、用户所有权、会话租约、帧缓冲、用户输入协议或进程路由。需把 session manager 做为平台后端能力，再由 Agent 工具和前端共同调用它。
- **不建议**：迁移 DeerFlow 的整个 Agent/harness 来获得浏览器。UniEmployee 已有 DeepAgents/LangGraph 与 MCP；换 harness 对抓取没有必要，还会改变审批、checkpoint、guard 和租户上下文。

结论：两个项目共同使用 LangChain 生态让**工具层兼容容易**，但“Live Browser”主要是应用服务和交互层投资，不能用框架相同作为直接移植的理由。

## 5. 分阶段迭代方案与验收

| 优先级 | 方案与目的 | 完成后的业务收益 | 验收门槛 / 启动条件 |
|---|---|---|---|
| **P0 核验** | 在现有员工上核对 Playwright MCP 的实际工具名、工具数、调用 Trace、浏览器依赖和错误反馈；做一组公开页面只读与导航用例 | 明确已经能做什么，避免重复开发；提前发现 MCP 初始化失败却静默降级、Chromium 缺失等问题 | 记录 employee、connector、发现工具、成功/失败、时延、截图/产物情况；能解释配置、授权和不可用的不同原因 |
| **P1 条件实施：只读 `web_fetch`** | 增加正文读取，严格限定完整 URL 与 public HTTP(S)，默认不带 cookie/登录态；请求大小/超时/正文长度受限；返回 canonical URL、标题、抓取时间、正文和错误类型；仅对通过评测的员工授权 | 从搜索摘要进到原文核实，减少遗漏并改善出处可追溯性；HTTP 抓取成本通常低于完整浏览器 | 至少准备 20 个代表性 URL（正常、重定向、超时、拒绝、正文抽取失败、恶意内网 URL）；和仅搜索摘要基线比较来源可用率/答案正确性/耗时；确认安全检查覆盖重定向和 DNS 解析。通过后再设默认员工范围 |
| **P1/P2 依据场景：浏览器结果交付** | 先借助现有 MCP 在工具结果里回传一张受 ACL 保护的截图 artifact 与页面 URL/标题/动作摘要；沿用 UniEmployee Artifact/FileCard 展示，不引入 live session | 用户能够验证关键 UI 操作停在哪、看到的页面是否正确；排查自动化失败更快 | 用例确实需要 DOM 之外的视觉证据时启动；截图确实能经既有 artifact_id ACL 返回、会话/密钥未泄露 |
| **P2 条件项：Live Browser 面板** | 只有静态截图不能解决的 authenticated/JS 页面任务出现时，设计 thread-owned BrowserSession manager、单 worker/远端 browser service 边界、WS 认证与 Origin 校验、SSRF、限并发与过期清理、只读预览及显式写操作接管 | 可监督并接管长流程，减少浏览器环境无法观察导致的失败/人工重复操作 | 需要至少 3 个跨步骤用例证明截图+工具无法满足；先明确谁的账号登录、cookie 保存与销毁、用户接管权限、浏览器与 API 是否允许访问私网，再估算并发和部署成本 |
| **暂缓** | CDP 连接个人 Chrome、全量移植 DeerFlow BrowserView/agent loop、多 provider 抓取框架 | 暂无已验证增量收益 | 等确有已登录内部系统或多 provider SLA 问题，再单项立项；CDP 不能为演示方便而默认放开无 SSRF guard 模式 |

### `web_fetch` 的建议目标接口

建议 UniEmployee 第一期只设计成一个无状态工具：

```text
web_fetch(url: str) -> {
  requested_url, final_url, title, fetched_at,
  content_markdown, truncated, source_provider
}
```

- URL 要求由用户或已授权搜索结果提供，拒绝 `file:`、非 HTTP(S)、localhost、私网/链路本地/云元数据地址；每次重定向重新验证解析后的地址，防 DNS rebinding。
- 不支持用户 cookie、Authorization header 透传或任意请求头；抓取公开页面。若将来确有登录需求，应进入 BrowserSession 设计与单独审批，而不是给 web_fetch 悄悄加凭据。
- 设置请求超时、最大响应体、最大重定向次数、正文最大 token/字符数；返回截断标记而不是静默剪掉。保留最终 URL 和来源 provider，失败用可诊断类型返回，不把异常堆栈或敏感 URL query 原样喂给模型/日志。
- 优先用简单可控的 HTTP fetch + HTML 正文提取做第一版；若常见站点的 JS 渲染命中率不足，先对比现有 Playwright MCP 以及自托管 Crawl4AI。只有代理可用率/合规性、规模或费用形成证据后才接 Jina/Browserless 等外部服务。
- 全部经现有 Guard / Trace /员工资源配置授权；agent compile/cache 的生效策略需按现有规则处理。未经验证不授予全员。

## 6. 最终建议供评审

1. **先批准验证，不先批准全面浏览器改造**：核验 Playwright MCP 当前工具集和本地可执行情况；补网页来源读取的成功/失败评测样本。
2. **网页抓取属于可能的近期 P1**：当“只靠搜索摘要导致答案不可核验”在样本中出现时，实现受限 `web_fetch`，收益能通过来源有效率、事实正确率和耗时变化衡量。
3. **Live Browser 暂列 P2**：目前已有 MCP 自动化入口与图片 Artifact 预览；缺的是共享会话和实时接管。没有认证页面/用户接管的用例时，不值得承担整个 WS 浏览器栈。
4. **不迁移 DeerFlow Agent 框架**：工具接口兼容足够；保留 UniEmployee 的 employee catalog、guard、Trace、artifact、DeepAgents/LangGraph 生命周期，只在具体工具边界吸收验证过的设计。

## 7. 源码依据

UniEmployee：

- [`search.py`](../../backend/app/tools/search.py)：Bocha 搜索只返回摘要/URL。
- [`seeds.py`](../../backend/app/catalog/seeds.py)：Playwright MCP 命令、headless/isolated 参数、员工 connector 分配。
- [`compiler.py`](../../backend/app/compiler.py)：员工 compile 时发现 MCP tools、guard 过滤并处理连接器故障降级。
- [`FileCard.vue`](../../frontend/src/components/chat/FileCard.vue)：现有 artifact 图片预览和受 ACL 文件读取。
- [`ChatMessage.vue`](../../frontend/src/components/chat/ChatMessage.vue)：当前 chat tool trace 与消息/文件展示。

DeerFlow 本机源码：

- [`jina_ai/tools.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/community/jina_ai/tools.py:43>)、[`jina_client.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/community/jina_ai/jina_client.py:1>)：Jina Reader 正文抓取。
- [`browser_automation/tools.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/community/browser_automation/tools.py:276>)：8 个工具、动作快照、ToolMessage 和截图 artifact。
- [`browser_automation/session.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/community/browser_automation/session.py:1>)、[`url_safety.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/community/url_safety.py:1>)：loop-affine 会话、会话上限/worker 限制与 URL 防护。
- [`routers/browser.py`](</Users/wrg/mystudy/deer-flow/backend/app/gateway/routers/browser.py:1>)：thread owner、权限、Origin、REST 导航与双向 WS 帧/输入。
- [`browser-view-panel.tsx`](</Users/wrg/mystudy/deer-flow/frontend/src/components/workspace/browser-view/browser-view-panel.tsx:1>)、[`use-browser-stream.ts`](</Users/wrg/mystudy/deer-flow/frontend/src/components/workspace/browser-view/use-browser-stream.ts:1>)：用户侧实时显示、输入、重连和帧缓冲。
- [`config.yaml`](</Users/wrg/mystudy/deer-flow/config.yaml:1217>)：当前配置启用 Jina `web_fetch`；Browserless/Crawl4AI/browser automation 示例在相邻段落中注释，不能算当前激活。
