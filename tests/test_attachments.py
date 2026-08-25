"""附件功能测试：文件名清洗 / 落盘 / 路径校验 / 消息内容注入。"""
import asyncio
import io

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app import attachments


def _upload(name, data, ctype="text/csv"):
    return UploadFile(file=io.BytesIO(data), filename=name,
                      headers=Headers({"content-type": ctype}))


@pytest.fixture(autouse=True)
def tmp_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "WORKSPACE_DATA", tmp_path)


def test_sanitize_name():
    assert attachments._sanitize_name("报告 v1.csv") == "报告_v1.csv"
    assert attachments._sanitize_name("../../etc/passwd") == "etc_passwd"
    assert attachments._sanitize_name("") == "file"


async def _save(name, data, ctype="text/csv"):
    return await attachments.save_attachment("c1", "u1", _upload(name, data, ctype))


def test_save_attachment_lands_in_user_dir():
    meta = asyncio.run(_save("data.csv", b"a,b\n1,2\n"))
    assert meta["name"] == "data.csv"
    assert meta["size"] == 8
    assert meta["content_type"] == "text/csv"
    assert meta["path"].startswith("/data/uploads/u1/c1/")
    assert meta["path"].endswith("data.csv")
    # 真实落盘位置与虚拟路径一一对应
    real = attachments.WORKSPACE_DATA / "uploads" / "u1" / "c1" / meta["path"].rsplit("/", 1)[-1]
    assert real.read_bytes() == b"a,b\n1,2\n"


def test_save_attachment_rejects_empty_and_oversize(monkeypatch):
    with pytest.raises(HTTPException) as e:
        asyncio.run(_save("empty.csv", b""))
    assert e.value.status_code == 400

    monkeypatch.setattr(attachments, "MAX_ATTACHMENT_SIZE", 10)
    with pytest.raises(HTTPException) as e:
        asyncio.run(_save("big.csv", b"x" * 11))
    assert e.value.status_code == 413


def test_validate_attachment_path():
    ok = "/data/uploads/u1/c1/123_a.csv"
    assert attachments.validate_attachment_path("u1", ok) is True
    # 别的用户目录 / 任意路径 / 目录穿越均拒绝
    assert attachments.validate_attachment_path("u1", "/data/uploads/u2/c1/a.csv") is False
    assert attachments.validate_attachment_path("u1", "/etc/passwd") is False
    assert attachments.validate_attachment_path("u1", "/data/uploads/u1/c1/../../secret") is False
    assert attachments.validate_attachment_path("u1", None) is False


def test_compose_user_content():
    atts = [{"name": "sales.csv", "path": "/data/uploads/u1/c1/1_sales.csv",
             "size": 2048, "content_type": "text/csv"}]
    # 有文本：文本在前，附件清单在后，且含读取指引
    out = attachments.compose_user_content("分析一下", atts)
    assert out.startswith("分析一下")
    assert "sales.csv" in out and "/data/uploads/u1/c1/1_sales.csv" in out
    assert "read_file" in out and "run_python" in out
    # 纯附件消息也合法
    out2 = attachments.compose_user_content("", atts)
    assert "sales.csv" in out2
    # 无附件：原样返回
    assert attachments.compose_user_content("hi", []) == "hi"
