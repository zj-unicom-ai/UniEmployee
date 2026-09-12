# 开发者指南（docs/guide/）

面向**动手**的实操手册：怎么配置、怎么部署、怎么扩展。原理与设计动机的深度解读见 [docs/articles](../articles/README.md)（八篇系列：编译机制 / 技能与SOP / 本体 / HITL / Trace / 落地路径）。

| 指南 | 内容 | 适合谁 |
|---|---|---|
| [部署指南](./deployment.md) | 裸机 / Docker Compose / 已有 PG 三种形态、备份恢复、升级与排障速查 | 部署运维 |
| [配置参考](./configuration.md) | 全部环境变量逐项说明（含代码默认值） | 所有人 |
| [新增数字员工指南](./add-employee.md) | 从零接入一个员工的完整流程，以市场情报员工「小察」为贯穿实例 | 开发者 |
| [技能规程（SKILL.md）编写规范](./skill-authoring.md) | 结构模板、触发条件提取规则、看板输出约定、值守模式 | 开发者 / 员工调教者 |
| [自定义工具开发](./custom-tools.md) | @tool 三处登记、人工审批标记、运行时上下文、产物文件推送 | 开发者 |

快速索引：改配置看[配置参考](./configuration.md)；跑不起来看[部署排障速查](./deployment.md#排障速查)；想加员工看[新增指南](./add-employee.md)。
