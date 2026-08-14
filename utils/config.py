"""集中管理项目常量。"""

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

# 向量嵌入微服务监听地址：A8 拆分为独立 FastAPI 进程，客户端按此地址对接
EMBEDDING_SERVICE_HOST = "127.0.0.1"
EMBEDDING_SERVICE_PORT = 8765

# 错因 AI 归类：默认关闭（基础用户规则分档），落入模糊带才调 DeepSeek 细分类
ERROR_AI_MODE = False
ERROR_AI_BAND_LOW = 30.0  # 模糊带下界：低于此分一律规则分档
ERROR_AI_BAND_HIGH = 85.0  # 模糊带上界：高于此分一律规则分档

# 批量批改分区裁剪临时目录（文件名用 uuid，防并发冲突）
SEGMENT_OUTPUT_FOLDER = './output/segments'
