# 本地 CRM Lab 集成验证记录

**验证时间：** 2026-09-26（本机 CST）
**结论范围：** UniEmployee Docker 容器通过 MCP 只读查询同网络中的 CRM Lab API，并完成 Agent SSE 对话；这次没有接入真实业务系统，也没有验证生产权限或生产负载。

## 验证环境

- CRM Lab 位于 UniEmployee 同级目录 `/Users/wrg/Important/crm-lab`，由独立 Docker Compose 管理，API 映射到 `127.0.0.1:18780`，健康状态为 `healthy`。
- CRM 数据为 SQLite 持久卷中的合成客户与 Case，接口响应标记 `source=crm-lab`、`synthetic=true`。
- UniEmployee Docker 应用映射到 `127.0.0.1:8788`，连接独立 PostgreSQL 容器 `uniemployee-crm-docker-verify-pg`（映射端口 `15434`），并与 CRM Lab 共享 Docker 网络。
- 本机联调登录用户名为 `admin`；随机密码保存在同级目录的忽略文件 `.verify-container-admin.env`。联调数据库密码保存在 `.verify-container-pg.env`。
- 未启动、迁移或写入原有 `uniemployee-pg` 容器。验证用 UniEmployee 数据库使用独立卷。
- 仓库的 `crm_lab` 连接器默认不分配给员工；验证用数据库中的 `xiaoxiao` 已绑定连接器，供本地演示。

## 结果明细

| 验证项 | 操作与观测 | 结果 |
|---|---|---|
| CRM API 健康与读取 | `/healthz` 返回 `200`；只读密钥查询到客户 `C-DEMO-001`，响应标记合成数据 | 通过 |
| MCP 工具发现 | 从 MCP stdio 客户端发现客户搜索、客户详情、客户 Case 列表、Case 详情 4 个只读工具 | 通过 |
| 源数据变化可见 | API 写入联调 Case `CASE-5A2E18E32165` 后，MCP 查询立即读到相同 ID、主题和状态 | 通过 |
| 权限边界 | 只读密钥写 Case 返回 `403`；错误密钥读 API 返回 `401` | 通过 |
| 连接器错误处理 | 错误密钥返回可识别鉴权错误；将服务地址指向关闭端口时，连接器返回“CRM Lab 暂时不可用”，不抛出原始异常 | 通过 |
| UniEmployee Docker 镜像 | 从项目 `backend/requirements.lock.txt` 安装依赖并构建镜像 `uniemployee:latest` | 通过；镜像内依赖完整，应用成功启动 |
| UniEmployee 容器健康 | 容器状态 `running healthy`；容器内 `/readyz` 和宿主机 `/health` 均返回 `200`，7 个业务库状态均为 `ok` | 通过 |
| 容器网络与 CRM API | UniEmployee 容器加入 `uniemployee-crm-lab_default`，以 `http://api:8000` 实际调用 CRM API | 通过 |
| Agent 端到端调用 | 通过 Docker 中的 UniEmployee 登录、创建会话、发 SSE 消息；`xiaoxiao` 本轮实际调用全部 4 个 `crm_lab_*` 工具，回答引用客户 ID、Case ID，并声明合成数据 | 通过 |
| 用户页面复测与 Trace | 会话 `c_202609261357340386`，执行 `r_226abed6a0d440a6`：状态 `done`、3 次工具调用，依次为客户搜索、客户详情、Case 列表；无知识库或本体工具事件，答案与 API 返回记录一致 | 通过 |
| Compose 配置 | `docker compose -f docker-compose.yml -f docker-compose.crm-lab.yml config --quiet` | 通过 |
| MCP 装配回归 | `pytest tests/test_mcp_connectors.py` | 6 passed |
| 后端全量测试 | `PYTHONPATH=backend .venv/bin/python -m pytest -o addopts='' tests/ -q -ra` | **531 passed, 40 skipped**，退出码 0 |
| 补丁格式检查 | `git diff --check` | 通过 |

联调 Case 已保留在 CRM Lab 中作为验证记录，并更新为 `resolved`、`normal`，不会继续显示为待处理高优先级事项。客户与所有 CRM Lab 数据仍为合成数据。

## 现有评测工作台回归基线

在上述 Docker 环境中，使用管理端现有评测 API 为员工 `xiaoxiao` 建立并运行评测集 **CRM Lab 本地只读基准 v1 2026-09**。评测集 ID：`es_5f7dc3b8261d4317`；运行 ID：`ebr_af7e824adcee49dd`；员工配置 hash：`5f36a89dbb460c20`。执行模型为 `deepseek-v4-flash`。运行状态 `completed`，3/3 用例已执行；逐条核对回答及 Trace 后，已在人审字段标记为 `pass`。

