"""会话 / 会员判定与门控（task/19）：基于 Flask session 的登录与档位控制。

档位排序 free < pro；plan_required / login_required 返回 (response, status) 或 None，
供路由直接 return 短路。current_user() 必须通过模块级函数名调用，保证测试可用
monkeypatch.setattr("services.auth.current_user", ...) 生效。
"""
from __future__ import annotations

from flask import jsonify, session

# 档位排序：数字越大权限越高
_PLAN_RANK = {"free": 0, "pro": 1}


def current_user_id() -> str:
    """返回当前会话用户 id，游客返回空字符串。"""
    return str(session.get("user_id", ""))


def current_user() -> dict | None:
    """按会话 user_id 查 UserStore；游客返回 None。"""
    user_id = current_user_id()
    if not user_id:
        return None
    from services.user_store import default_user_store

    return default_user_store().get_user(user_id)


def current_plan() -> str:
    """返回当前用户档位，游客返回 free。"""
    user = current_user()
    if user is None:
        return "free"
    return str(user.get("plan", "free"))


def plan_required(min_plan: str) -> tuple | None:
    """当前档位低于 min_plan 时返回 402 提示，否则返回 None。"""
    if _PLAN_RANK.get(current_plan(), 0) < _PLAN_RANK.get(min_plan, 0):
        return (
            jsonify({"message": "该功能需升级专业版", "code": "PLAN_REQUIRED"}),
            402,
        )
    return None


def login_required() -> tuple | None:
    """游客返回 401 提示，登录用户返回 None。"""
    if not current_user_id():
        return jsonify({"message": "请先登录"}), 401
    return None
