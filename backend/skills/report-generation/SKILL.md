---
name: report-generation
description: 生成数据分析报告。当用户要求"报告/可视化报告/趋势报告/分析报告/统计报告/月报/周报"等任何报告类输出时启用。完整流程：理解需求 → 检索表结构 → 多维度 SQL 查询 → 智能深度分析归因 → 动态风格 HTML 可视化报告（ECharts）→ 分隔符包裹后直接输出到对话。
---

# 报告生成技能

## ⚠️ 输出方式红线（最高优先级，违反即失败）

**报告 HTML 必须作为助手消息文本的一部分，直接输出到对话窗口**——用 `<!-- REPORT_HTML_START -->` 和 `<!-- REPORT_HTML_END -->` 分隔符独占行包裹完整 HTML，让前端用 iframe srcdoc 渲染并提供下载/新窗口打开按钮，用户在对话里即可点击查看。

**严禁调用以下任何文件系统工具把报告写到磁盘：**
- ❌ `write_file` / `edit_file` / `delete` —— 不要把 HTML 内容写到 `workspace/data/` 或任何路径
- ❌ `execute` —— 不要用 shell 命令（`echo > file.html`、`cat <<EOF > ...`）落盘
- ❌ `ls` / `glob` / `read_file` —— 不要去探查或读取本地已存在的 html 文件

**也禁止在回复里告诉用户"报告已保存到 /xxx/yyy.html"或类似路径**——你无权写文件，写不出来也不要假装写了。前端只会从对话文本里提取分隔符包裹的 HTML 段来渲染，写到磁盘的 HTML 用户看不到也打不开。

正确输出长这样（节选）：

```
根据查询结果，为您生成《2024 月度销售趋势报告》：

<!-- REPORT_HTML_START -->
<!DOCTYPE html>
<html lang="zh-CN">
... 完整 HTML（含 ECharts CDN + CSS + 数据 + 初始化脚本）...
</html>
<!-- REPORT_HTML_END -->

报告已生成完毕，包含 KPI 卡片 4 个、图表 3 个...
```

---

## 何时使用

用户提出以下任意诉求时启用本技能：
- 显式关键词：**报告、分析报告、可视化报告、趋势报告、统计报告、月报、周报、季度复盘、专题分析**
- 隐式诉求：用户希望"总结、汇总、复盘、对比、看趋势、看分布、看排名、给老板看"等需要结构化呈现的场景

普通单点问数（用户只想知道一个具体数字、一条 SQL 结果）走 [data-analysis](./data-analysis) 规程，**不要**误用本技能。

## 不可违反的约束

1. **HTML 必须用分隔符 `<!-- REPORT_HTML_START -->` 和 `<!-- REPORT_HTML_END -->` 独占行包裹后，作为消息文本直接输出**——见顶部红线块，禁止 `write_file`/`edit_file`/`execute` 落盘，禁止谎称"已保存到某路径"
2. **查询完数据后必须立即生成报告，禁止中途停顿、问用户"要不要继续"**
3. **本技能是流程指令文档，按步骤一次性走完，不要说"调用技能"然后停下**
4. **报告中的所有数字必须来自 SQL 真实输出**，禁止估算、编造、四舍五入到"看起来合理"的整数
5. **遵守 xiaoshu 的安全规则**：只允许 SELECT，结果限制 100 行，查询失败最多重试 2 次
6. **HTML 单文件自包含**：所有 CSS/JS 内联，除 ECharts CDN 外无外部依赖
7. **不使用 emoji 作为图标**（报告正文中允许 ↑↓→← 等方向符号）

---

## 工作流程（7 步，必须全部完成）

### 第 1 步：理解需求

从用户诉求中提取并默念（不必输出）：
- **报告主题**：销售、用户、产品、运营、财务、客诉等
- **关键指标**：总量、增长率、排名、占比、转化率、复购率等
- **分析维度**：时间、地区、品类、渠道、客户分群等
- **时间范围**：最近一周/月/季度/年，或具体日期段
- **决策视角**：报告读者是老板、运营、销售负责人——决定结论的颗粒度

### 第 2 步：检索表结构

调用 `sql_db_smart_search(user_query="用户报告诉求原话")` 获取最相关的表结构。
- `datasource_id` 可不传，会话会自动注入当前选中的数据源
- 工具用 BM25 检索最相关的表，表数 ≤ 20 时返回全量
- 根据 user_query 语义判断需要哪些表，**通常 3-8 张**

若涉及多表 JOIN，再调用：
- `sql_db_table_schema(table_names="表1,表2")` 获取字段详情
- `sql_db_table_relationship(table_names="表1,表2")` 获取外键关联

