"""Flask 路由：首页、OCR 识别、文本评分。"""
import logging

from flask import Blueprint, request, jsonify, render_template

from services.ocr import recognize_texts
from services.scoring import grade_answer
from utils.config import OCR_LANG_MAP
from utils.files import allowed_file, save_upload

logger = logging.getLogger(__name__)

bp = Blueprint('main', __name__)


@bp.route('/')
def home():
    """渲染首页。"""
    return render_template('index.html')


@bp.route('/ocr', methods=['POST'])
def ocr_service():
    """识别学生作业图片与参考答案图片中的文字。"""
    if 'file1' not in request.files or 'file2' not in request.files:
        return jsonify({"message": "没有找到文件！"}), 400

    file1 = request.files['file1']
    file2 = request.files['file2']

    if not file1 or not file1.filename or not file2 or not file2.filename:
        return jsonify({"message": "上传文件失败"}), 400

    if not allowed_file(file1.filename) or not allowed_file(file2.filename):
        return jsonify({"message": "不支持的文件类型"}), 400

    file1_path = save_upload(file1)
    file2_path = save_upload(file2)

    language = request.form.get('language')
    lang = OCR_LANG_MAP.get(language, 'en')
    logger.info("OCR 请求: %s, %s, language=%s", file1_path, file2_path, language)

    try:
        work_content, answer_content = recognize_texts([file1_path, file2_path], lang=lang)
        return jsonify({
            "workContent": work_content,
            "answerContent": answer_content,
        }), 200

    except Exception as e:
        logger.error("OCR 处理出错: %s", e, exc_info=True)
        return jsonify({"message": "文字识别失败，请重试"}), 500


@bp.route('/compare_texts', methods=['POST'])
def compare_texts():
    """对作业内容与参考答案评分，支持在线/离线模式。"""
    data = request.json
    work_content = data.get('workContent')
    answer_content = data.get('answerContent')
    force_online = data.get('forceOnline', False)

    if not work_content or not answer_content:
        return jsonify({"message": "请输入作业内容和参考答案内容"}), 400

    result = grade_answer(answer_content, work_content, force_online=force_online)
    return jsonify({
        "score": result["score"],
        "method": result["method"],
        "degraded": result["degraded"],
        "routed": result["routed"],
    }), 200
