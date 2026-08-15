#!/usr/bin/env python3
"""生成企业经营分析模拟数据集（CSV），输出到 workspace/data/。

覆盖四个经营分析必需的数据维度：
  1. sales_detail.csv      — 销售流水明细（含成本、利润）
  2. financial_daily.csv   — 每日收支与现金流
  3. inventory_weekly.csv  — 产品库存周转
  4. customer_kpi.csv      — 客户维度 KPI（客单价、复购率等）

数据集是一个"智选智能硬件公司"2026年Q1-Q2的经营模拟数据。
所有数字均按消费电子行业真实水平估算。
"""

import csv
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "workspace" / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 产品体系 ──
PRODUCTS = [
    {"product": "X1 智能音箱",     "unit_price": 399,  "unit_cost": 210, "category": "音频"},
    {"product": "S2 智能台灯",     "unit_price": 199,  "unit_cost": 105, "category": "照明"},
    {"product": "S2 Pro 智能台灯", "unit_price": 299,  "unit_cost": 155, "category": "照明"},
    {"product": "P3 智能投影仪",   "unit_price": 2599, "unit_cost": 1480,"category": "影音"},
    {"product": "W5 智能手表",     "unit_price": 599,  "unit_cost": 330, "category": "穿戴"},
    {"product": "W5 Pro 智能手表", "unit_price": 899,  "unit_cost": 490, "category": "穿戴"},
    {"product": "H7 降噪耳机",     "unit_price": 499,  "unit_cost": 265, "category": "音频"},
    {"product": "H7 Pro 降噪耳机", "unit_price": 699,  "unit_cost": 370, "category": "音频"},
]

REGIONS = ["华东", "华北", "华南", "西部", "华中"]
CHANNELS = ["线上旗舰店", "线下直营", "经销商分销", "企业集采"]

# ── 1. 销售流水明细 ──
def gen_sales_detail():
    rows = []
    start_date = datetime(2026, 1, 1)
    for day_offset in range(181):  # 1月~6月
        date = start_date + timedelta(days=day_offset)
        month = date.month
        # 淡旺季系数：2月春节前旺 + 618预热
        season_factor = 1.0
        if month == 1:   season_factor = 1.15
        elif month == 2: season_factor = 0.65   # 春节淡季
        elif month == 3: season_factor = 1.05
        elif month == 4: season_factor = 1.0
        elif month == 5: season_factor = 1.10   # 520/母亲节
        elif month == 6: season_factor = 1.30   # 618

        # 每家门店/渠道每日产生若干笔交易
        num_orders = random.randint(20, 60)
        for _ in range(num_orders):
            region = random.choice(REGIONS)
            channel = random.choice(CHANNELS)
            prod = random.choice(PRODUCTS)
            # 周末订单量 +20%
            weekday_factor = 1.2 if date.weekday() >= 5 else 1.0
            qty = random.choices([1, 1, 1, 1, 2, 2, 3], weights=[30,30,15,10,8,5,2])[0]
            # 企业集采批量大
            if channel == "企业集采":
                qty = random.randint(5, 30)
            qty = int(qty * season_factor * weekday_factor)
            if qty < 1:
                qty = 1
            amount = qty * prod["unit_price"]
            cost = qty * prod["unit_cost"]
            profit = amount - cost
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "region": region,
                "channel": channel,
                "product": prod["product"],
                "category": prod["category"],
                "quantity": qty,
                "unit_price": prod["unit_price"],
                "amount": amount,
                "cost": cost,
                "profit": profit,
            })
    path = OUTPUT_DIR / "sales_detail.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"生成 {path} — {len(rows)} 行")
    return rows

# ── 2. 每日收支与现金流 ──
def gen_financial_daily(sales_rows):
    rows = []
    # 按日期汇总销售收入
    daily_revenue = {}
    for r in sales_rows:
        d = r["date"]
        daily_revenue.setdefault(d, 0)
        daily_revenue[d] += r["amount"]

    start_date = datetime(2026, 1, 1)
    cash_balance = 8000000  # 起始现金 800万

    fixed_costs = {
        "人员薪资": 35000, "办公场地": 12000, "服务器/IT": 8000,
        "营销推广": random.randint(5000, 25000),
    }

    for day_offset in range(181):
        date = start_date + timedelta(days=day_offset)
        ds = date.strftime("%Y-%m-%d")
        revenue = daily_revenue.get(ds, 0)

        # 每月/固定日期出账
        variable_costs = {}
        # 采购成本：按销量的加权采购
        purchase_cost = sum(
            r["cost"] for r in sales_rows if r["date"] == ds
        ) * random.uniform(0.85, 0.95)
        variable_costs["采购支出"] = round(purchase_cost, 2)

        # 每周一支出营销固定费用
        if date.weekday() == 0:
            variable_costs["营销推广"] = random.randint(8000, 30000)

        # 每月1号大额支出
        if date.day == 1:
            variable_costs["房租"] = 50000
            variable_costs["云服务费"] = 18000

        # 每月15号发薪
        if date.day == 15:
            variable_costs["薪资发放"] = random.randint(280000, 350000)

        total_cost = sum(variable_costs.values())
        net = revenue - total_cost
        cash_balance += net

        rows.append({
            "date": ds,
            "revenue": round(revenue, 2),
            "total_cost": round(total_cost, 2),
            "net_profit": round(net, 2),
            "cash_balance": round(cash_balance, 2),
        })

    path = OUTPUT_DIR / "financial_daily.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"生成 {path} — {len(rows)} 行")
    return rows