### 第 3 步：多维度 SQL 查询

根据报告需求生成多条 SQL，覆盖不同分析维度：

| 报告需要 | 查询策略 |
|---------|---------|
| KPI 汇总 | 聚合查询（SUM/COUNT/AVG/MAX/MIN） |
| 时间趋势 | DATE_TRUNC/DATE_FORMAT + GROUP BY 时间 + ORDER BY ASC |
| 分类对比 | GROUP BY 类别 + ORDER BY DESC |
| Top N 排名 | ORDER BY DESC LIMIT N |
| 占比分析 | GROUP BY + 百分比计算（SUM(...) OVER ()）|
| 增长率 | 窗口函数 LAG() 或自连接 |
| 归因分解 | 多维度 GROUP BY + 增量贡献 |

**查询原则：**
- 只查必要列，不用 `SELECT *`
- 使用表别名、清晰的 JOIN 条件
- 合理使用聚合函数、GROUP BY、ORDER BY
- 默认 `LIMIT 100`
- 每条 SQL 在内部默念用途（不必对用户解释每条 SQL）
- 复杂 SQL 可先用 `sql_db_query_checker(query)` 预检语法

### 第 4 步：执行查询

调用 `sql_db_query(query="...")` 逐条执行 SQL，收集所有结果数据。

**执行失败时：**
1. 分析错误信息（表名/列名/函数语法/引号/日期格式）
2. 修正 SQL 重试一次
3. 仍失败则在报告中明确标注"该维度数据获取失败，已跳过"，不要编造数字

### 第 5 步：智能分析引擎（核心 — 动态维度，不可跳过）

查询到数据后，**必须先做深度分析再生成报告**。不要把原始数据塞进 HTML 就完事。

#### 动态维度选择策略

根据数据特征自动判断适用的分析维度：

| 数据特征 | 触发的分析维度 | 说明 |
|---------|-------------|------|
| 包含时间字段 + 数值指标 | **趋势分析** | 同比/环比、拐点识别、趋势方向和加速度 |
| 包含分类字段 + 数值指标 | **结构分析** | 各分类占比、帕累托（80/20）、集中度 |
| 包含多个分类维度 | **归因分析** | 维度下钻、贡献度量化、交叉分析 |
| 存在可对比的分组 | **对比分析** | Top N / Bottom N 排名、组间差异 |
| 数值分布范围大 | **异常检测** | 均值±2σ、离群值识别 |
| 包含率/比值指标 | **效率分析** | 转化率、完成率的横向和纵向对比 |
| 多指标同时存在 | **相关性分析** | 指标间关联关系、协同/对冲效应 |
| 用户问"为什么" | **因果探索** | 驱动因素假设、影响链路推测 |

**至少完成 3 个分析维度**，根据数据特征选择最相关的，不要硬塞。

#### 各维度分析要点

**A. 趋势分析 — How is it changing**
- 趋势方向：上升/下降/平稳/波动
- 变化速率：加速还是减速
- 拐点识别：趋势逆转的关键时间点
- 环比变化率
- 周期性模式：季节性、节假日效应

**B. 结构分析 — What's the composition**
- 各分类占比分布
- 帕累托分析：头部集中度（80/20 效应）
- 集中度评估

**C. 归因分析 — Why did it happen（核心，当数据支持时必须执行）**
- **维度下钻**：哪个地区/产品/渠道对变化贡献最大
- **贡献度量化**：各维度对总体变化的贡献百分比
- **对比归因**：表现优于/低于平均水平的类别
- **结构变化**：各维度占比随时间的迁移

**D. 对比分析 — How does it compare**
- 时间对比：同比、环比
- 分组对比：地区/产品/渠道间差异
- 排名分析：Top N 和 Bottom N

**E. 异常检测 — What's unusual**
- 偏离均值超过 2 倍标准差的数据
- 断崖式变化

#### 分析输出要求

每个被选中的分析维度必须输出：
1. **维度标题**：明确的分析维度名称
2. **核心发现**：2-4 个带具体数字的发现
3. **数据支撑**：引用具体数据作为证据

#### 结论与建议（必须包含）

**核心发现**（3-5 条，每条必须带具体数字）：
- 用"发现"而非"猜测"的语气
- 每条发现必须有数据支撑
- 按影响程度从大到小排列

**风险提示**（如果存在）：
- 异常波动、断崖式下降、集中度过高
- 必须给出具体数字和影响范围