| 用例 | 评测结果 / Trace | Trace 中的实际工具调用 | 人工判定 |
|---|---|---|---|
| 客户全景：客户档案与全部 Case | `ebrres_15a57ab4906a417c` / `r_c6ee84f8d572404b`；4,950 ms；Trace 记录 30,227 tokens | `crm_lab_search_customers`、`crm_lab_customer_cases`、`crm_lab_get_customer`；无知识库、本体或其他数据源调用 | pass：客户字段、2 条 Case、来源及合成数据说明均与 API 一致 |
| Case 详情：字段和缺失值 | `ebrres_e2c4d2bcdcd94bd6` / `r_0b78e31c57dd4402`；3,420 ms；Trace 记录 19,460 tokens | `crm_lab_get_case`；无其他工具调用 | pass：主题、描述、状态、优先级正确；未提供的客户名称明确标为未提供 |
| 无答案：不存在的客户 | `ebrres_e4f53f01777e4b91` / `r_6265ddde346347ef`；4,138 ms；Trace 记录 28,848 tokens | `crm_lab_search_customers` 两次（全名及关键词）；无其他工具调用 | pass：明确报告无匹配记录，没有编造档案，也没有将空结果误报为服务故障 |

**这次结果的适用范围：**它验证了当前员工配置能在 CRM Lab 合成数据上完成三类只读任务，工具来源也能通过 Trace 核对；这不是业务方签收的真实工作样本，不能据此宣称真实数据准确率、任务采纳率或 ROI。三例 Trace 共记录 78,535 tokens（约 26,178 tokens/例）；这是当前 Trace 的统计值，需与模型供应商用量账单校准后才能估算费用。无答案用例出现两次搜索，可作为后续观察项；单个样本不足以支持立即增加工具调用限制或改提示词。

在管理界面可从 **管理后台 → 评测工作台 → 基准评测**查看用例、运行结果和人工判定。后续应由首个试点业务 owner 用授权的真实任务/失败样本替换或扩充此集，并确定越权、严重误答、过期数据的放行门槛；替换完成前，此基线只用于本地技术回归。

## 尚未覆盖

1. 全量测试中的 40 个用例因为 `8787` 没有测试服务而按仓库规则跳过；这些是依赖固定端口的 HTTP/浏览器集成用例。此次已独立通过容器 Agent SSE 对话，但不等同于这些浏览器页面和管理 API 全覆盖。
2. MCP 调用链已实测只读权限和故障降级；没有测试生产数据量、并发、API 限流、业务账号权限映射或对外写回。
3. 所有 CRM 记录都是合成数据。端到端通过只说明“Agent 能按授权读取指定 API 并说明数据来源”，不证明具体业务流程的准确率、人工节省或 ROI。
4. 页面复测的 Case 时间显示未统一标注时区；CRM API 返回的是 UTC（`+00:00`），客户表明确写了 UTC，Case 表未写。正式验收用例应要求时间列统一标注时区或按用户时区转换。

## 这轮实现带来的修复

本轮验证发现并修复了三个会阻断 Docker 联调的问题：

1. `.dockerignore` 曾排除 Dockerfile 要复制的 `frontend/dist/`，导致镜像构建上下文缺文件；已恢复该产物进入构建上下文。
2. MCP 子进程没有拿到 UniEmployee `.env` 中的 CRM 密钥；现由编译器仅把 `CRM_LAB_API_URL` 和 `CRM_LAB_READ_KEY` 传给 `crm_lab` 子进程，密钥不写入 catalog，应用其他环境变量也不传给该连接器。
3. `backend/requirements.lock.txt` 原先漏掉 `requirements.txt` 中的 8 个直接运行依赖，包括启动导入链需要的 `sqlglot`；这会造成 Docker 镜像构建成功、应用启动却失败。已用 Python 3.13 从 `requirements.txt` 重新生成 138 个固定版本，并在真实镜像中确认完整安装。

此外，Dockerfile 原先通过 Debian apt 安装 `build-essential` 和 `curl`，镜像构建多次遇到包源 `502`。锁定依赖在目标架构均可安装（`jieba` 已在 pip 构建阶段成功生成 wheel），所以移除这两个系统依赖，并将镜像和 Compose 健康检查改为 Python 标准库请求 `/readyz`。调整后镜像构建、启动、健康检查和 Agent 查询均通过。

## 验收状态与下一步

**本地 Docker 技术集成验收通过**：镜像、容器、共享网络、只读 MCP、SSE Agent 查询及合成数据来源提示都有实测记录。后续若要衡量业务价值，应由业务 owner 选择一个真实流程，换成授权的权威只读数据，并收集基线与人工验收样例；当前技术验证不等于业务试点或生产验收。
