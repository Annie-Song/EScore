"""Flask 应用工厂。"""
import logging
import os

# 必须先于 paddle（OCR）加载 torch，避免两者在 Windows 同进程的 DLL 冲突：
# 若 paddle 先加载，torch 的 shm.dll 会报 WinError 127。此导入确保 torch 的
# 运行库先进入进程，paddle 随后加载时可复用，二者才能共存。
import torch  # noqa: F401

from flask import Flask
from flask_cors import CORS

from utils import config

# 项目根目录，模板与上传目录均相对根目录定位
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app() -> Flask:
    """创建并配置 Flask 应用实例，注册路由。"""
    logging.basicConfig(level=logging.INFO)

    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, 'templates'),
        static_folder=os.path.join(BASE_DIR, 'static'),
    )
    CORS(app)
    app.secret_key = config.SECRET_KEY

    from app.routes import bp
    app.register_blueprint(bp)

    from app.batch_routes import bp as batch_bp
    app.register_blueprint(batch_bp)

    from app.stats_routes import bp as stats_bp
    app.register_blueprint(stats_bp)

    from app.bank_routes import bp as bank_bp
    app.register_blueprint(bank_bp)

    from app.bank_manage_routes import bp as bank_manage_bp
    app.register_blueprint(bank_manage_bp)

    from app.auth_routes import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.me_routes import bp as me_bp
    app.register_blueprint(me_bp)

    from app.pay_routes import bp as pay_bp
    app.register_blueprint(pay_bp)

    from app.school_routes import bp as school_bp
    app.register_blueprint(school_bp)

    from app.health_routes import bp as health_bp
    app.register_blueprint(health_bp)

    return app
