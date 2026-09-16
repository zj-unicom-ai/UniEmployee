# 小数数据分析师能力升级迭代计划

本文档记录“小数”从数据库问数助手升级为数据分析师工作流 Agent 的分阶段计划。

目标链路：

`理解业务问题 -> 获取数据 -> 验证数据 -> 分析 -> 归因 -> 生成结论 -> 输出报告`

## v1：分析师方法论固化

目标：让小数不再只按“连接数据 -> 写 SQL -> 返回结果”工作，而是按分析师流程思考和输出。

范围：

- 升级 `backend/employees/xiaoshu.yaml` persona。
- 升级 `backend/skills/data-analysis/SKILL.md`，加入理解问题、数据验证、分析、归因、结论输出步骤。
- 新增 `backend/skills/sql-root-cause-analysis/SKILL.md`，提供不依赖 `run_python` 的 SQL 版归因规程。
- 将 `sql-root-cause-analysis` 绑定给 xiaoshu，并通过 backfill 覆盖老库。

验收：

- 普通分析问题会先理解业务口径，再查询和解释。
- 复杂趋势/异常/为什么类问题会进入归因流程。
- 输出区分事实、推断、建议和数据限制。

## v2：数据验证工具落地

目标：让“验证数据”成为可执行工具能力，而不是提示词里的要求。

范围：

- 新增 `sql_db_profile`：生成表画像，包括行数、字段数、非空率、数值范围、时间范围、分类 Top 值。
- 新增 `sql_db_quality_check`：检查分析 SQL 或目标表的空结果、样本量、缺失值和重复记录风险。
- 将工具注册到 `ALL_LOCAL_TOOLS`、catalog 种子和老库 backfill。
- 补充工具级单元测试。

验收：

- 复杂分析前可调用画像工具判断数据覆盖。
- 核心 SQL 结果可被质量检查工具判定为通过、有风险或不通过。
- 数据质量风险会进入最终结论。

## v3：归因分析工具化

目标：把“为什么变化”从提示词推理升级成稳定的 SQL 辅助分析能力。

计划能力：

- `sql_db_dimension_breakdown`：按维度计算当前值、对比值、变化量、变化率、贡献度。
- `sql_db_top_contributors`：找出整体变化的主要拖累项和拉动项。
- `sql_db_anomaly_scan`：识别时间序列中的突变、断崖式下降和高波动点。
- 指标拆解模板：金额类指标拆为量、价、结构；漏斗类指标拆为各环节转化。

验收：

- “为什么 8 月销售下降”类问题能稳定输出异常确认、维度贡献和主要归因。
- 归因输出必须带贡献度或变化量。

## v4：结构化分析结果

目标：让报告和结论不直接依赖一次性 HTML 生成，而是先生成可测试的结构化分析对象。

计划结构：

```json
{
  "question": "",
  "assumptions": [],
  "data_sources": [],
  "data_quality": [],
  "kpis": [],
  "findings": [],
  "root_causes": [],
  "risks": [],
  "recommendations": [],
  "charts": [],
  "confidence": "high|medium|low"
}
```

验收：

- 报告生成前已有结构化分析中间产物。
- 单元测试可以校验 findings/root_causes/recommendations 是否包含数字证据。
- HTML 报告只负责呈现，不负责临场编造分析。

## v5：前端阶段化分析体验

目标：让用户在 `/app/analyst` 看见小数正在执行完整分析流程。

计划体验：

- SSE 阶段扩展：`understand`、`retrieve`、`validate`、`analyze`、`attribute`、`report`。
- 前端显示阶段进度、已使用数据源、质量检查摘要和关键 SQL。
- 报告页展示数据质量提示、结论置信度、建议动作。

验收：

- 用户可以清楚看到小数不是直接回答，而是在按分析流程工作。
- 数据质量风险和报告结论在 UI 上可追踪。

## 当前落地状态

- v1：已启动，persona、data-analysis 规程、SQL 版归因技能已纳入。
- v2：已启动，数据画像和质量检查工具已纳入。
- v3-v5：进入后续迭代池。
