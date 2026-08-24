"""Flask 路由：用户角色分配（F10 学校管理员权限体系，全局 admin 专属）。

POST /api/admin/users/<user_id>/role 设置目标用户角色；仅全局 admin 可调用，
school_admin/teacher/游客调用一律 403。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from services import auth
from services.user_store import default_user_store

bp = Blueprint('user_role', __name__)

_VALID_ROLES = {"teacher", "school_admin", "admin"}


@bp.route('/api/admin/users/<user_id>/role', methods=['POST'])
def update_user_role(user_id: str):
    """更新用户角色；非法角色 400、用户不存在 404、非 admin 403。"""
    guard = auth.login_required()
    if guard:
        return guard
    user = auth.current_user()
    if user is None or user.get("role") != "admin":
        return jsonify({"message": "需要管理员权限"}), 403
    body = request.get_json(silent=True) or {}
    role = body.get('role')
    if role not in _VALID_ROLES:
        return jsonify({"message": "非法角色"}), 400
    store = default_user_store()
    if store.get_user(user_id) is None:
        return jsonify({"message": "用户不存在"}), 404
    store.update_role(user_id, role)
    return jsonify({"message": "角色已更新", "role": role}), 200
