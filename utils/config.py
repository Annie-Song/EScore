"""集中管理项目常量。"""
import os

# 文件上传目录
UPLOAD_FOLDER = './uploads'

# 支持的文件类型
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'tiff'}

# OCR 语言映射：前端语言选项映射到 PaddleOCR 的 lang 参数，未匹配默认英文
OCR_LANG_MAP = {"中文": "ch", "英文": "en"}

# 级联精排路由配置（阈值量纲与 offline_score 一致，均为百分制 0-100）
ROUTING_MODE = "threshold"  # 路由策略："threshold" 低分路由 / "band" 中段边界带 / "off" 关闭
LOW_THRESHOLD = 60.0        # 低分路由阈值：离线分低于此值转 DeepSeek 精排
BAND_LOW = 40.0             # 中段边界带下界
BAND_HIGH = 80.0            # 中段边界带上界

# 级联精排路由双档预设：使用者在评分时自选（fast=低成本快速版/quality=高质版）
# fast 与既有默认常量一致（LOW_THRESHOLD=60，行为不变）；quality 提高 low 阈值，
# 差档作答更多被路由到 DeepSeek 精排（代价是优档浪费与总路由成本上升）
ROUTING_PRESETS = {
    "fast": {"mode": ROUTING_MODE, "low": LOW_THRESHOLD},
    "quality": {"mode": "threshold", "low": 80.0},
}
DEFAULT_ROUTING_PRESET = "fast"

# 报告下载配置
REPORT_FOLDER = './output/reports'  # Word 报告临时落盘目录
REPORT_FILENAME = '批改报告'        # 报告下载文件名前缀（前端展示的中文名）

# ESRGAN 图像增强（备选）：低置信度 OCR 自动增强重识别
ENHANCE_WEIGHTS_PATH = './ESRGAN/models/RealESRGAN_x4plus.pth'  # 超分模型预训练权重
ENHANCE_CONFIDENCE_THRESHOLD = 0.6  # 平均置信度低于此值触发增强
ENHANCE_OUTPUT_FOLDER = './output/enhance'  # 增强输出图临时落盘目录

# 作业智能分区：水平投影切分一图多题作业图片为独立区域
SEGMENT_BLANK_RATIO = 0.005  # 空白行判定阈值：行前景像素占比低于 0.5% 视为空白行
SEGMENT_MIN_GAP = 20         # 相邻非空白带最小合并间隙：小于 20 行的间隙并入相邻带
SEGMENT_MIN_HEIGHT = 15      # 噪声带最小高度：低于 15px 的带丢弃

# 批改记录 SQLite 数据库文件，WAL 模式
DB_PATH = './output/grades.db'

# 参考答案嵌入缓存上限：满则整体清空重算，保证内存有界（缓存只是优化）
REF_CACHE_MAX = 256

# 评分评测集（A9）：GAOKAO-Bench 题库 + DeepSeek 三档生成作答 + 离线 benchmark
EVAL_GAOKAO_DIR = './data/gaokao'  # GAOKAO-Bench 根目录（已下载，题目+标准答案+分值）
EVAL_GAOKAO_SUBJECTIVE_DIR = 'Data/Subjective_Questions'  # 主观题相对路径
# 纳入评测的中文主观题文件（全部含标准答案与给分点，与中文作业批改语义一致）
EVAL_SUBJECT_FILES = [
    '2010-2022_Chinese_Language_Ancient_Poetry_Reading.json',
    '2010-2022_Chinese_Language_Classical_Chinese_Reading.json',
    '2010-2022_Chinese_Language_Famous_Passages_and_Sentences_Dictation.json',
    '2010-2022_Chinese_Language_Language_and_Writing_Skills_Open-ended_Questions.json',
    '2010-2022_Chinese_Language_Literary_Text_Reading.json',
    '2010-2022_Chinese_Language_Practical_Text_Reading.json',
]
EVAL_SAMPLE_PER_FILE = 10  # 每类题目采样上限（控制 DeepSeek 生成成本：10×6 题 ×3 档 ≈ 180 次调用）
EVAL_ANSWERS_PATH = './data/eval/answers.json'  # 三档生成作答缓存（生成一次，评测纯离线）
# 档位真实性独立校验（MiniLM 语义分，与生成器无关）：优档离线分低于此值视为可疑、差档高于此值视为可疑
EVAL_TIER_SUSPECT_GOOD_BELOW = 0.6
EVAL_TIER_SUSPECT_BAD_ABOVE = 0.7

# 向量嵌入微服务监听地址：A8 拆分为独立 FastAPI 进程，客户端按此地址对接
EMBEDDING_SERVICE_HOST = "127.0.0.1"
EMBEDDING_SERVICE_PORT = 8765

# 向量嵌入微服务地址：默认本地监听地址，可用环境变量覆盖（独立进程部署时指向其他主机）
EMBEDDING_SERVICE_URL = os.environ.get(
    "EMBEDDING_SERVICE_URL",
    f"http://{EMBEDDING_SERVICE_HOST}:{EMBEDDING_SERVICE_PORT}",
)

# OCR 微服务监听地址：拆分独立 FastAPI 进程，客户端按此地址对接
OCR_SERVICE_HOST = "127.0.0.1"
OCR_SERVICE_PORT = 8766

# OCR 微服务地址：默认本地监听地址，可用环境变量覆盖
OCR_SERVICE_URL = os.environ.get(
    "OCR_SERVICE_URL",
    f"http://{OCR_SERVICE_HOST}:{OCR_SERVICE_PORT}",
)

# 错因 AI 归类：默认关闭（基础用户规则分档），落入模糊带才调 DeepSeek 细分类
ERROR_AI_MODE = False
ERROR_AI_BAND_LOW = 30.0  # 模糊带下界：低于此分一律规则分档
ERROR_AI_BAND_HIGH = 85.0  # 模糊带上界：高于此分一律规则分档

# 批量批改分区裁剪临时目录（文件名用 uuid，防并发冲突）
SEGMENT_OUTPUT_FOLDER = './output/segments'

# 分类题库（F7）：GAOKAO-Bench 全量主客观题入库为可检索题库（数据底座）
QUESTION_BANK_GRADE = '高中'
QUESTION_BANK_DB_PATH = './output/question_bank.db'
QUESTION_BANK_GAOKAO_DIR = EVAL_GAOKAO_DIR  # './data/gaokao'
QUESTION_BANK_SUBJECTIVE_DIR = 'Data/Subjective_Questions'
QUESTION_BANK_OBJECTIVE_DIR = 'Data/Objective_Questions'
QUESTION_BANK_GPT4_OBJ_DIR = 'Results/gpt_4_0314_obj'
QUESTION_BANK_DIFFICULTY_ADVANCED_MIN = 12  # 主观题分值分档：>=此值为进阶
QUESTION_BANK_DIFFICULTY_BASIC_MAX = 6      # 主观题分值分档：<此值为基础，其余中等

# 会话签名密钥：生产必须用环境变量覆盖
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")
# 用户体系 SQLite（users/user_batches/user_favorites 三表）
USER_DB_PATH = './output/users.db'
