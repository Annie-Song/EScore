"""评分评测离线 benchmark（A9）：量化路由策略的离线判别力与成本。

加载评测集（GAOKAO-Bench 题目 + DeepSeek 三档生成作答），对每对(标准答案, 作答)算
离线 MiniLM 语义分（0-100，复用 services.scoring.offline_score），对照金标档位量化：
1. 档位判别力：各档位分数分布、优差类间分离度、档位等级与分数的 Spearman 相关、
   优/差二分类 AUC（判别低质量作答的能力）。
2. 路由策略模拟：复用 services.scoring.should_route，按 ROUTING_MODE 统计各档位
   路由率（成本）、差档漏判（未被路由的低质量）、优档浪费（被路由的高质量）。
3. 档位真实性校验：优档分数低于阈值、差档高于阈值的样本标为可疑（独立 MiniLM 信号）。

需先运行 scripts/generate_eval_answers.py 生成作答，并启动嵌入服务
python -m services.embedding_server。头条指标全程不涉及 DeepSeek 评判自身。

用法：
    python scripts/benchmark_eval.py              # 全量评测
    python scripts/benchmark_eval.py --limit 20   # 仅前 20 条（快速冒烟）
"""
from __future__ import annotations

import argparse
import sys

import numpy as np

from services.eval_set import load_generated_cases
from services.scoring import offline_score, should_route
from utils import config

_TIER_RANK = {"good": 3, "medium": 2, "bad": 1}
_TIERS = ("good", "medium", "bad")


def _collect(cases: list, limit: int) -> list[dict]:
    """为每个(题目, 档位作答)计算离线分与路由决策，返回明细行。"""
    rows = []
    for case in cases[:limit] if limit else cases:
        for tier in _TIERS:
            answer = case.tiers.get(tier)
            if not answer:
                continue
            score = offline_score(case.reference, answer)
            rows.append(
                {
                    "subject": case.subject,
                    "index": case.index,
                    "tier": tier,
                    "score": score,
                    "routed": should_route(score),
                }
            )
    return rows


def _spearman(x: list[float], y: list[float]) -> float:
    """斯皮尔曼等级相关：两序列各自排序取秩后求皮尔逊相关。"""
    x_rank = np.argsort(np.argsort(x))
    y_rank = np.argsort(np.argsort(y))
    return float(np.corrcoef(x_rank, y_rank)[0, 1])


def _auc(pos: list[float], neg: list[float]) -> float:
    """优/差二分类 AUC（Mann-Whitney U）：正样本分数高于负样本的概率。

    AUC = P(正样本分 > 负样本分)，相等计 0.5；评测集规模下 O(n*m) 逐对比较即可。
    """
    if not pos or not neg:
        return 0.0
    wins = sum(
        1.0 if p > q else (0.5 if p == q else 0.0)
        for p in pos
        for q in neg
    )
    return float(wins / (len(pos) * len(neg)))


def _tier_metrics(rows: list[dict]) -> dict:
    """档位判别力指标：分布、优差分离度、Spearman、优差 AUC。"""
    by_tier = {t: [r["score"] for r in rows if r["tier"] == t] for t in _TIERS}
    stats = {
        t: {"n": len(v), "mean": float(np.mean(v)), "std": float(np.std(v))}
        for t, v in by_tier.items()
        if v
    }
    good = by_tier["good"]
    bad = by_tier["bad"]
    return {
        "stats": stats,
        "separation": float(np.mean(good) - np.mean(bad)) if good and bad else 0.0,
        "spearman": _spearman(
            [_TIER_RANK[r["tier"]] for r in rows],
            [r["score"] for r in rows],
        ),
        "auc_good_vs_bad": _auc(good, bad),
    }


def _routing_metrics(rows: list[dict]) -> dict:
    """路由策略模拟：各档位路由率（成本）、差档漏判、优档浪费。"""
    per_tier = {
        t: [r for r in rows if r["tier"] == t]
        for t in _TIERS
    }
    return {
        "route_rate": {
            t: round(len([r for r in v if r["routed"]]) / len(v), 3)
            for t, v in per_tier.items()
            if v
        },
        "missed_bad": len([r for r in per_tier["bad"] if not r["routed"]]),
        "wasted_good": len([r for r in per_tier["good"] if r["routed"]]),
    }


def _suspect_counts(rows: list[dict]) -> dict:
    """档位真实性校验：独立 MiniLM 信号与构造档位冲突的样本数。"""
    return {
        "good_suspect": len(
            [r for r in rows if r["tier"] == "good" and r["score"] / 100 < config.EVAL_TIER_SUSPECT_GOOD_BELOW]
        ),
        "bad_suspect": len(
            [r for r in rows if r["tier"] == "bad" and r["score"] / 100 > config.EVAL_TIER_SUSPECT_BAD_ABOVE]
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="仅评测前 N 条（0=全部）")
    args = parser.parse_args(argv)

    cases = load_generated_cases()
    rows = _collect(cases, args.limit)
    if not rows:
        print("[错误] 评测集为空：请先运行 scripts/generate_eval_answers.py", file=sys.stderr)
        return 1

    tier = _tier_metrics(rows)
    routing = _routing_metrics(rows)
    suspect = _suspect_counts(rows)
    n = len(rows)
    print(f"== 评分评测离线 benchmark（共 {n} 条作答，{len(cases)} 题 × 3 档）==")
    print(f"路由策略: {config.ROUTING_MODE} (low={config.LOW_THRESHOLD}, band={config.BAND_LOW}-{config.BAND_HIGH})")
    print("\n[档位判别力]")
    for t in _TIERS:
        s = tier["stats"].get(t)
        if s:
            print(f"  {t:>6}: n={s['n']:3d}  mean={s['mean']:6.1f}  std={s['std']:5.1f}")
    print(f"  优差类间分离度 = {tier['separation']:.1f}")
    print(f"  档位-Spearman 相关 = {tier['spearman']:.3f}")
    print(f"  优/差二分类 AUC = {tier['auc_good_vs_bad']:.3f}")
    print("\n[路由策略模拟]")
    for t in _TIERS:
        rr = routing["route_rate"].get(t)
        if rr is not None:
            print(f"  {t:>6} 路由率 = {rr:.1%}")
    print(f"  差档漏判（未被路由的低质量） = {routing['missed_bad']}")
    print(f"  优档浪费（被路由的高质量） = {routing['wasted_good']}")
    print("\n[档位真实性校验]")
    print(f"  优档低分可疑 = {suspect['good_suspect']}，差档高分可疑 = {suspect['bad_suspect']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
