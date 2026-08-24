"""内存任务注册表：跟踪批量批改后台任务的进度与结果。

进程内全局字典 + 线程锁实现，任务量小、生命周期短，无需持久化；
查询接口返回副本，避免外部修改内部状态。
"""
import threading
import uuid
from datetime import datetime
from typing import Optional

_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def create_task(total_items: int) -> str:
    """创建批量批改任务并登记，返回生成的 task_id。"""
    task_id = uuid.uuid4().hex
    task = {
        "task_id": task_id,
        "status": "running",
        "progress": 0,
        "current_item": 0,
        "total_items": total_items,
        "message": "",
        "result": None,
        "error": None,
        "created_at": datetime.now().isoformat(),
        "finished_at": None,
    }
    with _lock:
        _tasks[task_id] = task
    return task_id


def update_task(task_id: str, **fields: object) -> None:
    """加锁更新任务字段；finished_at 由成功/失败时调用方显式传入。"""
    with _lock:
        task = _tasks.get(task_id)
        if task is not None:
            task.update(fields)


def get_task(task_id: str) -> Optional[dict]:
    """查询任务，返回字典副本（外部改动不影响内部状态）；不存在返回 None。"""
    with _lock:
        task = _tasks.get(task_id)
        return dict(task) if task is not None else None


def list_tasks() -> list[dict]:
    """列出全部任务副本，按创建时间倒序。"""
    with _lock:
        tasks = list(_tasks.values())
    return [dict(task) for task in sorted(tasks, key=lambda t: t["created_at"], reverse=True)]
