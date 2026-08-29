"""gunicorn 生产 WSGI 入口（仅容器内使用；原生开发走 run.py）。"""
from dotenv import load_dotenv

from backend.app import create_app

load_dotenv()

app = create_app()
