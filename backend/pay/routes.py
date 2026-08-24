"""Flask 路由：专业版升级与支付闭环（F5）。

提供升级页面、创建订单、演示回调、异步通知与订单状态查询五个接口。
订单归属校验 + mark_paid 幂等 + 升级 plan，回调重放不会重复升级。
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session

from backend.auth import session as auth
from backend.pay.gateway import LocalDemoGateway, get_active_gateway
from backend.pay.store import default_payment_store
from backend.auth.store import default_user_store
from backend.core import config

logger = logging.getLogger(__name__)

bp = Blueprint('pay', __name__)


@bp.route('/upgrade', methods=['GET'])
def pay_upgrade_page():
    """渲染升级套餐选择页，把定价表传给模板渲染专业版价格。"""
    return render_template('upgrade.html', pricing=config.PRICING), 200


@bp.route('/api/pay/orders', methods=['POST'])
def pay_create_order():
    """创建支付订单：仅支持 pro 套餐，返回支付 URL 供前端跳转。"""
    guard = auth.login_required()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    plan = (body.get('plan') or '').strip()
    if plan not in config.PRICING:
        return jsonify({"message": "不支持的套餐"}), 400
    gateway = get_active_gateway()
    order = default_payment_store().create_order(
        user_id=auth.current_user_id(),
        plan=plan,
        amount_cents=config.PRICING[plan],
        gateway=gateway.name,
    )
    pay_url = gateway.create_order(
        order_id=order["id"],
        amount_cents=order["amount_cents"],
        subject="升级专业版",
    )
    return jsonify({
        "order_id": order["id"],
        "pay_url": pay_url,
        "gateway": gateway.name,
    }), 201


@bp.route('/api/pay/demo/confirm', methods=['GET'])
def pay_demo_confirm():
    """本地演示网关回调：校验令牌后幂等升级，成功跳转个人主页。"""
    params = {
        "order_id": request.args.get("order_id"),
        "token": request.args.get("token"),
    }
    if not LocalDemoGateway().verify_callback(params):
        return jsonify({"message": "支付回调校验失败"}), 400
    order = default_payment_store().get_order(params["order_id"])
    if order is None:
        return jsonify({"message": "订单不存在"}), 404
    _apply_paid(params["order_id"])
    return redirect("/me?upgraded=1")


@bp.route('/api/pay/notify', methods=['POST'])
def pay_notify():
    """支付宝异步通知：验签通过则幂等升级，返回 'success' 文本供支付平台停止重试。"""
    params = request.form.to_dict()
    gateway = get_active_gateway()
    if not gateway.verify_callback(params):
        logger.warning("支付通知验签失败: %s", params)
        return "fail"
    parsed = gateway.parse_callback(params)
    if not parsed.get("success"):
        return "success"
    try:
        _apply_paid(parsed["order_id"])
    except (KeyError, ValueError) as exc:
        # 订单不存在等不可处理情形返回 fail，让支付平台重试而非吞掉
        logger.error("支付通知处理失败: %s", exc)
        return "fail"
    return "success"


@bp.route('/api/pay/status/<order_id>', methods=['GET'])
def pay_status(order_id: str):
    """查询当前登录用户自己的订单状态，返回 {status, plan}。"""
    guard = auth.login_required()
    if guard:
        return guard
    order = default_payment_store().get_order(order_id)
    if order is None:
        return jsonify({"message": "订单不存在"}), 404
    if order["user_id"] != auth.current_user_id():
        return jsonify({"message": "无权查看该订单"}), 403
    return jsonify({"status": order["status"], "plan": order["plan"]}), 200


def _apply_paid(order_id: str) -> None:
    """幂等应用一笔已支付订单：mark_paid 成功后升级用户 plan 并同步会话。

    mark_paid 返回 False 表示订单已是 paid（回调重放），直接返回不重复升级。
    """
    store = default_payment_store()
    order = store.get_order(order_id)
    if order is None:
        raise ValueError("订单不存在")
    if not store.mark_paid(order_id):
        return
    default_user_store().update_plan(order["user_id"], order["plan"])
    session["plan"] = order["plan"]
