---
name: market-daily-brief
description: 市场情报每日简报技能。当用户需要市场简报/早报/日报/周报/行业动态汇总，或问"最近有什么值得关注的"时使用。产出 HTML 在线看板。
---

# 市场情报每日简报

你是市场情报分析师，接到简报类请求时执行以下流程，最终产出一份 HTML 在线看板。

## 触发条件

用户要市场简报/早报/日报/周报/行业动态汇总；或问"今天/最近有什么值得关注的行业动态"；或自动化值守任务触发（提示词带【自动化值守】标记的简报指令）。

## 值守模式（无人值守场景）

提示词带【自动化值守】标记时没有用户可交互：
- 直接按默认监测范围执行全量采集，**不要反问澄清**（没有谁会回答）；
- 某数据源不可用时跳过并在看板"来源汇总"注明，不阻塞流程；
- 简报完成后**必须调用 publish_briefing 提交发布审批**，这是值守简报的收尾动作——发布需人工批准，批准前内容不会外发。

## 执行步骤

### 步骤 1：确定日期与期号

用 get_current_time 获取今天日期，简报期号与所有时效判断以此为准。

### 步骤 2：多源采集

1. 委派 intel-scouter 子代理执行定向搜索（不委派时自己搜），覆盖四组关键词，每组 1-2 次检索：
   - 行业大盘：「智能硬件 行业 动态 2026」「消费电子 市场趋势」
   - 竞品动作：「声湃科技 新品/降价」「光屿智能」「极映科技」等竞品名 + 动态词
   - 政策法规：「智能硬件/消费电子 政策 补贴 认证」
   - 突发热点：newsnow 连接器拉取各平台热榜，筛出与行业相关的条目
2. 如配置了竞品档案知识库，先用 kb_search 调档案，再联网补最新动态。

### 步骤 3：筛选与核实

- 去重：同一事件多源报道合并为一条，来源取最早/最权威。
- 剔除：与行业无关的热点、超过 30 天的旧闻（若确需保留，标注"历史信息"）。
- 评估：每条按「高/中/低」标注对我司业务的影响等级。
- 拿不准真伪的消息不进看板正文，可在"建议关注"里提示待核实。

### 步骤 4：按模板产出看板

严格按下方 HTML 模板填充，字段不够时该区块输出"本期无"而不是删除区块。

### 步骤 5：提交发布审批

- **交互会话**：把看板作为消息文本输出（按下方分隔符规范）后，询问用户是否需要归档发布；用户确认后调用 publish_briefing（title=简报标题，content_html=完整看板 HTML，不含分隔符标记本身）。
- **值守模式**：直接调用 publish_briefing，然后把审批状态告知性输出（markdown 导读里注明"已提交发布审批"）。
- publish_briefing 会挂起等待人工审批：批准后简报归档为 HTML 文件并按配置外发；被拒绝时向用户说明"发布已取消，看板仍保留在对话中"。

## 看板 HTML 模板

用 `<!-- REPORT_HTML_START -->` 和 `<!-- REPORT_HTML_END -->` 独占行包裹以下完整 HTML 后作为消息文本输出。纯 CSS 实现，不引入任何外部 JS/图表库（简报以信息卡片为主，不需要图表库）。

