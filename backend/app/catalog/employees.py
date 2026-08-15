"""员工配置读取/写入：config_from_ids, get_employee_config, create/update/delete。"""

import json
import time
from .db import _conn


def _build_interrupt_on(tool_ids: list[str]) -> dict:
    """根据所选工具的中断策略自动推导 interrupt_on（需审批的给 allowed_decisions）。"""
    con = _conn()
    cur = con.cursor()
    interrupt_on = {}
    for tid in tool_ids:
        row = cur.execute("SELECT needs_approval FROM tools WHERE id=?", (tid,)).fetchone()
        if row and row["needs_approval"]:
            interrupt_on[tid] = {"allowed_decisions": json.loads(row["needs_approval"])}
        else:
            interrupt_on[tid] = False
    con.close()
    return interrupt_on


def _config_from_ids(emp_row: dict, skills: list, tools: list, kbs: list,
                     sops: list, cons: list) -> dict:
    """按一组已选定的资源 id 拼出完整编译配置。"""
    con = _conn()
    cur = con.cursor()
    skill_dirs = {}
    for sid in skills:
        row = cur.execute("SELECT dir FROM skills WHERE id=? AND deleted_at IS NULL",
                          (sid,)).fetchone()
        if row and row["dir"]:
            skill_dirs[sid] = row["dir"]
    kb_ragflow_datasets = {}
    for kb in kbs:
        kb_row = cur.execute(
            "SELECT ragflow_dataset_id FROM knowledge_bases WHERE id=? AND deleted_at IS NULL",
            (kb,)).fetchone()
        if kb_row and kb_row["ragflow_dataset_id"]:
            kb_ragflow_datasets[kb] = kb_row["ragflow_dataset_id"]
    sop_text = ""
    for sid in sops:
        s = cur.execute("SELECT content FROM sops WHERE id=? AND deleted_at IS NULL",
                        (sid,)).fetchone()
        if s and s["content"]:
            sop_text += ("\n\n" if sop_text else "") + s["content"]
    mcp_servers = {}
    for cid in cons:
        c = cur.execute("SELECT config FROM connectors WHERE id=? AND deleted_at IS NULL",
                        (cid,)).fetchone()
        if c and c["config"]:
            mcp_servers[cid] = json.loads(c["config"])
    con.close()
    return {
        "id": emp_row["id"], "name": emp_row["name"], "role": emp_row["role"],
        "model": emp_row["model"], "persona": emp_row["persona"],
        "backend": emp_row["backend"] or "state",
        "interrupt_on": _build_interrupt_on(tools),
        "subagents": json.loads(emp_row["subagents"]) if isinstance(emp_row["subagents"], str) else (emp_row["subagents"] or []),
        "subagent_policy": emp_row["subagent_policy"] or "",
        "skills": skills, "tools": tools, "kbs": kbs, "sops": sops, "connectors": cons,
        "sop_text": sop_text, "mcp_servers": mcp_servers,
        "skill_dirs": skill_dirs, "kb_ragflow_datasets": kb_ragflow_datasets,
    }


def list_employees_meta() -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT id,name,role,model,backend FROM employees "
        "WHERE deleted_at IS NULL ORDER BY created_at").fetchall()
    out = [dict(r) for r in rows]
    con.close()
    return out


def _set_links(cur, emp_id: str, data: dict):
    for table, key in (("employee_skills", "skills"), ("employee_tools", "tools"),
                       ("employee_kbs", "kbs"), ("employee_sops", "sops"),
                       ("employee_connectors", "connectors")):
        cur.execute(f"DELETE FROM {table} WHERE employee_id=?", (emp_id,))
        for v in data.get(key, []):
            cur.execute(f"INSERT OR IGNORE INTO {table} VALUES(?,?)", (emp_id, v))


# ---------------------------------------------------------------------------
# 读取（编译用）
# ---------------------------------------------------------------------------

