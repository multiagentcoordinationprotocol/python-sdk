from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthConfig:
    bearer_token: str | None = None
    agent_id: str | None = None
    sender_hint: str | None = None

    def __post_init__(self) -> None:
        if self.bearer_token and self.agent_id:
            raise ValueError("choose either bearer_token or agent_id, not both")
        if not self.bearer_token and not self.agent_id:
            raise ValueError("either bearer_token or agent_id is required")

    @classmethod
    def for_dev_agent(cls, agent_id: str) -> AuthConfig:
        return cls(agent_id=agent_id, sender_hint=agent_id)

    @classmethod
    def for_bearer(cls, token: str, *, sender_hint: str | None = None) -> AuthConfig:
        return cls(bearer_token=token, sender_hint=sender_hint)

    @property
    def sender(self) -> str | None:
        return self.sender_hint or self.agent_id

    def metadata(self) -> list[tuple[str, str]]:
        headers: list[tuple[str, str]] = []
        if self.bearer_token:
            headers.append(("authorization", f"Bearer {self.bearer_token}"))
        if self.agent_id:
            headers.append(("x-macp-agent-id", self.agent_id))
        return headers
