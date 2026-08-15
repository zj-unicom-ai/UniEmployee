"""资源管理：技能/工具/知识库/SOP/连接器 CRUD。"""

import json
import time
from pathlib import Path

from .db import _conn, _soft_delete_row, _unlink, _unlink_view


# ---------------------------------------------------------------------------
# 技能管理（上传/删除）
# ---------------------------------------------------------------------------

def upsert_skill(skill_id: str, name: str, description: str, dir_: str):
    con = _conn()
    con.execute(
        "INSERT INTO skills(id,name,description,dir) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "dir=excluded.dir, deleted_at=NULL",
        (skill_id, name, description, dir_))
    con.commit()
    con.close()


def get_skill(skill_id: str) -> dict | None:
    con = _conn()
    r = con.execute(
        "SELECT id,name,description,dir FROM skills WHERE id=? AND deleted_at IS NULL",
        (skill_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def get_skill_content(skill_id: str) -> str | None:
    """读取技能 SKILL.md 内容；目录相对 backend/ 或绝对路径都按仓库根解析。"""
    info = get_skill(skill_id)
    if not info:
        return None
    dir_ = info.get("dir") or f"skills/{skill_id}"
    p = Path(dir_)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent.parent / p
    md = p / "SKILL.md"
    if not md.exists():
        return None
    return md.read_text(encoding="utf-8")


def update_skill_content(skill_id: str, content: str) -> bool:
    """覆写自定义技能 SKILL.md 内容；内置技能拒绝。返回是否更新成功。"""
    info = get_skill(skill_id)
    if not info:
        return False
    dir_ = info.get("dir") or ""
    if not dir_.startswith("skills-custom/"):
        raise PermissionError("内置技能不允许直接修改内容")
    p = Path(__file__).resolve().parent.parent.parent / dir_ / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return True


def employees_using_skill(skill_id: str) -> list[str]:
    con = _conn()
    out = [r[0] for r in con.execute(
        "SELECT employee_id FROM employee_skills WHERE skill_id=?", (skill_id,))]
    con.close()
    return out


def delete_skill(skill_id: str):
    _soft_delete_row("skills", skill_id)
    con = _conn()
    con.execute("DELETE FROM employee_skills WHERE skill_id=?", (skill_id,))
    con.commit()
    con.close()


def employees_using_sop(sop_id: str) -> list[str]:
    con = _conn()
    out = [r[0] for r in con.execute(
        "SELECT employee_id FROM employee_sops WHERE sop_id=?", (sop_id,))]
    con.close()
    return out


# ---------------------------------------------------------------------------
# 工具管理（工具由代码定义，页面只编辑元信息）
# ---------------------------------------------------------------------------

def update_tool(tool_id: str, description: str, needs_approval) -> bool:
    con = _conn()
    cur = con.cursor()
    na = json.dumps(needs_approval, ensure_ascii=False) if needs_approval else None
    cur.execute("UPDATE tools SET description=?, needs_approval=? WHERE id=?",
                (description, na, tool_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def employees_using_tool(tool_id: str) -> list[str]:
    return _unlink_view("tool", tool_id)


# ---------------------------------------------------------------------------
# 知识库管理（含 RAGFlow dataset 映射）
# ---------------------------------------------------------------------------

def create_kb(kb_id: str, name: str, description: str = "", ragflow_dataset_id: str = "") -> str:
    con = _conn()
    con.execute(
        "INSERT INTO knowledge_bases(id,name,description,ragflow_dataset_id) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "ragflow_dataset_id=excluded.ragflow_dataset_id, "
        "deleted_at=NULL",
        (kb_id, name, description, ragflow_dataset_id))
    con.commit()
    con.close()
    return kb_id


def update_kb(kb_id: str, name: str, description: str,
              ragflow_dataset_id: str | None = None) -> bool:
    con = _conn()
    cur = con.cursor()
    if ragflow_dataset_id is None:
        cur.execute("UPDATE knowledge_bases SET name=?, description=? WHERE id=?",
                    (name, description, kb_id))
    else:
        cur.execute(
            "UPDATE knowledge_bases SET name=?, description=?, ragflow_dataset_id=? WHERE id=?",
            (name, description, ragflow_dataset_id, kb_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def get_kb(kb_id: str) -> dict | None:
    con = _conn()
    r = con.execute(
        "SELECT id,name,description,ragflow_dataset_id FROM knowledge_bases "
        "WHERE id=? AND deleted_at IS NULL", (kb_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def employees_using_kb(kb_id: str) -> list[str]:
    return _unlink_view("kb", kb_id)


def delete_kb(kb_id: str) -> list[str]:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    affected = [r[0] for r in cur.execute(
        "SELECT employee_id FROM employee_kbs WHERE kb_id=?", (kb_id,))]
    cur.execute("UPDATE knowledge_bases SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (now, kb_id))
    # kb_entries 表已废弃，不再需要级联删除
    cur.execute("DELETE FROM employee_kbs WHERE kb_id=?", (kb_id,))
    con.commit()
    con.close()
    return affected

# ---------------------------------------------------------------------------
# SOP 管理
# ---------------------------------------------------------------------------

def create_sop(sop_id: str, name: str, description: str = "", content: str = "") -> str:
    con = _conn()
    con.execute(
        "INSERT INTO sops(id,name,description,content) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "content=excluded.content, deleted_at=NULL",
        (sop_id, name, description, content))
    con.commit()
    con.close()
    return sop_id


def update_sop(sop_id: str, name: str, description: str, content: str) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "UPDATE sops SET name=?, description=?, content=? WHERE id=?",
        (name, description, content, sop_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def get_sop(sop_id: str) -> dict | None:
    con = _conn()
    r = con.execute(
        "SELECT id,name,description,content FROM sops WHERE id=? AND deleted_at IS NULL",
        (sop_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def delete_sop(sop_id: str) -> list[str]:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    affected = [r[0] for r in cur.execute(
        "SELECT employee_id FROM employee_sops WHERE sop_id=?", (sop_id,))]
    cur.execute("UPDATE sops SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (now, sop_id))
    cur.execute("DELETE FROM employee_sops WHERE sop_id=?", (sop_id,))
    con.commit()
    con.close()
    return affected


# ---------------------------------------------------------------------------
# 连接器管理
# ---------------------------------------------------------------------------

def create_connector(conn_id: str, name: str, description: str = "",
                     config: dict | None = None) -> str:
    con = _conn()
    con.execute(
        "INSERT INTO connectors(id,name,description,config) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "config=excluded.config, deleted_at=NULL",
        (conn_id, name, description, json.dumps(config or {}, ensure_ascii=False)))
    con.commit()
    con.close()
    return conn_id


def update_connector(conn_id: str, name: str, description: str,
                     config: dict | None = None) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "UPDATE connectors SET name=?, description=?, config=? WHERE id=?",
        (name, description, json.dumps(config or {}, ensure_ascii=False), conn_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def get_connector(conn_id: str) -> dict | None:
    con = _conn()
    r = con.execute(
        "SELECT id,name,description,config FROM connectors WHERE id=? AND deleted_at IS NULL",
        (conn_id,)).fetchone()
    con.close()
    if not r:
        return None
    out = dict(r)
    try:
        out["config"] = json.loads(out["config"]) if isinstance(out["config"], str) else out.get("config", {})
    except (json.JSONDecodeError, TypeError):
        out["config"] = {}
    return out


def delete_connector(conn_id: str) -> list[str]:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    affected = [r[0] for r in cur.execute(
        "SELECT employee_id FROM employee_connectors WHERE connector_id=?", (conn_id,))]
    cur.execute("UPDATE connectors SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (now, conn_id))
    cur.execute("DELETE FROM employee_connectors WHERE connector_id=?", (conn_id,))
    con.commit()
    con.close()
    return affected
