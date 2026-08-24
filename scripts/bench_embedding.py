"""嵌入服务可复用压测脚本（供每轮 /loop Phase 3 使用）。

替代每次迭代临时手写压测脚本。v2.5.1 自省：临时脚本踩过两个坑——端点方法用错
（/health 是 GET 却用 POST 报 405）；每次请求新建 httpx.Client 造成顺序延迟虚高
（连接复用后从 186ms 回落到 28.8ms）。本脚本固化正确做法：连接复用、端点方法
正确、同会话 A/B 对照，跑前可先小规模校准再正式测量。

用法：
    python scripts/bench_embedding.py                 # 默认：健康检查 + e2e + /similarity A/B（顺序+并发）
    python scripts/bench_embedding.py --seq --n 20    # 仅顺序测量（20 请求）
    python scripts/bench_embedding.py --conc --threads 10 --each 30  # 仅并发测量
    python scripts/bench_embedding.py --calibrate     # 小规模校准（顺序 2 次/并发 2×2），验证脚本与端点正确性

A/B 对照：before 为旧 /similarity 等价路径（POST /encode {texts:[参考,答案]}，
一次批量编码 2 文本），after 为新 /similarity（参考走服务端缓存，每请求只编码答案
1 文本）。同会话、同服务实例，保证可比。
"""
from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from pathlib import Path

import httpx

# 支持 `python scripts/xxx.py` 直接运行：把项目根加入 sys.path，使 services/utils 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.scoring import batch_scoring
from backend.scoring import engine as scoring
from backend.core import config

# 默认参考与答案：约 40 字中文句子，贴近单题离线评分真实负载
REF = "光合作用是指绿色植物利用光能，将二氧化碳和水转化为有机物并释放氧气的过程。"
ANS = "绿色植物通过叶绿体，在光下把二氧化碳和水合成有机物，同时放出氧气，这个过程叫光合作用。"

# 端点方法约定：/health 是 GET，其余为 POST
BEFORE = ("/encode", {"texts": [REF, ANS]})
AFTER = ("/similarity", {"reference": REF, "answer": ANS})


def _client() -> httpx.Client:
    """共享 httpx.Client：连接复用，避免每次请求新建连接造成虚假开销。"""
    return httpx.Client(timeout=120.0)


def _post(client: httpx.Client, path: str, payload: dict) -> dict:
    resp = client.post(config.EMBEDDING_SERVICE_URL + path, json=payload)
    resp.raise_for_status()
    return resp.json()


def health_check() -> None:
    """/health 是 GET 端点，校验服务可达与模型名。"""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(config.EMBEDDING_SERVICE_URL + "/health")
        resp.raise_for_status()
        print(f"[health] {resp.json()}")


def e2e_check() -> None:
    """评分链路 e2e：单条 offline_score（走 /similarity）与批量（走 /batch_similarity）。"""
    score = scoring.offline_score(REF, ANS)
    print(f"[e2e offline_score] {score:.3f}")
    scores = batch_scoring.batch_offline_scores(REF, [ANS, "地球是行星", ANS])
    print(f"[e2e batch] {[round(s, 1) for s in scores]}")


def _warm(path: str, payload: dict) -> None:
    """发一次请求触发模型加载/缓存预热，不计入测量。"""
    with _client() as client:
        _post(client, path, payload)


def measure_seq(path: str, payload: dict, n: int) -> float:
    """连接复用下的顺序平均延迟（ms）。"""
    lat = []
    with _client() as client:
        for _ in range(n):
            t0 = time.perf_counter()
            _post(client, path, payload)
            lat.append((time.perf_counter() - t0) * 1000)
    return statistics.mean(lat)


def measure_conc(path: str, payload: dict, threads: int, each: int) -> dict:
    """并发测量：threads 线程各发 each 次，返回吞吐与 P50/P95。"""
    lat: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        with _client() as client:
            for _ in range(each):
                t0 = time.perf_counter()
                _post(client, path, payload)
                with lock:
                    lat.append((time.perf_counter() - t0) * 1000)

    start = time.perf_counter()
    workers = [threading.Thread(target=worker) for _ in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    elapsed = time.perf_counter() - start
    lat.sort()
    n = len(lat)
    return {
        "req_per_s": round(n / elapsed, 1),
        "p50_ms": round(lat[int(n * 0.50)], 1),
        "p95_ms": round(lat[int(n * 0.95)], 1),
    }


def ab_sequential(n: int) -> None:
    """/similarity 参考缓存顺序 A/B：before(2 文本批量编码) vs after(参考缓存+1 文本)。"""
    _warm(*BEFORE)
    _warm(*AFTER)
    before_ms = measure_seq(*BEFORE, n=n)
    after_ms = measure_seq(*AFTER, n=n)
    print(f"[seq] before(2文本批量编码)={before_ms:.1f}ms  after(参考缓存+1文本)={after_ms:.1f}ms  "
          f"提升 {before_ms / after_ms:.2f}x")


def ab_concurrent(threads: int, each: int) -> None:
    """/similarity 参考缓存并发 A/B：吞吐与分位数对比。"""
    _warm(*BEFORE)
    before = measure_conc(*BEFORE, threads=threads, each=each)
    after = measure_conc(*AFTER, threads=threads, each=each)
    print(f"[conc before] {before}")
    print(f"[conc after ] {after}")
    ratio = before["req_per_s"] / after["req_per_s"]
    print(f"[conc 吞吐提升] {ratio:.2f}x")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seq", action="store_true", help="只测顺序")
    parser.add_argument("--conc", action="store_true", help="只测并发")
    parser.add_argument("--calibrate", action="store_true", help="小规模校准（验证脚本与端点）")
    parser.add_argument("--n", type=int, default=20, help="顺序请求数")
    parser.add_argument("--threads", type=int, default=10, help="并发线程数")
    parser.add_argument("--each", type=int, default=30, help="每线程请求数")
    args = parser.parse_args(argv)

    health_check()
    e2e_check()
    if args.calibrate:
        ab_sequential(2)
        ab_concurrent(threads=2, each=2)
    elif args.seq:
        ab_sequential(args.n)
    elif args.conc:
        ab_concurrent(args.threads, args.each)
    else:
        ab_sequential(args.n)
        ab_concurrent(args.threads, args.each)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
