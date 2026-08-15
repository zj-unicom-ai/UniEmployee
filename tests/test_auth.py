"""认证模块回归测试：密码哈希、JWT、用户 CRUD、角色。"""
import os

from app import auth, catalog


def test_password_hash_and_verify():
    h = auth.hash_password("secret123")
    assert h != "secret123"
    assert auth.verify_password("secret123", h) is True
    assert auth.verify_password("wrong", h) is False


def test_create_token_and_decode():
    catalog.create_user("alice", auth.hash_password("pw"), role="user", user_id="u_alice")
    user = catalog.get_user_by_username("alice")
    token = auth.create_token(user)
    payload = auth.decode_token(token)
    assert payload["sub"] == "u_alice"
    assert payload["username"] == "alice"
    assert payload["role"] == "user"


def test_decode_invalid_token_raises():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        auth.decode_token("not.a.valid.token")


def test_user_crud():
    catalog.create_user("bob", auth.hash_password("x"), role="user", user_id="u_bob")
    assert catalog.get_user_by_username("bob") is not None
    catalog.update_user("u_bob", role="admin")
    assert catalog.get_user("u_bob")["role"] == "admin"
    catalog.set_password("u_bob", auth.hash_password("new"))
    assert auth.verify_password("new", catalog.get_user("u_bob")["password_hash"])
    assert catalog.delete_user("u_bob") is True
    assert catalog.get_user("u_bob") is None


def test_username_unique():
    catalog.create_user("dup", auth.hash_password("p"), user_id="u_dup1")
    # 同 username 不同 id —— INSERT OR IGNORE 会因 username UNIQUE 静默跳过
    catalog.create_user("dup", auth.hash_password("p"), user_id="u_dup2")
    assert catalog.get_user("u_dup2") is None  # 第二个没插进去
    assert catalog.get_user("u_dup1") is not None


def test_list_users():
    catalog.create_user("u1", auth.hash_password("p"), user_id="u_l1")
    catalog.create_user("u2", auth.hash_password("p"), user_id="u_l2")
    names = [u["username"] for u in catalog.list_users()]
    assert "u1" in names and "u2" in names
