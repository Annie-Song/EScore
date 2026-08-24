"""Flask 路由：用户认证 REST API（task/19）。

提供注册 / 登录 / 登出 / 当前会话查询四个接口，会话信息写入 Flask session。
"""
from __future__ import annotations

import sqlite3

from flask import Blueprint, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from services.school_store import default_school_store
from services.user_store import default_user_store

bp = Blueprint('auth', __name__)

# 公开字段：剔除 password_hash，避免哈希泄露到响应
_PUBLIC_FIELDS = (
    "id", "username", "display_name", "role", "plan",
    "school_id", "avatar", "created_at", "updated_at",
)


def _user_public(row: dict) -> dict:
    """从用户存储字典挑选公开字段，剔除 password_hash。"""
    return {field: row[field] for field in _PUBLIC_FIELDS}


def _set_session(row: dict) -> None:
    """将会话用户关键字段写入 session，供 base.html 免 DB 渲染。"""
    session["user_id"] = row["id"]
    session["display_name"] = row["display_name"]
    session["role"] = row["role"]
    session["plan"] = row["plan"]
    session["school_id"] = row.get("school_id")


@bp.route('/api/auth/register', methods=['POST'])
def auth_register():
    """注册新用户：校验参数、写库并建立会话，重名返回 409。"""
    body = request.get_json(silent=True) or {}
    username = (body.get('username') or '').strip()
    password = body.get('password') or ''
    if not username:
        return jsonify({"message": "用户名不能为空"}), 400
    if len(password) < 6:
        return jsonify({"message": "密码至少 6 位"}), 400

    store = default_user_store()
    school_id = None
    school_code = (body.get('school_code') or '').strip()
    if school_code:
        school = default_school_store().get_school_by_code(school_code)
        if school is None:
            return jsonify({"message": "学校代码无效"}), 400
        school_id = school["id"]
    try:
        user = store.create_user(
            username=username,
            password_hash=generate_password_hash(password),
            display_name=(body.get('display_name') or '').strip(),
            school_id=school_id,
        )
    except sqlite3.IntegrityError:
        return jsonify({"message": "用户名已存在"}), 409

    _set_session(user)
    return jsonify({"user": _user_public(user)}), 201


@bp.route('/api/auth/login', methods=['POST'])
def auth_login():
    """登录：校验用户名密码，成功写入会话并返回公开用户信息。"""
    body = request.get_json(silent=True) or {}
    username = (body.get('username') or '').strip()
    password = body.get('password') or ''

    user = default_user_store().get_user_by_username(username)
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"message": "用户名或密码错误"}), 401

    session.permanent = True
    _set_session(user)
    return jsonify({"user": _user_public(user)}), 200


@bp.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """登出：清空会话。"""
    session.clear()
    return jsonify({"ok": True}), 200


@bp.route('/api/auth/me', methods=['GET'])
def auth_me():
    """返回当前会话用户（游客为 None），供前端会话还原。"""
    user_id = str(session.get("user_id", ""))
    if not user_id:
        return jsonify({"user": None}), 200
    user = default_user_store().get_user(user_id)
    return jsonify({"user": _user_public(user) if user else None}), 200


@bp.route('/login', methods=['GET'])
def auth_login_page():
    """登录/注册页面。"""
    return render_template('login.html')