**可执行建议**（分短期/中期/长期）：
- **短期（1-2 周）**：可立即采取的行动
- **中期（1-3 月）**：需要资源投入的优化
- **长期（3-12 月）**：战略性调整
- 每条建议必须具体可操作，避免"加强管理"这种空话

### 第 6 步：生成 HTML 报告

**第 5 步的所有分析结果必须写入 HTML 报告。** 不要重复输出纯文本分析。

#### 动态风格选择

**必须参考 `frontend-design` 技能的设计原则**为每份报告创造独特视觉风格，避免千篇一律的 AI 模板化。

**风格设计流程：**

1. **确定报告基调**（根据数据场景）：
   - 经营分析 → 专业沉稳（暗色 / 玻璃拟态）
   - 趋势分析 → 科技未来感（渐变 / 发光效果）
   - 分类对比 → 明快清晰（高对比 / 鲜明色彩）
   - 异常/风险 → 警示醒目（红橙色系 / 高亮标注）
   - 综合报告 → 仪表盘风格（网格布局 / 多区块）

2. **应用 frontend-design 设计原则**：
   - **字体**：避免默认 Arial/Inter，选择有特色的字体组合
   - **色彩**：承诺一个大胆的主色调，主色 + 鲜明强调色优于平均分配的温和配色；用 CSS 变量保持一致性
   - **空间构成**：尝试不对称布局、元素重叠、网格打破、留白控制
   - **背景与质感**：渐变网格、噪点纹理、几何图案、毛玻璃、戏剧性阴影
   - **动效**：KPI 卡片悬停、图表入场动画、页面加载错落展现

3. **每份报告风格尽量不同**：在暗色/亮色、不同字体、不同美学之间变化，避免多次生成趋同

#### 报告结构（6 个必需区块，缺一不可）

`<body>` 必须按顺序包含：

| # | 区块 | HTML 结构 | 内容要求 |
|---|------|----------|---------|
| 1 | **报告标题** | `<header class="report-header">` | 报告名称 + 时间范围 + 数据源信息 |
| 2 | **KPI 统计卡片** | `<section class="kpi-cards">` | 3-6 个关键指标卡片，每个含：指标名、数值、同比/环比变化（↑绿↓红），悬停有微动效 |
| 3 | **可视化图表** | `<section class="charts">` | 至少 2 个 ECharts 图表，根据数据特征动态选择类型 |
| 4 | **详细数据表格** | `<section class="data-table">` | 完整数据列表，斑马纹+悬停高亮，关键行高亮，超 20 行时表格内滚动 |
| 5 | **深度分析与归因** | `<section class="deep-analysis">` | 第 5 步动态分析结果的呈现 |
| 6 | **结论与建议** | `<section class="conclusions">` | 核心发现 + 风险提示 + 可操作建议（短/中/长期） |

#### 图表类型选择（ECharts）

| 数据特征 | 推荐图表 | ECharts 配置要点 |
|---------|---------|----------------|
| 时间序列 | 面积折线图 | `areaStyle` + `smooth: true` + 渐变填充 |
| 分类排名 | 水平柱状图 | `yAxis` 做类别轴 + 渐变色条 + 数据标签 |
| 占比结构 | 环形图 | `radius: ['40%', '70%']` + 中心统计文字 |
| 多维对比 | 分组柱状图 | 多 `series` + `barGap` 调整间距 |
| 变化归因 | 瀑布图 | 堆叠柱状图模拟，正值绿色负值红色 |
| 趋势+量 | 双轴图 | `yAxis` 数组 + 柱线组合 |
| 综合评估 | 雷达图 | 多维度能力画像 |
| 帕累托 | 组合图 | 柱状 + 累积线 |

#### 第 5 区块「深度分析与归因」HTML 结构（强制）

```html
<section class="deep-analysis">
  <h2>深度分析与归因</h2>

  <!-- 每个被选中的分析维度一个区块 -->
  <div class="analysis-block">
    <h3>{分析维度标题}</h3>
    <div class="analysis-content">
      <p>{核心发现描述，必须带具体数字}</p>
      <div class="analysis-chart" id="analysis-chart-{n}" style="height:350px"></div>
      <!-- 如有归因数据，展示贡献度表格 -->
      <table class="attribution-table">
        <thead><tr><th>维度</th><th>贡献值</th><th>贡献占比</th><th>变化方向</th></tr></thead>
        <tbody>
          <tr>
            <td>{维度名}</td>
            <td>{+/-数值}</td>
            <td>
              <div class="progress-bar">
                <div class="progress-fill positive" style="width: {百分比}%"></div>
                <span>{百分比}%</span>
              </div>
            </td>
            <td class="trend-up">↑</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 风险提示（如果存在异常数据） -->
  <div class="risk-alert">
    <h3>风险提示</h3>
    <ul>
      <li><strong>{异常类型}：</strong>{具体数字 + 影响说明 + 建议关注点}</li>
    </ul>
  </div>
</section>
```

