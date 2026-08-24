"""种子脚本 scripts/seed_demo_user.py 单元测试（task/23 + task/24 增强）。

用 monkeypatch 把 scripts.seed_demo_user.default_user_store 与
default_school_store 替换为指向 tmp_path 临时库的工厂，隔离真实
output/users.db，离线独立运行。mock 目标取调用方命名空间：
scripts/seed_demo_user.py 顶层 `from services.user_store import
default_user_store` 与 `from services.school_store import
default_school_store` 均绑定在模块级，故替换 seed_demo_user 上同名引用。
task/24 增强：补 default_school_store 的 patch，杜绝在真实 output/users.db
落 DEMO 学校的副作用；新增学校种子幂等与账号 school_id 指向用例。
"""
from __future__ import annotations

import sqlite3

import pytest
from werkzeug.security import check_password_hash

import scripts.seed_demo_user as seed_demo_user
from services.school_store import SchoolStore
from services.user_store import UserStore

# 演示账号期望值：(role, plan, display_name, 明文密码)
_EXPECTED_USERS = {
    "demo": {"role": "teacher", "plan": "pro", "display_name": "演示教师",
             "password": "demo1234"},
    "admin": {"role": "admin", "plan": "pro", "display_name": "系统管理员",
              "password": "admin123"},
}


@pytest.fixture
def store(monkeypatch, tmp_path):
    """把种子脚本 default_user_store/default_school_store 指向 tmp 临时库，返回用户 store。"""
    db_path = str(tmp_path / "seed_users.db")
    store = UserStore(db_path)
    school_store = SchoolStore(db_path)
    monkeypatch.setattr(seed_demo_user, "default_user_store", lambda: store)
    monkeypatch.setattr(
        seed_demo_user, "default_school_store", lambda: school_store
    )
    return store


def _row_count(store: UserStore) -> int:
    """直连 store 底层 db 统计 users 表行数。"""
    conn = sqlite3.connect(store._db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def _school_row_count(store: UserStore) -> int:
    """直连 store 底层 db 统计 schools 表行数。"""
    conn = sqlite3.connect(store._db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
    finally:
        conn.close()


def test_seed_first_run_creates_demo_and_admin_with_fields(store):
    """首次运行：demo/admin 均创建，role/plan/display_name 正确。"""
    assert seed_demo_user.main() == 0
    for username, expected in _EXPECTED_USERS.items():
        user = store.get_user_by_username(username)
        assert user is not None, f"{username} 应已创建"
        assert user["role"] == expected["role"]
        assert user["plan"] == expected["plan"]
        assert user["display_name"] == expected["display_name"]
    assert _row_count(store) == 2


def test_seed_password_stored_as_hash_verifiable_and_not_plaintext(store):
    """DB 存的是可校验的密码哈希，非明文。"""
    seed_demo_user.main()
    for username, expected in _EXPECTED_USERS.items():
        user = store.get_user_by_username(username)
        assert user is not None
        stored = user["password_hash"]
        assert stored != expected["password"]
        assert expected["password"] not in stored
        assert check_password_hash(stored, expected["password"]) is True


def test_seed_second_run_idempotent(store, capsys):
    """二次运行幂等：不报错、不重复创建，记录仍各一条。"""
    assert seed_demo_user.main() == 0
    assert seed_demo_user.main() == 0
    assert _row_count(store) == 2
    out = capsys.readouterr().out
    assert out.count("已存在，跳过") == 2


def test_seed_stdout_contains_no_password_hash(store, capsys):
    """种子脚本输出不含 DB 中的密码哈希（仅明文登录指引）。"""
    seed_demo_user.main()
    out = capsys.readouterr().out
    for username in _EXPECTED_USERS:
        stored = store.get_user_by_username(username)["password_hash"]
        assert stored not in out


def test_seed_creates_demo_school_and_assigns_school_id(store):
    """种子同时创建 DEMO 学校，demo/admin 账号 school_id 指向该校。"""
    seed_demo_user.main()
    school_store = SchoolStore(store._db_path)
    school = school_store.get_school_by_code("DEMO")
    assert school is not None, "DEMO 学校应已创建"
    assert school["name"] == "演示学校"
    for username in _EXPECTED_USERS:
        user = store.get_user_by_username(username)
        assert user["school_id"] == school["id"], (
            f"{username} school_id 应指向演示学校"
        )
    assert _school_row_count(store) == 1


def test_seed_second_run_school_idempotent(store):
    """二次运行幂等：学校仍只有一条，账号仍各一条且 school_id 不变。"""
    assert seed_demo_user.main() == 0
    assert seed_demo_user.main() == 0
    assert _school_row_count(store) == 1
    assert _row_count(store) == 2
    school_id = SchoolStore(store._db_path).get_school_by_code("DEMO")["id"]
    for username in _EXPECTED_USERS:
        assert store.get_user_by_username(username)["school_id"] == school_id
