"""Flask 路由：管理端学校与跨校批次查询（F10 学校管理员权限体系）。

admin 与 school_admin 可进入管理端：admin 全局建校/跨校查询，school_admin
仅限本校成员、批改统计与批次；teacher/游客一律 403。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from backend.auth import session as auth
from backend.school.store import default_school_store
from backend.batch.store import default_store
from backend.batch.user_activity_store import default_user_activity_store
from backend.auth.store import default_user_store

bp = Blueprint('school', __name__)


def _require_admin() -> tuple | None:
    """非 admin 返回 403 提示，admin 返回 None。"""
    user = auth.current_user()
    if user is None or user.get("role") != "admin":
        return jsonify({"message": "需要管理员权限"}), 403
    return None


def _require_manage() -> tuple | None:
    """非 admin/school_admin 返回 403 提示，二者之一返回 None。"""
    user = auth.current_user()
    if user is None or user.get("role") not in ("admin", "school_admin"):
        return jsonify({"message": "需要管理员权限"}), 403
    return None


@bp.route('/admin')
def admin_page():
    """渲染学校管理页（数据接口单独做角色校验）。"""
    return render_template('admin.html'), 200


@bp.route('/api/admin/schools', methods=['GET'])
def admin_schools_list():
    """列出学校聚合：admin 返回全部，school_admin 仅本校（无校返回空列表）。"""
    guard = _require_manage()
    if guard:
        return guard
    user = auth.current_user()
    store = default_school_store()
    if user["role"] == "admin":
        schools = store.list_schools()
    else:
        school_id = user.get("school_id")
        school = store.get_school(school_id) if school_id else None
        schools = [school] if school else []
    items = []
    for school in schools:
        stats = store.school_batch_stats(school["id"])
        items.append({
            "id": school["id"],
            "name": school["name"],
            "code": school["code"],
            "member_count": school.get("member_count")
            or len(default_user_store().list_users_by_school(school["id"])),
            "batch_count": stats["batch_count"],
            "record_count": stats["record_count"],
            "avg_score": stats["avg_score"],
        })
    return jsonify(items), 200


@bp.route('/api/admin/schools', methods=['POST'])
def admin_schools_create():
    """新建学校（仅 admin，school_admin 建校返回 403）；代码重名返回 409。"""
    guard = _require_admin()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    code = (body.get('code') or '').strip()
    if not name or not code:
        return jsonify({"message": "学校名称与代码均不能为空"}), 400
    store = default_school_store()
    if store.get_school_by_code(code) is not None:
        return jsonify({"message": "学校代码已存在"}), 409
    school = store.create_school(name, code)
    return jsonify({
        "id": school["id"],
        "name": school["name"],
        "code": school["code"],
    }), 201


@bp.route('/api/admin/schools/<school_id>/members', methods=['GET'])
def admin_schools_members(school_id: str):
    """列出学校成员，剔除 password_hash；school_admin 仅限本校。"""
    guard = _require_manage()
    if guard:
        return guard
    user = auth.current_user()
    if user["role"] == "school_admin" and school_id != user.get("school_id"):
        return jsonify({"message": "无权限查看其他学校成员"}), 403
    store = default_school_store()
    if store.get_school(school_id) is None:
        return jsonify({"message": "学校不存在"}), 404
    members = default_user_store().list_users_by_school(school_id)
    public = [
        {key: value for key, value in member.items() if key != "password_hash"}
        for member in members
    ]
    return jsonify(public), 200


@bp.route('/api/admin/batches', methods=['GET'])
def admin_batches():
    """批次列表：admin 可选 school_id 过滤缺省全部，school_admin 强制本校。"""
    guard = _require_manage()
    if guard:
        return guard
    user = auth.current_user()
    school_id = request.args.get('school_id') or ''
    if user["role"] == "school_admin":
        school_id = user.get("school_id") or ''
    return jsonify(_aggregate_school_batches(school_id)), 200


def _aggregate_school_batches(school_id: str) -> list[dict]:
    """联查 user_batches→users→batches，按学校过滤后聚合批次统计。"""
    store = default_store()
    user_store = default_user_store()
    items = []
    for mapping in default_user_activity_store().list_all_batches():
        user = user_store.get_user(mapping["user_id"])
        if user is None:
            continue
        if school_id and user.get("school_id") != school_id:
            continue
        batch = store.get_batch(mapping["batch_id"])
        if batch is None:
            continue
        records = store.list_records(mapping["batch_id"])
        count = len(records)
        items.append({
            "batch_id": mapping["batch_id"],
            "status": batch["status"],
            "teacher_name": user.get("display_name") or user.get("username", ""),
            "school_id": user.get("school_id"),
            "created_at": batch["created_at"],
            "record_count": count,
            "avg_score": round(sum(record.score for record in records) / count, 1)
            if count else 0.0,
        })
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items
