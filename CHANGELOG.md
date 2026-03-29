# Changelog

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
