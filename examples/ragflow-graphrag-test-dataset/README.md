# RAGFlow GraphRAG 测试数据集

这是一套用于验证 GraphRAG 效果的小型中文测试数据集。它故意设计了跨文档实体、关系、时间线和 SOP 链路，适合导入 RAGFlow 后生成 Knowledge Graph / Timeline / Wiki 等知识产物。

## 导入方式

1. 在 RAGFlow 新建 Dataset，例如：`UniEmployee GraphRAG 演示库`。
2. 上传本目录下除 `README.md` 以外的 6 个 `.md` 文件。
3. 等待文档解析完成。
4. 在 RAGFlow 中进入 Knowledge Compilation，选择 Graph 模板生成知识图谱。
5. 建议配置实体类型：
   - customer
   - industry
   - product
   - service
   - sla
   - incident
   - system
   - sop
   - team
   - person
   - policy
   - metric
6. 建议配置关系类型：
   - belongs_to
   - uses
   - depends_on
   - affects
   - protected_by
   - handled_by
   - triggers
   - requires
   - measured_by
   - supersedes
   - valid_from
   - valid_until

## 适合测试的问题

- 浙江省立医院和云专线、SLA、故障保障之间有什么关系？
- 2026 年 8 月 18 日云专线抖动会影响哪些客户、系统和 SOP？
- 智造云工厂为什么推荐边缘云专线加云联网，而不是单独互联网专线？
- 云专线银牌 SLA 和金牌 SLA 的差异会影响哪些客户承诺？
- 如果 CRM-CRM-20260818 事件再次发生，应该触发哪些处理流程？
- 哪些客户依赖杭州滨江边缘云节点？
- 2026 年 7 月之后，旧的故障升级规则是否还有效？

## 如何看出 GraphRAG 起作用

普通 RAG 往往只返回某个命中文档片段。GraphRAG 应该能返回或推理出跨文档链路，例如：

`浙江省立医院 -> uses -> 云专线金牌 SLA -> protected_by -> SOP-INC-P1 -> handled_by -> 政企保障专班`

或者：

`CRM-CRM-20260818 -> affects -> 云联网控制面 -> affects -> 浙江省立医院 HIS 灾备同步`

