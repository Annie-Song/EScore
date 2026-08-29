"""gunicorn 生产配置（容器内主应用）。

并发模型：workers=1 保证批改任务注册表与内存缓存等进程内状态在单进程内一致；
threads=8 用 gthread worker 并发处理 HTTP，长 OCR/评分请求不阻塞健康检查与其他请求。
"""
import os

bind = f"0.0.0.0:{os.environ.get('FLASK_PORT', '5000')}"
workers = 1
threads = 8
timeout = 300        # 单图增强+评分可达数十秒，gunicorn 默认 30s 会误杀
graceful_timeout = 30
accesslog = "-"      # 请求日志走 stderr → docker compose logs 可见
errorlog = "-"
