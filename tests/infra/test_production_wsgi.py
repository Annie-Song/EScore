"""gunicorn 生产化改动单元测试（task/2.20-1）。

覆盖三项改动：
1. 根目录 wsgi.py 生产 WSGI 入口：load_dotenv() 后 create_app()，app 须为 Flask 实例且核心路由注册完整。
2. docker/gunicorn.conf.py 生产配置：workers=1、threads=8、timeout=300、graceful_timeout=30、
   accesslog/errorlog 走 "-"，bind 绑定 0.0.0.0 且默认端口 5000、可被 FLASK_PORT 环境变量覆盖。
   该文件名含点号（gunicorn.conf.py），无法按常规 import 解析为 docker.gunicorn_conf，
   故用 importlib 按文件路径加载（与 gunicorn 实际 exec 该文件的行为一致）。
3. docker-compose.yml 三服务（embedding/ocr/app）自愈重启：restart == "unless-stopped"。

全部离线运行，不发起真实请求。
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import flask
import pytest
import yaml

# 项目根目录：本文件位于 <root>/tests/infra/ 下，向上两级即项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_GUNICORN_CONF_NAME = "gunicorn_conf_under_test"


def _load_gunicorn_conf() -> ModuleType:
    """按文件路径加载 docker/gunicorn.conf.py，返回其模块对象。

    文件名含点号（gunicorn.conf.py），gunicorn 通过 exec 加载而非 import；
    这里用 importlib 模拟同样行为，保证每次调用重新执行模块代码。
    """
    sys.modules.pop(_GUNICORN_CONF_NAME, None)
    path = PROJECT_ROOT / "docker" / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location(_GUNICORN_CONF_NAME, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_GUNICORN_CONF_NAME] = module
    spec.loader.exec_module(module)
    return module


def test_wsgi_exposes_flask_app() -> None:
    """根目录 wsgi.py 应暴露一个注册了核心路由的 Flask 应用实例。"""
    import wsgi

    assert isinstance(wsgi.app, flask.Flask)
    rules = {rule.rule for rule in wsgi.app.url_map.iter_rules()}
    assert "/health" in rules
    assert "/" in rules


def test_gunicorn_conf_importable_and_values() -> None:
    """gunicorn 配置应可加载，且并发与日志关键值符合容器化生产设定。"""
    conf = _load_gunicorn_conf()

    assert conf.workers == 1
    assert conf.threads == 8
    assert conf.timeout == 300
    assert conf.graceful_timeout == 30
    assert conf.accesslog == "-"
    assert conf.errorlog == "-"
    assert isinstance(conf.bind, str)
    assert "0.0.0.0" in conf.bind
    assert "5000" in conf.bind


def test_gunicorn_conf_bind_reads_flask_port_env() -> None:
    """bind 端口应读取 FLASK_PORT 环境变量，缺省时回退 5000。"""
    conf = _load_gunicorn_conf()
    assert conf.bind == "0.0.0.0:5000"

    with patch.dict(os.environ, {"FLASK_PORT": "8080"}, clear=False):
        conf_override = _load_gunicorn_conf()
    assert conf_override.bind == "0.0.0.0:8080"


def test_compose_three_services_restart_self_heal() -> None:
    """docker-compose 三服务均应启用 unless-stopped 自愈重启。"""
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    with compose_path.open(encoding="utf-8") as fh:
        compose: dict[str, Any] = yaml.safe_load(fh)

    services: dict[str, Any] = compose["services"]
    assert set(("embedding", "ocr", "app")) <= set(services)
    for name in ("embedding", "ocr", "app"):
        assert services[name]["restart"] == "unless-stopped"


def test_gunicorn_importable() -> None:
    """gunicorn 依赖应已安装（证明 requirements 追加项可安装）。"""
    import gunicorn  # noqa: F401

    assert gunicorn.__version__ == "23.0.0"
