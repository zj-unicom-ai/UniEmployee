"""表格附件注册与 DuckDB 查询管理。

职责：
  - register_data_file: 把上传的 CSV/Excel 解析（多 sheet）并注册进用户级 DuckDB 库
  - list_user_tables: 列出当前用户已注册的表格及结构（含样本行，供 LLM 理解数据）
  - execute_query: 对用户 DuckDB 库执行只读 SELECT

注意：paths.WORKSPACE_DATA 通过模块属性动态读取（`_paths.WORKSPACE_DATA`），
测试可 monkeypatch 到临时目录而不影响真实 workspace。
"""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd

from app import paths as _paths

logger = logging.getLogger("app.agent.analyst.fileqa")

# DuckDB 单表返回行数上限（与 sql_tools 的 _MAX_RESULT_ROWS 口径一致）
_MAX_RESULT_ROWS = 50

# 当前用户 ID（streaming.py 在 astream 前 set，工具内部读取）
# 与 sql_tools 的 conv_id/datasource_id contextvar 同一模式：
# 避免依赖 LLM 自觉传 uid——用户身份由后端注入，不可伪造。
_user_id_var: ContextVar[str] = ContextVar("fileqa_user_id", default="")


def set_user_id(uid: str) -> None:
    """streaming.py 在调用 agent.astream 前注入当前用户 ID。"""
    _user_id_var.set(uid or "")


def clear_user_id() -> None:
    """astream 结束后清理。"""
    _user_id_var.set("")


def _json_safe(obj):
    """Decimal/datetime/date → 基本类型（与 sql_tools._json_safe 同口径）。"""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def _sanitize_ident(name: str, max_len: int = 40) -> str:
    """把文件名/sheet 名清洗成 DuckDB 标识符片段：保留字母数字/下划线/中文。"""
    clean = re.sub(r"[^\w\u4e00-\u9fff]", "_", (name or "t"), flags=re.UNICODE)
    clean = re.sub(r"_+", "_", clean).strip("_")
    return (clean or "t")[:max_len]


def _uploads_dir(uid: str) -> Path:
    """用户上传根目录（paths.WORKSPACE_DATA 动态读取，便于测试替换）。"""
    return _paths.WORKSPACE_DATA / "uploads" / uid


def _duckdb_path(uid: str) -> Path:
    """用户级 DuckDB 库文件：每用户一个，跨会话复用。"""
    return _uploads_dir(uid) / "uploaded_tables.duckdb"


def virtual_to_real(virtual_path: str, uid: str) -> Optional[Path]:
    """校验并转换 /data/ 虚拟路径为真实路径。

    只允许本用户 uploads 目录内的 csv/xlsx/xls 文件，防止路径伪造/穿越。
    """
    if not isinstance(virtual_path, str):
        return None
    prefix = f"/data/uploads/{uid}/"
    if not virtual_path.startswith(prefix) or ".." in virtual_path:
        return None
    rel = virtual_path[len("/data/"):]
    if not rel.lower().endswith((".csv", ".xlsx", ".xls")):
        return None
    return _paths.WORKSPACE_DATA / rel


