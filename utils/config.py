"""集中管理项目常量。"""

# 文件上传目录
UPLOAD_FOLDER = './uploads'

# 支持的文件类型
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'tiff'}

# OCR 语言映射：前端语言选项映射到 PaddleOCR 的 lang 参数，未匹配默认英文
OCR_LANG_MAP = {"中文": "ch", "英文": "en"}
