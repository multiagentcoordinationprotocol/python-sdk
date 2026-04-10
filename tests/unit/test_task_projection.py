from __future__ import annotations

from macp.modes.task.v1 import task_pb2

from macp_sdk.constants import MODE_TASK
from macp_sdk.task import TaskProjection
from tests.conftest import make_envelope


class TestTaskProjection:
    def _proj(self) -> TaskProjection:
        return TaskProjection()

    def test_initial_state(self):
        p = self._proj()
        assert p.phase == "Pending"
        assert len(p.tasks) == 0
        assert not p.is_accepted("t1")
        assert not p.is_completed("t1")
        assert not p.is_failed("t1")

    def test_task_request(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskRequest",
                task_pb2.TaskRequestPayload(
                    task_id="t1",
                    title="Analyze data",
                    instructions="run the pipeline",
                    requested_assignee="worker",
                ),
                sender="planner",
            )
        )
        assert p.get_task("t1") is not None
        assert p.get_task("t1").task_id == "t1"
        assert p.phase == "Requested"

    def test_accept(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskRequest",
                task_pb2.TaskRequestPayload(task_id="t1", title="x"),
                sender="planner",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskAccept",
                task_pb2.TaskAcceptPayload(task_id="t1", assignee="worker"),
                sender="worker",
            )
        )
        assert p.is_accepted("t1")
        assert p.phase == "InProgress"

    def test_reject(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskRequest",
                task_pb2.TaskRequestPayload(task_id="t1", title="x"),
                sender="planner",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskReject",
                task_pb2.TaskRejectPayload(task_id="t1", assignee="worker", reason="busy"),
                sender="worker",
            )
        )
        assert not p.is_accepted("t1")

    def test_update(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskUpdate",
                task_pb2.TaskUpdatePayload(
                    task_id="t1", status="running", progress=0.5, message="halfway"
                ),
                sender="worker",
            )
        )
        assert len(p.updates) == 1
        assert p.latest_progress() == 0.5

    def test_complete(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskRequest",
                task_pb2.TaskRequestPayload(task_id="t1", title="x"),
                sender="planner",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskComplete",
                task_pb2.TaskCompletePayload(
                    task_id="t1", assignee="worker", summary="done", output=b"result"
                ),
                sender="worker",
            )
        )
        assert p.is_completed("t1")
        assert not p.is_failed("t1")
        assert p.phase == "Completed"
        assert p.progress_of("t1") == 1.0

    def test_fail(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskRequest",
                task_pb2.TaskRequestPayload(task_id="t1", title="x"),
                sender="planner",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskFail",
                task_pb2.TaskFailPayload(
                    task_id="t1",
                    assignee="worker",
                    error_code="TIMEOUT",
                    reason="too slow",
                    retryable=True,
                ),
                sender="worker",
            )
        )
        assert p.is_failed("t1")
        assert not p.is_completed("t1")
        assert p.is_retryable("t1")
        assert p.phase == "Failed"

    def test_active_tasks(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskRequest",
                task_pb2.TaskRequestPayload(task_id="t1", title="x"),
                sender="planner",
            )
        )
        assert len(p.active_tasks()) == 1
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskComplete",
                task_pb2.TaskCompletePayload(task_id="t1", assignee="worker"),
                sender="worker",
            )
        )
        assert len(p.active_tasks()) == 0
