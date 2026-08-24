"""批量批改任务注册表单元测试。"""
import pytest

import backend.batch.task_store as task_store


@pytest.fixture(autouse=True)
def _reset_tasks():
    """每轮测试前清空任务注册表，保证用例隔离。"""
    task_store._tasks.clear()
    yield
    task_store._tasks.clear()


def test_create_task_unique_id_and_initial_state():
    """create_task 返回唯一 id，初始 status/progress/total_items 正确。"""
    id1 = task_store.create_task(5)
    id2 = task_store.create_task(5)
    assert id1 != id2
    task = task_store.get_task(id1)
    assert task["task_id"] == id1
    assert task["total_items"] == 5
    assert task["status"] == "running"
    assert task["progress"] == 0
    assert task["current_item"] == 0
    assert task["result"] is None
    assert task["error"] is None


def test_update_task_applies_fields():
    """update_task 更新字段生效。"""
    task_id = task_store.create_task(3)
    task_store.update_task(task_id, status="succeeded", progress=100, current_item=3)
    task = task_store.get_task(task_id)
    assert task["status"] == "succeeded"
    assert task["progress"] == 100
    assert task["current_item"] == 3


def test_get_task_returns_copy():
    """get_task 返回副本，外部修改不影响内部状态。"""
    task_id = task_store.create_task(2)
    task_store.update_task(task_id, progress=60)
    returned = task_store.get_task(task_id)
    returned["progress"] = 0
    returned["task_id"] = "hacked"
    assert task_store.get_task(task_id)["progress"] == 60
    assert task_store.get_task(task_id)["task_id"] == task_id


def test_get_task_missing_returns_none():
    """不存在的任务返回 None。"""
    assert task_store.get_task("no-such-id") is None


def test_list_tasks_contains_created_tasks():
    """list_tasks 包含已创建任务且字段为副本。"""
    id1 = task_store.create_task(1)
    id2 = task_store.create_task(2)
    listed = task_store.list_tasks()
    ids = {task["task_id"] for task in listed}
    assert {id1, id2}.issubset(ids)
    for task in listed:
        task["progress"] = -1
    assert task_store.get_task(id1)["progress"] == 0
