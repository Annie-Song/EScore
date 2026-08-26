"""应用启动入口：python run.py。"""
import os

from dotenv import load_dotenv

from backend.app import create_app

load_dotenv()


def main() -> None:
    """启动 Flask 开发服务器（host 可用 FLASK_HOST 覆盖，容器部署须绑 0.0.0.0）。"""
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    create_app().run(host=host, debug=debug)


if __name__ == '__main__':
    main()
