from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration for a MACP client or session.

    The ``expected_sender`` field is a client-side guardrail: when set, any
    explicit ``sender=`` passed to a session helper must match it, otherwise
    the SDK raises :class:`MacpIdentityMismatchError` before the envelope
    reaches the wire. Per RFC-MACP-0004 §4 the runtime derives ``sender``
    from authenticated identity, so mismatches are always rejected — this
    check just surfaces the problem earlier and more clearly.

    When ``expected_sender`` is ``None`` the check is skipped (preserves
    legacy behaviour for dev/test flows that use a single shared identity).
    """

    bearer_token: str | None = None
    agent_id: str | None = None
    sender_hint: str | None = None
    expected_sender: str | None = None

    def __post_init__(self) -> None:
        if self.bearer_token and self.agent_id:
            raise ValueError("choose either bearer_token or agent_id, not both")
        if not self.bearer_token and not self.agent_id:
            raise ValueError("either bearer_token or agent_id is required")

    @classmethod
    def for_dev_agent(cls, agent_id: str, *, expected_sender: str | None = None) -> AuthConfig:
        """Build an AuthConfig for local development without a real token.

        Emits ``Authorization: Bearer <agent_id>``. The runtime's
        ``dev_authenticate`` fallback (``runtime/src/security.rs:91``)
        binds the bearer token value verbatim as the authenticated
        sender, so passing the raw agent id keeps participant lists
        like ``["coordinator", "alice"]`` working unchanged.

        Runtime ≥ 0.4.0 **removed** the ``x-macp-agent-id`` header path
        (``dev_mode_rejects_dev_sender_header`` test in ``security.rs``),
        so earlier SDK versions that relied on
        ``MACP_ALLOW_DEV_SENDER_HEADER=1`` no longer authenticate. This
        Bearer-based dev auth replaces that path — no runtime env flag
        is required.

        For production deployments issue real tokens via the auth
        resolver chain and use :meth:`for_bearer` directly.
        """
        return cls(
            bearer_token=agent_id,
            sender_hint=agent_id,
            expected_sender=expected_sender or agent_id,
        )

    @classmethod
    def for_bearer(
        cls,
        token: str,
        *,
        sender_hint: str | None = None,
        expected_sender: str | None = None,
    ) -> AuthConfig:
        """Build a Bearer-token AuthConfig.

        :param token: the Bearer token issued by the runtime
        :param sender_hint: the sender string the SDK places on envelopes when
            no explicit ``sender=`` is provided. Defaults to ``expected_sender``
            when only the latter is supplied.
        :param expected_sender: the identity the runtime will bind this token
            to. When set, the SDK rejects any explicit ``sender=`` that does
            not match with :class:`MacpIdentityMismatchError`.
        """
        return cls(
            bearer_token=token,
            sender_hint=sender_hint or expected_sender,
            expected_sender=expected_sender,
        )

    @property
    def sender(self) -> str | None:
        return self.sender_hint or self.agent_id

    def metadata(self) -> list[tuple[str, str]]:
        headers: list[tuple[str, str]] = []
        if self.bearer_token:
            headers.append(("authorization", f"Bearer {self.bearer_token}"))
        # Note: the legacy ``x-macp-agent-id`` header was ignored by the
        # runtime as of v0.4.0 (RFC-MACP-0006 §3 tightening). Callers
        # constructing ``AuthConfig(agent_id=...)`` directly must now
        # supply a Bearer token instead — see :meth:`for_dev_agent` for
        # the supported dev-mode path.
        return headers
