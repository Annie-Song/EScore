"""种子演示账号脚本（task/23）：幂等创建 demo / admin 两个演示登录账号。

用法：
    python scripts/seed_demo_user.py

重复运行安全：账号已存在时跳过创建，仅打印登录指引，可反复执行。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 支持 `python scripts/xxx.py` 直接运行：把项目根加入 sys.path，使 services/utils 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.security import generate_password_hash

from services.user_store import UserStore, default_user_store

# 演示账号清单：(用户名, 明文密码, 角色, 套餐, 显示名)
_DEMO_USERS = (
    ("demo", "demo1234", "teacher", "pro", "演示教师"),
    ("admin", "admin123", "admin", "pro", "系统管理员"),
)


def _upsert_demo_user(
    store: UserStore,
    username: str,
    password: str,
    role: str,
    plan: str,
    display_name: str,
) -> str:
    """幂等写入单个演示账号：已存在则跳过，否则创建，返回动作状态。"""
    if store.get_user_by_username(username) is not None:
        return "exists"
    try:
        store.create_user(
            username=username,
            password_hash=generate_password_hash(password),
            display_name=display_name,
            role=role,
            plan=plan,
        )
        return "created"
    except sqlite3.IntegrityError:
        # 并发插入竞争：另一连接已建同名账号，按已存在处理即可
        return "exists"


def main() -> int:
    """创建演示账号并打印登录指引，返回进程退出码。"""
    store = default_user_store()
    for username, password, role, plan, display_name in _DEMO_USERS:
        action = _upsert_demo_user(store, username, password, role, plan, display_name)
        status = "创建" if action == "created" else "已存在，跳过"
        print(f"[种子] {status} 账号 {username}（role={role}, plan={plan}, 显示名={display_name}）")
    print("\n登录指引：")
    for username, password, role, plan, display_name in _DEMO_USERS:
        print(f"  用户名: {username}  密码: {password}  role: {role}  plan: {plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
