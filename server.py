"""Flask 后端服务：提供 OCR 识别与作业评分接口。"""
import os
import uuid
import logging
import pytesseract
from PIL import Image
from flask_cors import CORS
from paddleocr import PaddleOCR
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

from scoring import grade_answer

# 加载 .env 配置
load_dotenv()

# 设置日志
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# Tesseract 可执行文件路径（仅使用 Tesseract 路线时需要）
tesseract_cmd = os.environ.get("TESSERACT_CMD")
if tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

# 配置文件上传目录
UPLOAD_FOLDER = './uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 支持的文件类型
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'tiff'}


def allowed_file(filename: str) -> bool:
    """校验文件名后缀是否在允许范围内。"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/ocr', methods=['POST'])
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

    # 生成唯一文件名，避免路径穿越与同名覆盖
    ext1 = file1.filename.rsplit('.', 1)[1].lower()
    ext2 = file2.filename.rsplit('.', 1)[1].lower()
    file1_name = f"{uuid.uuid4().hex}.{ext1}"
    file2_name = f"{uuid.uuid4().hex}.{ext2}"
    file1_path = os.path.join(app.config['UPLOAD_FOLDER'], file1_name)
    file2_path = os.path.join(app.config['UPLOAD_FOLDER'], file2_name)
    file1.save(file1_path)
    file2.save(file2_path)

    model = request.form.get('model')
    language = request.form.get('language')
    logging.info("OCR 请求: %s, %s, model=%s, language=%s", file1_path, file2_path, model, language)

    if model == "PaddleOCR":
        ocr = PaddleOCR(show_log=False, use_angle_cls=True, lang='ch' if language == "中文" else 'en')
    elif model == "Tesseract":
        ocr = None
    else:
        return jsonify({"message": "无效的 OCR 模型！"}), 400

    try:
        if model == "PaddleOCR":
            result1 = ocr.ocr(file1_path, cls=True)
            work_content = '\n'.join([str(line[1][0]) for line in (result1[0] or [])])
            result2 = ocr.ocr(file2_path, cls=True)
            answer_content = '\n'.join([str(line[1][0]) for line in (result2[0] or [])])
        else:  # Tesseract
            tesseract_lang = 'chi_sim' if language == "中文" else 'eng'
            work_content = pytesseract.image_to_string(Image.open(file1_path), lang=tesseract_lang)
            answer_content = pytesseract.image_to_string(Image.open(file2_path), lang=tesseract_lang)

        return jsonify({
            "workContent": work_content,
            "answerContent": answer_content,
        }), 200

    except Exception as e:
        logging.error("OCR 处理出错: %s", e, exc_info=True)
        return jsonify({"message": "文字识别失败，请重试"}), 500


@app.route('/compare_texts', methods=['POST'])
def compare_texts():
    """对作业内容与参考答案评分，支持在线/离线模式。"""
    data = request.json
    work_content = data.get('workContent')
    answer_content = data.get('answerContent')
    use_online = data.get('useDeepseek', False)  # 开关：在线模式启用 DeepSeek

    if not work_content or not answer_content:
        return jsonify({"message": "请输入作业内容和参考答案内容"}), 400

    result = grade_answer(answer_content, work_content, use_online)
    return jsonify({
        "score": result["score"],
        "method": result["method"],
        "degraded": result["degraded"],
    }), 200


if __name__ == '__main__':
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug)
