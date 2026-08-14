"""路由配置扫描工具（scripts/sweep_routing.py）单元测试。

覆盖 _parse_config 配置解析、_routing_metrics 阈值路由指标、_collect_scores 离线分收集
（patch 调用方模块命名空间）、_default_candidates 默认候选去重、main 退出码与错误输出。
外部依赖（offline_score / load_generated_cases）全部 mock，测试可离线独立运行。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sweep_routing  # noqa: E402

from services.eval_set import GeneratedCase  # noqa: E402


@pytest.mark.parametrize(
    "spec, low",
    [
        ("fast", 60.0),
        ("quality", 80.0),
    ],
)
def test_parse_config_预设名(spec: str, low: float):
    """预设名 fast/quality 委托 resolve_preset，解析为 threshold 模式对应低阈值。"""
    assert sweep_routing._parse_config(spec) == sweep_routing.RoutingConfig(
        mode="threshold", low=low
    )


def test_parse_config_threshold():
    """threshold:X 解析为 threshold 模式，low 取 X 数值。"""
    cfg = sweep_routing._parse_config("threshold:75")
    assert cfg == sweep_routing.RoutingConfig(mode="threshold", low=75.0)


def test_parse_config_band():
    """band:LO-HI 解析为 band 模式，带上下界取区间数值。"""
    cfg = sweep_routing._parse_config("band:40-80")
    assert cfg == sweep_routing.RoutingConfig(
        mode="band", band_low=40.0, band_high=80.0
    )


@pytest.mark.parametrize("spec", ["bogus", "threshold:abc", "band:1-2-3"])
def test_parse_config_非法规格抛错(spec: str):
    """无法解析的配置规格抛 ValueError（fail-fast，不塞默认值）。"""
    with pytest.raises(ValueError):
        sweep_routing._parse_config(spec)


def test_routing_metrics_阈值路由指标():
    """threshold 路由：各档路由率、差档捕获/漏判、优档浪费、总路由率按定义计算。

    覆盖 should_route 边界：score == low 时不路由（严格小于）。
    """
    routing = sweep_routing.RoutingConfig(mode="threshold", low=70.0)
    rows = [
        {"tier": "good", "score": 90.0},
        {"tier": "good", "score": 60.0},
        {"tier": "medium", "score": 70.0},  # score == low，不路由
        {"tier": "medium", "score": 55.0},
        {"tier": "bad", "score": 40.0},
        {"tier": "bad", "score": 80.0},
        {"tier": "bad", "score": 30.0},
    ]
    result = sweep_routing._routing_metrics(rows, routing)

    assert result["route_rate"] == {"good": 0.5, "medium": 0.5, "bad": 0.667}
    assert result["bad_caught"] == 2
    assert result["missed_bad"] == 1
    assert result["wasted_good"] == 1
    assert result["total_rate"] == pytest.approx(0.571)


def test_collect_scores_调用离线分与缺失跳过():
    """_collect_scores 按 (reference, answer) 调离线分，缺失档位跳过，返回行字段完整。"""
    cases = [
        GeneratedCase(
            subject="语文", index=1, question="题干一", reference="ref1",
            tiers={"good": "优1", "medium": "中1", "bad": "差1"},
        ),
        GeneratedCase(
            subject="语文", index=2, question="题干二", reference="ref2",
            tiers={"good": "优2"},  # 缺失 medium/bad，应被跳过
        ),
    ]
    score_map = {"优1": 90.0, "中1": 70.0, "差1": 40.0, "优2": 95.0}

    def fake_offline(reference: str, answer: str) -> float:
        return score_map[answer]

    with patch.object(sweep_routing, "offline_score", side_effect=fake_offline) as mock_offline:
        rows = sweep_routing._collect_scores(cases, limit=0)

    assert len(rows) == 4  # case1 三档 + case2 仅 good，共 4 条作答
    assert rows[0] == {"subject": "语文", "index": 1, "tier": "good", "score": 90.0}
    assert rows[1] == {"subject": "语文", "index": 1, "tier": "medium", "score": 70.0}
    assert rows[2] == {"subject": "语文", "index": 1, "tier": "bad", "score": 40.0}
    assert rows[3] == {"subject": "语文", "index": 2, "tier": "good", "score": 95.0}

    called = [c.args for c in mock_offline.call_args_list]
    assert ("ref1", "优1") in called
    assert ("ref1", "中1") in called
    assert ("ref1", "差1") in called
    assert ("ref2", "优2") in called
    assert len(called) == 4


def test_collect_scores_limit截断():
    """limit 非 0 时只收集前 limit 条题目的作答。"""
    cases = [
        GeneratedCase(subject="语文", index=i, question="题干", reference="ref",
                      tiers={"good": "优"})
        for i in (1, 2, 3)
    ]
    with patch.object(sweep_routing, "offline_score", return_value=90.0):
        rows = sweep_routing._collect_scores(cases, limit=2)
    assert len(rows) == 2
    assert [r["index"] for r in rows] == [1, 2]


def test_default_candidates_去重与预设保留():
    """默认候选：threshold 45-95 步进 5，与 fast(60)/quality(80) 重复的阈值被去重，
    预设项保留在末尾，所有 low 无重复。"""
    candidates = sweep_routing._default_candidates()
    labels = [label for label, _ in candidates]
    by_label = dict(candidates)

    assert "fast" in labels
    assert "quality" in labels
    assert "threshold:60" not in labels  # 与 fast 重复，去重
    assert "threshold:80" not in labels  # 与 quality 重复，去重
    for t in (45, 50, 55, 65, 70, 75, 85, 90, 95):
        assert f"threshold:{t}" in labels

    lows = [cfg.low for _, cfg in candidates]
    assert len(lows) == len(set(lows))  # 无重复 low
    assert labels[-2:] == ["fast", "quality"]  # 预设保留在末尾
    assert by_label["fast"] == sweep_routing.RoutingConfig(mode="threshold", low=60.0)
    assert by_label["quality"] == sweep_routing.RoutingConfig(mode="threshold", low=80.0)


def test_main_空评测集返回1(capsys):
    """作答列表为空时 main 返回 1 并向 stderr 报错。"""
    with patch.object(sweep_routing, "load_generated_cases", return_value=[]):
        assert sweep_routing.main([]) == 1
    assert "评测集为空" in capsys.readouterr().err


def test_main_非法配置返回1(capsys):
    """--config 含非法规格时 main 返回 1 并向 stderr 报错，不崩溃。"""
    case = GeneratedCase(subject="语文", index=1, question="题干", reference="ref",
                         tiers={"good": "优", "medium": "中", "bad": "差"})
    with patch.object(sweep_routing, "load_generated_cases", return_value=[case]), \
         patch.object(sweep_routing, "offline_score", return_value=50.0):
        assert sweep_routing.main(["--config", "bogus"]) == 1
    assert "无法解析" in capsys.readouterr().err


def test_main_正常扫描返回0(capsys):
    """--config fast quality 正常扫描，返回 0 且输出表含两预设行。"""
    case = GeneratedCase(subject="语文", index=1, question="题干", reference="ref",
                         tiers={"good": "优", "medium": "中", "bad": "差"})
    with patch.object(sweep_routing, "load_generated_cases", return_value=[case]), \
         patch.object(sweep_routing, "offline_score", return_value=50.0):
        assert sweep_routing.main(["--config", "fast", "quality"]) == 0
    out = capsys.readouterr().out
    assert "fast" in out
    assert "quality" in out
