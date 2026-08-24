"""有界内存缓存与内容哈希工具：供 OCR 结果缓存与单图评分缓存复用。

设计取舍：单机低 TPS 场景用进程内存有界字典（满则整体清空），与项目参考缓存
REF_CACHE_MAX=256 先例一致；将来多实例部署时可在不改变调用方的前提下替换为
Redis 实现。内容哈希使缓存键与文件路径解耦，批量裁剪图（uuid 文件名但内容
确定）天然去重。
"""
from __future__ import annotations

import hashlib
import threading


class BoundedCache:
    """有界内存缓存：满则整体清空，线程安全。key 须可哈希。"""

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size 必须为正整数")
        self._max_size = max_size
        self._data: dict[object, object] = {}
        self._lock = threading.Lock()

    def get(self, key) -> object | None:
        """命中返回 value，未命中返回 None。"""
        with self._lock:
            return self._data.get(key)

    def set(self, key, value) -> None:
        """写入键值；长度达上限先 clear() 再写入。"""
        with self._lock:
            if len(self._data) >= self._max_size:
                self._data.clear()
            self._data[key] = value

    def __len__(self) -> int:
        """返回当前缓存的条目数。"""
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        """整体清空缓存。"""
        with self._lock:
            self._data.clear()


def file_sha1(path: str) -> str:
    """读取文件字节返回 sha1 十六进制（内容寻址缓存键）。"""
    sha1 = hashlib.sha1()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(8192), b''):
            sha1.update(chunk)
    return sha1.hexdigest()


def text_sha1(text: str) -> str:
    """对字符串 utf-8 编码计算 sha1 十六进制。"""
    return hashlib.sha1(text.encode('utf-8')).hexdigest()
