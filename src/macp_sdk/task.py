from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from macp.modes.task.v1 import task_pb2
from macp.v1 import envelope_pb2

from .auth import AuthConfig
from .base_projection import BaseProjection
from .base_session import BaseSession
from .constants import MODE_TASK
from .envelope import build_envelope, serialize_message

# ---------------------------------------------------------------------------
# Projection records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TaskRequestRecord:
    task_id: str
    title: str
    instructions: str
    requested_assignee: str
    requester: str


@dataclass(slots=True)
class TaskRejectRecord:
    task_id: str
    assignee: str
    reason: str


@dataclass(slots=True)
class TaskUpdateRecord:
    task_id: str
    status: str
    progress: float
    message: str


@dataclass(slots=True)
class TaskCompleteRecord:
    task_id: str
    assignee: str
    summary: str
    output: bytes


@dataclass(slots=True)
class TaskFailRecord:
    task_id: str
    assignee: str
    error_code: str
    reason: str
    retryable: bool


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


class TaskProjection(BaseProjection):
    """In-process state tracking for Task mode sessions.

    Supports multiple tasks within a single session.  Each task is tracked
    independently with its own status and progress.
    """

    MODE = MODE_TASK

    def __init__(self) -> None:
        super().__init__()
        self.phase = "Pending"
        self.tasks: dict[str, TaskRequestRecord] = {}
        self.updates: list[TaskUpdateRecord] = []
        self.completions: list[TaskCompleteRecord] = []
        self.failures: list[TaskFailRecord] = []
        # Per-task mutable state
        self._assignees: dict[str, str] = {}  # task_id -> assignee
        self._statuses: dict[str, str] = {}  # task_id -> status
        self._progress: dict[str, float] = {}  # task_id -> progress

    def _apply_mode_message(self, envelope: envelope_pb2.Envelope) -> None:
        mt = envelope.message_type

        if mt == "TaskRequest":
            p = task_pb2.TaskRequestPayload()
            p.ParseFromString(envelope.payload)
            self.tasks[p.task_id] = TaskRequestRecord(
                task_id=p.task_id,
                title=p.title,
                instructions=p.instructions,
                requested_assignee=p.requested_assignee,
                requester=envelope.sender,
            )
            self._statuses[p.task_id] = "requested"
            self._progress[p.task_id] = 0.0
            self.phase = "Requested"
            return

        if mt == "TaskAccept":
            p = task_pb2.TaskAcceptPayload()
            p.ParseFromString(envelope.payload)
            assignee = p.assignee or envelope.sender
            self._assignees[p.task_id] = assignee
            self._statuses[p.task_id] = "accepted"
            self.phase = "InProgress"
            return

        if mt == "TaskReject":
            p = task_pb2.TaskRejectPayload()
            p.ParseFromString(envelope.payload)
            self._statuses[p.task_id] = "rejected"
            return

        if mt == "TaskUpdate":
            p = task_pb2.TaskUpdatePayload()
            p.ParseFromString(envelope.payload)
            self.updates.append(
                TaskUpdateRecord(
                    task_id=p.task_id,
                    status=p.status,
                    progress=p.progress,
                    message=p.message,
                )
            )
            self._statuses[p.task_id] = "in_progress"
            self._progress[p.task_id] = p.progress
            return

        if mt == "TaskComplete":
            p = task_pb2.TaskCompletePayload()
            p.ParseFromString(envelope.payload)
            self.completions.append(
                TaskCompleteRecord(
                    task_id=p.task_id,
                    assignee=p.assignee or envelope.sender,
                    summary=p.summary,
                    output=p.output,
                )
            )
            self._statuses[p.task_id] = "completed"
            self._progress[p.task_id] = 1.0
            self.phase = "Completed"
            return

        if mt == "TaskFail":
            p = task_pb2.TaskFailPayload()
            p.ParseFromString(envelope.payload)
            self.failures.append(
                TaskFailRecord(
                    task_id=p.task_id,
                    assignee=p.assignee or envelope.sender,
                    error_code=p.error_code,
                    reason=p.reason,
                    retryable=p.retryable,
                )
            )
            self._statuses[p.task_id] = "failed"
            self.phase = "Failed"

    # -- State query helpers --

    def get_task(self, task_id: str) -> TaskRequestRecord | None:
        """Return the task request record for *task_id*, or None."""
        return self.tasks.get(task_id)

    def is_accepted(self, task_id: str) -> bool:
        status = self._statuses.get(task_id)
        return status == "accepted" or status == "in_progress"

    def is_completed(self, task_id: str) -> bool:
        return self._statuses.get(task_id) == "completed"

    def is_failed(self, task_id: str) -> bool:
        return self._statuses.get(task_id) == "failed"

    def is_retryable(self, task_id: str) -> bool:
        """True if the task failed with ``retryable=True``."""
        return any(f.task_id == task_id and f.retryable for f in self.failures)

    def progress_of(self, task_id: str) -> float:
        """Return the latest progress value for *task_id*, or 0 if unknown."""
        return self._progress.get(task_id, 0.0)

    def latest_progress(self) -> float | None:
        return self.updates[-1].progress if self.updates else None

    def active_tasks(self) -> list[TaskRequestRecord]:
        """Return task records that are not in a terminal state."""
        active_statuses = {"requested", "accepted", "in_progress"}
        return [t for t in self.tasks.values() if self._statuses.get(t.task_id) in active_statuses]


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


class TaskSession(BaseSession):
    """High-level helper for Task mode sessions."""

    MODE = MODE_TASK

    def _create_projection(self) -> BaseProjection:
        return TaskProjection()

    @property
    def task_projection(self) -> TaskProjection:
        assert isinstance(self.projection, TaskProjection)
        return self.projection

    def request(
        self,
        task_id: str,
        title: str,
        *,
        instructions: str = "",
        requested_assignee: str = "",
        input_data: bytes = b"",
        deadline_unix_ms: int = 0,
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = task_pb2.TaskRequestPayload(
            task_id=task_id,
            title=title,
            instructions=instructions,
            requested_assignee=requested_assignee,
            input=input_data,
            deadline_unix_ms=deadline_unix_ms,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="TaskRequest",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def accept_task(
        self,
        task_id: str,
        *,
        assignee: str = "",
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = task_pb2.TaskAcceptPayload(
            task_id=task_id,
            assignee=assignee or self._sender_for(sender),
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="TaskAccept",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def reject_task(
        self,
        task_id: str,
        *,
        assignee: str = "",
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = task_pb2.TaskRejectPayload(
            task_id=task_id,
            assignee=assignee or self._sender_for(sender),
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="TaskReject",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def update(
        self,
        task_id: str,
        *,
        status: str = "",
        progress: float = 0.0,
        message: str = "",
        partial_output: bytes = b"",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = task_pb2.TaskUpdatePayload(
            task_id=task_id,
            status=status,
            progress=progress,
            message=message,
            partial_output=partial_output,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="TaskUpdate",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def complete(
        self,
        task_id: str,
        *,
        assignee: str = "",
        output: bytes = b"",
        summary: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = task_pb2.TaskCompletePayload(
            task_id=task_id,
            assignee=assignee or self._sender_for(sender),
            output=output,
            summary=summary,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="TaskComplete",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def fail(
        self,
        task_id: str,
        *,
        assignee: str = "",
        error_code: str = "",
        reason: str = "",
        retryable: bool = False,
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = task_pb2.TaskFailPayload(
            task_id=task_id,
            assignee=assignee or self._sender_for(sender),
            error_code=error_code,
            reason=reason,
            retryable=retryable,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="TaskFail",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)
