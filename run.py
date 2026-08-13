"""应用启动入口：python run.py。"""
import os

from dotenv import load_dotenv

from app import create_app

load_dotenv()


def main() -> None:
    """启动 Flask 开发服务器。"""
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    create_app().run(debug=debug)


if __name__ == '__main__':
    main()