# ── 3. 产品库存周报 ──
def gen_inventory_weekly(sales_rows):
    rows = []
    # 计算每种产品每个日期的总销量
    sales_by_prod_date = {}
    for r in sales_rows:
        key = (r["product"], r["date"])
        sales_by_prod_date[key] = sales_by_prod_date.get(key, 0) + r["quantity"]

    # 初始库存
    inv = {p["product"]: random.randint(3000, 8000) for p in PRODUCTS}
    reorder_point = 800
    reorder_qty = {p["product"]: random.randint(3000, 6000) for p in PRODUCTS}

    start_date = datetime(2026, 1, 1)
    for day_offset in range(0, 181, 7):
        date = start_date + timedelta(days=day_offset)
        ds = date.strftime("%Y-%m-%d")
        for prod in PRODUCTS:
            pname = prod["product"]
            # 本周销量
            week_sales = 0
            for dd in range(7):
                d = (start_date + timedelta(days=day_offset + dd)).strftime("%Y-%m-%d")
                week_sales += sales_by_prod_date.get((pname, d), 0)

            # 到货：如果上周库存低于安全线，补货到货
            arrived = 0
            if inv[pname] < reorder_point:
                arrived = reorder_qty[pname]
                inv[pname] += arrived

            inv[pname] -= week_sales
            if inv[pname] < 0:
                inv[pname] = 0

            turnover_days = round(inv[pname] / max(week_sales / 7, 0.01), 1)

            rows.append({
                "date": ds,
                "product": pname,
                "category": prod["category"],
                "opening_inventory": inv[pname] + week_sales - arrived,
                "weekly_sales": week_sales,
                "arrived_qty": arrived,
                "closing_inventory": inv[pname],
                "turnover_days": turnover_days,
                "reorder_point": reorder_point,
            })

    path = OUTPUT_DIR / "inventory_weekly.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"生成 {path} — {len(rows)} 行")
    return rows

# ── 4. 客户 KPI 日报 ──
def gen_customer_kpi(sales_rows):
    rows = []
    start_date = datetime(2026, 1, 1)

    # 模拟客户池
    total_customers = 15000
    new_customers_per_day_base = random.randint(60, 120)

    for day_offset in range(181):
        date = start_date + timedelta(days=day_offset)
        ds = date.strftime("%Y-%m-%d")
        day_sales = [r for r in sales_rows if r["date"] == ds]
        total_amount = sum(r["amount"] for r in day_sales)
        total_orders = sum(r["quantity"] for r in day_sales)
        total_transactions = len(day_sales)
        avg_order_value = round(total_amount / max(total_transactions, 1), 2)
        # 新客获取
        new_customers = int(new_customers_per_day_base * random.uniform(0.7, 1.3))
        if date.weekday() >= 5:
            new_customers = int(new_customers * 0.6)
        total_customers += new_customers
        # 活跃客户（有购买行为的比例）
        active_rate = round(random.uniform(0.12, 0.25), 3)
        active_customers = int(total_customers * active_rate)
        # 复购率（假设期内购买2次以上的占比）
        repeat_rate = round(random.uniform(0.18, 0.32), 3)

        rows.append({
            "date": ds,
            "total_customers": total_customers,
            "new_customers": new_customers,
            "active_customers": active_customers,
            "total_transactions": total_transactions,
            "total_orders": total_orders,
            "total_amount": round(total_amount, 2),
            "avg_order_value": avg_order_value,
            "repeat_purchase_rate": repeat_rate,
        })

    path = OUTPUT_DIR / "customer_kpi.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"生成 {path} — {len(rows)} 行")
    return rows


if __name__ == "__main__":
    print("== 生成企业经营分析模拟数据集 ==\n")
    sales = gen_sales_detail()
    gen_financial_daily(sales)
    gen_inventory_weekly(sales)
    gen_customer_kpi(sales)
    print("\n全部生成完毕，文件位于:", OUTPUT_DIR)
