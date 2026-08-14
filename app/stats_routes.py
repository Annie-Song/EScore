"""Flask 路由：批改统计查询与统计报告下载。"""
import logging
import os
import uuid
from datetime import datetime
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request, send_file

from services.stats import analyze_batch
from services.stats_report import build_stats_docx, build_stats_html
from services.store import default_store
from utils.config import REPORT_FOLDER

_DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

logger = logging.getLogger(__name__)

bp = Blueprint('stats', __name__)


@bp.route('/batches', methods=['GET'])
def list_batches():
    """列出全部批改批次，按创建时间倒序。"""
    return jsonify(default_store().list_batches()), 200


@bp.route('/stats/<batch_id>', methods=['GET'])
def batch_stats(batch_id: str):
    """查询批次聚合统计，批次不存在返回 404。"""
    store = default_store()
    if store.get_batch(batch_id) is None:
        return jsonify({"message": "批次不存在"}), 404
    return jsonify(analyze_batch(store, batch_id)), 200


@bp.route('/batch_records/<batch_id>', methods=['GET'])
def batch_records(batch_id: str):
    """查询批次全部批改明细记录，转字典列表返回。"""
    records = default_store().list_records(batch_id)
    return jsonify([_record_to_dict(record) for record in records]), 200


@bp.route('/stats_report', methods=['POST'])
def stats_report():
    """生成并下载批改统计报告，支持 html 与 docx 两种格式。"""
    data = request.json or {}
    batch_id = data.get('batch_id')
    fmt = data.get('format', 'html')

    if not batch_id:
        return jsonify({"message": "缺少批次 ID"}), 400
    if fmt not in ('html', 'docx'):
        return jsonify({"message": "不支持的下载格式"}), 400

    store = default_store()
    if store.get_batch(batch_id) is None:
        return jsonify({"message": "批次不存在"}), 404

    stats = analyze_batch(store, batch_id)
    try:
        if fmt == 'html':
            html_report = build_stats_html(stats)
            return Response(
                html_report,
                mimetype='text/html',
                headers={
                    'Content-Disposition': (
                        "attachment; filename=stats_report.html; "
                        f"filename*=UTF-8''{quote('统计报告.html')}"
                    )
                },
            )

        os.makedirs(REPORT_FOLDER, exist_ok=True)
        docx_name = f"stats_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.docx"
        # abspath 统一解析：makedirs/写入按 CWD 落盘，send_file 却按 app.root_path 拼接相对路径，
        # 不转绝对路径会导致 send_file 读不到文件，与 routes.py download_report 处理一致。
        out_path = os.path.abspath(os.path.join(REPORT_FOLDER, docx_name))
        build_stats_docx(stats, out_path)
        return send_file(
            out_path,
            as_attachment=True,
            download_name='统计报告.docx',
            mimetype=_DOCX_MIMETYPE,
        )

    except Exception as e:  # noqa: BLE001 - 顶线兜底返回 500，不吞异常
        logger.error("统计报告生成出错: %s", e, exc_info=True)
        return jsonify({"message": "统计报告生成失败，请重试"}), 500


def _record_to_dict(record) -> dict:
    """将 GradeRecord 转为可 JSON 序列化的字典。"""
    return {
        "record_id": record.record_id,
        "batch_id": record.batch_id,
        "question_no": record.question_no,
        "work_text": record.work_text,
        "answer_text": record.answer_text,
        "score": record.score,
        "method": record.method,
        "degraded": record.degraded,
        "routed": record.routed,
        "error_category": record.error_category,
        "error_reason": record.error_reason,
        "created_at": record.created_at,
    }
