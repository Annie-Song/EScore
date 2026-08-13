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
