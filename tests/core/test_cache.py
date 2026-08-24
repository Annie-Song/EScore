"""backend/core/cache.py 有界缓存与内容哈希工具单元测试。

覆盖 BoundedCache 命中/未命中、满上限整体清空、非法 max_size、clear，
以及 file_sha1/text_sha1 的确定性与内容寻址。全程不依赖外部服务。
"""
import pytest

from backend.core.cache import BoundedCache, file_sha1, text_sha1


def test_bounded_cache_hit_returns_value():
    """set 后 get 返回同一 value；未 set 的键返回 None。"""
    cache = BoundedCache(max_size=4)
    cache.set("key", "value")
    assert cache.get("key") == "value"
    assert cache.get("missing") is None


def test_bounded_cache_evicts_all_when_full():
    """达上限后整体清空再写入：旧键全部失效，仅保留新键。"""
    cache = BoundedCache(max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert len(cache) == 2
    cache.set("c", 3)
    assert len(cache) == 1
    assert cache.get("c") == 3
    assert cache.get("a") is None
    assert cache.get("b") is None


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_bounded_cache_rejects_non_positive_max_size(bad):
    """max_size<=0 构造时抛 ValueError。"""
    with pytest.raises(ValueError):
        BoundedCache(max_size=bad)


def test_bounded_cache_clear_empties():
    """clear 清空所有键值。"""
    cache = BoundedCache(max_size=4)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_file_sha1_deterministic_and_path_independent(tmp_path):
    """同一文件两次哈希一致；同内容不同路径哈希一致（内容寻址）。"""
    path_a = tmp_path / "a.bin"
    path_b = tmp_path / "b.bin"
    path_a.write_bytes(b"identical-bytes")
    path_b.write_bytes(b"identical-bytes")
    assert file_sha1(str(path_a)) == file_sha1(str(path_a))
    assert file_sha1(str(path_a)) == file_sha1(str(path_b))


def test_file_sha1_differs_by_content(tmp_path):
    """不同内容文件哈希不同。"""
    path_a = tmp_path / "a.bin"
    path_b = tmp_path / "b.bin"
    path_a.write_bytes(b"content-a")
    path_b.write_bytes(b"content-b")
    assert file_sha1(str(path_a)) != file_sha1(str(path_b))


def test_text_sha1_deterministic():
    """同文本两次哈希一致；不同文本哈希不同。"""
    assert text_sha1("参考答案") == text_sha1("参考答案")
    assert text_sha1("参考答案A") != text_sha1("参考答案B")