#### 第 6 区块「结论与建议」HTML 结构

```html
<section class="conclusions">
  <h2>结论与建议</h2>

  <div class="findings">
    <h3>核心发现</h3>
    <ol>
      <li>
        <div class="finding-item">
          <span class="finding-badge">发现 1</span>
          <p>{发现内容，必须带具体数字和百分比}</p>
        </div>
      </li>
      <!-- 3-5 条核心发现 -->
    </ol>
  </div>

  <div class="recommendations">
    <h3>行动建议</h3>
    <div class="rec-timeline">
      <div class="rec-item rec-short">
        <div class="rec-label">短期 (1-2周)</div>
        <ul><li>{具体可操作建议，包含预期效果}</li></ul>
      </div>
      <div class="rec-item rec-mid">
        <div class="rec-label">中期 (1-3月)</div>
        <ul><li>{具体可操作建议，包含预期效果}</li></ul>
      </div>
      <div class="rec-item rec-long">
        <div class="rec-label">长期 (3-12月)</div>
        <ul><li>{具体可操作建议，包含预期效果}</li></ul>
      </div>
    </div>
  </div>
</section>
```

---

#### HTML 技术规范

**必须使用的技术栈：**
- **图表库**：Apache ECharts CDN（`https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`）
- **字体**：系统字体栈 + 可选 Google Fonts（Noto Sans SC / Noto Serif SC）
- **CSS**：变量系统 + `backdrop-filter` 玻璃效果 + CSS Grid/Flexbox 响应式
- **单文件**：所有 CSS/JS 内联，除 ECharts CDN 外无外部依赖

**ECharts 主题色板（根据报告场景选择）：**

```javascript
const PALETTES = {
  business: ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4'],
  tech:     ['#00d4ff', '#7c4dff', '#00e676', '#ff6d00', '#2979ff', '#651fff', '#00b0ff', '#d500f9'],
  warm:     ['#ff6b6b', '#ffa06b', '#ffd93d', '#6bcb77', '#4d96ff', '#9b59b6', '#1abc9c', '#e74c3c'],
  cool:     ['#667eea', '#764ba2', '#36d1dc', '#5b86e5', '#06beb6', '#48b1bf', '#4568dc', '#b06ab3']
};
```

**CSS 核心变量系统（每份报告根据风格动态定制，以下仅为参考结构）：**

```css
:root {
  /* 主色调 — 每次根据报告场景和 frontend-design 原则选择不同配色 */
  --primary: /* 动态选择 */;
  --primary-light: /* 主色浅色变体 */;
  --primary-dark: /* 主色深色变体 */;
  --accent: /* 强调色，与主色形成对比 */;

  /* 背景系统 — 暗色/亮色/渐变均可 */
  --bg-main: /* 动态选择 */;
  --bg-card: /* 卡片背景 */;
  --bg-card-hover: /* 卡片悬停 */;

  /* 文字层次 */
  --text-primary: /* 主文字 */;
  --text-secondary: /* 次要文字 */;
  --text-muted: /* 辅助文字 */;

  /* 状态色 */
  --success: #10b981;
  --warning: #f59e0b;
  --danger: #ef4444;
  --info: #3b82f6;

  /* 玻璃效果（可选，适合暗色主题） */
  --glass-bg: rgba(255, 255, 255, 0.05);
  --glass-border: rgba(255, 255, 255, 0.1);
  --glass-blur: 12px;

  /* 布局 */
  --radius: 16px;
  --radius-sm: 8px;
  --shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}
```

**关键 CSS 组件样式参考：**

