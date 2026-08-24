"""三进程健康检查脚本：探测主应用、向量嵌入、OCR 三个服务是否就绪。

D3 单环境收敛收尾：run.bat 用 start 起三个进程后立即开浏览器，服务未就绪
（模型加载、端口未绑定）时用户只会看到连接失败，无明确报错。本脚本在开浏览器
前做健康检查，失败给出明确提示与非零退出码，fail-fast 不静默放行。

用法：
    python scripts/healthcheck.py              # 只测一轮
    python scripts/healthcheck.py --wait 30    # 每 1 秒重试直到全部就绪或 30 秒超时

退出码：0=三服务全部就绪，1=存在未就绪服务。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

# 支持 `python scripts/healthcheck.py` 直接运行：把项目根加入 sys.path，使 utils 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import config

# 主应用默认地址，可用环境变量 MAIN_APP_URL 覆盖（默认与 run.bat 启动端口一致）
_MAIN_APP_URL = os.environ.get("MAIN_APP_URL", "http://127.0.0.1:5000")


def _default_endpoints() -> list[tuple[str, str]]:
    """默认三端点列表：主应用、向量嵌入、OCR 各自的 /health 地址。"""
    return [
        ("main", f"{_MAIN_APP_URL}/health"),
        ("embedding", f"{config.EMBEDDING_SERVICE_URL}/health"),
        ("ocr", f"{config.OCR_SERVICE_URL}/health"),
    ]


def check_endpoints(endpoints: list[tuple[str, str]], timeout: float = 2.0) -> dict:
    """探测每个端点，收集 {name: {"ok", "status", "elapsed_ms"}}。

    对每个 (name, url) 发 GET，httpx.Client 复用连接；单端点超时由 timeout 控制，
    单个端点异常记为 ok=False，不中断整体探测。
    """
    results: dict[str, dict] = {}
    with httpx.Client(timeout=timeout) as client:
        for name, url in endpoints:
            t0 = time.perf_counter()
            try:
                resp = client.get(url)
                results[name] = {
                    "ok": resp.status_code == 200,
                    "status": resp.status_code,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                }
            except httpx.HTTPError:
                results[name] = {
                    "ok": False,
                    "status": None,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                }
    return results


def _print_results(results: dict) -> None:
    """打印逐端点健康检查结果。"""
    for name, info in results.items():
        status = str(info["status"]) if info["status"] is not None else "无响应"
        state = "ok" if info["ok"] else "FAIL"
        print(f"[{name}] {state} status={status} elapsed={info['elapsed_ms']}ms")


def main(argv: list[str] | None = None) -> int:
    """解析参数并探测三服务；--wait N 时每 1 秒重试直到全部就绪或 N 秒超时。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wait", type=float, default=0.0,
        help="等待全部就绪的最大秒数，每 1 秒重试一轮；缺省 0 表示只测一轮",
    )
    args = parser.parse_args(argv)

    endpoints = _default_endpoints()
    deadline = time.monotonic() + max(args.wait, 0.0)
    while True:
        results = check_endpoints(endpoints)
        _print_results(results)
        if all(info["ok"] for info in results.values()):
            print("全部服务已就绪")
            return 0
        if time.monotonic() >= deadline:
            print("服务启动失败或未就绪，请查看对应终端日志", file=sys.stderr)
            return 1
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