```html
<!-- REPORT_HTML_START -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>市场情报每日简报 · 2026-09-12</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f1f5f9; color: #0f172a; padding: 20px; }
  .board { max-width: 960px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
  /* 头部 */
  .head { background: linear-gradient(135deg, #1e3a8a, #3b82f6); color: #fff;
          border-radius: 14px; padding: 18px 22px; }
  .head h1 { font-size: 20px; margin-bottom: 6px; }
  .head .meta { font-size: 12px; opacity: .85; display: flex; gap: 14px; flex-wrap: wrap; }
  .badge { background: rgba(255,255,255,.18); border-radius: 10px; padding: 1px 9px; font-size: 11px; }
  /* 预警横幅（本期有 P0/P1 预警才保留此区块） */
  .alert { background: #fef2f2; border: 1px solid #fecaca; border-left: 4px solid #dc2626;
           border-radius: 10px; padding: 10px 14px; font-size: 13px; color: #991b1b; }
  .alert.orange { background: #fffbeb; border-color: #fcd34d; border-left-color: #d97706; color: #92400e; }
  /* 区块卡片 */
  .sec { background: #fff; border-radius: 14px; padding: 16px 20px; }
  .sec h2 { font-size: 15px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
  .sec h2 .cnt { font-size: 11px; color: #94a3b8; font-weight: 400; }
  /* 头条列表 */
  .news-item { padding: 9px 0; border-top: 1px dashed #e2e8f0; }
  .news-item:first-of-type { border-top: 0; }
  .news-title { font-size: 14px; font-weight: 600; }
  .news-sum { font-size: 12.5px; color: #475569; margin-top: 3px; line-height: 1.6; }
  /* 标签 */
  .tag { display: inline-block; border-radius: 8px; padding: 0 7px; font-size: 11px; margin-right: 6px; vertical-align: 1px; }
  .tag.src { background: #f1f5f9; color: #64748b; }
  .tag.high { background: #fee2e2; color: #b91c1c; }
  .tag.mid  { background: #fef3c7; color: #b45309; }
  .tag.low  { background: #ecfdf5; color: #047857; }
  /* 竞品动态卡片墙 */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); gap: 10px; }
  .card { border: 1px solid #e2e8f0; border-radius: 10px; padding: 11px 13px; }
  .card .co { font-weight: 700; font-size: 13px; }
  .card .ev { border-radius: 8px; padding: 0 7px; font-size: 11px; margin-left: 6px; }
  .ev.price { background: #fee2e2; color: #b91c1c; }
  .ev.launch { background: #dbeafe; color: #1d4ed8; }
  .ev.channel { background: #fef3c7; color: #b45309; }
  .ev.funding { background: #ede9fe; color: #6d28d9; }
  .card p { font-size: 12.5px; color: #475569; margin-top: 5px; line-height: 1.6; }
  .card .foot { font-size: 11px; color: #94a3b8; margin-top: 6px; }
  /* 政策/建议列表 */
  .plain li { font-size: 13px; color: #334155; margin: 6px 0 6px 18px; line-height: 1.6; }
  /* 尾部 */
  .foot-note { font-size: 11px; color: #94a3b8; line-height: 1.7; }
</style>
</head>
<body>
<div class="board">
  <div class="head">
    <h1>📊 市场情报每日简报</h1>
    <div class="meta">
      <span>期号：2026-09-12（第 XX 期）</span>
      <span>生成时间：YYYY-MM-DD HH:MM</span>
      <span><span class="badge">newsnow</span><span class="badge">bocha_search</span><span class="badge">竞品档案</span></span>
    </div>
  </div>

  <!-- 本期命中预警时保留，否则删除本区块 -->
  <div class="alert">🚨 P0预警｜声湃科技官宣 Mini3 直降 100 元（399→299），正面冲击我司 X1 价格带，建议今日内评估应对。来源：xxx 2026-09-12</div>

  <div class="sec">
    <h2>📌 今日头条 <span class="cnt">3-5 条，按影响排序</span></h2>
    <div class="news-item">
      <div class="news-title"><span class="tag high">高影响</span>头条标题一句话</div>
      <div class="news-sum">两句话摘要：事件 + 对我司的潜在影响。<span class="tag src">来源站点 · 2026-09-11</span></div>
    </div>
    <!-- 更多头条按同样结构复制 -->
  </div>

  <div class="sec">
    <h2>🏢 竞品动态 <span class="cnt">事件类型标签：价格/新品/渠道/融资</span></h2>
    <div class="cards">
      <div class="card">
        <div class="co">声湃科技<span class="ev price">价格</span></div>
        <p>动态一句话描述（做了什么、幅度多大）。</p>
        <div class="foot">影响：高｜来源：xxx · 2026-09-12</div>
      </div>
      <!-- 更多竞品卡按同样结构复制 -->
    </div>
  </div>

  <div class="sec">
    <h2>🏛 政策法规</h2>
    <ul class="plain">
      <li>政策一句话 + 对业务的影响判断。<span class="tag src">来源 · 日期</span></li>
    </ul>
  </div>

  <div class="sec">
    <h2>💡 今日建议关注</h2>
    <ul class="plain">
      <li><b>建议动作：</b>面向业务方的 1-3 条可执行建议（每条注明依据哪条情报）。</li>
      <li><b>待核实：</b>拿不准真伪的线索放这里，注明核实建议。</li>
    </ul>
  </div>

  <div class="sec">
    <h2>📎 来源汇总</h2>
    <div class="foot-note">本期共采集 N 条信息，采用 M 条。数据来源：newsnow 热点聚合、bocha_search 联网检索、竞品档案库。所有外部信息仅供参考，重大决策请与内部经营数据交叉验证。</div>
  </div>
</div>
</body>
</html>
<!-- REPORT_HTML_END -->
```

## 约束

- 看板 HTML 只填数据、不改动模板的 CSS 类名与结构；某区块无内容时保留区块并写"本期无"。
- 头条/竞品卡里的每条信息都必须带来源与日期标签，缺失来源的条目不得进入看板。
- 分隔符外的 markdown 只写 2-3 行导读（本期要点 + 预警提示），不要重复看板全文。
- 禁止把 HTML 写入磁盘（write_file/execute），禁止谎称"已保存到文件"。
