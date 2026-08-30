"""E2E 验证 net-ops 四能力：通过 HTTP API 登录→建会话→发消息→读 SSE 流。

4 个典型问题：
  Q1 故障影响分析：高新区1号基站近一周故障，告警+影响面+责任人
  Q2 运营指标分析：近 30 天 KPI（趋势/环比/SLA/异常归因）
  Q3 资源容量分析：利用率/阈值/扩容缺口/资源归属
  Q4 SOP 路由：城东基站割接升级，按制度走流程（触发 SOP）

每个问题输出工具调用摘要 + 回答要点，随后对每条 SKILL 预期做自动核对。
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787"
USER, PWD = "admin", "admin123"
ALT_PWD = "Netops@2026verify"  # 非默认密码，避免 must_change_password 拦截


# ---------------- 基础 HTTP ----------------

def _http(method, path, data=None, token=None, timeout=20):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"[ERR HTTP {e.code}] {method} {path}: {err[:400]}", file=sys.stderr)
        raise


def post(path, data=None, token=None, timeout=20):
    return _http("POST", path, data=data, token=token, timeout=timeout)


def get(path, token=None, timeout=20):
    return _http("GET", path, token=token, timeout=timeout)


def ensure_usable_token():
    """登录+如果 must_change_password 就改成 alt 密码再登录，返回可通行 token。"""
    for password in (PWD, ALT_PWD):
        try:
            login_raw = post("/api/auth/login", {"username": USER, "password": password})
        except urllib.error.HTTPError as e:
            if e.code in (401, 429):
                continue
            raise
        login = json.loads(login_raw)
        token = login["token"]
        must = login.get("must_change_password")
        print(f"[login] 以 passwd=...{password[-4:]} 登录 must_change={must}")
        if not must:
            return token, login
        # must change → 先改密再用 ALT 重登
        try:
            post("/api/auth/change-password",
                 {"old_password": password, "new_password": ALT_PWD},
                 token=token)
            print("  [改密] 已改为 ALT_PWD")
        except urllib.error.HTTPError as e:
            print(f"  [改密] 失败{e.code}（可能已改过）")
    raise RuntimeError("两次登录都失败")


# ---------------- SSE ----------------

def sse_chat(conv_id, message, token, timeout=360):
    body = json.dumps({"message": message, "attachments": []}).encode()
    req = urllib.request.Request(
        BASE + f"/api/conversations/{conv_id}/messages",
        data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    req.timeout = timeout
    final_chunks = []
    tool_calls = []
    pending_tool = None
    errors = []
    event_types = set()
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        buf = b""
        while time.time() - t0 < timeout:
            ch = r.read(16384)
            if not ch:
                break
            buf += ch
            while b"\n\n" in buf:
                i = buf.index(b"\n\n")
                frame = buf[:i].decode("utf-8", errors="replace")
                buf = buf[i+2:]
                if not frame.startswith("data: "):
                    continue
                try:
                    evt = json.loads(frame[len("data: "):])
                except Exception:
                    continue
                tp = evt.get("type")
                event_types.add(tp)
                if tp == "token":
                    final_chunks.append(evt.get("content", ""))
                elif tp == "tool":
                    nm = evt.get("name", "")
                    st = evt.get("status", "")
                    if st == "start":
                        args = evt.get("args") or {}
                        try:
                            arg_str = json.dumps(args, ensure_ascii=False)
                        except Exception:
                            arg_str = str(args)[:200]
                        pending_tool = {"name": nm, "args": arg_str, "output_len": 0}
                    elif st == "end":
                        out = evt.get("output") or ""
                        if pending_tool is None:
                            pending_tool = {"name": nm, "args": "", "output_len": 0}
                        pending_tool["output_len"] = len(str(out))
                        if evt.get("isError"):
                            pending_tool["error"] = True
                        tool_calls.append(pending_tool)
                        pending_tool = None
                elif tp == "error":
                    errors.append(f"{evt.get('error_code')}: {evt.get('message')}")
                elif tp == "message_end":
                    pass
    if pending_tool:
        tool_calls.append(pending_tool)
    return "".join(final_chunks).strip(), tool_calls, errors, event_types


# ---------------- 展示 ----------------

def print_tool_table(calls):
    if not calls:
        print("  （未调用任何工具 ⚠️）")
        return
    print(f"  工具调用（共 {len(calls)} 次）:")
    for i, t in enumerate(calls, 1):
        inp = str(t.get("args") or t.get("input") or "").replace("\n", " ")
        if len(inp) > 140:
            inp = inp[:137] + "..."
        mark = " ❌" if t.get("error") else ""
        print(f"    {i:2d}. {t.get('name','?')} → 输出 {t.get('output_len',0)} 字符{mark}")
        if inp:
            print(f"        参数: {inp}")


def key_points(text, n=6):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) <= n:
        return lines
    return lines[:n] + [f"...（共 {len(lines)} 行，回答总长度 {len(text)} 字）"]


def _tf(t):
    return str(t.get("args") or t.get("input") or "")


# ---------------- 期望核对 ----------------

def check_expectations(label, ans, tools):
    checks = []
    a = ans
    tool_names = [t.get("name") or "" for t in tools]
    data_tool = any(("execute" in n.lower() or "run_python" in n.lower()
                     or ("read_file" in n.lower() and "alerts" in _tf(t)))
                    for n, t in zip(tool_names, tools))
    onto_tool = any("ontology" in n.lower() for n in tool_names)

    if label == "Q1-故障影响分析":
        checks.append((data_tool, "数据工具（execute/run_python/read_file）查了告警"))
        checks.append((onto_tool, "本体工具被调用（基站→片区→客户→装维多跳）"))
        checks.append(("告警" in a or "P1" in a or "P2" in a,
                       "回答提到告警严重度/P1/P2"))
        checks.append(("片区" in a or "客户" in a, "回答给出影响面（片区/客户）"))
        checks.append(("VIP" in a or "政企" in a or "重要" in a or any(
            nm in a for nm in ["王强", "赵敏", "陈涛"]),
                       "提到 VIP/责任人（至少其一）"))
        checks.append((any(nm in a for nm in ["王强", "赵敏", "陈涛"]),
                       "给出装维人姓名"))
    elif label == "Q2-运营指标分析":
        checks.append((data_tool, "pandas 跑 KPI 数据"))
        checks.append(("SLA" in a, "提到 SLA 达标率"))
        checks.append(("环比" in a or any(k in a for k in ["上升", "下降", "提升", "恶化"]),
                       "有环比/升降趋势表述"))
        checks.append(("异常" in a or "告警" in a or any(k in a for k in ["归因", "根因"]),
                       "异常日/告警归因"))
        checks.append((any(k in a for k in ["接通率", "掉线率", "时延", "满意度"]),
                       "至少提到一个具体 KPI 指标名"))
    elif label == "Q3-资源容量分析":
        checks.append((data_tool, "pandas 跑资源台账"))
        checks.append((any(k in a for k in ["80%", "利用率", "高水位", "预警"]),
                       "提到利用率阈值/水位"))
        checks.append((any(k in a for k in ["GPU训练", "高新-下沙光缆", "扩容", "缺口",
                                              "滨江核心机房", "下沙汇聚机房"]),
                       "至少点出一个具体高水位资源或机房名称"))
        checks.append((any(k in a for k in ["扩容", "缺口", "建议增加", "升级", "整治"]),
                       "给出扩容/整改建议或测算"))
    elif label == "Q4-SOP 路由":
        sop_read = sum(1 for n, t in zip(tool_names, tools)
                       if "read_file" in n.lower()
                       and any(s in _tf(t) for s in [
                           "sop_netops_cutover", "sop_netops_emergency",
                           "sop_netops_escalation", "/sops/"]))
        checks.append((sop_read >= 1, f"read_file 读算网 SOP ≥1 条（实际 {sop_read}）"))
        checks.append((("create_ticket" in tool_names) or ("工单" in a),
                       "调用 create_ticket 或在回答里写明工单留痕"))
        checks.append((any(k in a for k in ["步骤", "流程", "1.", "（1）", "第一步"]),
                       "回答按步骤分解"))
        checks.append(("割接" in a and "SOP" in a,
                       "明确引用了割接 SOP 或制度"))
        checks.append((any(k in a for k in ["上报", "审批", "回退", "告知客户", "VIP"]),
                       "包含 SOP 刚性动作（上报/审批/回退/客户告知之一）"))
    return checks


# ---------------- 主流程 ----------------

QUESTIONS = [
    ("Q1-故障影响分析",
     "高新区1号基站最近一周出什么故障了？看看告警，再查一下这个基站覆盖哪个片区、"
     "影响哪些客户（特别是VIP），谁负责维护？最后给我处置建议。"),
    ("Q2-运营指标分析",
     "看一下近 30 天整体运营指标。分片区对比一下接通率、掉线率、SLA 达标率，"
     "环比上一周期是升还是降？有没有异常日？关联告警归因。"),
    ("Q3-资源容量分析",
     "查一下算网资源整体利用率，算力/网络/IDC 哪些超 80% 水位了？需要扩容的给出缺口测算"
     "（目标水位按 70%），顺便查一下资源归属。"),
    ("Q4-SOP 路由",
     "我计划后天对城东1号基站和城东2号基站做设备升级割接，按公司制度该怎么走流程？"
     "每一步都要写明依据哪个 SOP。"),
]


def main():
    print("=" * 64)
    print("  net-ops 算网运营专家 · E2E 问答验证")
    print("=" * 64)

    token, login = ensure_usable_token()
    print(f"[✓] admin 角色={login['user']['role']}")

    emps = json.loads(get("/api/employees", token=token))
    netops = next((e for e in emps if e["id"] == "net-ops"), None)
    if not netops:
        print("[✗] 员工列表无 net-ops"); sys.exit(1)
    print(f"[✓] net-ops：{netops['name']} / {netops['role']} / 技能 {netops.get('skills')}")

    results = []
    for label, q in QUESTIONS:
        print(f"\n{'─'*64}")
        print(f"▶ {label}")
        print(f"  Q: {q[:110]}{'…' if len(q)>110 else ''}")
        cid = json.loads(post(f"/api/employees/net-ops/conversations",
                              data={}, token=token))["conversation_id"]
        print(f"  会话: {cid}")
        t0 = time.time()
        try:
            ans, tools, sse_errs, evts = sse_chat(cid, q, token, timeout=360)
        except Exception as e:
            import traceback
            print(f"  [✗] 异常 {type(e).__name__}: {e}")
            traceback.print_exc()
            results.append((label, False, "", [], 0, 0))
            continue
        dt = time.time() - t0
        print(f"  用时: {dt:.1f}s  |  SSE事件: {sorted(evts)}  |  回答长度: {len(ans)}字")
        if sse_errs:
            print(f"  [SSE error] {'; '.join(sse_errs)}")
        print_tool_table(tools)
        print("  回答要点:")
        for p in key_points(ans, 8):
            print(f"    · {p[:140]}")
        checks = check_expectations(label, ans, tools)
        print("  期望核对:")
        for ok, note in checks:
            print(f"    {'✅' if ok else '❌'} {note}")
        passed_n = sum(1 for o, _ in checks if o)
        results.append((label, all(o for o, _ in checks), ans, tools, dt, passed_n / max(1, len(checks))))

    # 汇总
    print("\n" + "=" * 64)
    print("  汇 总")
    print("=" * 64)
    for label, passed, ans, tools, dt, rate in results:
        mark = "✅" if passed else "⚠️"
        print(f"  {mark} {label:<16} 用时{dt:5.1f}s  回答{len(ans):>4}字  工具{len(tools):>2}次  期望通过率{int(rate*100):>3}%")
    print(f"\n  全部通过期望数: {sum(1 for _,p,_,_,_,_ in results if p)}/{len(results)}")


if __name__ == "__main__":
    main()
