"""裸机 SQLite 起步护栏：数据目录不存在时 catalog.init 必须自建父目录。

上游 sqlite 路径只服务测试夹具（conftest 先建好临时目录），裸机首跑时
DATA_DIR 还不存在，而 sqlite3.connect 不自建父目录，会直接 OperationalError
导致整个应用启动失败。本用例钉住 _conn() 里的 mkdir 护栏。
"""
from app.catalog import db as catdb


def test_init_creates_missing_data_dir(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "db" / "catalog.db"
    assert not target.parent.exists()
    monkeypatch.setattr(catdb, "DB", target)

    catdb.init()

    assert target.exists()
    con = catdb._conn()
    try:
        names = {r[0] for r in con.execute(
            "select name from sqlite_master where type='table'")}
    finally:
        con.close()
    assert "employees" in names
    assert "knowledge_bases" in names


def test_init_is_idempotent_on_existing_dir(tmp_path, monkeypatch):
    target = tmp_path / "catalog.db"
    monkeypatch.setattr(catdb, "DB", target)

    catdb.init()
    catdb.init()  # 目录已存在时 mkdir(exist_ok=True) 不得抛错

    assert target.exists()
