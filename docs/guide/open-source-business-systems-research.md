# 本地开源业务系统对接候选（资料核验）

> 2026-09-26 核验。以下是基于项目官方文档和源码的选型资料，不代表已经在本机部署或完成 UniEmployee 对接。先构造可重复的业务样本，再衡量数字员工相对于人工操作的收益。

## 结论

| 候选 | 适合验证的业务链 | 本地试点判断 | 主要代价 |
| --- | --- | --- | --- |
| **EspoCRM** | 客户、联系人、商机、客服 Case：客户画像、跟进与投诉处理 | **本项目首选**：现有“小小”及 mock CRM 可对应到真实的客户/Case API，同一个系统即可验证读与人审后写 | 需单独部署 CRM 和数据库，创建合成业务数据及专用 API 用户；系统真实不等于数据真实。[[Docker](https://docs.espocrm.com/administration/docker/installation/)] [[API](https://docs.espocrm.com/development/api/)] |
| **Zammad** | 客服/内部服务工单：查单、分类、汇总、建议处理、人审后更新 | 如果只想验证工单而不关心 CRM 客户经理流程，可作为第一轮替代 | 官方要求 Docker Compose **2.23.1+**、至少 **4 GB RAM**；默认含 Elasticsearch 等多容器，Webhook 需另配 Trigger/Scheduler。[[安装](https://docs.zammad.org/en/latest/install/docker-compose.html)] [[Compose 仓库](https://github.com/zammad/zammad-docker-compose)] [[Webhook](https://admin-docs.zammad.org/en/pre-release/manage/webhook.html)] |
| **ERPNext / Frappe** | 客户—销售订单—交付—库存—发票跨流程问答与协助 | 第二轮：业务对象丰富，但要先配置基础资料和状态流转，否则只是空系统演示 | 官方 `pwd.yml` 是**可丢弃的短期体验环境**，不宜当作长期试点底座；正式容器编排要用官方 `compose.yaml` + overrides，成本更高。[[Docker 仓库](https://github.com/frappe/frappe_docker)] [[部署方式](https://github.com/frappe/frappe_docker/blob/main/docs/01-getting-started/01-choosing-a-deployment-method.md)] |
| **Chatwoot CE** | 在线客服会话与人工接管；验证 IM 入口、上下文和响应效率 | 仅当目标明确是“客服会话渠道”时选择 | 偏渠道/会话管理，不是订单或工单事实源；运行 Rails、worker、PostgreSQL、Redis；需选 `*-ce` 镜像以明确社区版边界。[[Docker](https://developers.chatwoot.com/self-hosted/deployment/docker)] [[许可证](https://github.com/chatwoot/chatwoot/blob/develop/LICENSE)] |

## 1. EspoCRM：当前项目的首选

- [官方 Docker 部署文档](https://docs.espocrm.com/administration/docker/installation/)提供 Docker Compose 配置，应用默认可在 `localhost:8080` 访问，与 UniEmployee 的 8787 端口不冲突；建议独立 Compose、独立数据卷，固定镜像版本。
- [REST API](https://docs.espocrm.com/development/api/)根路径是 `api/v1/`。官方建议创建单独的 API 用户，用[角色](https://docs.espocrm.com/administration/roles-management/)限定读取范围，API Key 经 `X-Api-Key` 传递。[Account API](https://docs.espocrm.com/development/api/account/)支持列表和单条读取；[Case](https://docs.espocrm.com/user-guide/case-management/)是正式的客服问题对象，支持手工及 API 创建。可由 UniEmployee 的 stdio MCP 连接器封装少量只读 API 工具。
- EspoCRM 核心为 [AGPLv3](https://github.com/espocrm/espocrm)；本地实验可使用。若未来修改并对外提供服务或再分发，按实际方式审查许可义务。

**第一轮闭环**：在 EspoCRM 人工建立一组有客户、联系人、商机、Case 关联的合成数据；让“小小”查客户近况和未结 Case；在 EspoCRM 改变 Case 状态后，UniEmployee 立即读到新状态。对照 API 实际返回逐条评测，特别检查空结果、无权限、过期信息与网络失败。当前 UniEmployee 的 CRM 连接器是内存 mock，`create_ticket` 只返回编号，未写入外部系统；这两个点能通过实验直接验证差距。

## 2. Zammad：只做工单窄场景的替代

- 官方提供 [`zammad-docker-compose`](https://github.com/zammad/zammad-docker-compose)，按[安装文档](https://docs.zammad.org/en/latest/install/docker-compose.html)执行 `git clone`、`docker compose up -d`，应用默认可在 `localhost:8080` 访问；与 UniEmployee 的 8787 端口不冲突。Compose 运行还需要检查内存与 Docker 版本。
- [REST API](https://docs.zammad.org/en/latest/api/intro.html)支持个人访问令牌或 OAuth2；[工单端点](https://docs.zammad.org/en/latest/api/ticket/)包括 `GET /api/v1/tickets` 与单工单读取。工单可见性受用户及组权限约束。第一版用专用集成用户、最小组权限、只读工具；写单动作等人工审批流程稳定后再开放。
- [Webhook](https://admin-docs.zammad.org/en/pre-release/manage/webhook.html)可推送工单变更，但必须由 Trigger 或 Scheduler 引用；它不是“启用 Webhook 即自动触发”。第一轮可先用 API 主动查询，事件触发是下一步。
- 核心软件采用 [AGPLv3](https://github.com/zammad/zammad-docker-compose)；本地试点可使用，若以后修改并对外提供网络服务，需由法务按实际分发/服务方式审查许可证义务。

**建议做一个真实可评测的闭环**：预置 30–50 张合成但符合实际规则的工单，含重复工单、SLA 临界、跨组转派、已解决/未解决、信息缺失和用户无权访问案例。让 UniEmployee 完成“查当前状态、总结证据与来源、建议下一步、人工确认后回写”，用人工逐张核对正确率、节省时间、误写率和越权率。该样本应由预期使用者/业务规则定义；开源系统只提供业务载体，不能自动证明真实业务价值。

## 3. ERPNext：跨对象验证的第二阶段

- [Frappe REST API](https://docs.frappe.io/framework/user/en/api/rest)为 DocType 自动提供 CRUD，API Key/Secret 绑定用户权限；官方[集成说明](https://docs.frappe.io/erpnext/integrating-erpnext-with-other-applications)列出 Customer、Item、Sales Order、Delivery Note、Sales Invoice、Payment Entry 等对象，并建议专用集成用户与最小权限。
- [Webhook](https://docs.frappe.io/framework/user/en/guides/integration/webhooks)按 DocType 文档事件触发，支持 `X-Frappe-Webhook-Signature` 验签。
- 官方 Docker 项目提供 `docker compose -f pwd.yml up -d` 体验入口，默认 8080、`Administrator/admin`，但该配置被明确标为 disposable demo，不能安装自定义 App。适合快速观察对象和 API；如果要保存试点数据，改用正式 [Compose 配置](https://github.com/frappe/frappe_docker/blob/main/docs/02-setup/06-setup-examples.md)，并修改默认凭据。[[快速开始](https://github.com/frappe/frappe_docker/blob/main/docs/getting-started.md)]
- ERPNext 为 [GPLv3](https://docs.frappe.io/legal/others/license-and-trademark)。使用其 API 对接通常属于独立系统交互，但未来若分发修改版或合并源码，应单独审查许可边界。

建议只选一条可核验业务链，例如“订单状态/缺货原因解释 → 根据库存与交付单给出下一步建议”。先人工建立客户、商品、订单、库存、交付等一致数据，再接只读 API；暂不让模型直接创建财务或库存变动。

## 4. Chatwoot CE：渠道验证的备选

- 官方提供 [Docker Compose 部署流程](https://developers.chatwoot.com/self-hosted/deployment/docker)，包括 `.env`、数据库初始化和 Rails/worker 启动；本地默认绑定 `127.0.0.1:3000`。要用社区版，官方文档要求镜像标签使用 `latest-ce` 或版本化 `v*-ce`。生产服务还需处理数据库迁移及备份。
- [应用 API 令牌](https://www.chatwoot.com/hc/user-guide/articles/1677141565-chatwoot-glossary)关联用户；源码 [API 路由](https://github.com/chatwoot/chatwoot/blob/develop/swagger/paths/index.yml)包含会话、消息与联系人；[Webhook](https://chatwoot.help/hc/user-guide/articles/1677693021-how-to-use-webhooks)包含会话和消息事件。
- 仓库根目录是 MIT 许可，但 [`enterprise/` 目录有独立许可](https://github.com/chatwoot/chatwoot/blob/develop/LICENSE)。试点应固定 CE 镜像，避免把企业版功能误认为可免费使用。

若产品目标是“让数字员工接手用户聊天、需要时转人工”，它的渠道价值高；若优先验证 CRM、工单或订单判断，分别选 EspoCRM、Zammad 或 ERPNext 更容易定义正确答案。

## 最小对接路径

1. **先确定一个任务，不先建设通用连接器框架。** 对当前“小小”员工，推荐 EspoCRM 的“客户近况与未结 Case 查询”；若只检验工单能力，则选 Zammad。把输入、人工标准答案、允许读取的字段和需要人审的写动作定下来。
2. 业务系统用独立 Docker Compose 项目部署；固定镜像版本，卷保存数据；UniEmployee 通过 HTTP API 对接。不要让两个系统共用数据库。UniEmployee 在宿主机运行时访问 `http://localhost:8080`；它在本机 Docker Desktop 容器中运行时，可经已发布端口使用 `http://host.docker.internal:8080`，或让两个 Compose 项目加入同一外部网络后使用服务名。[[Docker Desktop 主机地址](https://docs.docker.com/desktop/features/networking/networking-how-tos/)] [[Compose 跨项目网络](https://docs.docker.com/compose/how-tos/networking/)]
3. 建专用 API 用户和最小权限。先做 `list/get` 等只读工具，返回业务对象 ID、时间戳、来源 URL；在评测集中同时验证正确率与越权拒绝。
4. 对确有价值的写操作复用 UniEmployee 现有人审/审计链，并设计幂等键与回读确认。最后才接 Webhook 驱动自动化。
5. 试点评审看“完成一单需时、可核验准确率、人工接管率、错误写入/越权次数、集成维护时间”；如果收益不明显，停止扩展系统数。

**边界**：开源业务系统能提供真实数据结构、权限、事件和状态迁移，但样本数据仍是我们构造的。它能证明“集成与任务执行能力”，不能替代真实用户采用率和真实业务 ROI 的验证。
