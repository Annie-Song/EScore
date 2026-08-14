"""批改记录持久化存储层：存储抽象接口 + 模块级默认存储入口。

GradeStore 抽象接口隔离存储实现细节，为将来切换 PostgreSQL 预留扩展路径；
SQLite 实现位于 services.sqlite_store，由 default_store() 惰性加载避免循环依赖。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

# 批次状态字面量
BATCH_STATUS_RUNNING = "running"      # 批改进行中
BATCH_STATUS_SUCCEEDED = "succeeded"  # 批改成功完成
BATCH_STATUS_FAILED = "failed"        # 批改失败

# 表结构 DDL：CREATE IF NOT EXISTS，幂等可重复初始化
_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY, reference_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running', total_questions INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS grade_records (
    record_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, question_no INTEGER NOT NULL,
    work_text TEXT NOT NULL DEFAULT '', answer_text TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL, method TEXT NOT NULL DEFAULT 'offline',
    degraded INTEGER NOT NULL DEFAULT 0, routed INTEGER NOT NULL DEFAULT 0,
    error_category TEXT NOT NULL DEFAULT '', error_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, FOREIGN KEY(batch_id) REFERENCES batches(batch_id));
CREATE INDEX IF NOT EXISTS idx_grade_records_batch ON grade_records(batch_id);
"""


@dataclass
class GradeRecord:
    """单条批改记录，score 为 0-100 百分制。"""

    record_id: str
    batch_id: str
    question_no: int
    work_text: str
    answer_text: str
    score: float
    method: str
    degraded: bool
    routed: bool
    # created_at 无默认值，置于带默认字段之前以满足 dataclass 字段顺序约束
    created_at: str
    error_category: str = ""
    error_reason: str = ""


class GradeStore(ABC):
    """批改记录存储抽象接口，具体实现可选用 SQLite / PostgreSQL 等。"""

    @abstractmethod
    def save_record(self, record: GradeRecord) -> None:
        """保存单条批改记录。"""

    @abstractmethod
    def save_records(self, records: list[GradeRecord]) -> None:
        """单事务批量保存批改记录。"""

    @abstractmethod
    def get_record(self, record_id: str) -> Optional[GradeRecord]:
        """按 record_id 查询单条记录，不存在返回 None。"""

    @abstractmethod
    def list_records(self, batch_id: str) -> list[GradeRecord]:
        """按批次列出全部记录。"""

    @abstractmethod
    def save_batch(self, batch_id: str, reference_text: str, status: str,
                   total_questions: int, created_at: str) -> None:
        """保存批次元信息，已存在则覆盖更新。"""

    @abstractmethod
    def update_batch_status(self, batch_id: str, status: str, total_questions: int) -> None:
        """更新批次状态与总题数。"""

    @abstractmethod
    def get_batch(self, batch_id: str) -> Optional[dict]:
        """查询批次元信息，不存在返回 None。"""

    @abstractmethod
    def list_batches(self) -> list[dict]:
        """列出全部批次，按创建时间倒序。"""

    @abstractmethod
    def stats_by_question(self, batch_id: str) -> list[dict]:
        """按题号聚合：数量/平均分/最高分/最低分，数值保留 1 位小数。"""

    @abstractmethod
    def stats_by_category(self, batch_id: str) -> list[dict]:
        """按错误类别聚合：数量/平均分，按数量倒序。"""


_store: Optional["SqliteGradeStore"] = None


def default_store() -> "SqliteGradeStore":
    """懒加载并缓存全局共享存储单例，供路由与批改线程共用。"""
    from services.sqlite_store import SqliteGradeStore

    global _store
    if _store is None:
        _store = SqliteGradeStore()
    return _store