def get_employee_config(emp_id: str) -> dict | None:
    """返回编译一个员工所需的完整配置（纯模板，不含任何用户覆盖）。"""
    con = _conn()
    cur = con.cursor()
    r = cur.execute("SELECT * FROM employees WHERE id=? AND deleted_at IS NULL",
                    (emp_id,)).fetchone()
    if not r:
        con.close()
        return None
    skills = [x[0] for x in cur.execute(
        "SELECT skill_id FROM employee_skills WHERE employee_id=?", (emp_id,))]
    tools = [x[0] for x in cur.execute(
        "SELECT tool_id FROM employee_tools WHERE employee_id=?", (emp_id,))]
    kbs = [x[0] for x in cur.execute(
        "SELECT kb_id FROM employee_kbs WHERE employee_id=?", (emp_id,))]
    sops = [x[0] for x in cur.execute(
        "SELECT sop_id FROM employee_sops WHERE employee_id=?", (emp_id,))]
    cons = [x[0] for x in cur.execute(
        "SELECT connector_id FROM employee_connectors WHERE employee_id=?", (emp_id,))]
    con.close()
    return _config_from_ids(r, skills, tools, kbs, sops, cons)


def get_effective_config(user_id: str, emp_id: str) -> dict | None:
    """返回某用户视角下该员工的有效配置 = 模板基础 ∪ add − remove。"""
    from .users import get_assignment
    base = get_employee_config(emp_id)
    if not base:
        return None
    asg = get_assignment(user_id, emp_id)
    if not asg:
        return base
    ov = asg.get("overrides") or {}
    add = ov.get("add", {}) or {}
    remove = ov.get("remove", {}) or {}

    def merge(base_list, key):
        a = set(add.get(key, []))
        rm = set(remove.get(key, []))
        out = [x for x in base_list if x not in rm]
        existing = set(out)
        for x in a:
            if x not in existing and x not in rm:
                out.append(x)
                existing.add(x)
        return out

    skills = merge(base["skills"], "skills")
    tools = merge(base["tools"], "tools")
    kbs = merge(base["kbs"], "kbs")
    sops = merge(base["sops"], "sops")
    cons = merge(base["connectors"], "connectors")
    return _config_from_ids(base, skills, tools, kbs, sops, cons)


def get_skill_dirs_for_employee(emp_id: str, user_id: str | None = None) -> dict[str, str]:
    """返回某员工（可选按用户视角）当前可用技能的目录映射：skill_id -> dir。

    给 runtime 做技能 Store 动态同步提供数据源，避免把 sync 逻辑塞进
    compile_agent 的 system_prompt 组装流程里。目录来自 catalog.db 的 skills.dir，
    允许相对 backend/ 路径或绝对路径（如 ~/.agents/skills/...）。
    """
    cfg = get_effective_config(user_id, emp_id) if user_id else get_employee_config(emp_id)
    if not cfg:
        return {}
    return dict(cfg.get("skill_dirs") or {})


def get_full_employee(emp_id: str) -> dict | None:
    """get_employee_config + 各选中项的展示名（供管理页回显）。"""
    cfg = get_employee_config(emp_id)
    if not cfg:
        return None
    con = _conn()
    cur = con.cursor()

    def names(table):
        return {x["id"]: x["name"] for x in
                cur.execute(f"SELECT id,name FROM {table} WHERE deleted_at IS NULL")}
    cfg["skill_names"] = names("skills")
    cfg["tool_names"] = names("tools")
    cfg["kb_names"] = names("knowledge_bases")
    cfg["sop_names"] = names("sops")
    cfg["connector_names"] = names("connectors")
    con.close()
    return cfg


