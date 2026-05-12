# Changelog

All notable changes to this project will be documented here. Format roughly Keep-a-Changelog; versions follow PEP 440.

## [Unreleased]

## [0.1.0-rc1] -- 2026-05-12

First release candidate for v0.1.0. 7/8 acceptance gates met; AC-7 (AQH PASS real Zoom meeting) is the rc1->v0.1.0 gate.

### Added
- `Assistant` class -- in-meeting AI assistant primitive for Lattice meeting-platform adapters
- Private DM handling via `on_private_chat()` (Zoom adapter v0.2+)
- Public @-mention handling via `on_public_mention()`
- TG-owner + in-meeting-DM transports with transport-bound cortex tool resolution
- 5 Architectural Invariants enforced in code (separated send paths, transport-bound knowledge, per-thread memory isolation, visibility-tag fail-closed, admin surface isolation)
- 12 boundary tests T1-T12 green (AC-2)
- 11 cortex tools (5 in-meeting curated + 6 TG-owner Nexus wrappers)
- `BLOCKED_IN_MEETING_TOOLS` deny-list + boot self-test
- `SeriesMatcher` -- Path 1 (explicit recurring meeting ID) + Path 2 (implicit host-cohort with TG ratification)
- `ChatThreadActor` -- FIFO worker + holding message + backpressure + history compaction + lifecycle
- Global cortex semaphore (default 4 concurrent calls per meeting)
- Admin command parser (TG-only per `Meeting Platform Admin Surface Isolation`)
- Profile YAML loader + Brain MCP write-back for persistent mutations (ruamel.yaml round-trip preserves comments + anchors)
- Public-mention rate limit (default 1 reply / 30s per meeting)
- `WrapupTranscriptConsumer` Protocol -- consumer-side boundary contract documenting that private chat events never reach wrap-up consumers
- `AssistantStats` observability surface

### Dependencies
- `lattice-meeting-contracts >= 0.3.0-rc1`
- `lattice-meeting >= 0.2.0`
- `lattice-cortex >= 0.6.0`
- `ruamel.yaml >= 0.18.0` (YAML round-trip fidelity for profile write-back)

### Acceptance gates (rc1)
- AC-1 mypy --strict (26 src files clean) -- PASS
- AC-2 12 boundary tests T1-T12 PASS -- PASS
- AC-3 YAML round-trip (ruamel.yaml round-trip mode preserves comments + anchors) -- PASS
- AC-4 cortex tool registration (11 tools + resolver + boot self-test) -- PASS
- AC-5 >=90% critical-path coverage (privacy/ 91-100%, actor.py 94%, tools/ 93-100%, series.py 99%) -- PASS
- AC-6 series ratification mock-TG E2E -- PASS
- AC-7 AQH PASS real Zoom -- DEFERRED (**rc1->v0.1.0 gate**). Blockers: (a) meetbot v0.2 W6 hardening complete; (b) Cyril available during AQH run. Will promote rc1 -> v0.1.0 once green.
- AC-8 PVD-clean -- PASS

### Deferred to v0.1.0 GA (this rc1's promotion gate)
- AC-7 AQH PASS real Zoom meeting evidence

### Known follow-ups (v0.1.x / v0.2 backlog)
- `TKT-c775d84e` (p2) -- prompt-renderer stubs need `lattice-persona-profile` v0.1 library to render `persona_voice_block` / `transcript_hot_window` / meeting metadata. Currently shipped with empty strings (functional but unpersonalized).
- `TKT-5d89d16d` (p2) -- `lattice-meeting-contracts` `AdminTransport` Protocol is send-only; SeriesMatcher Path 2 ratification uses duck-typed `getattr` workaround for `await_admin_reply`. Contracts v0.3.1+ should canonicalize the receive half.

### Architectural references
- Spec: `02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec.md`
- Plan: `02_Projects/Lattice/lattice-meeting-assistant/Plans/2026-05-11 lattice-meeting-assistant v0.1 - Implementation Plan.md`
- Lattice-wide protocols: `Meeting Platform Admin Surface Isolation.md`, `Surfaced Follow-ups Tracking Discipline.md`

## [0.1.0.dev0] - 2026-05-11

### Added
- Initial scaffold (W1.1): `LICENSE` (Apache 2.0), `README.md`, `.gitignore` (Lattice security block + Python), `.gitleaks.toml`, pre-commit hook, `src/lattice_meeting_assistant/` + `tests/` skeletons.
- `pyproject.toml` + `requirements.txt` (W1.2). Pinned to git tags pending sibling-package PyPI publish; intended semantic ranges are `lattice-meeting-contracts >=0.3.0rc2,<0.4`, `lattice-meeting >=0.2.0,<0.3`, `lattice-cortex >=0.6.0,<0.7`. Swap to PEP 440 version specifiers when the sibling packages publish to PyPI.
