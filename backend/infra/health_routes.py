"""Flask 路由：主应用健康检查（task/26 D3 单环境收敛）。

统一三进程健康探测：主应用 /health 与嵌入/OCR 微服务的 /health 保持同构，
供 scripts/healthcheck.py 一键检查三服务就绪状态。
"""
from flask import Blueprint, jsonify

bp = Blueprint('health', __name__)


@bp.route('/health')
def health():
    """健康检查：返回主应用存活状态，200。"""
    return jsonify({"status": "ok"}), 200
