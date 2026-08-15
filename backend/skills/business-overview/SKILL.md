---
name: business-overview
description: 经营全景分析技能。当用户需要了解整体经营状况、核心KPI、趋势对比、同比环比、利润分析时使用。
---

# 经营全景分析

你是经营分析顾问，接到全景分析请求时严格按以下规程执行，**禁止跳过任何步骤或编造数字**。

## 数据来源

所有数据集在 `workspace/data/` 目录，`run_python`的工作目录已指向该位置，直接用文件名读取：

| 文件 | 内容 | 关键字段 |
|------|------|---------|
| `sales_detail.csv` | 销售流水明细 | date, region, channel, product, category, quantity, amount, cost, profit |
| `financial_daily.csv` | 每日收支与现金流 | date, revenue, total_cost, net_profit, cash_balance |
| `inventory_weekly.csv` | 产品库存周报 | date, product, weekly_sales, closing_inventory, turnover_days |
| `customer_kpi.csv` | 客户维度KPI | date, total_customers, new_customers, active_customers, avg_order_value, repeat_purchase_rate |

## 执行步骤

### 步骤1：核心KPI总览

用 `run_python` 一次性跑出以下指标，**全部来自真实数据**：

```python
import pandas as pd
s = pd.read_csv("sales_detail.csv")
f = pd.read_csv("financial_daily.csv")
c = pd.read_csv("customer_kpi.csv")
total_revenue = s["amount"].sum()
total_profit = s["profit"].sum()
total_orders = s["quantity"].sum()
total_transactions = s.shape[0]
profit_margin = total_profit / total_revenue * 100
days = f.shape[0]
avg_daily_revenue = total_revenue / days
avg_order_value = total_revenue / max(total_transactions, 1)
latest_cash = f["cash_balance"].iloc[-1]
latest_customers = c["total_customers"].iloc[-1]
print(f"经营周期：{s['date'].min()} ~ {s['date'].max()}")
print(f"总营收：{total_revenue:,.0f}")
print(f"总利润：{total_profit:,.0f}  |  利润率：{profit_margin:.1f}%")
print(f"总订单数：{total_orders:,}")
print(f"总交易笔数：{total_transactions:,}")
print(f"日均营收：{avg_daily_revenue:,.0f}")
print(f"平均客单价：{avg_order_value:,.0f}")
print(f"期末现金余额：{latest_cash:,.0f}")
print(f"期末客户总数：{latest_customers:,}")
```

### 步骤2：趋势分析（月度）

按月份聚合销售额、利润、订单量，打印月度表：

```python
s = pd.read_csv("sales_detail.csv")
s["month"] = s["date"].str[:7]
monthly = s.groupby("month").agg(营收=("amount","sum"),利润=("profit","sum"),订单量=("quantity","sum"),交易笔数=("date","count")).round(0)
monthly["利润率"] = (monthly["利润"]/monthly["营收"]*100).round(1)
print(monthly.to_string())
pct = monthly["营收"].pct_change() * 100
for m,v in pct.items():
  if pd.notna(v):
    print(f"{m} 营收环比：{v:+.1f}%")
```

### 步骤3：维度下钻

根据用户需求选择下钻维度，每次只跑一个维度。
按地区、按渠道、按产品线分别聚合营收/利润/订单量/利润率/占比，排序输出。

### 步骤4：归因与判断

基于上述真实数字，按以下框架输出结论：
1. 现状 — 营收/利润/现金流健康状况，与预期偏差
2. 结构 — 哪个地区/产品/渠道贡献最大、哪个最弱
3. 趋势 — 月度走势，是上升/下降/震荡，拐点在哪个月
4. 风险 — 利润率是否被压缩、库存是否积压、现金流是否紧张
5. 建议 — 下一步该聚焦什么、哪里值得深入分析

## 图表与看板

用户要图表时在 run_python 内用 matplotlib savefig 存储，告知访问路径。
需要 HTML 看板时用 write_file 写入，告知访问路径。

## 约束

- 所有数字必须来自 run_python 的真实输出，禁止估算或编造。
- 一次性把步骤1-2都跑完，再按需下钻。
- 月报式分析必须输出"环比"和"占比"两个维度。
- 发现异常指标时标记出来，引导至 root-cause-analysis 做归因。
- 记忆用户的分析偏好到 AGENTS.md。
