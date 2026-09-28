# 开发者指南（docs/guide/）

面向**动手**的实操手册：怎么配置、怎么部署、怎么扩展。原理与设计动机的深度解读见 [docs/articles](../articles/README.md)（八篇系列：编译机制 / 技能与SOP / 本体 / HITL / Trace / 落地路径）。

| 指南 | 内容 | 适合谁 |
|---|---|---|
| [部署指南](./deployment.md) | 裸机 / Docker Compose / 已有 PG 三种形态、备份恢复、升级与排障速查 | 部署运维 |
| [配置参考](./configuration.md) | 全部环境变量逐项说明（含代码默认值） | 所有人 |
| [新增数字员工指南](./add-employee.md) | 从零接入一个员工的完整流程，以市场情报员工「小察」为贯穿实例 | 开发者 |
| [技能规程（SKILL.md）编写规范](./skill-authoring.md) | 结构模板、触发条件提取规则、看板输出约定、值守模式 | 开发者 / 员工调教者 |
| [自定义工具开发](./custom-tools.md) | @tool 三处登记、人工审批标记、运行时上下文、产物文件推送 | 开发者 |
| [产物工作区与部门协作](./artifact-workspace.md) | 个人产物归档、部门共享、文件访问控制与部署注意事项 | 普通用户 / 管理员 / 运维 |
| [DeerFlow 对比与价值驱动迭代方案](./deerflow-value-driven-iteration-plan.md) | 源码差距、业务收益、优先级、启动条件和 LangChain 架构可行性 | 产品负责人 / 技术负责人 |
| [DeerFlow 工具加载机制与借鉴评估](./deerflow-tool-loading-comparison.md) | 内置/条件工具、社区 provider、MCP 延迟发现、插件加载、当前运行时核验及 UniEmployee 借鉴优先级 | 技术负责人 / 开发者 |
| [DeerFlow 网页抓取与浏览器交付评估](./deerflow-web-crawl-browser-migration.md) | 网页正文抓取、Agent 浏览器工具、实时浏览器交付链路与 UniEmployee 分阶段迁移建议 | 产品负责人 / 技术负责人 / 开发者 |
| [DeerFlow 可借鉴能力补充评估](./deerflow-additional-capabilities-review.md) | 外部工具结果信任处理、行动凭据、Skill 审查、批量子代理、项目上下文等能力的缺口、收益与优先级 | 产品负责人 / 技术负责人 / 开发者 |
| [DeerFlow 能力逐项验证台账](./deerflow-capability-verification-log.md) | P0/P1/P2 验证状态、运行证据、未通过项与继续条件 | 产品负责人 / 验收人员 / 开发者 |
| [本地开源业务系统对接候选](./open-source-business-systems-research.md) | EspoCRM、Zammad、ERPNext、Chatwoot 的场景匹配、部署与 API 依据 | 产品负责人 / 开发者 |
| [本地 CRM Lab 集成验证记录](./crm-lab-integration-validation.md) | 合成 CRM API、MCP 与 Agent 端到端验证结果和 Docker 尚未覆盖项 | 开发者 / 验收人员 |
| [企业业务本体演示问题清单](./ontology-demo-scenarios.md) | 路径查询、客户 360、实体展开、故障影响等 9 个已实测演示场景 | 售前 / 演示人员 / QA |

快速索引：改配置看[配置参考](./configuration.md)；跑不起来看[部署排障速查](./deployment.md#排障速查)；想加员工看[新增指南](./add-employee.md)。
