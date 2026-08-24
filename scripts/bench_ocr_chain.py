"""OCR→评分链路可复用压测脚本（供每轮 /loop Phase 3 使用）。

测量四项：
1. OCR 单图识别延迟（HTTP POST /recognize_texts，经 backend.ocr.client）
2. 离线评分延迟（grade_answer force_online=False allow_online=False，走嵌入服务）
3. 全链路（OCR 识别文本 + grade_answer）
4. 单图合并评分 /api/grade_image（若路由已注册，经 Flask test client 触发）

前置：需先启动 OCR 微服务（python -m servers.ocr.server）与嵌入微服务
（python -m servers.embedding.server）。服务不可达时脚本 fail-fast 退出。

用法：
    python scripts/bench_ocr_chain.py             # 正式测量（每项 1 次预热 + 5 次计时）
    python scripts/bench_ocr_chain.py --calibrate # 小规模校准（1 次预热 + 2 次计时）
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

import httpx

# 支持 `python scripts/xxx.py` 直接运行：把项目根加入 sys.path，使 backend 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.config import EMBEDDING_SERVICE_URL, OCR_SERVICE_URL
from backend.ocr.client import recognize_texts
from backend.scoring.engine import grade_answer

# 样本图：单题作业图（存在性在运行期校验）
SAMPLE_IMAGE = Path(__file__).resolve().parent.parent / "experiments/image/chinese/homework.jpeg"
# 参考答案与识别文本：贴近单题离线评分真实负载
REFERENCE = "光合作用是指绿色植物利用光能，将二氧化碳和水转化为有机物并释放氧气的过程。"
WORK_TEXT = "绿色植物通过叶绿体，在光下把二氧化碳和水合成有机物，同时放出氧气，这个过程叫光合作用。"


def _require_sample() -> None:
    """校验样本图存在，缺失则 fail-fast 退出。"""
    if not SAMPLE_IMAGE.exists():
        raise SystemExit(f"样本图不存在: {SAMPLE_IMAGE}")


def _health_checks() -> None:
    """校验 OCR 与嵌入微服务可达（各发一次 /health，短超时）。"""
    for name, url in (("OCR", OCR_SERVICE_URL), ("嵌入", EMBEDDING_SERVICE_URL)):
        try:
            resp = httpx.get(f"{url}/health", timeout=5.0)
            resp.raise_for_status()
            print(f"[{name} 服务] 可达")
        except httpx.HTTPError as exc:
            raise SystemExit(f"[{name} 服务] 不可达: {exc}")


def _measure(fn: Callable[[], None], n: int, warm: int) -> float:
    """预热 warm 次后计时 n 次，返回平均延迟（ms）。"""
    for _ in range(warm):
        fn()
    lat = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        lat.append((time.perf_counter() - t0) * 1000)
    return statistics.mean(lat)


def bench_ocr(n: int, warm: int) -> float:
    """OCR 单图识别平均延迟（ms），复用 client 连接。"""
    image = str(SAMPLE_IMAGE)
    return _measure(lambda: recognize_texts([image], lang='ch'), n, warm)


def bench_scoring(n: int, warm: int) -> float:
    """离线评分平均延迟（ms），强制离线不调 DeepSeek。"""
    def _score() -> None:
        grade_answer(REFERENCE, WORK_TEXT, force_online=False, allow_online=False)
    return _measure(_score, n, warm)


def bench_chain(n: int, warm: int) -> float:
    """全链路平均延迟（ms）：OCR 识别文本后离线评分。"""
    image = str(SAMPLE_IMAGE)

    def _chain() -> None:
        work_text = recognize_texts([image], lang='ch')[0]
        grade_answer(REFERENCE, work_text, force_online=False, allow_online=False)
    return _measure(_chain, n, warm)


def bench_grade_image(n: int, warm: int) -> float:
    """单图合并评分平均延迟（ms），经 Flask test client 触发 /api/grade_image。"""
    from backend.app import create_app

    test = create_app().test_client()

    def _grade_image() -> None:
        with open(SAMPLE_IMAGE, 'rb') as f:
            resp = test.post(
                '/api/grade_image',
                data={'file': (f, SAMPLE_IMAGE.name), 'reference': REFERENCE},
                content_type='multipart/form-data',
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"/api/grade_image 返回 {resp.status_code}")
    return _measure(_grade_image, n, warm)


def _route_exists() -> bool:
    """检查 /api/grade_image 路由是否已注册（兼容未含该路由的旧后端）。"""
    from backend.app import create_app

    app = create_app()
    return any(rule.rule == '/api/grade_image' for rule in app.url_map.iter_rules())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrate", action="store_true", help="小规模校准（1 次预热 + 2 次计时）")
    parser.add_argument("--n", type=int, help="每项计时次数（默认校准 2 / 正式 5）")
    parser.add_argument("--warm", type=int, default=1, help="每项预热次数")
    args = parser.parse_args(argv)

    _require_sample()
    _health_checks()
    n = args.n if args.n else (2 if args.calibrate else 5)
    warm = args.warm

    print(f"样本图: {SAMPLE_IMAGE}")
    print(f"[ocr]         平均 {bench_ocr(n, warm):.1f} ms")
    print(f"[scoring]     平均 {bench_scoring(n, warm):.1f} ms")
    print(f"[chain]       平均 {bench_chain(n, warm):.1f} ms")
    if _route_exists():
        print(f"[grade_image] 平均 {bench_grade_image(n, warm):.1f} ms")
    else:
        print("[grade_image] 路由未注册，跳过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
