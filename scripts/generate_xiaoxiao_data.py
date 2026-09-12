#!/usr/bin/env python3
"""生成客户经理（xiaoxiao）签后经营模拟数据集（CSV），输出到 workspace/datasets/。

演示案例背景：浙江联通 × 吉利汽车（新能源车企政企大客户）。
覆盖两个签后经营维度：
  1. crm_contracts.csv      — 合同台账（签约/到期日、金额、产品）
  2. crm_opportunities.csv  — 商机台账（阶段、金额、最后跟进日、跟进备注）

客户公司与产品名对齐浙江联通政企真实客户与产品体系（吉利汽车、零跑汽车；
5G 专网/联通云/MPLS-VPN 专线/物联网芯模服务/SD-WAN 智选专线/视频云）。
注意：合同金额、联系人、商机均为演示用模拟数据，非真实商务数据。

内嵌四条可扫描出的"故事线"（相对数据截止日 TODAY，供 renewal-scan 技能扫描）：
  A. 吉利汽车 5G 专网（杭州湾制造基地）320 万合同 2026-10-05 到期（临期 23 天）
  B. 零跑汽车 SD-WAN 智选专线 42 万合同 2026-09-28 到期（临期 16 天）
  C. 吉利汽车 5G 专网二期（极氪工厂）260 万商机方案报价后停滞 21 天
  D. 吉利汽车 车联网数据合规平台 88 万商机需求确认后停滞 16 天
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
TODAY = datetime(2026, 9, 12)


def _d(s: str) -> str:
    return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")


def gen_contracts():
    rows = [
        # 故事线 A：临期大额（到期日距 TODAY 23 天）
        dict(contract_id="HT-2025-0031", customer="李总监", company="吉利汽车",
             product="5G 专网（杭州湾制造基地）", amount_wan="320.0",
             sign_date=_d("2025-10-05"), expire_date=_d("2026-10-05")),
        # 故事线 B：临期（16 天）
        dict(contract_id="HT-2025-0089", customer="陈经理", company="零跑汽车",
             product="SD-WAN 智选专线", amount_wan="42.0",
             sign_date=_d("2025-09-28"), expire_date=_d("2026-09-28")),
        # 预警（69 天）
        dict(contract_id="HT-2025-0044", customer="王工", company="吉利汽车",
             product="联通云（车联网数据平台承载）", amount_wan="150.0",
             sign_date=_d("2025-11-20"), expire_date=_d("2026-11-20")),
        # 健康水位
        dict(contract_id="HT-2026-0012", customer="李总监", company="吉利汽车",
             product="MPLS-VPN 专线（全国 9 个基地互联）", amount_wan="96.0",
             sign_date=_d("2026-03-31"), expire_date=_d("2027-03-31")),
        dict(contract_id="HT-2026-0033", customer="王工", company="吉利汽车",
             product="物联网芯模服务（车联网前装模组）", amount_wan="58.0",
             sign_date=_d("2026-06-30"), expire_date=_d("2027-06-30")),
        dict(contract_id="HT-2026-0007", customer="陈经理", company="零跑汽车",
             product="联通云（研发桌面云）", amount_wan="75.0",
             sign_date=_d("2026-05-31"), expire_date=_d("2027-05-31")),
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
        dict(opp_id="OPP-2026-0208", customer="李总监", company="吉利汽车",
             product="5G 专网二期（极氪工厂）", stage="方案报价", amount_wan="260.0",
             last_follow_up=_d("2026-08-22"),
             note="一期验收满意；二期方案已提交，客户在等集团数字化预算批复，需跟进预算进度并推动立项"),
        # 故事线 D：需求确认后停滞 16 天
        dict(opp_id="OPP-2026-0195", customer="王工", company="吉利汽车",
             product="车联网数据合规平台（联通云+元景大模型）", stage="需求确认", amount_wan="88.0",
             last_follow_up=_d("2026-08-27"),
             note="数据出境合规是核心诉求；客户要找法务确认数据驻留方案，需主动提供合规材料支持"),
        # 活跃商机
        dict(opp_id="OPP-2026-0240", customer="李总监", company="吉利汽车",
             product="视频云（园区安防 AI 分析扩容）", stage="商务谈判", amount_wan="46.0",
             last_follow_up=_d("2026-09-06"),
             note="报价已确认，等客户法务走完供应商准入，随时可签"),
        dict(opp_id="OPP-2026-0251", customer="陈经理", company="零跑汽车",
             product="物联网卡统一管理平台", stage="初步接触", amount_wan="35.0",
             last_follow_up=_d("2026-09-09"),
             note="智博会认识的新线索，已约下周技术交流"),
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
