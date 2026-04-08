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
        assert p.task is None
        assert not p.is_accepted()
        assert not p.is_completed()
        assert not p.is_failed()

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
        assert p.task is not None
        assert p.task.task_id == "t1"
        assert p.phase == "Requested"

    def test_accept(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskAccept",
                task_pb2.TaskAcceptPayload(task_id="t1", assignee="worker"),
                sender="worker",
            )
        )
        assert p.is_accepted()
        assert p.active_assignee == "worker"
        assert p.phase == "InProgress"

    def test_reject(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskReject",
                task_pb2.TaskRejectPayload(task_id="t1", assignee="worker", reason="busy"),
                sender="worker",
            )
        )
        assert len(p.rejections) == 1
        assert not p.is_accepted()

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
                "TaskComplete",
                task_pb2.TaskCompletePayload(
                    task_id="t1", assignee="worker", summary="done", output=b"result"
                ),
                sender="worker",
            )
        )
        assert p.is_completed()
        assert not p.is_failed()
        assert p.phase == "Completed"

    def test_fail(self):
        p = self._proj()
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
        assert p.is_failed()
        assert not p.is_completed()
        assert p.phase == "Failed"

    def test_active_assignee_reject_clears_assignee(self):
        """When the active assignee rejects (reassignment policy allowed it),
        the projection should clear active_assignee and revert phase."""
        p = self._proj()
        # Accept first
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskAccept",
                task_pb2.TaskAcceptPayload(task_id="t1", assignee="worker-a"),
                sender="worker-a",
            )
        )
        assert p.active_assignee == "worker-a"
        assert p.phase == "InProgress"

        # Active assignee rejects (runtime allowed it via reassignment policy)
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskReject",
                task_pb2.TaskRejectPayload(task_id="t1", assignee="worker-a", reason="can't do it"),
                sender="worker-a",
            )
        )
        assert p.active_assignee is None
        assert not p.is_accepted()
        assert p.phase == "Requested"
        assert len(p.rejections) == 1

    def test_non_assignee_reject_does_not_clear_assignee(self):
        """Rejection by a non-assignee should not affect active_assignee."""
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskAccept",
                task_pb2.TaskAcceptPayload(task_id="t1", assignee="worker-a"),
                sender="worker-a",
            )
        )
        # Different participant rejects
        p.apply_envelope(
            make_envelope(
                MODE_TASK,
                "TaskReject",
                task_pb2.TaskRejectPayload(task_id="t1", assignee="worker-b", reason="not me"),
                sender="worker-b",
            )
        )
        assert p.active_assignee == "worker-a"
        assert p.is_accepted()
        assert p.phase == "InProgress"
