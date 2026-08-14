"""评测离线 benchmark（scripts/benchmark_eval.py）单元测试。

覆盖 AUC / Spearman 统计函数、_collect 明细行收集（patch 调用方模块命名空间）、
档位判别力指标、路由策略模拟、档位真实性校验与 main 空数据退出码。
外部依赖（offline_score / should_route / load_generated_cases）全部 mock。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import benchmark_eval  # noqa: E402

from services.eval_set import GeneratedCase  # noqa: E402


def test_auc_完美分离():
    """正样本分全部高于负样本时 AUC 为 1.0。"""
    assert benchmark_eval._auc([10, 9], [2, 1]) == 1.0


def test_auc_平局计05():
    """正负样本分数相等时按 0.5 计（平局）。"""
    assert benchmark_eval._auc([5], [5]) == 0.5


def test_auc_随机为05():
    """分不出高低时 AUC 应为 0.5。"""
    assert benchmark_eval._auc([3, 1], [2, 2]) == 0.5


def test_auc_空列表返回0():
    """任一侧样本为空时 AUC 返回 0.0。"""
    assert benchmark_eval._auc([], [1]) == 0.0
    assert benchmark_eval._auc([1], []) == 0.0


def test_spearman_正负相关():
    """完全正序相关为 1.0，完全逆序相关为 -1.0。"""
    assert benchmark_eval._spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    assert benchmark_eval._spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)


def test_collect_调用离线分与路由():
    """_collect 按 (reference, answer) 调离线分、按分数调路由，并跳过缺失档位。"""
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

    def fake_should_route(score: float) -> bool:
        return score < 60.0

    with patch.object(benchmark_eval, "offline_score", side_effect=fake_offline) as mock_offline, \
         patch.object(benchmark_eval, "should_route", side_effect=fake_should_route):
        rows = benchmark_eval._collect(cases, limit=0)

        assert len(rows) == 4  # case1 三档 + case2 仅 good，共 4 条作答
        assert rows[0] == {"subject": "语文", "index": 1, "tier": "good", "score": 90.0, "routed": False}
        assert rows[1] == {"subject": "语文", "index": 1, "tier": "medium", "score": 70.0, "routed": False}
        assert rows[2] == {"subject": "语文", "index": 1, "tier": "bad", "score": 40.0, "routed": True}
        assert rows[3] == {"subject": "语文", "index": 2, "tier": "good", "score": 95.0, "routed": False}

        called = [c.args for c in mock_offline.call_args_list]
        assert ("ref1", "优1") in called
    assert ("ref1", "中1") in called
    assert ("ref1", "差1") in called
    assert ("ref2", "优2") in called


def test_collect_limit截断():
    """limit 非 0 时只收集前 limit 条题目的作答。"""
    cases = [
        GeneratedCase(subject="语文", index=i, question="题干", reference="ref",
                      tiers={"good": "优"})
        for i in (1, 2, 3)
    ]
    with patch.object(benchmark_eval, "offline_score", return_value=90.0), \
         patch.object(benchmark_eval, "should_route", return_value=False):
        rows = benchmark_eval._collect(cases, limit=2)
    assert len(rows) == 2
    assert [r["index"] for r in rows] == [1, 2]


def test_tier_metrics_指标正确():
    """档位判别力：分布统计、分离度、Spearman 与优差 AUC 均按定义计算。"""
    rows = [
        {"subject": "语文", "index": 1, "tier": "good", "score": 90.0, "routed": False},
        {"subject": "语文", "index": 2, "tier": "good", "score": 80.0, "routed": False},
        {"subject": "语文", "index": 3, "tier": "medium", "score": 50.0, "routed": True},
        {"subject": "语文", "index": 4, "tier": "bad", "score": 30.0, "routed": True},
        {"subject": "语文", "index": 5, "tier": "bad", "score": 20.0, "routed": True},
    ]
    result = benchmark_eval._tier_metrics(rows)

    assert result["stats"]["good"] == {"n": 2, "mean": 85.0, "std": 5.0}
    assert result["stats"]["medium"] == {"n": 1, "mean": 50.0, "std": 0.0}
    assert result["stats"]["bad"] == {"n": 2, "mean": 25.0, "std": 5.0}
    assert result["separation"] == pytest.approx(60.0)
    assert result["spearman"] == pytest.approx(0.8)
    assert result["auc_good_vs_bad"] == 1.0


def test_routing_metrics_路由率与漏判浪费():
    """路由率按档位统计，差档未路由计入漏判、优档被路由计入浪费。"""
    rows = [
        {"tier": "good", "score": 90.0, "routed": True},
        {"tier": "good", "score": 80.0, "routed": False},
        {"tier": "medium", "score": 50.0, "routed": True},
        {"tier": "bad", "score": 30.0, "routed": False},
        {"tier": "bad", "score": 20.0, "routed": True},
    ]
    result = benchmark_eval._routing_metrics(rows)

    assert result["route_rate"] == {"good": 0.5, "medium": 1.0, "bad": 0.5}
    assert result["missed_bad"] == 1
    assert result["wasted_good"] == 1


def test_suspect_counts_档位真实性(monkeypatch):
    """可疑档位判定读取 config 阈值（而非硬编码），按独立 MiniLM 信号计可疑数。"""
    monkeypatch.setattr(benchmark_eval.config, "EVAL_TIER_SUSPECT_GOOD_BELOW", 0.5)
    monkeypatch.setattr(benchmark_eval.config, "EVAL_TIER_SUSPECT_BAD_ABOVE", 0.8)
    rows = [
        {"tier": "good", "score": 40.0, "routed": False},  # 0.4 < 0.5 → 可疑
        {"tier": "good", "score": 60.0, "routed": False},  # 0.6 >= 0.5 → 正常
        {"tier": "bad", "score": 90.0, "routed": True},    # 0.9 > 0.8 → 可疑
        {"tier": "bad", "score": 70.0, "routed": False},   # 0.7 <= 0.8 → 正常
    ]
    assert benchmark_eval._suspect_counts(rows) == {"good_suspect": 1, "bad_suspect": 1}


def test_main_缺数据返回1(capsys):
    """作答列表为空时 main 返回 1 并向 stderr 报错。"""
    with patch.object(benchmark_eval, "load_generated_cases", return_value=[]):
        assert benchmark_eval.main([]) == 1
    assert "评测集为空" in capsys.readouterr().err


def test_main_缓存缺失抛错():
    """作答缓存缺失时 load_generated_cases 抛 FileNotFoundError，main 不吞异常。"""
    with patch.object(benchmark_eval, "load_generated_cases", side_effect=FileNotFoundError):
        with pytest.raises(FileNotFoundError):
            benchmark_eval.main([])
