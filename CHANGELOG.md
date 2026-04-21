# Changelog

## 0.2.3 (unreleased)

Streaming-path uplift: non-initiator agents no longer miss
``SessionStart`` / early ``Proposal`` envelopes when their stream
opens after the initiator has already published them.

### Added

- **``MacpStream.send_subscribe(session_id, after_sequence=0)``** —
  RFC-MACP-0006-A1 subscribe-only frame. The runtime replays accepted
  session envelopes from ``after_sequence`` onwards then switches to
  live broadcast, removing the previous late-attach limitation
  documented in ``docs/guides/streaming.md``.
- **``GrpcTransportAdapter``** now invokes ``send_subscribe`` as the
  first frame on every stream, so ``Participant`` / ``from_bootstrap``
  agents receive the full session history without any caller changes.
- ``tests/unit/test_client_stream.py`` (7 tests) covering the
  subscribe frame, envelope multiplexing through ``_request_iter``,
  proto serialisation, and closed-stream guards.
- ``tests/integration/test_subscribe_replay.py`` (2 tests) covering
  the late-joiner replay path and the ``after_sequence`` skip path.
- ``tests/unit/test_agent_transports.py`` — two new assertions that
  verify ``GrpcTransportAdapter`` subscribes before consuming
  responses.

### Changed

- **``macp-proto`` pin widened** to ``>=0.1.2,<0.2.0``. 0.1.2 is the
  first release that exposes ``subscribe_session_id`` /
  ``after_sequence`` on ``StreamSessionRequest``; the subscribe path
  is a runtime ``ValueError`` against older bindings.
- Streaming guide documents the subscribe frame and removes the
  "No late-attach handshake" known-limitations bullet.

## 0.2.1 (unreleased)

Quality-uplift patch release (see `plans/code-quality-uplift.md`).
No public API changes; no semantic changes to the 0.2.0 behaviour.

### Changed (internal)

