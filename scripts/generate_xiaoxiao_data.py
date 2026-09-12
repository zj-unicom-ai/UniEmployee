#!/usr/bin/env python3
"""生成客户经理（xiaoxiao）签后经营模拟数据集（CSV），输出到 workspace/datasets/。

覆盖两个签后经营维度：
  1. crm_contracts.csv      — 合同台账（签约/到期日、金额、产品）
  2. crm_opportunities.csv  — 商机台账（阶段、金额、最后跟进日、跟进备注）

客户名称与 CRM 连接器（app/connectors/crm_server.py）的演示客户严格对齐：
张总/华强电子、李经理/鼎新科技、王老师/阳光中学、陈工/先锋设计院、
赵女士/瑞和地产、周同学/星辰科技。

内嵌四条可扫描出的"故事线"（相对数据截止日 TODAY，供 renewal-scan 技能扫描）：
  A. 华强电子 企业通信云合同 2026-09-20 到期（临期 10 天，大额 48 万）
  B. 阳光中学 智慧校园合同 2026-10-05 到期（临期 25 天）
  C. 鼎新科技 云安全组网商机方案报价后停滞 21 天（38 万）
  D. 先锋设计院 企业大模型应用平台商机需求确认后停滞 16 天（52 万）
其余合同/商机处于健康水位。

数据集输出到 workspace/datasets/（共享只读目录）：local_shell 后端员工的
execute 可直接以相对路径 workspace/datasets/ 读取。
"""

import csv
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "workspace" / "datasets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 数据截止日（与演示叙事对齐的固定日期，不用 datetime.now 保证可复现）
TODAY = datetime(2026, 9, 10)


def _d(s: str) -> str:
    return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")


def gen_contracts():
    rows = [
        # 故事线 A：临期大额（到期日距 TODAY 10 天）
        dict(contract_id="HT-2025-0117", customer="张总", company="华强电子",
             product="企业通信云服务", amount_wan="48.0",
             sign_date=_d("2025-09-20"), expire_date=_d("2026-09-20")),
        # 故事线 B：临期（25 天）
        dict(contract_id="HT-2025-0102", customer="王老师", company="阳光中学",
             product="智慧园区", amount_wan="12.5",
             sign_date=_d("2025-10-05"), expire_date=_d("2026-10-05")),
        # 预警（66 天）
        dict(contract_id="HT-2024-0311", customer="赵女士", company="瑞和地产",
             product="AI 视频分析", amount_wan="86.0",
             sign_date=_d("2024-11-15"), expire_date=_d("2026-11-15")),
        # 健康水位
        dict(contract_id="HT-2026-0088", customer="李经理", company="鼎新科技",
             product="企业通信云服务", amount_wan="23.0",
             sign_date=_d("2026-01-20"), expire_date=_d("2027-01-20")),
        dict(contract_id="HT-2026-0090", customer="周同学", company="星辰科技",
             product="云安全", amount_wan="9.8",
             sign_date=_d("2025-12-10"), expire_date=_d("2026-12-10")),
        dict(contract_id="HT-2026-0104", customer="陈工", company="先锋设计院",
             product="企业通信云服务", amount_wan="17.6",
             sign_date=_d("2026-03-15"), expire_date=_d("2027-03-15")),
        # 多合同客户：华强电子另一条早期合同，已正常续约在途
        dict(contract_id="HT-2023-0045", customer="张总", company="华强电子",
             product="AI 视频分析", amount_wan="31.0",
             sign_date=_d("2024-06-01"), expire_date=_d("2027-06-01")),
    ]
    fields = ["contract_id", "customer", "company", "product",
              "amount_wan", "sign_date", "expire_date"]
    path = OUTPUT_DIR / "crm_contracts.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"已生成 {path}（{len(rows)} 条合同）")
    return rows


def gen_opportunities():
    rows = [
        # 故事线 C：方案报价后停滞 21 天
        dict(opp_id="OPP-2026-0311", customer="李经理", company="鼎新科技",
             product="云安全（组网专线/安全专线）", stage="方案报价", amount_wan="38.0",
             last_follow_up=_d("2026-08-20"),
             note="方案已提交，客户内部走预算审批流程，需跟进预算进度并推动定标"),
        # 故事线 D：需求确认后停滞 16 天
        dict(opp_id="OPP-2026-0302", customer="陈工", company="先锋设计院",
             product="企业大模型应用平台", stage="需求确认", amount_wan="52.0",
             last_follow_up=_d("2026-08-25"),
             note="需求调研完成，客户在比选竞品，需提供对比材料并约二次拜访"),
        # 活跃商机
        dict(opp_id="OPP-2026-0345", customer="张总", company="华强电子",
             product="企业通信云服务（扩容）", stage="商务谈判", amount_wan="15.0",
             last_follow_up=_d("2026-09-06"),
             note="扩容报价已确认，等待客户合同用印"),
        dict(opp_id="OPP-2026-0350", customer="周同学", company="星辰科技",
             product="智慧园区", stage="初步接触", amount_wan="26.0",
             last_follow_up=_d("2026-09-08"),
             note="展会获取线索，已约下周上门交流"),
        dict(opp_id="OPP-2026-0338", customer="赵女士", company="瑞和地产",
             product="AI 视频分析（周界安防）", stage="需求确认", amount_wan="20.0",
             last_follow_up=_d("2026-09-02"),
             note="园区周界安防改造预算已立项，等待现场勘查排期"),
    ]
    fields = ["opp_id", "customer", "company", "product", "stage",
              "amount_wan", "last_follow_up", "note"]
    path = OUTPUT_DIR / "crm_opportunities.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"已生成 {path}（{len(rows)} 条商机）")
    return rows


if __name__ == "__main__":
    gen_contracts()
    gen_opportunities()