def _read_dataframes(real_path) -> dict[str, pd.DataFrame]:
    """解析数据文件为 {sheet名: DataFrame}。CSV 单表；Excel 多 sheet。

    CSV 编码先试 utf-8-sig（含 BOM 的导出文件），失败回退 gbk
    （国内业务系统导出常见编码），再失败抛出原异常。
    """
    suffix = str(real_path).lower().rsplit(".", 1)[-1]
    if suffix == "csv":
        try:
            df = pd.read_csv(real_path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(real_path, encoding="gbk")
        return {"data": df}
    # Excel：sheet_name=None 返回 {sheet: df}，空 sheet 自动跳过
    sheets = pd.read_excel(real_path, sheet_name=None)
    return {str(k): v for k, v in sheets.items()
            if v is not None and not v.empty}


def register_data_file(virtual_path: str, uid: str) -> dict:
    """把上传的数据文件注册进用户 DuckDB 库。

    返回 {"file": 原文件名, "tables": [{name, sheet, columns, row_count, sample}]}。
    表名规则：CSV 用文件名主干；Excel 每个 sheet 用 "{主干}__{sheet名}"。
    同名表用 CREATE OR REPLACE 覆盖（重复上传同文件即刷新数据）。
    """
    real = virtual_to_real(virtual_path, uid)
    if real is None:
        raise ValueError(f"非法的附件路径: {virtual_path}")
    if not real.exists():
        raise FileNotFoundError(f"附件文件不存在: {virtual_path}")

    stem = _sanitize_ident(real.stem)
    is_csv = real.suffix.lower() == ".csv"
    tables = []
    sheets = _read_dataframes(real)

    db_path = _duckdb_path(uid)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    import duckdb
    con = duckdb.connect(str(db_path))
    try:
        for sheet_name, df in sheets.items():
            # CSV 表名用文件主干；Excel 追加 sheet 名（含单 sheet，保持规则可预测）
            table = stem if is_csv else f"{stem}__{_sanitize_ident(sheet_name)}"
            con.execute(
                f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM df')
            sample = _json_safe(df.head(2).to_dict(orient="records"))
            tables.append({
                "name": table,
                "sheet": sheet_name,
                "columns": [str(c) for c in df.columns],
                "row_count": int(len(df)),
                "sample": sample,
            })
    finally:
        con.close()
    logger.info("表格附件注册成功 user=%s file=%s tables=%s",
                uid, real.name, [t["name"] for t in tables])
    return {"file": real.name, "tables": tables}


def register_attachments(atts: list[dict], uid: str) -> str:
    """批量注册消息里的数据文件附件，返回注入消息的注册摘要文本。

    单个文件注册失败不阻断发送（记日志，摘要中标注失败原因）。
    无数据文件附件时返回空字符串。
    """
    data_atts = [a for a in atts
                 if str(a.get("name", "")).lower().endswith((".csv", ".xlsx", ".xls"))]
    if not data_atts:
        return ""
    lines = ["", "[表格附件已自动注册为可查询数据表]"]
    for a in data_atts:
        try:
            reg = register_data_file(a["path"], uid)
        except Exception as e:
            logger.error("表格附件注册失败 user=%s path=%s: %s",
                         uid, a.get("path"), e, exc_info=True)
            lines.append(f"- {a.get('name', '未命名')}：注册失败（{str(e)[:100]}）")
            continue
        for t in reg["tables"]:
            cols = ", ".join(t["columns"])
            lines.append(f"- 表 \"{t['name']}\"（{t['row_count']} 行，字段: {cols}）")
    lines.append(
        "以上表格可直接用 file_table_query 工具编写 SQL 查询（DuckDB 只读）；"
        "用 file_table_list 可查看全部已注册表格。")
    return "\n".join(lines)


def list_user_tables(uid: str) -> list[dict]:
    """列出用户 DuckDB 库中全部已注册表格及结构。

    返回 [{name, columns: [{name, type}], row_count}]；库不存在返回空表。
    """
    db_path = _duckdb_path(uid)
    if not db_path.exists():
        return []
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        names = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        tables = []
        for name in names:
            cols = con.execute(f'DESCRIBE "{name}"').fetchall()
            count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            tables.append({
                "name": name,
                "columns": [{"name": c[0], "type": c[1]} for c in cols],
                "row_count": int(count),
            })
        return tables
    finally:
        con.close()


_FORBIDDEN_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                       "TRUNCATE", "CREATE", "GRANT", "REVOKE", "ATTACH")


def check_select_only(sql: str) -> Optional[str]:
    """只读校验：非 SELECT/WITH 开头或含写操作关键词时返回错误文案，否则 None。"""
    stripped = (sql or "").strip()
    upper = stripped.upper()
    if not upper:
        return "错误: SQL 查询为空"
    if not upper.startswith(("SELECT", "WITH")):
        return "错误: 只允许执行 SELECT 查询"
    for kw in _FORBIDDEN_KEYWORDS:
        if kw in upper:
            return f"错误: 不允许执行 {kw} 操作，只允许 SELECT 查询"
    return None


def execute_query(uid: str, sql: str, limit: int = _MAX_RESULT_ROWS) -> dict:
    """对用户 DuckDB 库执行只读 SELECT。

    返回 {success, columns, data, row_count, error}；data 最多 limit 行。
    """
    err = check_select_only(sql)
    if err:
        return {"success": False, "error": err, "columns": [], "data": [],
                "row_count": 0}
    db_path = _duckdb_path(uid)
    if not db_path.exists():
        return {"success": False, "error": "当前没有已注册的表格文件，请先上传 csv/xlsx 附件",
                "columns": [], "data": [], "row_count": 0}
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        cur = con.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(limit + 1)
        truncated = len(rows) > limit
        data = [dict(zip(columns, r)) for r in rows[:limit]]
        return {"success": True, "columns": columns, "data": _json_safe(data),
                "row_count": len(data) + (1 if truncated else 0),
                "truncated": truncated, "error": None}
    except Exception as e:
        return {"success": False, "error": str(e)[:300], "columns": [],
                "data": [], "row_count": 0}
    finally:
        con.close()