def catalog() -> dict:
    """返回管理页可用的全部目录（技能/工具/知识库/SOP/连接器）。"""
    from .db import GLOBAL_TOOL_NAMES
    con = _conn()
    cur = con.cursor()

    def allrows(table):
        return [dict(r) for r in cur.execute(
            f"SELECT * FROM {table} WHERE deleted_at IS NULL")]

    out = {
        "skills": [{"id": s["id"], "name": s["name"], "description": s["description"],
                     "dir": s["dir"],
                     "is_custom": bool(s["dir"] and s["dir"].startswith("skills-custom/"))}
                   for s in allrows("skills")],
        "tools": [{"id": t["id"], "name": t["name"], "description": t["description"],
                    "needs_approval": json.loads(t["needs_approval"]) if t["needs_approval"] else None,
                    "is_global": t["id"] in GLOBAL_TOOL_NAMES}
                  for t in allrows("tools")],
        "knowledge_bases": [
            {"id": k["id"], "name": k["name"], "description": k["description"],
             "ragflow_dataset_id": k["ragflow_dataset_id"] or ""}
            for k in allrows("knowledge_bases")
        ],
        "sops": [{"id": s["id"], "name": s["name"], "description": s["description"],
                   "content": s["content"]} for s in allrows("sops")],
        "connectors": [{"id": c["id"], "name": c["name"], "description": c["description"]}
                       for c in allrows("connectors")],
    }
    con.close()
    return out


# ---------------------------------------------------------------------------
# 写入（管理页调用）
# ---------------------------------------------------------------------------

def create_employee(data: dict) -> str:
    emp_id = data.get("id") or ("emp_" + time.strftime("%Y%m%d%H%M%S"))
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    interrupt_on = _build_interrupt_on(data.get("tools", []))
    subagents = json.dumps(data.get("subagents") or [], ensure_ascii=False)
    subagent_policy = data.get("subagent_policy", "")
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO employees(id,name,role,model,persona,backend,mcp_servers,interrupt_on,"
        "subagents,subagent_policy,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role, "
        "model=excluded.model, persona=excluded.persona, backend=excluded.backend, "
        "interrupt_on=excluded.interrupt_on, subagents=excluded.subagents, "
        "subagent_policy=excluded.subagent_policy, "
        "updated_at=excluded.updated_at, deleted_at=NULL",
        (emp_id, data.get("name", emp_id), data.get("role", ""), data.get("model", ""),
         data.get("persona", ""), data.get("backend", "state"), "{}",
         json.dumps(interrupt_on, ensure_ascii=False), subagents, subagent_policy, now, now))
    _set_links(cur, emp_id, data)
    con.commit()
    con.close()
    return emp_id


def update_employee(emp_id: str, data: dict) -> bool:
    con = _conn()
    cur = con.cursor()
    interrupt_on = _build_interrupt_on(data.get("tools", []))
    subagents = data.get("subagents")
    if subagents is None:
        row = cur.execute("SELECT subagents FROM employees WHERE id=?", (emp_id,)).fetchone()
        subagents = json.loads(row["subagents"]) if row and row["subagents"] else []
    subagent_policy = data.get("subagent_policy")
    if subagent_policy is None:
        row = cur.execute("SELECT subagent_policy FROM employees WHERE id=?", (emp_id,)).fetchone()
        subagent_policy = row["subagent_policy"] or "" if row else ""
    cur.execute(
        "UPDATE employees SET name=?,role=?,model=?,persona=?,backend=?,"
        "interrupt_on=?,subagents=?,subagent_policy=?,updated_at=? WHERE id=?",
        (data.get("name", emp_id), data.get("role", ""), data.get("model", ""),
         data.get("persona", ""), data.get("backend", "state"),
         json.dumps(interrupt_on, ensure_ascii=False),
         json.dumps(subagents, ensure_ascii=False),
         subagent_policy,
         time.strftime("%Y-%m-%d %H:%M:%S"), emp_id))
    if cur.rowcount == 0:
        con.close()
        return False
    _set_links(cur, emp_id, data)
    con.commit()
    con.close()
    return True


def delete_employee(emp_id: str):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    cur.execute("UPDATE employees SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (now, emp_id))
    for table in ("employee_skills", "employee_tools", "employee_kbs",
                  "employee_sops", "employee_connectors"):
        cur.execute(f"DELETE FROM {table} WHERE employee_id=?", (emp_id,))
    con.commit()
    con.close()