```css
/* 玻璃拟态卡片 */
.glass-card {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--glass-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

/* KPI 卡片悬停效果 */
.kpi-card {
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;
}
.kpi-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--accent));
}
.kpi-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 40px rgba(102, 126, 234, 0.15);
}

/* 归因贡献度进度条 */
.progress-bar {
  position: relative;
  background: rgba(255,255,255,0.1);
  border-radius: 12px;
  height: 24px;
  overflow: hidden;
}
.progress-fill.positive { background: linear-gradient(90deg, #10b981, #34d399); }
.progress-fill.negative { background: linear-gradient(90deg, #ef4444, #f87171); }

/* 归因分析区块高亮边框 */
.analysis-block.attribution { border-left: 4px solid var(--accent); }

/* 建议时间线 */
.rec-timeline {
  position: relative;
  padding-left: 24px;
  border-left: 2px solid var(--glass-border);
}
.rec-item::before {
  content: '';
  position: absolute;
  left: -29px; top: 22px;
  width: 12px; height: 12px;
  border-radius: 50%;
  border: 2px solid;
}
.rec-short::before { border-color: var(--success); background: rgba(16,185,129,0.2); }
.rec-mid::before   { border-color: var(--info);     background: rgba(59,130,246,0.2); }
.rec-long::before  { border-color: var(--accent);   background: rgba(124,77,255,0.2); }

/* 核心发现徽章 */
.finding-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  background: var(--primary);
  color: white;
}

/* 表格 */
.data-table table { width: 100%; border-collapse: collapse; }
.data-table tr:nth-child(even) { background: var(--table-stripe); }
.data-table tr:hover { background: var(--bg-card-hover); }
```

### 第 7 步：输出报告

用分隔符包裹 HTML 直接输出到对话：

```
根据查询结果，为您生成《{报告标题}》：

<!-- REPORT_HTML_START -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{报告标题}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <style>...完整CSS...</style>
</head>
<body>
    <div class="report-container">
        <!-- 6 个必需区块 -->
    </div>
    <script>...ECharts 初始化代码...</script>
</body>
</html>
<!-- REPORT_HTML_END -->

报告已生成完毕，包含：
- KPI 卡片 N 个：[列出关键指标]
- 图表 N 个：[列出图表类型与说明]
- 详细数据表格
- 深度分析与归因
- 结论与建议（短期/中期/长期）
```

**关键：**
- 分隔符 `<!-- REPORT_HTML_START -->` 和 `<!-- REPORT_HTML_END -->` 必须独占一行
- HTML 必须完整（`<!DOCTYPE html>` + `<html>` + `<head>` + `<body>`）
- ECharts 图表初始化代码放在 `</body>` 之前的 `<script>` 中
- 查询数据后必须立即生成报告，不要中途停顿
- 不使用 emoji 作为图标（报告中允许 ↑↓→←）
- 文字与背景对比度 ≥ 4.5:1

---

## 常见报告模式速查

| 模式 | 查询策略 | 推荐图表 |
|------|---------|---------|
| 时间趋势 | DATE_TRUNC + GROUP BY 月份 | 面积折线图 |
| 类别对比 | GROUP BY 类别 + ORDER BY | 柱状图 |
| Top N 排名 | ORDER BY DESC LIMIT N | 水平柱状图 |
| 占比分析 | GROUP BY + 百分比计算 | 环形图 |
| 增长率分析 | 窗口函数 LAG() | 折线图 + 数据标签 |
| 归因分解 | 多维度 GROUP BY + 增量贡献 | 瀑布图/堆叠柱状图 |
| 异常检测 | 均值 ± 2σ 标记异常 | 折线图 + 红色标注 |
| 帕累托分析 | 累积占比计算 | 组合图（柱状 + 累积线） |

---

## 完整示例

### 示例：用户要求"分析 2024 年月度销售趋势，为什么 8 月特别高？"

**执行流程：**
1. 理解需求 → 趋势 + 归因报告
2. `sql_db_smart_search(user_query="2024 月度销售趋势")` → 语义匹配出 orders, products, customers
3. `sql_db_table_schema(table_names="orders, products, customers")` → 获取字段详情
4. `sql_db_table_relationship(table_names="orders, products, customers")` → 获取外键
5. 生成多条 SQL：
   - SQL1：月度趋势（`GROUP BY month ORDER BY month`）
   - SQL2：8 月品类分解（`GROUP BY category ORDER BY sales DESC`）
   - SQL3：7 月 vs 8 月对比（`CASE WHEN` 计算增量）
6. `sql_db_query` 逐条执行
7. **动态分析**：
   - 趋势分析：8 月为全年峰值，环比 +142%
   - 归因分析：电子产品品类贡献 58%，七夕促销贡献 32%
   - 结构分析：Q3 品类结构从均衡型转向电子产品主导
8. 应用 frontend-design → 选择"科技渐变"风格 → 生成 HTML 报告
9. 输出分隔符包裹的完整 HTML

### 反面示例（禁止行为）

```
# 错误：工作流中途停顿
用户：生成一个销售报告
小数：我找到了相关表，要继续吗？        ← 禁止
小数：数据查询完毕，要生成报告吗？      ← 禁止
小数：用什么风格的报告？                ← 禁止

# 正确：一次性完成全部流程，自动决策所有选项，最终输出分隔符包裹的 HTML
```
