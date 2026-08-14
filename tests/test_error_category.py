"""错因归类服务单元测试：规则分档与 AI 细类混合级联。"""
from unittest.mock import MagicMock, patch

import pytest

from services.error_category import (
    CATEGORY_CONCEPT,
    CATEGORY_MASTER,
    CATEGORY_MOSTLY,
    CATEGORY_NONE,
    CATEGORY_PARTIAL,
    classify_ai,
    classify_error,
    rule_category,
)


def test_rule_category_boundaries():
    """规则分档分数区间边界精确判定。"""
    assert rule_category(0) == CATEGORY_NONE
    assert rule_category(29) == CATEGORY_CONCEPT
    assert rule_category(30) == CATEGORY_PARTIAL
    assert rule_category(59) == CATEGORY_PARTIAL
    assert rule_category(60) == CATEGORY_MOSTLY
    assert rule_category(84) == CATEGORY_MOSTLY
    assert rule_category(85) == CATEGORY_MASTER


def test_classify_error_default_ai_off_returns_rule_and_empty_reason():
    """ai_mode=False 走规则分档，reason 为空串。"""
    with patch("services.error_category.classify_ai") as mock_ai:
        assert classify_error("参考", "答案", 50) == (CATEGORY_PARTIAL, "")
    mock_ai.assert_not_called()


def test_classify_error_ai_mode_outside_band_returns_rule(monkeypatch):
    """ai_mode=True 但分数在模糊带外，走规则分档不调 AI。"""
    monkeypatch.setattr("utils.config.ERROR_AI_BAND_LOW", 30.0)
    monkeypatch.setattr("utils.config.ERROR_AI_BAND_HIGH", 85.0)
    with patch("services.error_category.classify_ai") as mock_ai:
        assert classify_error("参考", "答案", 10, ai_mode=True) == (CATEGORY_CONCEPT, "")
        assert classify_error("参考", "答案", 90, ai_mode=True) == (CATEGORY_MASTER, "")
    mock_ai.assert_not_called()


def test_classify_error_ai_mode_in_band_passes_through(monkeypatch):
    """ai_mode=True 且分数在模糊带内：AI 细类透传。"""
    monkeypatch.setattr("utils.config.ERROR_AI_BAND_LOW", 30.0)
    monkeypatch.setattr("utils.config.ERROR_AI_BAND_HIGH", 85.0)
    with patch("services.error_category.classify_ai", return_value=("计算错误", "符号算错")) as mock_ai:
        assert classify_error("参考", "答案", 50, ai_mode=True) == ("计算错误", "符号算错")
    mock_ai.assert_called_once_with("参考", "答案")


def test_classify_error_ai_mode_ai_failure_degrades_to_rule(monkeypatch):
    """ai_mode=True 在带内但 AI 归类抛异常：降级规则档 + 空 reason。"""
    monkeypatch.setattr("utils.config.ERROR_AI_BAND_LOW", 30.0)
    monkeypatch.setattr("utils.config.ERROR_AI_BAND_HIGH", 85.0)
    with patch("services.error_category.classify_ai", side_effect=RuntimeError("boom")):
        assert classify_error("参考", "答案", 50, ai_mode=True) == (CATEGORY_PARTIAL, "")


def _fake_client(content: str) -> MagicMock:
    """构造返回指定 content 的假 DeepSeek 客户端。"""
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = content
    return client


def test_classify_ai_parses_valid_json():
    """AI 返回合法 JSON，解析出 (category, reason)。"""
    client = _fake_client('{"category":"计算错误","reason":"符号算错"}')
    with patch("services.deepseek._get_client", return_value=client) as mock_get:
        assert classify_ai("参考", "答案") == ("计算错误", "符号算错")
    mock_get.assert_called_once()
    client.chat.completions.create.assert_called_once()


def test_classify_ai_category_not_in_table_raises_value_error():
    """AI 输出类别不在固定分类表内，抛 ValueError。"""
    client = _fake_client('{"category":"未知类别","reason":"x"}')
    with patch("services.deepseek._get_client", return_value=client):
        with pytest.raises(ValueError):
            classify_ai("参考", "答案")


def test_classify_ai_non_json_raises_value_error():
    """AI 输出不是合法 JSON，抛 ValueError。"""
    client = _fake_client("这不是 JSON")
    with patch("services.deepseek._get_client", return_value=client):
        with pytest.raises(ValueError):
            classify_ai("参考", "答案")


def test_classify_ai_extra_text_around_json_raises_value_error():
    """AI 输出含多余文本时按实现处理：直接 json.loads 全文，解析失败抛 ValueError。"""
    client = _fake_client('{"category":"计算错误","reason":"x"} 请忽略多余内容')
    with patch("services.deepseek._get_client", return_value=client):
        with pytest.raises(ValueError):
            classify_ai("参考", "答案")
