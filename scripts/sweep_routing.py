"""路由配置扫描工具（A9）：离线语义粗筛 + 路由阈值的运营点权衡表。

对 A9 评测集每对(标准答案, 三档作答)算一次离线 MiniLM 分（复用 backend.scoring.engine.offline_score），
再遍历候选路由配置逐个模拟路由决策（backend.scoring.engine.should_route），输出权衡表：差档捕获/漏判、
优档浪费、总路由率（即 DeepSeek 精排调用成本占比），供调优选运营点。

前置：先运行 scripts/generate_eval_answers.py 生成作答（缓存到 data/eval/answers.json），
并启动嵌入服务 python -m servers.embedding.server。头条指标全程不涉及 DeepSeek 评判自身。

用法：
    python scripts/sweep_routing.py                          # 默认扫描阈值 45-95 步进 5
    python scripts/sweep_routing.py --thresholds 55 60 65 70 75   # 自定义阈值
    python scripts/sweep_routing.py --config fast quality threshold:75 band:0-80  # 显式配置
    python scripts/sweep_routing.py --limit 20               # 快速冒烟（前 20 条）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 支持 `python scripts/xxx.py` 直接运行：把项目根加入 sys.path，使 services/utils 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.scoring.eval_set import load_generated_cases
from backend.scoring.engine import RoutingConfig, offline_score, resolve_preset, should_route
from backend.core import config

_TIERS = ("good", "medium", "bad")


def _collect_scores(cases: list, limit: int) -> list[dict]:
    """为每个(题目, 档位作答)计算离线分，返回明细行 [{subject, index, tier, score}]。"""
    rows: list[dict] = []
    for case in cases[:limit] if limit else cases:
        for tier in _TIERS:
            answer = case.tiers.get(tier)
            if not answer:
                continue
            rows.append(
                {
                    "subject": case.subject,
                    "index": case.index,
                    "tier": tier,
                    "score": offline_score(case.reference, answer),
                }
            )
    return rows


def _routing_metrics(rows: list[dict], routing: RoutingConfig) -> dict:
    """对给定路由配置模拟路由：各档路由率、差档捕获/漏判、优档浪费、总路由率。"""
    per_tier: dict[str, list[tuple[dict, bool]]] = {t: [] for t in _TIERS}
    for row in rows:
        per_tier[row["tier"]].append((row, should_route(row["score"], routing)))
    bad = per_tier["bad"]
    good = per_tier["good"]
    bad_caught = sum(1 for _, routed in bad if routed)
    return {
        "route_rate": {
            t: round(sum(1 for _, routed in v if routed) / len(v), 3)
            for t, v in per_tier.items()
            if v
        },
        "bad_caught": bad_caught,
        "missed_bad": len(bad) - bad_caught,
        "wasted_good": sum(1 for _, routed in good if routed),
        "total_rate": round(
            sum(1 for v in per_tier.values() for _, routed in v if routed) / len(rows),
            3,
        ),
    }


def _parse_config(spec: str) -> RoutingConfig:
    """解析路由配置规格：预设名 / threshold:X / band:LO-HI。

    预设名（fast/quality）委托 resolve_preset；threshold:X 为低分路由阈值（低分转精排）；
    band:LO-HI 为中段边界带。无法解析抛 ValueError（fail-fast）。
    """
    if spec in config.ROUTING_PRESETS:
        return resolve_preset(spec)
    if spec.startswith("threshold:"):
        try:
            return RoutingConfig(mode="threshold", low=float(spec.split(":", 1)[1]))
        except ValueError:
            raise ValueError(f"无法解析路由配置: {spec!r}，threshold: 后需为数值") from None
    if spec.startswith("band:"):
        try:
            low_s, high_s = spec.split(":", 1)[1].split("-", 1)
            return RoutingConfig(mode="band", band_low=float(low_s), band_high=float(high_s))
        except ValueError:
            raise ValueError(f"无法解析路由配置: {spec!r}，band: 后需为 LO-HI 数值区间") from None
    raise ValueError(
        f"无法解析路由配置: {spec!r}，支持格式: 预设名{sorted(config.ROUTING_PRESETS)}"
        " / threshold:X / band:LO-HI"
    )


def _default_candidates() -> list[tuple[str, RoutingConfig]]:
    """默认扫描候选：threshold 45-95 步进 5，加 fast/quality 双预设。

    预设与某阈值重复（如 fast 与 threshold:60）时保留预设项、跳过重复阈值，避免表格重复行。
    """
    candidates = [
        (f"threshold:{t}", RoutingConfig(mode="threshold", low=float(t)))
        for t in range(45, 100, 5)
    ]
    presets = [("fast", resolve_preset("fast")), ("quality", resolve_preset("quality"))]
    preset_lows = {cfg.low for _, cfg in presets if cfg.mode == "threshold"}
    deduped = [
        (label, cfg) for label, cfg in candidates
        if not (cfg.mode == "threshold" and cfg.low in preset_lows)
    ]
    return deduped + presets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thresholds", type=float, nargs="+", default=None,
                        help="自定义低分阈值集合（生成 threshold:X 候选）")
    parser.add_argument("--config", nargs="+", default=None,
                        help="显式路由配置规格列表（预设名/threshold:X/band:LO-HI）")
    parser.add_argument("--limit", type=int, default=0, help="仅扫描前 N 条作答（0=全部）")
    args = parser.parse_args(argv)

    cases = load_generated_cases()
    if not cases:
        print("[错误] 评测集为空：请先运行 scripts/generate_eval_answers.py", file=sys.stderr)
        return 1
    rows = _collect_scores(cases, args.limit)
    if not rows:
        print("[错误] 无作答可扫描：--limit 超出或三档作答缺失", file=sys.stderr)
        return 1

    # 候选构建优先级：--config > --thresholds > 默认双档 + 阈值扫描
    try:
        if args.config:
            candidates = [(spec, _parse_config(spec)) for spec in args.config]
        elif args.thresholds:
            candidates = [
                (f"threshold:{t:g}", RoutingConfig(mode="threshold", low=float(t)))
                for t in args.thresholds
            ]
        else:
            candidates = _default_candidates()
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    results = [
        (label, _routing_metrics(rows, routing)) for label, routing in candidates
    ]
    results.sort(key=lambda item: item[1]["total_rate"])

    print(f"== 路由配置扫描（共 {len(rows)} 条作答）==")
    print(f"{'配置':<14} {'差档路由':<18} {'差档漏判':<10} {'优档浪费':<10} {'总路由率'}")
    for label, m in results:
        bad_total = m["bad_caught"] + m["missed_bad"]
        rate = m["route_rate"].get("bad")
        bad_cell = f"{rate * 100:.1f}%（{m['bad_caught']}/{bad_total}）" if rate is not None else "-"
        print(
            f"{label:<14} {bad_cell:<18} {m['missed_bad']:<10} "
            f"{m['wasted_good']:<10} {m['total_rate'] * 100:.1f}%"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
