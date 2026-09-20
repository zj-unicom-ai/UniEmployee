# UniEmployee 数字员工平台解读系列

基于 UniEmployee 当前仓库源码与实现，从产品定位、运行机制到落地路径的系列文章。

| 篇 | 标题 | 文件 | 主题 |
| --- | --- | --- | --- |
| 01 | 让 AI 成为员工，而不是聊天机器人 | [01-uniemployee-intro.md](./01-uniemployee-intro.md) | 项目定位、核心特点、解决的问题与企业价值 |
| 02 | 一个数字员工是如何被"编译"出来的 | [02-how-a-digital-employee-is-compiled.md](./02-how-a-digital-employee-is-compiled.md) | EmployeeSpec、catalog 配置、工具装配与 Agent 编译 |
| 03 | 技能、SOP 与知识库：AI 如何不靠记忆工作 | [03-skills-sop-knowledge.md](./03-skills-sop-knowledge.md) | 技能双通道、SOP 软硬分层、RAGFlow 知识检索 |
| 04 | 业务本体：让 AI 理解企业的"人、客户、订单、项目" | [04-business-ontology.md](./04-business-ontology.md) | 本体 Schema/Data 两层、运行时工具与管理界面 |
| 05 | 人机协同：AI 干活，人把关 | [05-hitl-human-in-the-loop.md](./05-hitl-human-in-the-loop.md) | 双路径审批、退款状态机、审批治理 |
| 06 | Trace 与运营：让 AI 从黑箱变成可审计的劳动力 | [06-trace-observability-ops.md](./06-trace-observability-ops.md) | runs/events、SSE 实时过程、运维闭环 |
| 07 | 从 Demo 到生产：落地时最该先解决什么 | [07-demo-to-production.md](./07-demo-to-production.md) | 场景选择、数据接入、安全、生产化与落地顺序 |
| 08 | UniEmployee：让大模型从"聊天助手"进化为"可上岗的数字员工" | [08-digital-employee-value-and-scenarios.md](./08-digital-employee-value-and-scenarios.md) | 宣传博客：核心特点、三方价值与典型应用场景 |

文章以当前代码为准，对演示数据和仍在建设中的能力做了如实标注。
