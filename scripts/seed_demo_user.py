"""种子演示账号与演示学校脚本（task/24）：幂等创建 demo / admin 账号与 DEMO 学校。

用法：
    python scripts/seed_demo_user.py

重复运行安全：账号/学校已存在时跳过创建，账号 school_id 幂等指向演示学校。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 支持 `python scripts/xxx.py` 直接运行：把项目根加入 sys.path，使 services/utils 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.security import generate_password_hash

from backend.school.store import SchoolStore, default_school_store
from backend.auth.store import UserStore, default_user_store

# 演示学校固定标识：code 唯一，school_id 用固定值保证幂等可复用
_DEMO_SCHOOL_ID = "school-demo"
_DEMO_SCHOOL_NAME = "演示学校"
_DEMO_SCHOOL_CODE = "DEMO"

# 演示账号清单：(用户名, 明文密码, 角色, 套餐, 显示名)
_DEMO_USERS = (
    ("demo", "demo1234", "teacher", "pro", "演示教师"),
    ("admin", "admin123", "admin", "pro", "系统管理员"),
)


def _seed_demo_school(store: SchoolStore) -> tuple[str, str]:
    """幂等创建演示学校，返回 (school_id, 动作状态)。"""
    existing = store.get_school_by_code(_DEMO_SCHOOL_CODE)
    if existing is not None:
        return existing["id"], "exists"
    try:
        school = store.create_school(
            _DEMO_SCHOOL_NAME, _DEMO_SCHOOL_CODE, school_id=_DEMO_SCHOOL_ID
        )
        return school["id"], "created"
    except sqlite3.IntegrityError:
        # 并发插入竞争：另一连接已建同码学校，按已存在处理
        school = store.get_school_by_code(_DEMO_SCHOOL_CODE)
        if school is None:
            raise
        return school["id"], "exists"


def _upsert_demo_user(
    store: UserStore,
    username: str,
    password: str,
    role: str,
    plan: str,
    display_name: str,
    school_id: str,
) -> str:
    """幂等写入单个演示账号：已存在则更新 school_id，否则创建，返回动作状态。"""
    existing = store.get_user_by_username(username)
    if existing is not None:
        store.update_school_id(existing["id"], school_id)
        return "exists"
    try:
        store.create_user(
            username=username,
            password_hash=generate_password_hash(password),
            display_name=display_name,
            role=role,
            plan=plan,
            school_id=school_id,
        )
        return "created"
    except sqlite3.IntegrityError:
        # 并发插入竞争：另一连接已建同名账号，按已存在处理即可
        return "exists"


def main() -> int:
    """创建演示学校与演示账号并打印登录指引，返回进程退出码。"""
    user_store = default_user_store()
    school_store = default_school_store()
    school_id, school_action = _seed_demo_school(school_store)
    school_status = "创建" if school_action == "created" else "已存在，复用"
    print(f"[种子] {school_status} 学校 {_DEMO_SCHOOL_NAME}（code={_DEMO_SCHOOL_CODE}, id={school_id}）")
    for username, password, role, plan, display_name in _DEMO_USERS:
        action = _upsert_demo_user(
            user_store, username, password, role, plan, display_name, school_id
        )
        status = "创建" if action == "created" else "已存在，跳过（school_id 已指向演示学校）"
        print(f"[种子] {status} 账号 {username}（role={role}, plan={plan}, 显示名={display_name}）")
    print("\n登录指引：")
    for username, password, role, plan, display_name in _DEMO_USERS:
        print(f"  用户名: {username}  密码: {password}  role: {role}  plan: {plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
