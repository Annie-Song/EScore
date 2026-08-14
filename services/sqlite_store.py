"""SQLite 批改记录存储实现：标准库 sqlite3，零新依赖。

每操作独立连接（天然跨线程安全），WAL 日志模式，供批量批改写入与统计报告查询使用。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from services.store import GradeRecord, GradeStore, _SCHEMA
from utils.config import DB_PATH


def _record_params(record: GradeRecord) -> tuple:
    """展开为写入参数元组，bool 转 INTEGER(0/1)。"""
    return (
        record.record_id,
        record.batch_id,
        record.question_no,
        record.work_text,
        record.answer_text,
        record.score,
        record.method,
        int(record.degraded),
        int(record.routed),
        record.error_category,
        record.error_reason,
        record.created_at,
    )


def _row_to_record(row: sqlite3.Row) -> GradeRecord:
    """将数据库行完整转换为 GradeRecord，INTEGER(0/1) 还原为 bool。"""
    return GradeRecord(
        record_id=row["record_id"],
        batch_id=row["batch_id"],
        question_no=row["question_no"],
        work_text=row["work_text"],
        answer_text=row["answer_text"],
        score=row["score"],
        method=row["method"],
        degraded=bool(row["degraded"]),
        routed=bool(row["routed"]),
        created_at=row["created_at"],
        error_category=row["error_category"],
        error_reason=row["error_reason"],
    )


class SqliteGradeStore(GradeStore):
    """标准库 sqlite3 实现：WAL 模式、每操作独立连接、with 事务语义。"""

    _INSERT_RECORD_SQL = (
        "INSERT INTO grade_records (record_id, batch_id, question_no, work_text, "
        "answer_text, score, method, degraded, routed, error_category, error_reason, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    )

    def __init__(self, db_path: str = DB_PATH) -> None:
        """建父目录并幂等建表，可重复初始化。"""
        self._db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._session() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """开新连接：设置行工厂并启用 WAL 日志模式。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """事务会话：正常提交、异常回滚，退出时关闭连接。"""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save_record(self, record: GradeRecord) -> None:
        with self._session() as conn:
            conn.execute(self._INSERT_RECORD_SQL, _record_params(record))

    def save_records(self, records: list[GradeRecord]) -> None:
        with self._session() as conn:
            conn.executemany(self._INSERT_RECORD_SQL, [_record_params(r) for r in records])

    def get_record(self, record_id: str) -> Optional[GradeRecord]:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM grade_records WHERE record_id=?", (record_id,)
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_records(self, batch_id: str) -> list[GradeRecord]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM grade_records WHERE batch_id=? ORDER BY question_no",
                (batch_id,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def save_batch(self, batch_id: str, reference_text: str, status: str,
                   total_questions: int, created_at: str) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO batches "
                "(batch_id, reference_text, status, total_questions, created_at) "
                "VALUES (?,?,?,?,?)",
                (batch_id, reference_text, status, total_questions, created_at),
            )

    def update_batch_status(self, batch_id: str, status: str, total_questions: int) -> None:
        with self._session() as conn:
            conn.execute(
                "UPDATE batches SET status=?, total_questions=? WHERE batch_id=?",
                (status, total_questions, batch_id),
            )

    def get_batch(self, batch_id: str) -> Optional[dict]:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_batches(self) -> list[dict]:
        with self._session() as conn:
            rows = conn.execute("SELECT * FROM batches ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def stats_by_question(self, batch_id: str) -> list[dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT question_no, COUNT(*) AS cnt, AVG(score) AS avg_score, "
                "MAX(score) AS max_score, MIN(score) AS min_score "
                "FROM grade_records WHERE batch_id=? "
                "GROUP BY question_no ORDER BY question_no",
                (batch_id,),
            ).fetchall()
        return [
            {
                "question_no": row["question_no"],
                "count": row["cnt"],
                "avg_score": round(row["avg_score"], 1),
                "max_score": round(row["max_score"], 1),
                "min_score": round(row["min_score"], 1),
            }
            for row in rows
        ]

    def stats_by_category(self, batch_id: str) -> list[dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT error_category, COUNT(*) AS cnt, AVG(score) AS avg_score "
                "FROM grade_records WHERE batch_id=? "
                "GROUP BY error_category ORDER BY cnt DESC",
                (batch_id,),
            ).fetchall()
        return [
            {
                "error_category": row["error_category"],
                "count": row["cnt"],
                "avg_score": round(row["avg_score"], 1),
            }
            for row in rows
        ]
