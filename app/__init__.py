"""Flask 应用工厂。"""
import logging
import os

from flask import Flask
from flask_cors import CORS

# 项目根目录，模板与上传目录均相对根目录定位
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app() -> Flask:
    """创建并配置 Flask 应用实例，注册路由。"""
    logging.basicConfig(level=logging.INFO)

    app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
    CORS(app)

    from app.routes import bp
    app.register_blueprint(bp)

    return app