- **Ack error-reason parsing unified.** `MacpClient.send` and
  `MacpClient.cancel_session` now share a single
  `_failure_from_ack` helper, so `MacpAckError.reasons` surfaces on
  `CancelSession` NACKs too (e.g. `POLICY_DENIED` with structured
  rule IDs when cancellation isn't delegated).
- **Mode-helper return types narrowed** from `Any` to
  `envelope_pb2.Ack` on every action method in
  `Decision/Proposal/Task/Handoff/QuorumSession` and on
  `BaseSession.start` / `commit` / `cancel` / `metadata`. IDEs now
  autocomplete `ack.ok`, `ack.session_id`, `ack.message_id` directly.
- **`AuthConfig` docs rebalanced.** `docs/auth.md` now leads with
  `expected_sender` and treats `sender_hint` as an advanced escape
  hatch; `README.md` quick-start leads with a Bearer + TLS example.

### Added

- **Test backfill:** `tests/unit/test_watchers.py` (14 tests),
  `tests/unit/test_serialization_determinism.py` (11 tests),
  `tests/unit/test_proto_registry.py` (19 tests),
  `tests/unit/test_client_helpers.py` (17 tests),
  `tests/unit/test_validation.py` (19 tests). Unit-test line
  coverage moved from 80% → 87%.
- **Coverage gate:** CI and publish workflows now enforce
  `--cov-fail-under=85`.
- **Proto-drift cron:** `.github/workflows/proto-drift.yml` runs the
  test suite against the latest `macp-proto 0.x` daily and opens a
  tracking issue on regression.
- **Ruff rule set extended** with `ARG`, `RET`, `N`, `RUF`. Existing
  violations (sorted `__slots__`, unsorted `__all__`, stale `noqa`)
  auto-fixed; tests/examples got targeted per-file ignores.
- **Contributing guide:** `docs/contributing.md` documents the
  release flow and the `macp-proto` bump process.
- **Makefile help:** `make help` lists every target with a one-line
  description; `sync-fixtures` now points at the spec repo cleanly
  when missing.
- **`macp-proto` pin narrowed** to `>=0.1.0,<0.2.0`.
- **Direct-agent-auth examples:** `examples/direct_agent_auth_initiator.py`
  and `examples/direct_agent_auth_observer.py` mirror the
  integration test for runnable reference code.
- **Architecture doc** grew an "Action-method signature conventions"
  section pinning the `(ids*, *, payload_kwargs, sender, auth)` rule.

### Fixed

- Dropped an unused `monkeypatch` fixture in
  `tests/unit/test_sender_validation.py::test_signal_mismatch_raises`.
- Renamed an unused `message` parameter in the strategy-based
  `commitment_handler` factory to `_message` (with a comment) so
  the `ARG001` lint rule stays enabled going forward.

## 0.2.0 (unreleased)

Hardening release aligned with the `direct-agent-auth` plan — agents now
authenticate to the runtime directly with their own Bearer identity
(RFC-MACP-0004 §4), and the SDK enforces that posture client-side.

### Breaking

- `MacpClient(secure=...)` now defaults to `True` (RFC-MACP-0006 §3).
  Passing `secure=False` raises `MacpSdkError` unless `allow_insecure=True`
  is also supplied. Local dev must opt in explicitly:
  `MacpClient(target=..., allow_insecure=True, auth=...)`.
- `AuthConfig.for_dev_agent(agent_id)` now defaults
  `expected_sender=agent_id`. Calls that pass a different
  `sender=` without a matching per-call `auth=` override raise
  `MacpIdentityMismatchError`. This matches how the runtime already
  behaves and surfaces the problem earlier.
- Bootstrap files consumed by `from_bootstrap()` must set
  `"secure": false` **together with** `"allow_insecure": true` for
  plaintext transport.

### Added

- `MacpIdentityMismatchError` — raised client-side before an envelope
  reaches the wire when `sender=` conflicts with `auth.expected_sender`.
  Exported from `macp_sdk`.
- `AuthConfig.for_bearer(..., expected_sender=...)` — binds the token to
  an identity; the SDK enforces that `sender=` matches on every session
  helper and on `MacpClient.send_signal` / `send_progress`.
- `BaseSession.start(..., auth=...)` — matches the existing per-method
  `auth=` override on `commit/vote/...` so initiator agents can pass
  per-call credentials without reaching into private helpers.
- `.github/workflows/publish.yml` — trusted-publisher PyPI pipeline
  triggered on `v*` tags.
- Integration test `tests/integration/test_direct_agent_auth.py` covering
  the initiator-direct-auth flow (`DecisionSession(session_id=preallocated)
  .start().open_stream().propose()`) with both dev-header and Bearer auth.
- `docs/guides/direct-agent-auth.md` — walk-through of the new topology.

### Changed

- `MacpClient` bumps `client_version` default to `"0.2.0"` in the
  `ClientInfo` handshake.
- Examples, README, mode docs, and streaming guide updated to use
  `allow_insecure=True` for local dev and `expected_sender=` on every
  Bearer example.

## 0.1.0 (unreleased)

### Added
- `MacpClient` — sync gRPC client with all 14 runtime RPCs
- `MacpStream` — bidirectional streaming with background thread
- `BaseSession` / `BaseProjection` — abstract base classes for mode helpers
- `DecisionSession` + `DecisionProjection` — Decision mode
- `ProposalSession` + `ProposalProjection` — Proposal mode
- `TaskSession` + `TaskProjection` — Task mode
- `HandoffSession` + `HandoffProjection` — Handoff mode
- `QuorumSession` + `QuorumProjection` — Quorum mode
- `AuthConfig` — bearer token and dev agent authentication
- `RetryPolicy` + `retry_send` — exponential backoff retry helper
- `configure_logging` — SDK logger configuration
- Envelope builders and ID generators
- Full error hierarchy: `MacpSdkError`, `MacpAckError`, `MacpTransportError`, `MacpSessionError`, `MacpTimeoutError`, `MacpRetryError`
- Unit tests (90 tests)
- GitHub Actions CI (lint, typecheck, test, build)
- MkDocs documentation site
- Examples for all 5 modes
