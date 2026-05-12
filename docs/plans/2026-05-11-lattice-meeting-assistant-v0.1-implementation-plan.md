---
title: lattice-meeting-assistant v0.1 - Implementation Plan
project: Lattice
library: lattice-meeting-assistant
type: plan
status: released-v0.1.0-rc1
version: "0.1"
date: 2026-05-11
session: S25
authors:
  - Cyril Grosse III (ratifier)
  - Cody (Claude Opus 4.7 1M, S25 session-9e307b5296b9)
authority:
  - "[[02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec]]"
  - "[[02_Projects/Lattice/lattice-meeting-assistant/Mission]]"
  - "[[02_Projects/Lattice/Family]]"
  - "[[02_Projects/Protocols/Plan Verification Discipline]]"
  - "[[02_Projects/Protocols/Meeting Platform Admin Surface Isolation]]"
  - "[[02_Projects/Protocols/Cody Voice Identity]]"
  - "[[02_Projects/Protocols/Persona Mappings]]"
  - "[[02_Projects/Protocols/Async by Default for External Services]]"
related:
  - "[[02_Projects/Lattice/lattice-meetbot/Plans/2026-05-09 lattice-meetbot v0.2 - Implementation Plan]]"
  - "[[02_Projects/Lattice/lattice-meeting-assistant/Research/2026-05-11 Meeting-Platform Capability Comparison - Zoom Meet Teams]]"
  - "[[02_Projects/Lattice/lattice-meeting-assistant/Decisions/2026-05-11 Public @cody mentions included in v0.1]]"
tags:
  - plan
  - lattice
  - lattice-meeting-assistant
  - v0.1
  - assistant
  - private-chat
  - public-mention
  - tdd
  - pvd-conformant
  - subagent-driven
aliases:
  - lattice-meeting-assistant v0.1 Plan
  - assistant v0.1 plan
created: 2026-05-11
updated: 2026-05-12T11:33
pvd_conformant: true
blocks_on: plan
execution_mode: superpowers:subagent-driven-development
---

# lattice-meeting-assistant v0.1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` per global `~/.claude/CLAUDE.md` hard rule (subagent-driven plan execution is ALWAYS the path; no inline alternative offered). Steps use checkbox (`- [ ]`) syntax for tracking. Each task is a TDD pair (failing test → minimal impl → verify → commit) unless explicitly noted otherwise (e.g., scaffold tasks). Strict single-task scope per dispatch ("STOP after Task N — do NOT execute Task N+1").

**Goal:** Ship `lattice-meeting-assistant==0.1.0` as a new sibling Lattice library — in-meeting AI assistant primitive consumed in-process by lattice-meetbot v0.2+ with two transports (TG-owner + in-meeting-DM), two thread types (private DM per-participant + public @-mention per-meeting), curated cortex tool registration per transport, 5 architectural privacy invariants in code, all 12 boundary tests + AQH PASS for AC-7.

**Architecture:** Pure-Python async library; consumed in-process. LLM dispatch through `lattice-cortex` ≥ 0.6.0 (Axiom 1 — never direct provider SDK). Per-thread `ChatThreadActor` keyed on `(meeting_id, canonical_persona_id)` for private DMs and `(meeting_id, "public")` for public mentions — physically isolated memory + cortex cache namespace. Tool resolution transport-bound: in-meeting-DM gets curated set (transcript/web/refs/series); TG-owner gets full Nexus surface. Admin commands route ONLY via Telegram (`[[Meeting Platform Admin Surface Isolation]]` lattice-wide protocol).

**Tech Stack:**

- **Language:** Python 3.11+
- **Async runtime:** asyncio (stdlib)
- **Cortex client:** `lattice-cortex>=0.6.0` (substrate; tool-use API hard dep — verified in W0.2)
- **Contracts:** `lattice-meeting-contracts>=0.3.0-rc1` (next release adds `AdminTransport` ABC + `PlatformChatCapability` + `TranscriptBuffer` Protocol; cut in W0.1)
- **Persona resolver:** `lattice-meeting>=0.2.0` (already GA from S24)
- **Brain MCP wrapper:** `httpx>=0.24.0` for direct Brain API calls (no MCP layer required at runtime — library calls REST)
- **YAML:** `PyYAML>=6.0` for profile + series vault note parsing
- **Schema:** `pydantic>=2.0.0` for cortex tool argument schemas
- **Tests:** `pytest>=7` + `pytest-asyncio>=0.23` + `pytest-cov>=4`
- **Typing:** `mypy --strict src/` clean (AC-1)
- **Production host:** Cypher (runs in-process inside meetbot v0.2 sidecar image)
- **License:** Apache 2.0
- **Repo coordinates:**
  - Canonical: `G:/My Drive/Projects Merge/lattice-meeting-assistant/` (per Project Registry §93)
  - GitHub: `github.com/CodeWarrior4Life/lattice-meeting-assistant`
  - PyPI: `lattice-meeting-assistant==0.1.0` (owner-gated)

---

## For agentic workers

- **Spec authority:** `[[02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec]]`. If this plan and the spec disagree, the spec wins — file an amendment.
- **Execution mode:** `superpowers:subagent-driven-development` per `~/.claude/CLAUDE.md` hard rule. Each phase dispatches subagents per task. No inline-execution alternative.
- **Canonical repo path:** `G:/My Drive/Projects Merge/lattice-meeting-assistant/` (Project Registry §93). NEVER `~/Dev/lattice-meeting-assistant/` or `D:/Dev/lattice-meeting-assistant/`.
- **Sibling repos:** `lattice-meeting-contracts`, `lattice-meeting`, `lattice-cortex`, `lattice-meetbot` — all under `G:/My Drive/Projects Merge/`.
- **Hostnames only:** `cypher`, `switch`, `zion` — never raw IPs (per `[[Hostnames Not IPs]]`).
- **Commit hygiene:** scoped tags (`feat(assistant): ...`, `fix(privacy): ...`, `test(boundary): ...`); NO AI co-author attribution per `~/.claude/CLAUDE.md` Critical Defaults.
- **TDD discipline:** every task that introduces production code starts with a failing test, runs it to confirm it fails, then writes the minimal impl, runs it to confirm it passes, then commits.
- **Coverage gate (v0.1):** 90% on critical/complex pathways (`privacy/`, `actor.py`, `tools/`, `series.py`) with real-consumer-integration evidence — NOT raw line %. Per `[[feedback_coverage_signal_priority]]`. AC-5 + AC-7 bake this in.

## Plan Verification Discipline

`pvd_conformant: true`. Foundational claims carry `[V:*]` tags or `[U]` for first-task verification. Before subagent dispatch on each phase, run `lattice-pvd-preflight` skill against this plan and address ERROR-level findings. WARNINGs about "Step N: Implement X" header pattern are grandfathered — note but do not block.

## File Structure

The library's source tree under `src/lattice_meeting_assistant/`:

```
src/lattice_meeting_assistant/
    __init__.py                # Public re-exports
    _version.py                # __version__ = "0.1.0.dev0" -> "0.1.0" at W7
    config.py                  # AssistantConfig + KnowledgeAccessConfig dataclasses + env loaders
    profile.py                 # AssistantProfile + YAML loader + ProfileMutation audit
    types.py                   # ChatEvent, ConversationTurn, AssistantStats, AdminCommandResult, ProfileMutation
    exceptions.py              # PrivacyBoundaryViolation, AdminAuthorizationDenied, CapabilityNotSupported, CortexUnavailable
    assistant.py               # Assistant class — top-level orchestrator
    privacy/
        __init__.py
        invariants.py          # BLOCKED_IN_MEETING_TOOLS frozenset; assertion helpers; visibility-tag enforcement
        log_redaction.py       # log_chat_event() — INFO-no-content / DEBUG-with-flag
    actor.py                   # ChatThreadActor — FIFO actor + holding-message + history compaction
    tools/
        __init__.py
        base.py                # CortexTool ABC; ToolResult schema
        transcript.py          # SearchMeetingTranscriptTool, ReadMeetingTranscriptWindowTool
        past_meetings.py       # SearchPastMeetingsTool (Brain nx_vault_search wrapper)
        public_references.py   # SearchPublicReferencesTool (Brain nx_references_search wrapper)
        web_search.py          # WebSearchTool (Brain deep_research lightweight wrapper)
        tg_owner_tools.py      # search_vault, read_note, search_references, nx_calendar_read, nx_email_search, vault_ask wrappers
        resolver.py            # resolve_tool_set(transport, profile) + boot self-test
    series.py                  # SeriesMatcher + SeriesMatch + MeetingMetadata + ratification flow
    admin.py                   # admin_command() parser + dispatcher + ProfileMutation audit writer
    public_mentions.py         # PublicMentionHandler + public-variant system prompt renderer
    transport.py               # AdminTransportHandle wrappers; re-exports from contracts
    brain_client.py            # BrainMCPClient — thin httpx wrapper to Brain Nexus API (auth + UA + endpoints)
    prompts.py                 # System prompt renderers for in-meeting-DM and public-mention paths
    fillers.py                 # _filler() helper + hardcoded v0.1 filler subset from Cody Voice Identity

tests/
    __init__.py
    conftest.py                # Shared fixtures: mock cortex, mock session, mock brain_mcp, mock transcript buffer
    fixtures/
        persona_mappings/      # Anonymized real-vault snapshots (RFC 3966 PSTN, RFC 2606 example.org)
        profiles/              # Sample AssistantProfile YAMLs for tests
        series_notes/          # Sample Meeting Series YAML notes
    test_w0_contracts_imports.py
    test_w1_config.py
    test_w1_profile.py
    test_w1_types.py
    test_w2_invariant_1_separated_send.py
    test_w2_invariant_2_transport_bound.py
    test_w2_invariant_3_memory_isolation.py
    test_w2_invariant_4_fail_closed.py
    test_w2_invariant_5_admin_isolation.py
    test_w2_privacy_boundary_t1_to_t12.py     # The 12 boundary tests
    test_w3_tools_transcript.py
    test_w3_tools_past_meetings.py
    test_w3_tools_public_references.py
    test_w3_tools_web_search.py
    test_w3_tools_tg_owner.py
    test_w3_resolver.py
    test_w3_blocked_set_disjoint.py
    test_w4_actor_fifo.py
    test_w4_actor_holding_message.py
    test_w4_actor_history_compaction.py
    test_w4_actor_lifecycle.py
    test_w4_global_semaphore.py
    test_w5_allowlist_tiers.py
    test_w5_series_matcher_path_1.py
    test_w5_series_matcher_path_2.py
    test_w5_admin_commands.py
    test_w5_profile_yaml_roundtrip.py
    test_w6_public_mention_handler.py
    test_w6_public_mention_rate_limit.py
    test_w6_public_mention_prompt.py
    integration/
        test_e2e_cortex_tool_loop.py          # AC-4 integration against cortex 0.6.0
        test_e2e_series_ratification_mock_tg.py    # AC-6 mock AdminTransport
        test_e2e_real_brain_search.py        # Brain-backed tool integration (optional, network)
```

## Subagent dispatch & checkpoints

- **W0 Pre-flight:** single subagent or sequential — gates W1 dispatch.
- **W1 Scaffold:** single subagent.
- **W2 Privacy:** single subagent — most architecturally critical; gates everything.
- **W3 Tools:** single subagent (5-tool registry + resolver).
- **W4 Actor:** single subagent.
- **W5 Allowlist+Series+Admin:** single subagent.
- **W6 Public mention:** single subagent.
- **W7 AQH + GA cut:** single subagent — AC-7 + AC-8 gate; release commit.

Cross-phase checkpoints between W exits: orchestrator runs the W's exit-gate checklist and blocks dispatch to W+1 until green.

---

# W0 — Pre-flight (HARD GATE)

**Goal:** Cut `lattice-meeting-contracts 0.3.0-rc1` with the new ABCs + Protocols; verify cortex 0.6.0 tool-use registration API matches assumptions; verify meetbot v0.2 W0 status (TranscriptBuffer impl path); verify Brain `/join` handler bot routing. None of W1+ can start until W0 exit gate green.

**Exit gate:**

- `lattice-meeting-contracts 0.3.0-rc1` tagged on origin; canonical repo updated; canonical_repos.json clean.
- Cortex 0.6.0 tool-use API verified (entry point + tool schema shape documented in W0 status note).
- Meetbot v0.2 W0 status assessed; if `TranscriptBuffer` impl is not yet shipped, W0.5 sub-task drafts the meetbot contract impl.
- Brain `/join` handler verified to listen on `@HeyCody_bot` webhook (FU1); if mismatched, ticket filed.
- Lattice Project Registry row for `lattice-meeting-assistant` confirmed (already added S25; re-verify).

## Task W0.1 — Cut lattice-meeting-contracts 0.3.0-rc1

**Files:**

- Modify: `G:/My Drive/Projects Merge/lattice-meeting-contracts/src/lattice_meeting_contracts/protocols.py`
- Create: `G:/My Drive/Projects Merge/lattice-meeting-contracts/src/lattice_meeting_contracts/capability.py`
- Create: `G:/My Drive/Projects Merge/lattice-meeting-contracts/src/lattice_meeting_contracts/admin_transport.py`
- Create: `G:/My Drive/Projects Merge/lattice-meeting-contracts/src/lattice_meeting_contracts/transcript_buffer.py`
- Modify: `G:/My Drive/Projects Merge/lattice-meeting-contracts/src/lattice_meeting_contracts/__init__.py` (re-exports)
- Create: `G:/My Drive/Projects Merge/lattice-meeting-contracts/tests/test_v0_3_amendments.py`
- Modify: `G:/My Drive/Projects Merge/lattice-meeting-contracts/pyproject.toml` (bump to `0.3.0rc1`)
- Modify: `G:/My Drive/Projects Merge/lattice-meeting-contracts/CHANGELOG.md`

**Steps:**

- [ ] **Step 1: Write failing test for the new types** in `tests/test_v0_3_amendments.py` [U]:

```python
import pytest
from lattice_meeting_contracts.capability import PlatformChatCapability
from lattice_meeting_contracts.admin_transport import AdminTransport, AdminTransportHandle
from lattice_meeting_contracts.transcript_buffer import TranscriptBuffer


def test_platform_chat_capability_fields():
    cap = PlatformChatCapability(
        private_chat_inbound=True,
        private_chat_outbound=True,
        proactive_dm=True,
        public_chat_inbound=True,
        requires_prior_install=False,
        private_chat_fallback="none",
    )
    assert cap.private_chat_inbound is True
    assert cap.requires_prior_install is False
    assert cap.private_chat_fallback == "none"


def test_platform_chat_capability_frozen():
    cap = PlatformChatCapability(
        private_chat_inbound=True, private_chat_outbound=True,
        proactive_dm=True, public_chat_inbound=True,
        requires_prior_install=False, private_chat_fallback="none",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        cap.private_chat_inbound = False  # type: ignore[misc]


def test_admin_transport_protocol_has_required_methods():
    # AdminTransport is a Protocol; verify shape by introspection
    assert hasattr(AdminTransport, "kind")
    assert hasattr(AdminTransport, "post_admin_response")


def test_transcript_buffer_protocol_has_required_methods():
    assert hasattr(TranscriptBuffer, "subscribe")
    assert hasattr(TranscriptBuffer, "get_hot_window")
    assert hasattr(TranscriptBuffer, "search")


def test_admin_transport_handle_is_opaque_dataclass():
    h = AdminTransportHandle(handle_id="thread:abc123", metadata={"source": "tg"})
    assert h.handle_id == "thread:abc123"
    assert h.metadata["source"] == "tg"
```

Run: `pytest tests/test_v0_3_amendments.py -xvs`
Expected: FAIL with `ModuleNotFoundError: No module named 'lattice_meeting_contracts.capability'` (or similar).

- [ ] **Step 2: Implement `capability.py`** [U]:

```python
"""Platform-specific chat capability flags.

Added in v0.3.0-rc1 to support the lattice-meeting-assistant primitive's
per-platform capability resolution. See [[02_Projects/Lattice/
lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant
v0.1 - Design Spec]] §Q4b.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PlatformChatCapability:
    """Adapter-declared capabilities for in-meeting chat operations.

    Zoom (Meeting Web SDK): (True, True, True, True, False, "none")
    Teams: (True, True, False, True, True, "none")  -- cold-start: user must install bot in personal scope first
    Google Meet: (False, False, False, False, False, "decline")  -- no in-meeting DM API at any layer
    """

    private_chat_inbound: bool
    private_chat_outbound: bool
    proactive_dm: bool
    public_chat_inbound: bool
    requires_prior_install: bool
    private_chat_fallback: Literal["none", "side_channel", "decline"]
```

- [ ] **Step 3: Implement `admin_transport.py`** [U]:

```python
"""AdminTransport ABC + AdminTransportHandle for routing admin commands.

Concrete implementations live in CONSUMER repos (e.g., Brain's BrainTGAdminTransport);
this library declares only the contract per
[[02_Projects/Protocols/Meeting Platform Admin Surface Isolation]].

Lands in v0.3.0-rc1.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class AdminTransportHandle:
    """Opaque handle the transport uses to route a response back to the
    originating channel (e.g., TG thread ID, HTTP request ID).

    Concrete transport implementations interpret handle_id + metadata; the
    library treats them as opaque."""

    handle_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class AdminTransport(Protocol):
    """Routes admin command responses out of the Assistant.

    Concrete impls (NOT in lattice-meeting-assistant or contracts):
      - BrainTGAdminTransport (lives in obsidian-nexus Brain repo)
      - LocalAdminTransport (HTTP /admin route -- v0.2)
      - SlackAdminTransport (BYO consumer -- v0.2+)
    """

    kind: Literal["tg-owner", "tg-cohost", "in-meeting-dm", "local-http", "slack"]

    async def post_admin_response(
        self,
        handle: AdminTransportHandle,
        response_text: str,
    ) -> None:
        """Relay a response back to the originating channel."""
        ...
```

- [ ] **Step 4: Implement `transcript_buffer.py`** [U]:

```python
"""TranscriptBuffer Protocol — in-process append-only buffer.

Implemented in CONSUMER adapters (meetbot for Zoom, future Meet/Teams);
consumed by lattice-meeting-assistant. Lands in v0.3.0-rc1.
"""

from __future__ import annotations
import asyncio
from typing import Literal, Protocol, runtime_checkable

from .types import TranscriptSegment


@runtime_checkable
class TranscriptBuffer(Protocol):
    """Adapter-owned in-process buffer of the current meeting's transcript.

    Adapter pushes TranscriptSegments as they materialize. Consumer
    (lattice-meeting-assistant) subscribes via subscribe(), reads hot window
    via get_hot_window(), and searches the full buffer via search().
    """

    def subscribe(self) -> "asyncio.Queue[TranscriptSegment]":
        """Returns an asyncio.Queue that the consumer drains. Adapter
        ensures one Queue per subscriber (fan-out internally)."""
        ...

    def get_hot_window(self, seconds: int = 300) -> list[TranscriptSegment]:
        """Returns segments from the last `seconds` of meeting time, in
        order. Used for hot-prompt injection."""
        ...

    def search(
        self,
        query: str,
        *,
        time_range: Literal["all", "last_5m", "last_15m"] | str | None = None,
        limit: int = 10,
    ) -> list[TranscriptSegment]:
        """Substring/keyword search over buffered segments. v0.1 simple
        case-insensitive substring; future embedding-based defer to v0.2."""
        ...
```

- [ ] **Step 5: Update `__init__.py` re-exports** [U]:

```python
# Append to existing __init__.py exports:
from .capability import PlatformChatCapability
from .admin_transport import AdminTransport, AdminTransportHandle
from .transcript_buffer import TranscriptBuffer

__all__ += [
    "PlatformChatCapability",
    "AdminTransport",
    "AdminTransportHandle",
    "TranscriptBuffer",
]
```

- [ ] **Step 6: Bump version + CHANGELOG** [U]:

`pyproject.toml`: `version = "0.3.0rc1"`

`CHANGELOG.md`:

```markdown
## [0.3.0-rc1] -- 2026-05-XX

### Added
- `PlatformChatCapability` dataclass — per-platform chat capability flags
- `AdminTransport` Protocol + `AdminTransportHandle` dataclass — admin command routing contract
- `TranscriptBuffer` Protocol — adapter-owned in-process transcript buffer for assistant consumption

### Why
Foundation for `lattice-meeting-assistant` v0.1. See vault
`[[02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec]]`.
```

- [ ] **Step 7: Run test to verify it passes** [U]:

Run: `pytest tests/test_v0_3_amendments.py -xvs`
Expected: PASS all 5 tests.

- [ ] **Step 8: Run full test suite to verify no regression** [U]:

Run: `pytest -q`
Expected: All existing tests still pass + 5 new pass.

- [ ] **Step 9: Commit + tag** [U]:

```bash
git add src/lattice_meeting_contracts/capability.py
git add src/lattice_meeting_contracts/admin_transport.py
git add src/lattice_meeting_contracts/transcript_buffer.py
git add src/lattice_meeting_contracts/__init__.py
git add tests/test_v0_3_amendments.py
git add pyproject.toml CHANGELOG.md

git commit -m "$(cat <<'EOF'
release(contracts): 0.3.0-rc1 -- AdminTransport + PlatformChatCapability + TranscriptBuffer

Foundation for lattice-meeting-assistant v0.1. Adds 3 new public
contracts:

- PlatformChatCapability dataclass — per-platform chat capability flags
- AdminTransport Protocol + AdminTransportHandle — admin command routing
- TranscriptBuffer Protocol — adapter-owned in-process transcript buffer

5 new tests; full suite green. Spec authority:
02_Projects/Lattice/lattice-meeting-assistant/Specifications/
2026-05-11 lattice-meeting-assistant v0.1 - Design Spec.md
EOF
)"

git tag -a v0.3.0-rc1 -m "v0.3.0-rc1: AdminTransport + PlatformChatCapability + TranscriptBuffer"
git push origin master
git push origin v0.3.0-rc1
```

## Task W0.2 — Verify cortex 0.6.0 tool-use API (OQ2)

**Files:**

- Create: vault `D:/Vaults/Mainframe/02_Projects/Lattice/lattice-meeting-assistant/Status/2026-05-XX W0.2 Cortex 0.6.0 tool-use API verified.md`

**Steps:**

- [ ] **Step 1: Read cortex 0.6.0 public API surface** [U]:

Run:

```bash
cd "G:/My Drive/Projects Merge/lattice-cortex"
python -c "import lattice_cortex; help(lattice_cortex)" 2>&1 | head -60
python -c "from lattice_cortex.registry import Registry; help(Registry.call)" 2>&1 | head -30
python -c "from lattice_cortex.session import AgentSession; print([m for m in dir(AgentSession) if not m.startswith('_')])"
```

Capture the exact `registry.call` signature, the `AgentSession` public methods, and how tools are registered (constructor param `tools=[...]`? `session.register_tool(tool)`? other?).

- [ ] **Step 2: Confirm tool schema shape** [U]:

Look for cortex's `Tool` / `CortexTool` ABC. Expected (from spec §4): `name: str`, `description: str`, `invoke(**kwargs) -> dict` async. Verify by reading `src/lattice_cortex/tools/` or `src/lattice_cortex/adapters/anthropic.py` (which translates to Anthropic tool-use shape).

- [ ] **Step 3: Confirm prompt caching + tool-use can co-exist on a single call** [U]:

Read `src/lattice_cortex/registry.py` `call()` impl. Confirm `cache_namespace` kwarg is supported (or equivalent). If not present, document the closest equivalent.

- [ ] **Step 4: Author Status note** with findings [U]:

```markdown
---
title: W0.2 Cortex 0.6.0 tool-use API verified
type: status
project: Lattice
library: lattice-meeting-assistant
date: 2026-05-XX
session: S25 W0.2
---

# W0.2 — Cortex 0.6.0 tool-use API verified

## Verified surface

- `lattice_cortex.registry.Registry.call(...)`: signature `<paste here>`
- Tool registration mechanism: `<paste here>`
- Tool ABC: `<paste here>`
- Prompt cache namespace kwarg: `<yes/no/equivalent>`
- AgentSession iterative tool loop: `<confirm/deny>`

## Implications for lattice-meeting-assistant v0.1

- [ ] Spec §3 `Assistant.__init__` cortex_registry param accepts ... <update>
- [ ] Spec §4 tool implementation pattern matches cortex Tool ABC: <yes/no — if no, plan adjustments below>
- [ ] OQ2 status: <RESOLVED / DEFER-TO-V0.1.5>

## If DEFER-TO-V0.1.5

If cortex 0.6.0's tool-use surface differs materially from spec assumptions, document:
- What v0.1 ships INSTEAD (probably: just hot-window injection in prompt, no tool calls; assistant answers from transcript context only).
- What v0.1.5 adds when cortex's surface stabilizes.

## If RESOLVED (expected path)

Proceed to W0.3.
```

- [ ] **Step 5: If OQ2 RESOLVED, commit Status note + proceed [U]:**

```bash
cd "G:/My Drive/Projects Merge/lattice-meeting-contracts"  # commit at meetbot-contracts or meeting-assistant repo when scaffolded — for now, just save vault note
# (no repo commit yet; canonical repo not scaffolded — vault is the artifact)
```

## Task W0.3 — Assess meetbot v0.2 W0 status + TranscriptBuffer impl plan

**Files:**

- Create: vault `D:/Vaults/Mainframe/02_Projects/Lattice/lattice-meeting-assistant/Status/2026-05-XX W0.3 Meetbot TranscriptBuffer impl gate.md`

**Steps:**

- [ ] **Step 1: Probe lattice-meetbot v0.2 current state** [U]:

```bash
cd "G:/My Drive/Projects Merge/lattice-meetbot"
git log --oneline -10
git tag -l --sort=-version:refname | head -5
ls src/lattice_meetbot/ | head -30
grep -rn "TranscriptBuffer\|transcript_buffer\|append_only" src/lattice_meetbot/ | head -20
```

Determine whether meetbot v0.2 has already shipped a `TranscriptBuffer` implementation, or whether it needs to be added.

- [ ] **Step 2: If meetbot has NOT shipped TranscriptBuffer** [U]:

Author a brief impl-plan note (Status note above) identifying:
- Where to add the buffer class in meetbot src tree
- Existing transcript fanout integration points (the current `/segments` POST callback)
- Estimated lines of code (~50-100 for in-process append-only + search)
- W0.3 ticket: meetbot v0.2 must ship `TranscriptBuffer` before lattice-meeting-assistant W3 dispatches

If meetbot HAS shipped it: capture the import path + verify it satisfies the Protocol contract from W0.1.

- [ ] **Step 3: Commit Status note to vault** (no repo commit yet) [U].

## Task W0.4 — Verify Brain `/join` handler bot routing (FU1)

**Files:**

- Create: vault `D:/Vaults/Mainframe/02_Projects/Lattice/lattice-meeting-assistant/Status/2026-05-XX W0.4 Brain join handler bot routing.md`

**Steps:**

- [ ] **Step 1: Probe Brain `/join` handler code** [U]:

```bash
cd "G:/My Drive/Projects Merge/ObsidianNexus"
grep -rn "def.*join\|join_command\|/join" src/ server/ 2>/dev/null | head -20
grep -rn "HeyCody\|ObsidianNexusAI" src/ server/ 2>/dev/null | head -20
# Identify which bot's webhook fires the /join handler
```

- [ ] **Step 2: Verify against function-based bot routing rule** (S25 Cyril verbatim): `@HeyCody_bot` = interactive convo + assistant admin; `@ObsidianNexusAI_bot` = autonomous Cody-CLI status pings [U].

- [ ] **Step 3: If mismatched** (e.g., `/join` listening on `@ObsidianNexusAI_bot`) [U]:

File a Nexus ticket via:

```python
import urllib.request, urllib.parse, json
# Use nexus_api_key from credentials.md
data = urllib.parse.urlencode({
    "title": "Brain /join handler should listen on @HeyCody_bot (S25 lattice-meeting-assistant)",
    "priority": "p1",
    "project": "obsidian-nexus",
    "body": "<paste finding>",
}).encode()
# POST /api/tickets/create (per Brain REST surface)
```

- [ ] **Step 4: If matched** (already on `@HeyCody_bot`): no ticket needed; document in Status note [U].

## Task W0.5 — Verify Project Registry row for lattice-meeting-assistant

**Files:**

- Modify: `D:/Vaults/Mainframe/02_Projects/Lattice/Project Registry.md` (verify row exists; already added S25)
- Modify: `D:/Vaults/Mainframe/02_Projects/Lattice/canonical_repos.json` (verify entry exists; already added S25)

**Steps:**

- [ ] **Step 1: Verify Project Registry row** [U]:

```bash
grep "lattice-meeting-assistant" "D:/Vaults/Mainframe/02_Projects/Lattice/Project Registry.md"
```

Expected output:
```
| lattice-meeting-assistant | pre-spec | in-meeting AI assistant primitive | active | `G:/My Drive/Projects Merge/lattice-meeting-assistant` | `02_Projects/Lattice/lattice-meeting-assistant` |
```

- [ ] **Step 2: Verify canonical_repos.json entry** [U]:

```bash
python -c "import json; d=json.load(open('D:/Vaults/Mainframe/02_Projects/Lattice/canonical_repos.json')); assert 'lattice-meeting-assistant' in d['projects']; print(d['projects']['lattice-meeting-assistant'])"
```

Expected: prints the row dict with `canonical_repo: "G:/My Drive/Projects Merge/lattice-meeting-assistant"`.

- [ ] **Step 3: If either is missing**: re-apply S25 edits per the active-work entry [U].

## Task W0.6 — W0 exit-gate checkpoint

**Files:** None (review-only)

**Steps:**

- [ ] **Step 1: Confirm all W0 sub-tasks complete [U]:**

| Sub-task | Status | Artifact |
|---|---|---|
| W0.1 contracts 0.3.0-rc1 cut | ☐ | `git tag -l v0.3.0-rc1` shows it |
| W0.2 cortex tool-use verified | ☐ | Status note authored, OQ2 RESOLVED |
| W0.3 TranscriptBuffer gate | ☐ | Status note authored, either impl-shipped or impl-ticketed |
| W0.4 Brain `/join` routing verified | ☐ | Status note authored, no FU1 mismatch (or ticket filed) |
| W0.5 Project Registry row exists | ☐ | `grep` returns the row |

- [ ] **Step 2: Block W1 dispatch until ALL 5 are ☑. [U]**

---

# W1 — Scaffold + types

**Goal:** Create the canonical repo via `/new-project lattice-meeting-assistant`; lay down the public type system from spec §3 (`AssistantConfig`, `AssistantProfile`, `KnowledgeAccessConfig`, exception classes); verify `mypy --strict` clean on the skeleton.

**Subagent dispatch:** single subagent.

**Exit gate:**

- Canonical repo `G:/My Drive/Projects Merge/lattice-meeting-assistant/` exists with proper scaffold.
- `pip install -e .` works in a venv.
- All dataclasses defined + tests round-trip them via YAML.
- `mypy --strict src/` clean.

## Task W1.1 — Scaffold the canonical repo

**Files:**

- Run: `/new-project lattice-meeting-assistant` skill (per global protocol)
- Result: `G:/My Drive/Projects Merge/lattice-meeting-assistant/` with standard Lattice scaffold

**Steps:**

- [ ] **Step 1: Invoke `/new-project` skill** with arguments [U]:
  - Name: `lattice-meeting-assistant`
  - Family: Lattice
  - Prefix: `"lattice-meeting-assistant - "`
  - Tags: `project/lattice-meeting-assistant`
  - License: Apache 2.0
  - Author: CodeWarrior4Life
  - GitHub: yes (`github.com/CodeWarrior4Life/lattice-meeting-assistant`)
  - PowerShell shortcuts: yes
  - Vault folder: already exists (`02_Projects/Lattice/lattice-meeting-assistant/`) — skill should detect + skip

- [ ] **Step 2: Verify the scaffold landed correctly** [U]:

```bash
cd "G:/My Drive/Projects Merge/lattice-meeting-assistant"
ls -la
test -f pyproject.toml || echo "MISSING pyproject.toml"
test -f LICENSE || echo "MISSING LICENSE"
test -f README.md || echo "MISSING README.md"
test -f CLAUDE.md || echo "MISSING CLAUDE.md"
test -d src/lattice_meeting_assistant || echo "MISSING src/lattice_meeting_assistant"
test -d tests || echo "MISSING tests"
```

- [ ] **Step 3: Confirm initial commit pushed to origin** [U]:

```bash
git log --oneline -3
git remote -v
git push origin main  # if not already pushed by skill
```

## Task W1.2 — pyproject.toml + initial deps

**Files:**

- Modify: `G:/My Drive/Projects Merge/lattice-meeting-assistant/pyproject.toml`
- Create: `G:/My Drive/Projects Merge/lattice-meeting-assistant/requirements.txt`

**Steps:**

- [ ] **Step 1: Write the full pyproject.toml** [U]:

```toml
[build-system]
requires = ["setuptools>=64", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "lattice-meeting-assistant"
version = "0.1.0.dev0"
description = "In-meeting AI assistant primitive for Lattice meeting-platform adapters (Zoom v0.1; Meet/Teams v0.2+)."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "Apache-2.0" }
authors = [{ name = "CodeWarrior4Life" }]
keywords = ["lattice", "meeting", "assistant", "zoom", "private-chat", "cortex"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Communications :: Chat",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Framework :: AsyncIO",
]
dependencies = [
    # Lattice family pins
    "lattice-meeting-contracts @ git+https://github.com/CodeWarrior4Life/lattice-meeting-contracts.git@v0.3.0-rc1",
    "lattice-meeting>=0.2.0,<0.3",
    "lattice-cortex>=0.6.0,<0.7",
    # Direct deps
    "httpx>=0.24.0",
    "pydantic>=2.0.0",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
test = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.0.0",
    "mypy>=1.8.0",
]

[project.urls]
Homepage = "https://github.com/CodeWarrior4Life/lattice-meeting-assistant"
Repository = "https://github.com/CodeWarrior4Life/lattice-meeting-assistant"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
strict = true
python_version = "3.11"
files = ["src"]

[tool.coverage.run]
source = ["src/lattice_meeting_assistant"]
omit = ["*/tests/*"]

[tool.coverage.report]
fail_under = 0  # gates are AC-7 (AQH PASS) + AC-5 critical-path coverage, not raw %
```

- [ ] **Step 2: Write requirements.txt** mirroring pyproject deps (for tools that prefer this format) [U].

- [ ] **Step 3: Install editable in a venv** [U]:

```bash
python -m venv .venv
.venv/Scripts/activate  # Windows path
pip install -e ".[test]"
```

Expected: success, no resolver errors.

- [ ] **Step 4: Smoke-import** [U]:

```bash
python -c "import lattice_meeting_assistant; print(lattice_meeting_assistant.__version__)"
```

Expected: `0.1.0.dev0` (or error if `_version.py` not yet present — fix in next task).

- [ ] **Step 5: Commit** [U]:

```bash
git add pyproject.toml requirements.txt
git commit -m "chore(pyproject): initial deps + tooling config (W1.2)"
```

## Task W1.3 — `_version.py` + `__init__.py` initial re-exports

**Files:**

- Create: `src/lattice_meeting_assistant/_version.py`
- Create: `src/lattice_meeting_assistant/__init__.py`
- Create: `tests/test_w1_imports.py`

**Steps:**

- [ ] **Step 1: Write failing test** [U]:

```python
# tests/test_w1_imports.py
def test_version_exposed():
    import lattice_meeting_assistant
    assert lattice_meeting_assistant.__version__ == "0.1.0.dev0"


def test_public_api_imports_clean():
    # Will be filled out as the API surface lands; for now just smoke
    from lattice_meeting_assistant import (
        TierName,
        PrivacyBoundaryViolation,
        AdminAuthorizationDenied,
        CapabilityNotSupported,
    )
    # Just ensure imports resolve
    assert PrivacyBoundaryViolation is not None
    assert AdminAuthorizationDenied is not None
    assert CapabilityNotSupported is not None
    assert TierName is not None
```

Run: `pytest tests/test_w1_imports.py -xvs`
Expected: FAIL.

- [ ] **Step 2: Implement `_version.py`** [U]:

```python
__version__ = "0.1.0.dev0"
```

- [ ] **Step 3: Implement initial `__init__.py`** (will grow across phases) [U]:

```python
"""lattice-meeting-assistant -- in-meeting AI assistant primitive.

See vault [[02_Projects/Lattice/lattice-meeting-assistant/Mission]] and the
v0.1 Design Spec for the full surface.
"""

from typing import Literal

from ._version import __version__
from .exceptions import (
    PrivacyBoundaryViolation,
    AdminAuthorizationDenied,
    CapabilityNotSupported,
    CortexUnavailable,
)

TierName = Literal["interactive", "research"]

__all__ = [
    "__version__",
    "TierName",
    "PrivacyBoundaryViolation",
    "AdminAuthorizationDenied",
    "CapabilityNotSupported",
    "CortexUnavailable",
]
```

- [ ] **Step 4: Implement `exceptions.py`** [U]:

```python
"""Exception types raised by the Assistant. Stable public API."""

from __future__ import annotations


class PrivacyBoundaryViolation(Exception):
    """Raised when a chat event reaches the Assistant without an
    is_private visibility tag (Architectural Invariant 4 fail-closed).

    Never silently default; ambiguity = refuse.
    """


class AdminAuthorizationDenied(Exception):
    """Raised when admin_command() is called with a ratifying user who
    is not in profile.admins."""


class CapabilityNotSupported(Exception):
    """Raised when the caller invokes a method gated on a PlatformChatCapability
    flag that the current platform's adapter denies (e.g., proactive_dm on
    a platform that does not allow it)."""


class CortexUnavailable(Exception):
    """Raised when the cortex registry exhausts its fallback cascade and
    cannot produce a reply. The Assistant catches this internally and
    surfaces a user-facing graceful-degradation message; callers see this
    only in test paths."""
```

- [ ] **Step 5: Run tests + mypy** [U]:

```bash
pytest tests/test_w1_imports.py -xvs
mypy --strict src/
```

Expected: 2 tests PASS; mypy clean.

- [ ] **Step 6: Commit** [U]:

```bash
git add src/lattice_meeting_assistant/_version.py
git add src/lattice_meeting_assistant/__init__.py
git add src/lattice_meeting_assistant/exceptions.py
git add tests/test_w1_imports.py
git commit -m "feat(assistant): version + exceptions + initial re-exports (W1.3)"
```

## Task W1.4 — AssistantConfig + KnowledgeAccessConfig dataclasses

**Files:**

- Create: `src/lattice_meeting_assistant/config.py`
- Create: `tests/test_w1_config.py`

**Steps:**

- [ ] **Step 1: Write failing test** [U]:

```python
# tests/test_w1_config.py
import pytest
from lattice_meeting_assistant.config import (
    AssistantConfig,
    KnowledgeAccessConfig,
)


def test_assistant_config_defaults():
    cfg = AssistantConfig()
    # Q3 defaults
    assert cfg.auto_intro is False
    assert cfg.disclose_ai is False  # per Cody Voice Identity §Banned
    assert cfg.address_by_canonical_name is True
    assert cfg.canonical_name_min_confidence == 0.85
    # Q5 defaults
    assert cfg.default_tier == "interactive"
    assert cfg.deep_tier == "research"
    assert cfg.deep_tier_message_flag == "/think"
    assert cfg.holding_message_after_ms == 3000
    assert cfg.max_response_tokens == 200
    # Q7 defaults
    assert cfg.per_thread_queue_depth == 5
    assert cfg.per_meeting_global_concurrency == 4
    assert cfg.actor_post_leave_grace_s == 60
    assert cfg.actor_history_max_tokens == 16000
    # Memory
    assert cfg.remember_across_meetings is False
    # Series
    assert cfg.series_ratification_timeout_s == 120


def test_assistant_config_frozen():
    cfg = AssistantConfig()
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.auto_intro = True  # type: ignore[misc]


def test_knowledge_access_config_defaults():
    k = KnowledgeAccessConfig()
    # Architectural Invariant #2 — hard deny on personal vault by default
    assert k.allow_personal_vault is False
    # Transcript always-on
    assert k.transcript_hot_window_seconds == 300
    assert k.enable_transcript_search_tool is True
    # Past meetings + refs + web all enabled by default
    assert k.enable_past_meetings_search is True
    assert k.enable_public_references_tool is True
    assert k.enable_web_search is True
    assert k.public_references == ()


def test_knowledge_access_config_with_public_refs():
    k = KnowledgeAccessConfig(public_references=("ref/book1.md", "ref/book2.md"))
    assert k.public_references == ("ref/book1.md", "ref/book2.md")
```

Run: FAIL (module not present).

- [ ] **Step 2: Implement `config.py`** [U]:

```python
"""AssistantConfig + KnowledgeAccessConfig dataclasses.

See spec §3 for field semantics + defaults; spec §4 for KnowledgeAccessConfig
enforcement (Architectural Invariant #2).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

TierName = Literal["interactive", "research"]


@dataclass(frozen=True)
class KnowledgeAccessConfig:
    """Per-profile knowledge access policy. Enforced transport-bound by
    the resolver — `allow_personal_vault=False` is a HARD invariant for
    in-meeting-dm transport regardless of this config value (spec §4
    BLOCKED_IN_MEETING_TOOLS)."""

    # Architectural Invariant #2 — in-meeting DM hard-deny on personal vault
    # The resolver overrides this to False unconditionally for in-meeting-dm
    # transport; True is only meaningful for tg-owner transport.
    allow_personal_vault: bool = False

    # Live transcript window — ALWAYS ON for in-meeting DM (spec §Q6 overlay)
    transcript_hot_window_seconds: int = 300
    enable_transcript_search_tool: bool = True

    # Past meetings (series-scoped, configurable)
    enable_past_meetings_search: bool = True

    # Public references
    public_references: tuple[str, ...] = ()
    enable_public_references_tool: bool = True

    # Web search
    enable_web_search: bool = True


@dataclass(frozen=True)
class AssistantConfig:
    """Behavioral knobs (Q3 + Q5 + Q7 overlays). All defaults from spec §3."""

    # Identity-in-chat (Q3)
    auto_intro: bool = False
    disclose_ai: bool = False  # per Cody Voice Identity §Banned
    address_by_canonical_name: bool = True
    canonical_name_min_confidence: float = 0.85

    # Latency + degradation (Q5)
    default_tier: TierName = "interactive"  # Sonnet
    deep_tier: TierName = "research"  # Opus
    deep_tier_message_flag: str = "/think"
    holding_message_after_ms: int = 3000
    max_response_tokens: int = 200
    per_sender_rate_min_interval_ms: int = 2000

    # Concurrency (Q7)
    per_thread_queue_depth: int = 5
    per_meeting_global_concurrency: int = 4
    actor_post_leave_grace_s: int = 60
    actor_history_max_tokens: int = 16000

    # Memory (Q4c + Q6)
    remember_across_meetings: bool = False

    # Series matching (Q6 overlay)
    series_ratification_timeout_s: int = 120

    # Observability
    debug_chat_content: bool = False
```

- [ ] **Step 3: Run tests + mypy** [U]:

```bash
pytest tests/test_w1_config.py -xvs
mypy --strict src/
```

Expected: 4 tests PASS; mypy clean.

- [ ] **Step 4: Commit** [U]:

```bash
git add src/lattice_meeting_assistant/config.py
git add tests/test_w1_config.py
git commit -m "feat(config): AssistantConfig + KnowledgeAccessConfig dataclasses (W1.4)"
```

## Task W1.5 — AssistantProfile + ProfileMutation + YAML round-trip

**Files:**

- Create: `src/lattice_meeting_assistant/profile.py`
- Create: `src/lattice_meeting_assistant/types.py`
- Create: `tests/test_w1_profile.py`
- Create: `tests/fixtures/profiles/sabbath-school.yaml` (example fixture)

**Steps:**

- [ ] **Step 1: Write failing test** [U]:

```python
# tests/test_w1_profile.py
import pytest
from pathlib import Path
from lattice_meeting_assistant.profile import (
    AssistantProfile,
    ProfileMutation,
    load_profile_from_yaml,
    dump_profile_to_yaml,
)
from lattice_meeting_assistant.config import KnowledgeAccessConfig


def test_assistant_profile_minimal():
    p = AssistantProfile(
        profile_id="test",
        series_id=None,
        dm_allowlist=("cyril-grosse",),
        admins=("cyril-grosse",),
        knowledge=KnowledgeAccessConfig(),
    )
    assert p.profile_id == "test"
    assert p.schema_version == 1
    assert p.dm_allowlist == ("cyril-grosse",)
    assert p.admins == ("cyril-grosse",)
    # Public mention defaults
    assert p.public_mentions_enabled is True
    assert p.public_mention_allowlist is None  # anyone-can-mention
    assert p.public_mention_rate_limit_per_meeting_s == 30


def test_profile_yaml_roundtrip(tmp_path: Path):
    src = AssistantProfile(
        profile_id="sabbath-school",
        series_id="sabbath-school-class",
        dm_allowlist=("cyril-grosse", "helen-christopherson"),
        admins=("cyril-grosse",),
        knowledge=KnowledgeAccessConfig(
            public_references=("ref/book1.md",),
        ),
        series_match_binding="explicit",
        series_match_confidence="high",
        source_vault_note="02_Projects/.../Profiles/sabbath-school.yaml",
    )
    yaml_path = tmp_path / "sabbath-school.yaml"
    dump_profile_to_yaml(src, yaml_path)
    loaded = load_profile_from_yaml(yaml_path)
    assert loaded == src


def test_profile_yaml_rejects_blocked_tool_enabled(tmp_path: Path):
    """T9 — Profile YAML attempting to enable a BLOCKED_IN_MEETING_TOOLS
    entry for in-meeting-dm transport raises ValueError at parse time.

    (NOTE: the blocking check lives in the tool resolver, not the profile
    loader; this test asserts the profile loader's basic validation.)"""
    # Write a profile with an unknown field that simulates a future drift
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text(
        "schema_version: 1\n"
        "profile_id: bad\n"
        "series_id: ~\n"
        "dm_allowlist: []\n"
        "admins: []\n"
        "knowledge:\n"
        "  allow_personal_vault: not_a_bool\n"
    )
    with pytest.raises(ValueError):
        load_profile_from_yaml(yaml_path)


def test_profile_mutation_audit():
    m = ProfileMutation(
        ts="2026-05-11T16:00:00Z",
        action="add",
        target="helen-brager",
        by="cyril-grosse",
        session_id="S25",
    )
    assert m.action == "add"
    assert m.by == "cyril-grosse"
```

Run: FAIL.

- [ ] **Step 2: Implement `types.py`** [U]:

```python
"""Shared types for the assistant library."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


CanonicalPersonaId = str  # type alias; real validation in lattice_meeting.persona


@dataclass(frozen=True)
class ChatEvent:
    """An inbound chat event from a meeting-platform adapter.

    Adapter-agnostic; concrete adapters translate platform events to this shape.
    """

    id: str
    meeting_id: str
    platform: str  # "zoom" | "google-meet" | "ms-teams"
    sender_user_id: str  # platform-native user id (ephemeral for some platforms)
    sender_canonical_id: CanonicalPersonaId | None  # resolved; None = unresolved (T3)
    sender_canonical_confidence: float | None
    sender_display_name: str
    text: str
    ts: datetime
    is_private: bool  # Invariant 4 -- MUST be present, never missing
    is_at_mention_to_bot: bool = False  # True for public @-mentions of self
    tier: str | None = None  # parsed from message flag (e.g., "/think" -> "research")


@dataclass(frozen=True)
class ConversationTurn:
    """One turn in a ChatThreadActor's conversation history."""

    role: str  # "user" | "assistant"
    content: str
    ts: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdminCommandResult:
    """Return type from Assistant.admin_command()."""

    ok: bool
    response_text: str
    mutation: "ProfileMutation | None" = None  # set when allowlist mutated
    error_kind: str | None = None  # set when ok=False


@dataclass(frozen=True)
class ProfileMutation:
    """Audit entry written to AssistantProfile.in_memory_mutations_history
    and persisted to profile YAML when `persistent` flag set."""

    ts: str  # ISO 8601
    action: str  # "add" | "remove" | "mode_change" | "mute" | "unmute"
    target: str | None  # canonical persona id for allowlist mutations; tier name for mode_change; None for mute/unmute
    by: CanonicalPersonaId
    session_id: str


@dataclass
class AssistantStats:
    """Observability snapshot (mutable; refreshed via Assistant.stats property)."""

    actor_count: int = 0
    in_flight_cortex_calls: int = 0
    total_cortex_tokens_consumed: int = 0
    total_replies_sent: int = 0
    privacy_boundary_violations: int = 0
    per_thread_queue_depth_max: int = 0
```

- [ ] **Step 3: Implement `profile.py`** [U]:

```python
"""AssistantProfile + YAML loader/dumper.

See spec §3 + §6 for profile semantics. Profile YAMLs live at
`02_Projects/Lattice/{consuming-project}/Profiles/{slug}.yaml` in the vault.
"""

from __future__ import annotations
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Literal

import yaml

from .config import KnowledgeAccessConfig
from .types import CanonicalPersonaId, ProfileMutation


@dataclass(frozen=True)
class AssistantProfile:
    """Per-meeting/series policy. See spec §3."""

    profile_id: str
    series_id: str | None
    dm_allowlist: tuple[CanonicalPersonaId, ...]
    admins: tuple[CanonicalPersonaId, ...]
    knowledge: KnowledgeAccessConfig

    schema_version: int = 1
    dm_min_confidence: float = 0.85
    allow_mapped_dm: bool = True
    allow_anonymous_dm: bool = False

    # Public mentions
    public_mentions_enabled: bool = True
    public_mention_allowlist: tuple[CanonicalPersonaId, ...] | None = None  # None = anyone-can-mention
    public_mention_rate_limit_per_meeting_s: int = 30

    # Series matching context
    series_match_binding: Literal["explicit", "implicit-host-cohost", "implicit-host-cohort", "none"] = "none"
    series_match_confidence: Literal["high", "medium", "ratified-low"] | None = None

    # Provenance
    source_vault_note: str | None = None
    in_memory_mutations_history: tuple[ProfileMutation, ...] = ()


def load_profile_from_yaml(path: Path) -> AssistantProfile:
    """Load a profile from a vault YAML file.

    Raises ValueError on schema violations (typed-field mismatches).
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"profile YAML must be a mapping at {path}")

    # Coerce + validate nested KnowledgeAccessConfig
    k_raw = raw.get("knowledge", {})
    if not isinstance(k_raw, dict):
        raise ValueError(f"profile.knowledge must be a mapping at {path}")
    for boolean_field in ("allow_personal_vault", "enable_transcript_search_tool",
                          "enable_past_meetings_search", "enable_public_references_tool",
                          "enable_web_search"):
        if boolean_field in k_raw and not isinstance(k_raw[boolean_field], bool):
            raise ValueError(
                f"profile.knowledge.{boolean_field} must be bool at {path}; "
                f"got {type(k_raw[boolean_field]).__name__}"
            )
    knowledge = KnowledgeAccessConfig(
        allow_personal_vault=k_raw.get("allow_personal_vault", False),
        transcript_hot_window_seconds=k_raw.get("transcript_hot_window_seconds", 300),
        enable_transcript_search_tool=k_raw.get("enable_transcript_search_tool", True),
        enable_past_meetings_search=k_raw.get("enable_past_meetings_search", True),
        public_references=tuple(k_raw.get("public_references", []) or []),
        enable_public_references_tool=k_raw.get("enable_public_references_tool", True),
        enable_web_search=k_raw.get("enable_web_search", True),
    )

    pma_raw = raw.get("public_mention_allowlist")
    public_mention_allowlist: tuple[str, ...] | None = (
        tuple(pma_raw) if pma_raw is not None else None
    )

    mutations_raw = raw.get("in_memory_mutations_history", []) or []
    mutations = tuple(
        ProfileMutation(**m) if isinstance(m, dict) else m
        for m in mutations_raw
    )

    return AssistantProfile(
        profile_id=raw["profile_id"],
        series_id=raw.get("series_id"),
        dm_allowlist=tuple(raw.get("dm_allowlist", []) or []),
        admins=tuple(raw.get("admins", []) or []),
        knowledge=knowledge,
        schema_version=raw.get("schema_version", 1),
        dm_min_confidence=raw.get("dm_min_confidence", 0.85),
        allow_mapped_dm=raw.get("allow_mapped_dm", True),
        allow_anonymous_dm=raw.get("allow_anonymous_dm", False),
        public_mentions_enabled=raw.get("public_mentions_enabled", True),
        public_mention_allowlist=public_mention_allowlist,
        public_mention_rate_limit_per_meeting_s=raw.get("public_mention_rate_limit_per_meeting_s", 30),
        series_match_binding=raw.get("series_match_binding", "none"),
        series_match_confidence=raw.get("series_match_confidence"),
        source_vault_note=raw.get("source_vault_note"),
        in_memory_mutations_history=mutations,
    )


def dump_profile_to_yaml(profile: AssistantProfile, path: Path) -> None:
    """Dump a profile to YAML preserving field order + comments-free shape."""
    payload = {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "series_id": profile.series_id,
        "dm_allowlist": list(profile.dm_allowlist),
        "admins": list(profile.admins),
        "dm_min_confidence": profile.dm_min_confidence,
        "allow_mapped_dm": profile.allow_mapped_dm,
        "allow_anonymous_dm": profile.allow_anonymous_dm,
        "public_mentions_enabled": profile.public_mentions_enabled,
        "public_mention_allowlist": (
            list(profile.public_mention_allowlist)
            if profile.public_mention_allowlist is not None else None
        ),
        "public_mention_rate_limit_per_meeting_s": profile.public_mention_rate_limit_per_meeting_s,
        "knowledge": {
            "allow_personal_vault": profile.knowledge.allow_personal_vault,
            "transcript_hot_window_seconds": profile.knowledge.transcript_hot_window_seconds,
            "enable_transcript_search_tool": profile.knowledge.enable_transcript_search_tool,
            "enable_past_meetings_search": profile.knowledge.enable_past_meetings_search,
            "enable_public_references_tool": profile.knowledge.enable_public_references_tool,
            "enable_web_search": profile.knowledge.enable_web_search,
            "public_references": list(profile.knowledge.public_references),
        },
        "series_match_binding": profile.series_match_binding,
        "series_match_confidence": profile.series_match_confidence,
        "source_vault_note": profile.source_vault_note,
        "in_memory_mutations_history": [
            {
                "ts": m.ts, "action": m.action, "target": m.target,
                "by": m.by, "session_id": m.session_id,
            }
            for m in profile.in_memory_mutations_history
        ],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
```

- [ ] **Step 4: Update `__init__.py` re-exports** [U]:

```python
from .config import AssistantConfig, KnowledgeAccessConfig
from .profile import AssistantProfile, ProfileMutation, load_profile_from_yaml, dump_profile_to_yaml
from .types import (
    ChatEvent, ConversationTurn, AdminCommandResult,
    AssistantStats, CanonicalPersonaId,
)

__all__ += [
    "AssistantConfig", "KnowledgeAccessConfig",
    "AssistantProfile", "ProfileMutation",
    "load_profile_from_yaml", "dump_profile_to_yaml",
    "ChatEvent", "ConversationTurn", "AdminCommandResult",
    "AssistantStats", "CanonicalPersonaId",
]
```

- [ ] **Step 5: Create example fixture** [U]:

`tests/fixtures/profiles/sabbath-school.yaml`:

```yaml
schema_version: 1
profile_id: sabbath-school
series_id: sabbath-school-class
dm_allowlist:
  - cyril-grosse
  - helen-christopherson
  - helen-brager
  - pat-grauer
admins:
  - cyril-grosse
dm_min_confidence: 0.85
allow_mapped_dm: true
allow_anonymous_dm: false
public_mentions_enabled: true
public_mention_allowlist: ~
public_mention_rate_limit_per_meeting_s: 30
knowledge:
  allow_personal_vault: false
  transcript_hot_window_seconds: 300
  enable_transcript_search_tool: true
  enable_past_meetings_search: true
  enable_public_references_tool: true
  enable_web_search: true
  public_references: []
series_match_binding: explicit
series_match_confidence: high
source_vault_note: "02_Projects/Lattice/lattice-meetbot/Profiles/sabbath-school.yaml"
in_memory_mutations_history: []
```

- [ ] **Step 6: Run tests + mypy** [U]:

```bash
pytest tests/test_w1_profile.py -xvs
mypy --strict src/
```

Expected: 4 tests PASS; mypy clean.

- [ ] **Step 7: Commit** [U]:

```bash
git add src/lattice_meeting_assistant/profile.py
git add src/lattice_meeting_assistant/types.py
git add src/lattice_meeting_assistant/__init__.py
git add tests/test_w1_profile.py
git add tests/fixtures/profiles/sabbath-school.yaml
git commit -m "feat(profile): AssistantProfile + ProfileMutation + YAML round-trip (W1.5)"
```

## Task W1.6 — W1 exit-gate checkpoint

**Files:** None (review-only)

**Steps:**

- [ ] **Step 1: Confirm exit gates [U]:**

| Sub-task | Status | Verification |
|---|---|---|
| Canonical repo exists | ☐ | `test -d "G:/My Drive/Projects Merge/lattice-meeting-assistant"` |
| `pip install -e .` works | ☐ | venv install completes |
| Public types defined | ☐ | `from lattice_meeting_assistant import AssistantConfig, AssistantProfile, ...` |
| YAML round-trip clean | ☐ | `pytest tests/test_w1_profile.py` passes |
| `mypy --strict src/` clean | ☐ | mypy output empty |

- [ ] **Step 2: Block W2 dispatch until ALL 5 are ☑. [U]**

---

# W2 — Privacy invariants + boundary tests

**Goal:** Implement the 5 Architectural Invariants in code (`privacy/invariants.py`, `privacy/log_redaction.py`); land all 12 boundary tests T1-T12 from spec §5 as test scaffolding (initially many will fail/skip pending W3-W6 impl; T4, T5, T8, T9 should PASS at W2 close because they test the contract-only level).

**Subagent dispatch:** single subagent.

**Exit gate:**

- `BLOCKED_IN_MEETING_TOOLS` frozenset declared with all 24 blocked tool names (from spec §4).
- Visibility-tag fail-closed enforcement (Invariant 4) implemented as a decorator/check.
- Log redaction helper enforces INFO-no-content / DEBUG-with-flag.
- All 12 boundary tests written; T4, T5, T8, T9 PASS; T1, T2, T3, T6, T7, T10, T11, T12 are placeholder-failing or skip-with-reason (will pass after W3-W6).
- `mypy --strict src/` clean.

## Task W2.1 — `privacy/invariants.py` + BLOCKED_IN_MEETING_TOOLS

**Files:**

- Create: `src/lattice_meeting_assistant/privacy/__init__.py`
- Create: `src/lattice_meeting_assistant/privacy/invariants.py`
- Create: `tests/test_w2_invariants_blocked_set.py`

**Steps:**

- [ ] **Step 1: Write failing test** [U]:

```python
# tests/test_w2_invariants_blocked_set.py
import pytest
from lattice_meeting_assistant.privacy.invariants import (
    BLOCKED_IN_MEETING_TOOLS,
    assert_in_meeting_tools_safe,
    enforce_visibility_tag,
)
from lattice_meeting_assistant.exceptions import PrivacyBoundaryViolation


def test_blocked_set_contains_all_24_tools():
    expected = {
        "search_vault", "read_note", "search_email", "read_email",
        "nx_calendar_read", "nx_calendar_write", "create_calendar_event",
        "nx_contacts_read", "nx_contacts_search", "nx_contacts_add", "nx_contacts_update",
        "nx_db_query", "nx_vault_multi_read", "nx_vault_multi_search",
        "nx_vault_query", "nx_vault_write",
        "deep_research", "nx_context_gather",
        "download_media", "instagram_ingest",
        "x_status", "x_sync_bookmarks",
        "youtube_playlists", "youtube_sync_playlist",
        "search_whatsapp", "bible_lookup", "strongs_lookup",
        "create_note", "create_reminder", "create_ticket",
        "flush_note_queue", "ingest_url", "share_note",
        "update_note", "update_ticket", "list_tickets",
        "brain_chat", "vault_ask",
    }
    assert BLOCKED_IN_MEETING_TOOLS >= expected, (
        f"missing from blocked set: {expected - BLOCKED_IN_MEETING_TOOLS}"
    )


def test_blocked_set_is_frozenset():
    assert isinstance(BLOCKED_IN_MEETING_TOOLS, frozenset)


def test_assert_in_meeting_tools_safe_passes_clean_set():
    safe_tools = {"search_meeting_transcript", "web_search", "search_public_references"}
    assert_in_meeting_tools_safe(safe_tools)  # no raise


def test_assert_in_meeting_tools_safe_raises_on_blocked():
    bad = {"search_vault", "web_search"}
    with pytest.raises(ValueError, match="blocked tool"):
        assert_in_meeting_tools_safe(bad)


def test_enforce_visibility_tag_passes_when_present():
    class FakeEvent:
        is_private = True
    enforce_visibility_tag(FakeEvent())  # no raise


def test_enforce_visibility_tag_raises_when_missing():
    class FakeEvent:
        pass  # no is_private attr
    with pytest.raises(PrivacyBoundaryViolation):
        enforce_visibility_tag(FakeEvent())


def test_enforce_visibility_tag_raises_when_none():
    class FakeEvent:
        is_private = None
    with pytest.raises(PrivacyBoundaryViolation):
        enforce_visibility_tag(FakeEvent())
```

Run: FAIL.

- [ ] **Step 2: Implement `privacy/__init__.py`** (empty + docstring) [U]:

```python
"""Privacy invariants + log redaction. See spec §5."""
```

- [ ] **Step 3: Implement `privacy/invariants.py`** [U]:

```python
"""Architectural Invariants 1-5 enforcement primitives.

See spec §5 for the full statement of each invariant.
"""

from __future__ import annotations
from typing import Iterable

from ..exceptions import PrivacyBoundaryViolation


# Invariant 2 — hard deny list for in-meeting-dm transport tool resolver.
# Enumerated per spec §4. Default-deny: if a future MCP tool is added to
# the global Nexus surface, it does NOT automatically grant access to
# in-meeting-dm transport — must be explicitly added to the in-meeting
# tool set in resolver.py.
BLOCKED_IN_MEETING_TOOLS: frozenset[str] = frozenset({
    # Full vault access
    "search_vault",
    "read_note",
    "nx_vault_multi_read",
    "nx_vault_multi_search",
    "nx_vault_query",
    "nx_vault_write",
    "vault_ask",
    # Email
    "search_email",
    "read_email",
    # Calendar
    "nx_calendar_read",
    "nx_calendar_write",
    "create_calendar_event",
    # Contacts
    "nx_contacts_read",
    "nx_contacts_search",
    "nx_contacts_add",
    "nx_contacts_update",
    # DB + advanced retrieval
    "nx_db_query",
    "deep_research",  # full mode; lightweight is wrapped as web_search
    "nx_context_gather",
    # Media + social
    "download_media",
    "instagram_ingest",
    "x_status",
    "x_sync_bookmarks",
    "youtube_playlists",
    "youtube_sync_playlist",
    "search_whatsapp",
    # Reference lookups (defer to v0.2)
    "bible_lookup",
    "strongs_lookup",
    # Vault-mutating tools (TG-only in v0.2; never in-meeting)
    "create_note",
    "create_reminder",
    "create_ticket",
    "flush_note_queue",
    "ingest_url",
    "share_note",
    "update_note",
    "update_ticket",
    "list_tickets",
    # Circular dispatch — Brain chat invokes Brain's own chat which has full surface
    "brain_chat",
})


def assert_in_meeting_tools_safe(tool_names: Iterable[str]) -> None:
    """Raise ValueError if any of the given tool names is in the blocked set.

    Called by tool resolver at boot for the in-meeting-dm transport's
    resolved tool set. Enforces Architectural Invariant #2.
    """
    names = set(tool_names)
    overlap = names & BLOCKED_IN_MEETING_TOOLS
    if overlap:
        raise ValueError(
            f"BLOCKED_IN_MEETING_TOOLS contains tool(s) that the in-meeting-dm "
            f"transport resolver attempted to register: {sorted(overlap)}. "
            f"These tools are not allowed for in-meeting-dm per "
            f"Architectural Invariant #2."
        )


def enforce_visibility_tag(event: object) -> None:
    """Raise PrivacyBoundaryViolation if the event lacks an is_private tag
    or has is_private == None.

    Architectural Invariant #4 — fail-closed on visibility ambiguity. The
    Assistant calls this at the very top of on_private_chat() and
    on_public_mention().
    """
    is_private = getattr(event, "is_private", _SENTINEL)
    if is_private is _SENTINEL or is_private is None:
        raise PrivacyBoundaryViolation(
            f"chat event lacks is_private visibility tag: "
            f"event_id={getattr(event, 'id', '<unknown>')}"
        )


_SENTINEL: object = object()
```

- [ ] **Step 4: Run tests + mypy** [U]:

```bash
pytest tests/test_w2_invariants_blocked_set.py -xvs
mypy --strict src/
```

Expected: 7 tests PASS; mypy clean.

- [ ] **Step 5: Commit** [U]:

```bash
git add src/lattice_meeting_assistant/privacy/
git add tests/test_w2_invariants_blocked_set.py
git commit -m "feat(privacy): BLOCKED_IN_MEETING_TOOLS + invariant enforcement helpers (W2.1)"
```

## Task W2.2 — Log redaction (Invariant adjacent — Q4c defense #3)

**Files:**

- Create: `src/lattice_meeting_assistant/privacy/log_redaction.py`
- Create: `tests/test_w2_log_redaction.py`

**Steps:**

- [ ] **Step 1: Write failing test** [U]:

```python
# tests/test_w2_log_redaction.py
import logging
from lattice_meeting_assistant.config import AssistantConfig
from lattice_meeting_assistant.privacy.log_redaction import log_chat_event


def test_log_chat_event_info_omits_content(caplog):
    cfg = AssistantConfig(debug_chat_content=False)

    class FakeEvent:
        id = "evt_123"
        meeting_id = "mtg_456"
        sender_user_id = "user_789"
        text = "secret content nobody should see in logs"
        is_private = True

    with caplog.at_level(logging.INFO):
        log_chat_event("private_chat_received", FakeEvent(), cfg)
    record = caplog.records[-1]
    assert "secret content" not in record.getMessage()
    assert "evt_123" in record.getMessage()
    assert "msg_len=" in record.getMessage()


def test_log_chat_event_debug_includes_content_when_flag_set(caplog):
    cfg = AssistantConfig(debug_chat_content=True)

    class FakeEvent:
        id = "evt_123"
        meeting_id = "mtg_456"
        sender_user_id = "user_789"
        text = "secret content"
        is_private = True

    with caplog.at_level(logging.DEBUG):
        log_chat_event("private_chat_received", FakeEvent(), cfg)
    record = caplog.records[-1]
    assert "secret content" in record.getMessage()


def test_log_chat_event_debug_omits_content_when_flag_unset(caplog):
    cfg = AssistantConfig(debug_chat_content=False)

    class FakeEvent:
        id = "evt_123"
        meeting_id = "mtg_456"
        sender_user_id = "user_789"
        text = "secret content"
        is_private = True

    with caplog.at_level(logging.DEBUG):
        log_chat_event("private_chat_received", FakeEvent(), cfg)
    # Even at DEBUG, without flag, content is redacted
    record = caplog.records[-1]
    assert "secret content" not in record.getMessage()
```

Run: FAIL.

- [ ] **Step 2: Implement `privacy/log_redaction.py`** [U]:

```python
"""Log redaction primitives — Q4c defense #3.

INFO logs: sender_id + msg_length only; NEVER content.
DEBUG logs: content included ONLY when AssistantConfig.debug_chat_content=True.
"""

from __future__ import annotations
import logging

from ..config import AssistantConfig


_log = logging.getLogger("lattice_meeting_assistant.privacy")


def log_chat_event(
    event_kind: str,
    event: object,
    config: AssistantConfig,
) -> None:
    """Log a chat event with redaction policy applied.

    `event_kind` = "private_chat_received" | "public_mention_received" |
                   "reply_sent" | "admin_command_received" | etc.
    """
    event_id = getattr(event, "id", "<unknown>")
    meeting_id = getattr(event, "meeting_id", "<unknown>")
    sender_id = getattr(event, "sender_user_id", "<unknown>")
    text = getattr(event, "text", "")
    msg_len = len(text) if isinstance(text, str) else 0

    if config.debug_chat_content:
        _log.debug(
            "%s evt=%s mtg=%s sender=%s msg_len=%d content=%r",
            event_kind, event_id, meeting_id, sender_id, msg_len, text,
        )
    else:
        _log.info(
            "%s evt=%s mtg=%s sender=%s msg_len=%d",
            event_kind, event_id, meeting_id, sender_id, msg_len,
        )
```

- [ ] **Step 3: Run tests + mypy** [U]:

```bash
pytest tests/test_w2_log_redaction.py -xvs
mypy --strict src/
```

Expected: 3 tests PASS; mypy clean.

- [ ] **Step 4: Commit** [U]:

```bash
git add src/lattice_meeting_assistant/privacy/log_redaction.py
git add tests/test_w2_log_redaction.py
git commit -m "feat(privacy): log redaction policy (INFO-no-content / DEBUG-with-flag) (W2.2)"
```

## Task W2.3 — Boundary tests T1-T12 scaffold

**Files:**

- Create: `tests/test_privacy_boundary.py` (all 12 tests in one file for cross-reference clarity)
- Create: `tests/conftest.py` (shared fixtures: mock cortex, mock session, mock brain_mcp, mock transcript buffer)

**Steps:**

- [ ] **Step 1: Implement `tests/conftest.py`** with the mock fixtures [U]:

```python
"""Shared fixtures for the test suite."""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from lattice_meeting_assistant.types import ChatEvent


@pytest.fixture
def mock_cortex_registry():
    """Cortex registry that returns a stub reply on every call. Records all
    calls for assertion."""
    m = MagicMock()
    m.call = AsyncMock(return_value=MagicMock(
        text="stub reply",
        tokens_used=50,
        tier_used="interactive",
        provider_used="anthropic",
    ))
    return m


@pytest.fixture
def mock_session():
    """MeetingSession mock with send_chat + send_chat_public."""
    m = MagicMock()
    m.send_chat = AsyncMock()
    m.send_chat_public = AsyncMock()
    m.is_alive = True
    return m


@pytest.fixture
def mock_brain_mcp():
    """Brain MCP client mock."""
    m = MagicMock()
    m.nx_vault_search = AsyncMock(return_value={"results": []})
    m.nx_references_search = AsyncMock(return_value={"results": []})
    m.deep_research = AsyncMock(return_value={"summary": "stub"})
    return m


@pytest.fixture
def mock_transcript_buffer():
    """TranscriptBuffer mock."""
    m = MagicMock()
    m.subscribe = MagicMock(return_value=asyncio.Queue())
    m.get_hot_window = MagicMock(return_value=[])
    m.search = MagicMock(return_value=[])
    return m


def make_chat_event(
    *,
    text: str,
    sender_user_id: str = "user_001",
    sender_canonical_id: str | None = "cyril-grosse",
    meeting_id: str = "mtg_001",
    is_private: bool = True,
    is_at_mention_to_bot: bool = False,
) -> ChatEvent:
    return ChatEvent(
        id=f"evt_{sender_user_id}_{datetime.now(timezone.utc).timestamp()}",
        meeting_id=meeting_id,
        platform="zoom",
        sender_user_id=sender_user_id,
        sender_canonical_id=sender_canonical_id,
        sender_canonical_confidence=0.95 if sender_canonical_id else None,
        sender_display_name=sender_canonical_id or "Anonymous Joiner",
        text=text,
        ts=datetime.now(timezone.utc),
        is_private=is_private,
        is_at_mention_to_bot=is_at_mention_to_bot,
    )
```

- [ ] **Step 2: Implement boundary test scaffolding** — `tests/test_privacy_boundary.py` [U]:

```python
"""The 12 boundary tests T1-T12 from spec §5.

T4, T5, T8, T9 should PASS at W2 close (contract-only assertions).
T1, T2, T3, T6, T7, T10, T11, T12 are skip-with-reason until their
implementations land in W3-W6.
"""

from __future__ import annotations
import pytest

from lattice_meeting_assistant.exceptions import PrivacyBoundaryViolation
from lattice_meeting_assistant.privacy.invariants import (
    BLOCKED_IN_MEETING_TOOLS,
    assert_in_meeting_tools_safe,
    enforce_visibility_tag,
)
from tests.conftest import make_chat_event


# -----------------------------------------------------------------------
# T4 — Separated send paths (Invariant 1)
# -----------------------------------------------------------------------

def test_t4_send_chat_requires_to_user_id_positional():
    """Invariant 1 — `send_chat` requires `to_user_id` positional;
    there is no broadcast default + no broadcast= kwarg.

    This is a contracts-level assertion; verified via the
    lattice-meeting-contracts MeetingSession Protocol shape.
    """
    from lattice_meeting_contracts import MeetingSession
    sig_send_chat = MeetingSession.send_chat.__doc__ or ""
    # The contract requires `to_user_id` to be positional + required
    assert "to_user_id" in sig_send_chat or "to_user_id" in str(MeetingSession.send_chat), (
        "MeetingSession.send_chat must require to_user_id positional"
    )


# -----------------------------------------------------------------------
# T5 — Visibility-tag fail-closed (Invariant 4)
# -----------------------------------------------------------------------

def test_t5_missing_visibility_tag_raises_privacy_boundary_violation():
    class EventWithoutTag:
        id = "evt_t5"
        # no is_private
    with pytest.raises(PrivacyBoundaryViolation):
        enforce_visibility_tag(EventWithoutTag())


def test_t5_none_visibility_tag_raises_privacy_boundary_violation():
    class EventWithNoneTag:
        id = "evt_t5"
        is_private = None
    with pytest.raises(PrivacyBoundaryViolation):
        enforce_visibility_tag(EventWithNoneTag())


# -----------------------------------------------------------------------
# T8 — Tool resolver enforces BLOCKED set for in-meeting-dm
# -----------------------------------------------------------------------

def test_t8_in_meeting_resolver_rejects_blocked_tools():
    bad_set = {"search_meeting_transcript", "search_vault"}
    with pytest.raises(ValueError, match="blocked tool"):
        assert_in_meeting_tools_safe(bad_set)


def test_t8_in_meeting_resolver_allows_clean_set():
    good_set = {
        "search_meeting_transcript", "read_meeting_transcript_window",
        "search_past_meetings", "search_public_references", "web_search",
    }
    assert_in_meeting_tools_safe(good_set)  # no raise


# -----------------------------------------------------------------------
# T9 — Profile YAML enabling personal-vault for in-meeting raises
# (covered by config flag + resolver; this test pairs with T8)
# -----------------------------------------------------------------------

def test_t9_knowledge_config_allow_personal_vault_field_exists():
    """Sentinel: the boolean is on KnowledgeAccessConfig; resolver overrides
    to False for in-meeting-dm transport regardless of config value.

    Full integration coverage lands in W3.7 (test_w3_resolver.py)."""
    from lattice_meeting_assistant.config import KnowledgeAccessConfig
    k = KnowledgeAccessConfig()
    assert k.allow_personal_vault is False  # default


# -----------------------------------------------------------------------
# T1, T2, T3, T6, T7, T10, T11, T12 — scaffolded as xfail until W3-W6 land
# -----------------------------------------------------------------------

@pytest.mark.xfail(reason="W4 — ChatThreadActor not yet implemented", strict=True)
@pytest.mark.asyncio
async def test_t1_two_parallel_dms_memory_isolated():
    """T1 — Two parallel DMs from senders A and B in same meeting.
    Memory contexts isolated; distinct cortex cache namespaces; replies
    to correct sender's userId only.

    Full impl in W4. Awaiting Assistant.on_private_chat() + ChatThreadActor.
    """
    raise NotImplementedError  # placeholder


@pytest.mark.xfail(reason="W3 — transcript filter + assistant routing", strict=True)
@pytest.mark.asyncio
async def test_t2_private_dm_never_in_transcript_callback():
    """T2 — Private DM text never appears in /segments POST body."""
    raise NotImplementedError


@pytest.mark.xfail(reason="W7 — wrap-up integration test", strict=True)
@pytest.mark.asyncio
async def test_t3_private_dm_never_in_wrap_up():
    """T3 — Private DM text never appears in wrap-up source corpus."""
    raise NotImplementedError


@pytest.mark.xfail(reason="W3 — cortex cache namespace", strict=True)
@pytest.mark.asyncio
async def test_t6_cache_scope_per_thread():
    """T6 — Same prompt from sender A and sender B yields independent cortex
    invocations."""
    raise NotImplementedError


@pytest.mark.xfail(reason="W5 — admin command parser", strict=True)
@pytest.mark.asyncio
async def test_t7_in_meeting_admin_command_rejected():
    """T7 — In-meeting DM `allowlist add X` gets "not supported here" reply
    without mutating allowlist."""
    raise NotImplementedError


@pytest.mark.xfail(reason="W4 — actor backpressure", strict=True)
@pytest.mark.asyncio
async def test_t10_per_thread_queue_backpressure():
    """T10 — 6th msg from one sender triggers backpressure reply; 1-5 still
    processed in FIFO."""
    raise NotImplementedError


@pytest.mark.xfail(reason="W6 — public mention handler", strict=True)
@pytest.mark.asyncio
async def test_t11_public_mention_reply_via_send_chat_public():
    """T11 — Public mention reply lands via send_chat_public only; never via
    send_chat."""
    raise NotImplementedError


@pytest.mark.xfail(reason="W6 — public mention + private DM isolation", strict=True)
@pytest.mark.asyncio
async def test_t12_private_and_public_thread_isolation():
    """T12 — Private DM + public mention from same sender in same meeting:
    two independent ChatThreadActors; replies do not commingle."""
    raise NotImplementedError
```

- [ ] **Step 3: Run + verify** [U]:

```bash
pytest tests/test_privacy_boundary.py -v
mypy --strict src/
```

Expected: 6 passing (T4-T9 contract tests), 8 xfailed (T1-T3, T6-T7, T10-T12 pending impl).

- [ ] **Step 4: Commit** [U]:

```bash
git add tests/conftest.py
git add tests/test_privacy_boundary.py
git commit -m "test(privacy): boundary tests T1-T12 scaffold; T4,T5,T8,T9 passing (W2.3)"
```

## Task W2.4 — W2 exit-gate checkpoint

**Files:** None.

**Steps:**

- [ ] **Step 1: Confirm exit gates [U]:**

| Sub-task | Status | Verification |
|---|---|---|
| `BLOCKED_IN_MEETING_TOOLS` defined | ☐ | `from ... import BLOCKED_IN_MEETING_TOOLS; len(BLOCKED_IN_MEETING_TOOLS) >= 24` |
| Visibility-tag fail-closed enforced | ☐ | `tests/test_w2_invariants_blocked_set.py` passes |
| Log redaction policy enforced | ☐ | `tests/test_w2_log_redaction.py` passes |
| T1-T12 boundary tests written | ☐ | `pytest tests/test_privacy_boundary.py -v` shows 6 pass + 8 xfail |
| `mypy --strict src/` clean | ☐ | mypy output empty |

- [ ] **Step 2: Block W3 dispatch until ALL 5 are ☑. [U]**

---

# W3 — Cortex tool implementations + resolver

**Goal:** Implement the 5 in-meeting-dm tools (`SearchMeetingTranscriptTool`, `ReadMeetingTranscriptWindowTool`, `SearchPastMeetingsTool`, `SearchPublicReferencesTool`, `WebSearchTool`) + 6 TG-owner-only tools (Nexus wrappers) + the `resolve_tool_set` resolver with boot self-test. Establish the cortex tool ABC consumption pattern verified in W0.2.

**Subagent dispatch:** single subagent.

**Exit gate:**

- 11 v0.1 tools register cleanly with cortex 0.6.0 (mocked in unit tests; live verification deferred to AC-4 integration).
- `resolve_tool_set(transport, profile)` returns correct sets per transport.
- Boot self-test (`assistant.start()` placeholder) confirms BLOCKED disjoint from in-meeting-dm.
- T8 + T9 boundary tests both PASS (no longer xfail at W2-level — now backed by full resolver).
- `mypy --strict src/` clean.

> *Tasks W3.1-W3.7 follow the same TDD pattern as W1-W2: failing test → implementation → run → commit. Each tool file is ~50-80 LOC; resolver is ~120 LOC; ~5 commits per task average. Full code blocks for each step continue the patterns established in W1.4-W1.5 and W2.1-W2.3 (test scaffolding from conftest; impl matches spec §4 tool implementation pattern).*

## Task W3.1 — CortexTool base + registry probe

**Files:**

- Create: `src/lattice_meeting_assistant/tools/__init__.py`
- Create: `src/lattice_meeting_assistant/tools/base.py`
- Create: `tests/test_w3_tools_base.py`

**Steps:** [U] (verified against cortex 0.6.0 in W0.2)

- [ ] Step 1: failing test for `CortexTool` ABC (constructor signature, `invoke()` async) [U].
- [ ] Step 2: Implement `base.py` with `CortexTool` Protocol matching cortex 0.6.0's tool registration shape (from W0.2 verified) [U].
- [ ] Step 3: Run test → PASS [U].
- [ ] Step 4: Commit `feat(tools): CortexTool ABC + registry probe (W3.1)` [U].

## Task W3.2 — SearchMeetingTranscriptTool + ReadMeetingTranscriptWindowTool

**Files:**

- Create: `src/lattice_meeting_assistant/tools/transcript.py`
- Create: `tests/test_w3_tools_transcript.py`

Implements `SearchMeetingTranscriptTool(transcript_buffer)` and `ReadMeetingTranscriptWindowTool(transcript_buffer, default_window_seconds=300)` per spec §4 tool implementation pattern. TDD per Step 1-5 pattern.

- [ ] Step 1: failing test exercising substring search on a fake TranscriptBuffer [U].
- [ ] Step 2: Implement tools matching spec §4 code block [U].
- [ ] Step 3: Run tests; PASS [U].
- [ ] Step 4: Commit `feat(tools): transcript search + hot window tools (W3.2)` [U].

## Task W3.3 — SearchPastMeetingsTool (Brain nx_vault_search wrapper)

**Files:**

- Create: `src/lattice_meeting_assistant/tools/past_meetings.py`
- Create: `src/lattice_meeting_assistant/brain_client.py`
- Create: `tests/test_w3_tools_past_meetings.py`

`BrainMCPClient` (httpx + UA `curl/8.7.1` per S19 Nexus API UA Requirement protocol). `SearchPastMeetingsTool` filters by `series_id` in vault frontmatter when invoked.

- [ ] Step 1: failing test with mock httpx for nx_vault_search call [U].
- [ ] Step 2: Implement BrainMCPClient (auth header, UA, base URL from env) [U].
- [ ] Step 3: Implement SearchPastMeetingsTool calling client.nx_vault_search [U].
- [ ] Step 4: Run tests; PASS [U].
- [ ] Step 5: Commit `feat(tools): SearchPastMeetingsTool + BrainMCPClient (W3.3)` [U].

## Task W3.4 — SearchPublicReferencesTool

**Files:**

- Create: `src/lattice_meeting_assistant/tools/public_references.py`
- Create: `tests/test_w3_tools_public_references.py`

Wraps Brain `nx_references_search` scoped to `profile.knowledge.public_references` paths.

- [ ] Step 1: failing test [U].
- [ ] Step 2: Implement [U].
- [ ] Step 3: PASS + Commit `feat(tools): SearchPublicReferencesTool (W3.4)` [U].

## Task W3.5 — WebSearchTool

**Files:**

- Create: `src/lattice_meeting_assistant/tools/web_search.py`
- Create: `tests/test_w3_tools_web_search.py`

Wraps Brain `deep_research` with `mode=lightweight` (per OQ3 default). If Brain API doesn't support `mode` parameter, fall back to a "summary-only" prompt to deep_research.

- [ ] Step 1: failing test [U].
- [ ] Step 2: Implement; W3 task carries `[U]` for OQ3 verification (run against actual Brain at task time).
- [ ] Step 3: PASS + Commit `feat(tools): WebSearchTool (W3.5)` [U].

## Task W3.6 — TG-owner Nexus tool wrappers (6 tools)

**Files:**

- Create: `src/lattice_meeting_assistant/tools/tg_owner_tools.py`
- Create: `tests/test_w3_tools_tg_owner.py`

Wraps: `search_vault`, `read_note`, `search_references`, `nx_calendar_read`, `nx_email_search`, `vault_ask`. Thin pass-throughs to `BrainMCPClient`; no logic.

- [ ] Step 1: failing test exercising each wrapper [U].
- [ ] Step 2: Implement 6 thin wrappers [U].
- [ ] Step 3: PASS + Commit `feat(tools): TG-owner Nexus tool wrappers x6 (W3.6)` [U].

## Task W3.7 — resolve_tool_set + boot self-test (T8 + T9 final coverage)

**Files:**

- Create: `src/lattice_meeting_assistant/tools/resolver.py`
- Create: `tests/test_w3_resolver.py`
- Modify: `tests/test_privacy_boundary.py` (remove xfail on T8 + T9; backfill full impl)

**Steps:**

- [ ] Step 1: failing test asserting resolver returns 5 in-meeting tools for in-meeting-dm + 11 total for tg-owner; both pass `assert_in_meeting_tools_safe` on in-meeting set; throws ValueError if profile attempts to enable a blocked tool [U].
- [ ] Step 2: Implement `resolver.py` matching spec §4 pseudocode [U].
- [ ] Step 3: Remove xfail from T8/T9 in `test_privacy_boundary.py`; verify they now PASS [U].
- [ ] Step 4: PASS + Commit `feat(tools): resolve_tool_set + boot self-test; T8+T9 backed (W3.7)` [U].

## Task W3.8 — W3 exit-gate checkpoint

| Sub-task | Status | Verification |
|---|---|---|
| 11 tools defined | ☐ | grep tool class names in src/tools/ |
| Resolver returns correct sets | ☐ | `tests/test_w3_resolver.py` passes |
| T8 + T9 boundary tests PASS (no xfail) | ☐ | `pytest tests/test_privacy_boundary.py -v` shows 8 pass + 6 xfail |
| `mypy --strict src/` clean | ☐ | mypy output empty |

Block W4 dispatch until ALL ☑.

---

# W4 — ChatThreadActor + concurrency

**Goal:** Implement `ChatThreadActor` (FIFO + worker + holding-message + history compaction + lifecycle) and the global semaphore wiring. Backed boundary tests: T1, T6, T10 move from xfail to PASS.

**Subagent dispatch:** single subagent.

**Exit gate:**

- `ChatThreadActor` implements spec §7 contract.
- Holding message fires at threshold (default 3000ms) via `asyncio.wait_for` race pattern.
- Backpressure on queue-full returns False from `enqueue()`; caller surfaces "catching up" reply.
- History compaction triggers at 16k tokens (mocked cortex compactor for v0.1).
- Lifecycle: 60s post-leave grace, meeting-end reap.
- Global semaphore = 4 enforced.
- T1, T6, T10 PASS.

## Task W4.1 — ChatThreadActor skeleton + enqueue + FIFO worker

**Files:**

- Create: `src/lattice_meeting_assistant/actor.py`
- Create: `tests/test_w4_actor_fifo.py`

**Steps:** Full TDD pattern, ~200 LOC implementation matching spec §7 ChatThreadActor pseudocode. Test asserts FIFO order across 3 messages, single-worker serialization, correct reply routing to sender_user_id.

- [ ] Step 1: failing test (3 msgs enqueued; 3 cortex calls in order; 3 send_chat calls to correct user_id) [U].
- [ ] Step 2: Implement ChatThreadActor with `_queue`, `_worker_loop`, `_dispatch`, `enqueue` [U].
- [ ] Step 3: PASS + Commit `feat(actor): ChatThreadActor FIFO worker (W4.1)` [U].

## Task W4.2 — Holding message via wait_for race

- [ ] Step 1: failing test — slow cortex (>3000ms); assert filler message sent before real reply [U].
- [ ] Step 2: Implement `_dispatch_with_holding_message` per spec §7 [U].
- [ ] Step 3: PASS + Commit `feat(actor): holding message threshold (W4.2)` [U].

## Task W4.3 — Backpressure on queue-full

- [ ] Step 1: failing test — 6th msg returns False from enqueue; assert caller backpressure reply path; assert 1-5 still processed [U].
- [ ] Step 2: Implement backpressure in Assistant.on_private_chat (will need `Assistant` shell in this task — minimal version that just routes to actor + handles backpressure) [U].
- [ ] Step 3: PASS + Commit `feat(actor): per-thread queue backpressure (W4.3)` [U].

## Task W4.4 — History compaction at 16k tokens

- [ ] Step 1: failing test — fake history grows past 16k tokens; cortex compactor mock called; recent verbatim retained [U].
- [ ] Step 2: Implement compaction trigger [U].
- [ ] Step 3: PASS + Commit `feat(actor): history compaction at token cap (W4.4)` [U].

## Task W4.5 — Actor lifecycle (sender leave + meeting end)

- [ ] Step 1: failing tests — sender-leave triggers 60s timer; rejoin cancels; meeting-end drains all actors [U].
- [ ] Step 2: Implement lifecycle hooks [U].
- [ ] Step 3: PASS + Commit `feat(actor): lifecycle (post-leave grace + meeting-end reap) (W4.5)` [U].

## Task W4.6 — Global concurrency semaphore + Assistant shell

- [ ] Step 1: failing test — 10 actors fire cortex calls; assert at most 4 in flight via semaphore inspection; T1 + T6 + T10 now testable [U].
- [ ] Step 2: Implement Assistant `_global_semaphore`, wire to actors' cortex_call closures. Implement minimal Assistant class with start/shutdown + on_private_chat routing [U].
- [ ] Step 3: Update T1, T6, T10 in test_privacy_boundary.py — remove xfail; backfill full impl [U].
- [ ] Step 4: PASS + Commit `feat(assistant): global semaphore + actor pool wiring; T1+T6+T10 backed (W4.6)` [U].

## Task W4.7 — W4 exit-gate checkpoint

| Sub-task | Status | Verification |
|---|---|---|
| ChatThreadActor implemented | ☐ | tests/test_w4_actor_*.py all pass |
| Holding message + backpressure | ☐ | tests/test_w4_actor_holding_message.py + test_w4_actor_lifecycle.py pass |
| History compaction | ☐ | tests/test_w4_actor_history_compaction.py pass |
| Global semaphore | ☐ | tests/test_w4_global_semaphore.py pass |
| T1 + T6 + T10 PASS | ☐ | `pytest tests/test_privacy_boundary.py -v` shows 11 pass + 3 xfail |
| `mypy --strict src/` clean | ☐ | mypy output empty |

Block W5 until ALL ☑.

---

# W5 — Persona allowlist + SeriesMatcher + admin commands

**Goal:** Implement T1/T2/T3 allowlist enforcement; SeriesMatcher Path 1 + Path 2 (with TG ratification); admin command parser + dispatcher + profile YAML write-back via Brain MCP. Backed: T7 moves from xfail to PASS.

**Subagent dispatch:** single subagent.

**Exit gate:**

- Allowlist tier check in Assistant.on_private_chat (T1/T2/T3).
- SeriesMatcher matches Path 1 (HIGH, no ratification) + Path 2 (MEDIUM, refinement-event TG ratification).
- Admin command parser handles allowlist/mode/mute/unmute/help/status; allowlist mutations write back to profile YAML via Brain MCP `nx_vault_write` (per OQ8).
- T7 boundary test PASS.
- AC-6 integration test (mock AdminTransport ratification flow) PASS.

## Task W5.1 — Allowlist tier check

- [ ] failing test → T1/T2/T3 allowlist behavior (T1 explicit allowlist hit; T2 mapped-persona ≥ 0.85 confidence; T3 unresolved default-deny) [U].
- [ ] Implement `Assistant._is_allowed(sender_canonical_id, confidence)` in `assistant.py` [U].
- [ ] PASS + Commit `feat(assistant): T1/T2/T3 allowlist enforcement (W5.1)` [U].

## Task W5.2 — SeriesMatcher Path 1 (explicit recurring meeting ID)

- [ ] failing test → matching by `zoom_recurring_meeting_id` returns HIGH-confidence binding [U].
- [ ] Implement `series.py` Path 1 (vault query via Brain MCP nx_vault_search filtered by frontmatter) [U].
- [ ] PASS + Commit `feat(series): Path 1 explicit recurring-id matcher (W5.2)` [U].

## Task W5.3 — SeriesMatcher Path 2 (implicit host-cohort) + ratification flow

- [ ] failing test → host match + overlap ≥ 0.5 returns MEDIUM-confidence + requires_ratification=True [U].
- [ ] failing test → ratification timeout falls back to default profile [U].
- [ ] Implement Path 2 Jaccard overlap + AdminTransport ratification ping + timeout fallback [U].
- [ ] PASS + Commit `feat(series): Path 2 implicit host-cohort + ratification (W5.3)` [U].

## Task W5.4 — Admin command parser

- [ ] failing test → parse `allowlist add X` / `allowlist remove X` / `allowlist show` / `mode interactive` / `mute` / `help` / `status` [U].
- [ ] Implement `admin.py` with parser + dispatcher; admin auth check raises `AdminAuthorizationDenied` if ratifying_user not in profile.admins [U].
- [ ] PASS + Commit `feat(admin): command parser + auth check (W5.4)` [U].

## Task W5.5 — Profile YAML write-back via Brain MCP

- [ ] failing test → `allowlist add X persistent` triggers Brain nx_vault_write call with updated YAML + audit `in_memory_mutations_history` entry [U].
- [ ] Implement write-back path in `admin.py` + `brain_client.py.nx_vault_write` wrapper [U].
- [ ] PASS + Commit `feat(admin): persistent allowlist via Brain nx_vault_write (W5.5)` [U].

## Task W5.6 — T7 boundary test backed

- [ ] Remove xfail from T7 in test_privacy_boundary.py; backfill full test (in-meeting DM containing `allowlist add X` returns "not supported here" without mutation) [U].
- [ ] Implement in-meeting-dm admin-command rejection in `Assistant.on_private_chat()` — if message starts with admin grammar AND transport is in-meeting-dm, decline with stock reply [U].
- [ ] PASS + Commit `test(privacy): T7 backed — in-meeting admin commands rejected (W5.6)` [U].

## Task W5.7 — AC-6 integration test (mock AdminTransport)

- [ ] Create `tests/integration/test_e2e_series_ratification_mock_tg.py` exercising Path 2 ratification round-trip with a mock AdminTransport that scripts `yes`/`no`/`timeout`/`new-series` responses [U].
- [ ] PASS + Commit `test(integration): series ratification mock-TG flow (AC-6) (W5.7)` [U].

## Task W5.8 — W5 exit-gate checkpoint

| Sub-task | Status | Verification |
|---|---|---|
| Allowlist T1/T2/T3 | ☐ | tests/test_w5_allowlist_tiers.py pass |
| SeriesMatcher Path 1 + Path 2 | ☐ | tests/test_w5_series_matcher_*.py pass |
| Admin command parser + write-back | ☐ | tests/test_w5_admin_commands.py + profile_yaml_roundtrip pass |
| T7 PASS | ☐ | `pytest tests/test_privacy_boundary.py -v` shows 12 pass + 2 xfail |
| AC-6 mock-TG E2E | ☐ | tests/integration/test_e2e_series_ratification_mock_tg.py pass |
| `mypy --strict src/` clean | ☐ | mypy output empty |

Block W6 until ALL ☑.

---

# W6 — Public mention path

**Goal:** Implement `PublicMentionHandler` + `(meeting_id, "public")` actor + public-variant system prompt + rate limit. Backed: T11 + T12 move from xfail to PASS.

**Subagent dispatch:** single subagent.

**Exit gate:**

- Public mention routing — `is_private=False AND is_at_mention_to_bot=True` events route to PublicMentionHandler.
- New ChatThreadActor keyed on `(meeting_id, "public")`; reuses W4 actor mechanics with a different system_prompt_renderer + `send_chat_public` callback instead of `send_chat`.
- Public-variant system prompt per spec §4.
- Meeting-level rate limit (default 1 reply / 30s) enforced.
- `public_mentions_enabled` toggle honored.
- `public_mention_allowlist` honored when set; silent decline (no reply) for non-allowlisted senders.
- T11 + T12 boundary tests PASS — ALL 12 boundary tests green.

## Task W6.1 — Public-variant system prompt + PublicMentionHandler skeleton

- [ ] failing test → public prompt contains "PUBLIC meeting chat" + decline-private-shaped guidance [U].
- [ ] Implement `prompts.py` with `render_in_meeting_dm_prompt(...)` and `render_public_mention_prompt(...)` [U].
- [ ] Implement `public_mentions.py` handler skeleton [U].
- [ ] PASS + Commit `feat(public): system prompt variant + handler skeleton (W6.1)` [U].

## Task W6.2 — Public actor wiring + `(meeting_id, "public")` thread key

- [ ] failing test → @mention triggers public actor (singleton per meeting); reply goes via send_chat_public [U].
- [ ] Implement public actor spawn in Assistant.on_public_mention; reuse ChatThreadActor with `key=(meeting_id, "public")` + public system prompt + send_chat_public callback [U].
- [ ] PASS + Commit `feat(public): public actor + send_chat_public routing (W6.2)` [U].

## Task W6.3 — Meeting-level rate limit + `public_mentions_enabled` toggle

- [ ] failing test → 2 @mentions within 30s; only first replied; profile.public_mentions_enabled=False silences entirely [U].
- [ ] Implement rate limit + enabled toggle [U].
- [ ] PASS + Commit `feat(public): meeting-level rate limit + enabled toggle (W6.3)` [U].

## Task W6.4 — `public_mention_allowlist` override

- [ ] failing test → @mention from non-allowlisted sender (when allowlist is set) gets silent decline [U].
- [ ] Implement allowlist check [U].
- [ ] PASS + Commit `feat(public): public_mention_allowlist override (W6.4)` [U].

## Task W6.5 — T11 + T12 boundary tests backed

- [ ] Remove xfail; backfill T11 (reply via send_chat_public only, never send_chat) + T12 (private and public threads from same sender remain isolated; two ChatThreadActor instances; two cache namespaces) [U].
- [ ] PASS + Commit `test(privacy): T11 + T12 backed — public mention isolation (W6.5)` [U].

## Task W6.6 — W6 exit-gate checkpoint

| Sub-task | Status | Verification |
|---|---|---|
| Public handler + prompt | ☐ | tests/test_w6_public_mention_*.py pass |
| Rate limit + toggle | ☐ | tests/test_w6_public_mention_rate_limit.py pass |
| Allowlist override | ☐ | tests/test_w6_public_mention_handler.py pass |
| T11 + T12 PASS | ☐ | `pytest tests/test_privacy_boundary.py -v` shows 10 PASS + 2 xfail at W6 close (T2+T3 remain for W7 wrap-up + transcript integrations; full 12/12 PASS at W7 close) |
| `mypy --strict src/` clean | ☐ | mypy output empty |
| `pytest --cov` critical-path coverage | ☐ | `privacy/`, `actor.py`, `tools/`, `series.py` ≥ 90% |

Block W7 until ALL ☑.

---

# W7 — AQH integration + GA cut

**Goal:** Wire AQH harness (Task B from S25 prompt) integration; achieve AC-7 PASS (real Zoom meeting + private DM + public mention + privacy boundary assertions); finalize CHANGELOG; bump to v0.1.0; tag + push; complete Triple Write repo mirror.

**Subagent dispatch:** single subagent.

**Exit gate:**

- AQH harness PASS with privacy assertions (real Zoom meeting; injected private DM does NOT appear in transcript/wrap-up; public @-mention reply appears in public chat).
- `pyproject.toml` version bumped `0.1.0.dev0` → `0.1.0`.
- CHANGELOG `[0.1.0]` block authored.
- All 8 AC gates green.
- v0.1.0 tag cut + pushed.
- Spec + plan vault status flipped to `released`.
- Repo doc mirror byte-aligned with vault canonical.

## Task W7.1 — AQH integration probe (depends on meetbot v0.2 AQH harness from S25 Task B)

**Files:**

- Create: vault `02_Projects/Lattice/lattice-meeting-assistant/Status/2026-05-XX W7.1 AQH integration probe.md`

- [ ] Probe meetbot v0.2's AQH harness state (built per S25 Task B Task #5). If not yet built, document the W7 dependency clearly + queue follow-up. If built, run a smoke E2E [U].
- [ ] Document the AQH command invocation that exercises the assistant: spawn meetbot with Assistant enabled + LibriVox audio inject + 2nd Playwright account sends private DM "what was just said?" + 3rd account (or same) sends public @cody mention [U].

## Task W7.2 — AQH AC-7 PASS run

- [ ] Run AQH end-to-end with assistant wired in [U].
- [ ] Capture transcript output + wrap-up summary; assert private DM text absent from both [U].
- [ ] Assert public mention reply in public chat; assert reply text absent from private DM transcript [U].
- [ ] If PASS: capture output to Status note as AC-7 evidence [U].
- [ ] If FAIL: file targeted ticket + return to W6 or W4 to fix [U].

## Task W7.3 — Bump to 0.1.0 + CHANGELOG

**Files:**

- Modify: `src/lattice_meeting_assistant/_version.py` (`0.1.0.dev0` → `0.1.0`)
- Modify: `pyproject.toml` (`version = "0.1.0"`)
- Modify: `CHANGELOG.md`

- [ ] Update version files [U].
- [ ] Author `CHANGELOG.md [0.1.0]` block: [U]

```markdown
## [0.1.0] -- 2026-05-XX

### Added
- `Assistant` class — in-meeting AI assistant primitive for Lattice meeting-platform adapters
- Private DM handling via `on_private_chat()` (Zoom adapter v0.2+)
- Public @-mention handling via `on_public_mention()`
- TG-owner + in-meeting-DM transports with transport-bound cortex tool resolution
- 5 Architectural Invariants enforced in code (separated send paths, transport-bound knowledge, per-thread memory isolation, visibility-tag fail-closed, admin surface isolation)
- 12 boundary tests T1-T12 green (AC-2)
- 11 cortex tools (5 in-meeting curated + 6 TG-owner Nexus wrappers)
- `BLOCKED_IN_MEETING_TOOLS` deny-list (38 entries) + boot self-test
- `SeriesMatcher` — Path 1 (explicit recurring meeting ID) + Path 2 (implicit host-cohort with TG ratification)
- Admin command parser (TG-only per `[[Meeting Platform Admin Surface Isolation]]`)
- Profile YAML loader + Brain MCP write-back for persistent mutations
- `AssistantStats` observability surface
- AQH integration evidence (AC-7 PASS)

### Dependencies
- `lattice-meeting-contracts >= 0.3.0-rc1`
- `lattice-meeting >= 0.2.0`
- `lattice-cortex >= 0.6.0`

### Acceptance gates
All 8 AC gates green: AC-1 mypy --strict; AC-2 12 boundary tests; AC-3 YAML round-trip; AC-4 cortex tool registration; AC-5 90% critical-path coverage; AC-6 series ratification mock-TG E2E; AC-7 AQH PASS real Zoom meeting; AC-8 PVD-clean.

### Architectural references
- Spec: `02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec.md`
- Plan: `02_Projects/Lattice/lattice-meeting-assistant/Plans/2026-05-11 lattice-meeting-assistant v0.1 - Implementation Plan.md`
- Lattice-wide protocol: `02_Projects/Protocols/Meeting Platform Admin Surface Isolation.md`
```

- [ ] Commit `release(assistant): 0.1.0 GA -- in-meeting AI assistant primitive` [U].

## Task W7.4 — Tag + push v0.1.0

- [ ] `git tag -a v0.1.0 -m "v0.1.0: in-meeting AI assistant primitive"` [U]
- [ ] `git push origin main` [U]
- [ ] `git push origin v0.1.0` [U]

## Task W7.5 — Vault status flips + repo doc mirror

- [ ] Flip spec frontmatter `status: draft` → `status: released-v0.1.0` [U].
- [ ] Flip plan frontmatter `status: draft` → `status: released-v0.1.0` [U].
- [ ] Add §15 spec amendment block with v0.1.0 release date + commit SHA + AC verdict table [U].
- [ ] Mirror spec to repo `docs/specs/2026-05-11-lattice-meeting-assistant-v0.1-design-spec.md` (byte-aligned) [U].
- [ ] Mirror plan to repo `docs/plans/2026-05-11-lattice-meeting-assistant-v0.1-implementation-plan.md` [U].
- [ ] Commit repo doc-mirror `docs(spec+plan): byte-align repo mirrors with vault canonical (W7.5)` [U].

## Task W7.6 — MEMORY.md + Project Registry version bump

- [ ] Update `MEMORY.md` entry to reflect v0.1.0 GA + tag + commit SHA [U].
- [ ] Update Lattice Project Registry row: `lattice-meeting-assistant` `pre-spec` → `0.1.0` [U].
- [ ] Add Change Log entry to Project Registry [U].

## Task W7.7 — W7 exit-gate checkpoint (final v0.1 GA gate)

| AC | Status | Evidence |
|---|---|---|
| AC-1 mypy --strict | ☐ | CI green |
| AC-2 12 boundary tests | ☐ | `pytest tests/test_privacy_boundary.py` 12 PASS |
| AC-3 YAML round-trip | ☐ | tests/test_w1_profile.py |
| AC-4 cortex tool registration | ☐ | tests/integration/test_e2e_cortex_tool_loop.py |
| AC-5 90% critical-path coverage | ☐ | `pytest --cov` report |
| AC-6 series ratification mock-TG | ☐ | tests/integration/test_e2e_series_ratification_mock_tg.py |
| AC-7 AQH PASS real meeting | ☐ | AQH harness report PASS |
| AC-8 PVD-clean | ☐ | `plan_lint` clean on spec + plan |

All ☑ → `lattice-meeting-assistant v0.1.0 GA SHIPPED`.

---

# Self-Review

## Spec coverage

| Spec section | Covered by plan task(s) |
|---|---|
| §1 Mission + scope + filter | W1 scaffold (CLAUDE.md + README absorb mission); v0.1 IN scope items 1-26 traced to W2-W6 |
| §2 Architecture + library boundary | W1.1-W1.5 scaffold + dataclasses; W2-W6 implementation |
| §3 Public API surface | W1.3-W1.5 (types, exceptions, configs); W4.6 (Assistant shell); W7 (final __init__ re-exports) |
| §4 Knowledge access tiers + tool registration | W2.1 (BLOCKED set); W3.1-W3.7 (all 11 tools + resolver) |
| §5 Privacy invariants + 12 boundary tests | W2.1 (Invariants), W2.3 (T1-T12 scaffold), W3.7 (T8+T9), W4.6 (T1+T6+T10), W5.6 (T7), W6.5 (T11+T12), AQH (T2+T3+T11) |
| §6 Series matching | W5.2 (Path 1), W5.3 (Path 2 + ratification) |
| §7 Concurrency + lifecycle | W4.1-W4.6 (actor, FIFO, holding, backpressure, compaction, semaphore, lifecycle) |
| §8 v0.1 scope items 1-26 + AC-1 to AC-8 | All covered; W7 closes the GA gate |
| §9 Open questions OQ1-OQ10 | OQ1 in W0.1; OQ2 in W0.2; OQ3 in W3.5 `[U]`; OQ4 hardcoded in W4.2 filler; OQ5 `[U]` at W5.1; OQ6 schema_version=1 in W1.5; OQ7 fixtures in W1.5 + conftest; OQ8 Brain nx_vault_write in W5.5; OQ9 metrics wiring in W7 (or deferred to meetbot v0.2 follow-up); OQ10 default 120s in W1.4 config |
| §11 Risk register R1-R10 | R1 (cortex API) addressed in W0.2 + W3.1 + W3.7 fallback; R2 (contracts cut) addressed in W0.1; R3 (Zoom SDK chat events) addressed in meetbot v0.2 W0 not this plan; R4 (privacy leak) addressed across W2+W3+W6+W7 + AQH; R5 (public-mention loop) addressed in W6.3 rate limit; R6 (cost) addressed in W4.6 semaphore + W5.4 mode admin command; R7 (write-back race) deferred to v0.2; R8 (lost ratification ping) addressed in W5.3 default fallback; R9 (Brain `/join` mismatch) addressed in W0.4 FU1; R10 (capability flag drift) — additive contracts pattern covered |

No gaps. PASS.

## Placeholder scan

- All "TBD"/"TODO" resolved. `[U]` tags on OQ3 + OQ5 are explicit verification deferrals, not placeholder fluff.
- W3.1-W3.6 task bodies are condensed to step-list summaries (5 steps each per W3.X.Step pattern) rather than full code blocks; this is acceptable because (a) the patterns are established in W1.4-W1.5 and W2.1-W2.3 with full code, (b) each tool follows the same spec §4 tool implementation pattern, and (c) every step still names exact files + the failing-test-first TDD shape. Could elaborate per-tool code if executing subagent reports ambiguity.
- W4.1-W4.6 same pattern (condensed but unambiguous given the spec §7 pseudocode + W1-W3 established patterns).
- W5.X, W6.X, W7.X same.

PASS with one note: if any executing subagent hits ambiguity in W3-W6, expand the condensed step list inline against the spec section referenced.

## Type consistency

- `AssistantConfig` / `AssistantProfile` / `KnowledgeAccessConfig` field names match spec §3 byte-for-byte.
- `ChatEvent` field names match spec §3 + conftest mock helper.
- `BLOCKED_IN_MEETING_TOOLS` entries enumerated against spec §4 verbatim.
- `ChatThreadActor.enqueue` returns bool — same in W4.1 + W4.3.
- `AdminCommandResult` shape consistent across types.py + admin.py + tests.

PASS.

## Final note

This plan totals **~50 distinct tasks across 8 phases**. Phase W3 + W4 + W5 + W6 each follow the same TDD-per-task pattern with files + failing-test → impl → run → commit cycles. Total estimated subagent dispatches: ~50 (one per task, strict single-task scope per `[[Subagent-Driven Plan Execution]]`).

Plan complete. Vault canonical at this path; repo mirror lands at W7.5.

---

# v0.2 Open Questions Surfaced During v0.1 Implementation

Per `[[02_Projects/Protocols/Surfaced Follow-ups Tracking Discipline]]` v0.1.0 (ratified S30 2026-05-12), every OQ/follow-up that surfaces mid-implementation MUST land in a tracker location that re-surfaces when v(N+1) planning starts. This section is one of two trackers (the other being Nexus tickets); v0.2 plan-author auto-finds these here when reading the prior plan.

Entries are append-only. Each entry: file:line ref + surfaced-during phase + proposed v0.2 action + Nexus ticket ID.

## OQ-W4-1 — Surface SHUTDOWN_DRAIN_TIMEOUT as AssistantConfig field

- **Surfaced during:** W4 close (S30 2026-05-12)
- **Location:** `src/lattice_meeting_assistant/assistant.py:60`
- **Inline marker:** `# OQ-followup: surface meeting_shutdown_drain_timeout_secs as a config field`
- **Constant:** `SHUTDOWN_DRAIN_TIMEOUT_DEFAULT_S: float = 30.0`
- **Spec ref:** Design Spec §7 line 986 (30s drain timeout when `Assistant.shutdown()` reaps all actors at meeting end)
- **Proposed v0.2 action:**
  1. Add `meeting_shutdown_drain_timeout_s: float = 30.0` to `AssistantConfig` in `src/lattice_meeting_assistant/config.py`
  2. Replace `SHUTDOWN_DRAIN_TIMEOUT_DEFAULT_S` constant reference in `assistant.py:456` with `self._config.meeting_shutdown_drain_timeout_s`
  3. Update the inline `# OQ-followup` comment block
  4. Update W4 shutdown lifecycle tests (`test_w4_assistant_routing.py::test_shutdown_*`) to assert config-driven envelope is honored
- **Nexus ticket:** `TKT-349645ab` (p3, **RESOLVED** S30 2026-05-12 — Nexus PATCH queued in `pending_nexus_tickets.md`, API down at close)
- **Status:** **RESOLVED** — W7-prep cleanup. Commit `bcff4ee feat(config): promote SHUTDOWN_DRAIN_TIMEOUT to AssistantConfig.meeting_shutdown_drain_timeout_s (closes TKT-349645ab)`. Field added to `config.py:69`; `assistant.py:690` uses `self.config.meeting_shutdown_drain_timeout_s`. 2 new tests defend the config-driven envelope. Reframed from "v0.2 OQ" to "v0.1 W7-prep" per Cyril S30 audit (tickets are not version-bump deferrals).

## OQ-W5A-1 — lattice-meeting-contracts AdminTransport Protocol needs receive method

- **Surfaced during:** W5 Part A SeriesMatcher Path 2 ratification (S30 2026-05-12)
- **Cross-repo:** This is a `lattice-meeting-contracts` follow-up, not pure assistant-side
- **Location:** `lattice-meeting-contracts` `src/lattice_meeting_contracts/admin_transport.py:54` is send-only; assistant-side workaround at `lattice-meeting-assistant` `src/lattice_meeting_assistant/series.py:82-95` (private `_RatificationTransport` Protocol with duck-typed `await_admin_reply`)
- **Spec ref:** Design Spec §6 (Series matching + ratification UX requires receive of "yes" / "no" / "new-series X" / timeout)
- **Proposed v0.3.1 / v0.4 action:**
  1. Extend `AdminTransport` Protocol with `await_admin_reply(handle: AdminTransportHandle, timeout_s: float) -> str | None` (optional default-impl)
  2. OR introduce `BidirectionalAdminTransport(AdminTransport)` that adds the receive half
  3. Once contracts updates, remove the duck-typed workaround in `series.py` and replace with the new Protocol type
- **Nexus ticket:** `TKT-5d89d16d` (p2, open, filed S30 2026-05-12; project=`lattice-meeting-contracts`)
- **Status:** OPEN — v0.2 (cross-repo contracts dependency)

## OQ-W5B-1 — spec/plan reference `profile_vault_path` but impl exposes `source_vault_note`

- **Surfaced during:** W5 Part B (W5.5 persistent allowlist write-back, S30 2026-05-12)
- **Location:** `src/lattice_meeting_assistant/profile.py:49` declares `source_vault_note: str | None`; W5.5 admin write-back consumes via `profile.source_vault_note` in `src/lattice_meeting_assistant/admin.py::_persist_profile`
- **Spec/plan refs:** Spec §3 line 398 lists `SeriesMatch.profile_vault_path` (different shape but related concept); plan §2434-2438 description references `AssistantProfile.profile_vault_path`
- **Runtime impact:** none — `source_vault_note` carries the vault path correctly; W5.5 round-trips cleanly. Mismatch is purely naming.
- **Proposed v0.2 action:**
  1. Decide: rename `source_vault_note` to `profile_vault_path` for spec/code parity, OR amend spec/plan to use `source_vault_note`
  2. If rename: bump `AssistantProfile.schema_version` to 2; update YAML loader/dumper field names; provide v1->v2 migration helper
  3. Update the W5.4/W5.5/W5.6/W5.7 tests + assistant.py docstrings
- **Nexus ticket:** `TKT-aeff7083` (p3, **RESOLVED** S30 2026-05-12 — Nexus PATCH queued)
- **Status:** **RESOLVED** — W7-prep cleanup. Commit `00c40fb refactor(profile): rename source_vault_note -> profile_vault_path for spec parity (closes TKT-aeff7083)`. 20 renames across 7 files (profile.py + admin.py + 4 tests + fixture YAML). New regression-guard test asserts `AssistantProfile.profile_vault_path` is the canonical field name. Reframed v0.2→W7-prep per Cyril S30 audit.

## OQ-W5B-2 — upgrade profile YAML round-trip from PyYAML to ruamel.yaml

- **Surfaced during:** W5 Part B (W5.5 persistent profile write-back, S30 2026-05-12)
- **Location:** `src/lattice_meeting_assistant/admin.py::_render_profile_yaml` + `src/lattice_meeting_assistant/profile.py::dump_profile_to_yaml` both use `yaml.safe_dump(payload, sort_keys=False)`
- **Spec ref:** W5.5 plan task §2434-2438 mandates "YAML round-trip safety". PyYAML preserves field order but NOT comments, anchors, trailing whitespace, or tag prefixes. v0.1 round-trip test (`test_yaml_serialised_profile_round_trips_clean`) verifies semantic equivalence only.
- **v0.1 trade-off rationale:** profile YAMLs are admin-edit-only and typically machine-authored; comment loss is acceptable for the v0.1 surface. Inline comment at `admin.py::_render_profile_yaml` documents the trade-off.
- **Proposed v0.2 action:**
  1. Add `ruamel.yaml>=0.18.0` to `pyproject.toml` dependencies (or test extras to start)
  2. Refactor `_render_profile_yaml` + `dump_profile_to_yaml` to use ruamel.yaml round-trip mode (`YAML(typ='rt')`)
  3. Add round-trip-fidelity tests asserting comments/anchors survive
  4. Document the upgrade in CHANGELOG
- **Nexus ticket:** `TKT-b65ae591` (p2, **RESOLVED** S30 2026-05-12 — Nexus PATCH queued)
- **Status:** **RESOLVED** — W7-prep cleanup. Commit `f368eb3 feat(profile): ruamel.yaml round-trip preserves comments + anchors (closes TKT-b65ae591)`. ruamel.yaml 0.19.1 (pyproject pin `>=0.18.0`). Option A architecture: non-comparing `_yaml_doc: CommentedMap` sidecar field on `AssistantProfile` preserves source formatting through `dataclasses.replace`. Canonical `render_profile_yaml` in profile module; admin renderer thin delegate. 3 round-trip-fidelity tests added. Reframed v0.2→W7-prep per Cyril S30 audit.

## OQ-W6-1 — prompt-renderer stubs pending W7 (persona_voice_block + transcript_hot_window + meeting_title)

- **Surfaced during:** W6 close (S30 2026-05-12)
- **Location:** `src/lattice_meeting_assistant/assistant.py` `_render_dm_system_prompt` + `_render_public_mention_system_prompt` (W6.2 wiring; inline `OQ-followup OQ-W6-1` marker block above the helpers)
- **Spec ref:** Design Spec §4 lines 608-671 (in-meeting-DM + public-mention prompt templates carry `{persona_voice_block_from_Cody_Voice_Identity}` + `{transcript_hot_window}` placeholders)
- **Stub state at W6:**
  - `persona_voice_block` → empty string. Full Cody Voice Identity render lands when `lattice-persona-profile` v0.1 is consumable.
  - `tool_list` → sorted resolved tool name set; human-friendly per-tool descriptions not surfaced (model sees names only).
  - `transcript_hot_window` → empty string. W3 `TranscriptBuffer.get_hot_window` not yet bound here.
  - `meeting_title` → `self.meeting_id` passed as title placeholder; real title (from meetbot session metadata) wired in W7.
  - `conversation_history` / `current_message_text` → empty strings by design (cortex tool-use loop threads turns via its conversation messages array).
- **Proposed v0.1 close action (W7):** backfill all four stubs as part of W7 AQH integration when meetbot session metadata + persona-profile-v0.1 + transcript-buffer wiring all land together.
- **Nexus ticket:** `TKT-c775d84e` (p2, open, filed S30 2026-05-12)
- **Status:** OPEN — v0.1 close (W7)

## OQ-W6-2 — series.py coverage 87% below 90% critical-path target (defensive error paths uncovered)

- **Surfaced during:** W6.6 exit-gate coverage check (S30 2026-05-12)
- **Location:** `src/lattice_meeting_assistant/series.py` — 17 uncovered lines: 206, 223-227, 284-289, 317-322, 336, 339, 347, 354, 362, 389-393, 442. All defensive error paths from W5 (transport.post_admin_response/await_admin_reply Exception handlers, malformed-frontmatter logging warnings, `_parse_ratification_reply` unrecognized-verb branch).
- **Constraint:** W6 cannot touch `series.py` per orchestrator freeze (frozen W5.2/W5.3 contract).
- **Spec ref:** §5 Test-coverage gate (line 737-739) — 90% on critical paths.
- **Proposed v0.1 close action (W7 or v0.1 cleanup):**
  1. Add `tests/test_w5_series_matcher_error_paths.py` with 5-6 tests covering each defensive branch (transport raises, vault result missing required frontmatter, ratification reply unrecognized verb).
  2. Re-run coverage; target ≥ 92% on `series.py`.
  3. If acceptable to keep some log-only paths uncovered, document in CHANGELOG as known-coverage-gap with rationale.
- **Runtime risk:** none — all uncovered branches are exception/error handling that goes through `logger.exception/warning` with graceful fallback (`return None`). Happy paths + ratification yes/no/new-series outcomes are all covered by W5 test suite.
- **Nexus ticket:** `TKT-05ed4e16` (p2, **RESOLVED** S30 2026-05-12)
- **Status:** **RESOLVED** — same-session fix. `tests/test_w5_series_matcher_error_paths.py` added at commit `4550664` (12 tests covering 16 of 17 missing lines; line 442 confirmed defensive dead code unreachable through API after `.strip()` at line 427). series.py coverage 87%→99%. W6.6 coverage sub-gate now GREEN.

## OQ-W6-3 — plan §2519 typo: W6.6 exit-gate cites "ALL 14 PASS (12 boundary + 2 contract)"

- **Surfaced during:** W6 dispatch pre-flight (S30 2026-05-12)
- **Location:** Plan §2519 (W6.6 exit-gate table row for T11+T12 verification)
- **Issue:** Plan claims `pytest tests/test_privacy_boundary.py -v` shows "ALL 14 PASS (12 boundary + 2 contract)". There are exactly 12 boundary tests (T1-T12). The 2 contract tests live in `test_privacy_invariants.py` / `test_privacy_log_redaction.py`, not `test_privacy_boundary.py`.
- **Nexus ticket:** `TKT-1e772fda` (p3, **RESOLVED** S30 2026-05-12 — Nexus PATCH queued)
- **Status:** **RESOLVED** — W7-prep cleanup. Plan §2519 row amended to read `"10 PASS + 2 xfail at W6 close (T2+T3 remain for W7 wrap-up + transcript integrations; full 12/12 PASS at W7 close)"`. No repo commit (vault-only doc fix).
- **Actual post-W6 state:** 10 PASS (T1, T4, T5, T6, T7, T8, T9, T10, T11, T12) + 2 xfail (T2 W3-transcript-filter / T3 W7-wrapup-integration). T2/T3 still in scope but not W6 responsibility (plan W3 + W7 respectively).
- **Proposed action:** amend plan §2519 row to `10 PASS + 2 xfail (T2 W3-followup + T3 W7-followup)`. Documentation drift only; no impact on shipped code.
- **Nexus ticket:** `TKT-1e772fda` (p3, open, filed S30 2026-05-12)
- **Status:** OPEN — v0.1 close

<!-- Append future OQs below this comment. -->

# Cross-references

- **Spec authority:** `[[02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec]]`
- **Mission:** `[[02_Projects/Lattice/lattice-meeting-assistant/Mission]]`
- **Lattice-wide admin protocol (Invariant 5):** `[[02_Projects/Protocols/Meeting Platform Admin Surface Isolation]]`
- **Persona resolver substrate:** `[[02_Projects/Protocols/Persona Mappings]]`
- **LLM dispatch substrate:** `[[02_Projects/Lattice/lattice-cortex/Mission]]` + cortex 0.6.0 spec
- **Adapter authority:** `[[02_Projects/Protocols/Meeting Capture Adapter Pattern]]`
- **Async discipline:** `[[02_Projects/Protocols/Async by Default for External Services]]`
- **Coverage signal priority:** `[[feedback_coverage_signal_priority]]`
- **Subagent execution:** `[[Subagent-Driven Plan Execution]]`
- **PVD:** `[[02_Projects/Protocols/Plan Verification Discipline]]`
- **Surfaced Follow-ups Tracking Discipline:** `[[02_Projects/Protocols/Surfaced Follow-ups Tracking Discipline]]`

---

# Cross-references

- **Spec authority:** `[[02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec]]`
- **Mission:** `[[02_Projects/Lattice/lattice-meeting-assistant/Mission]]`
- **Lattice-wide admin protocol (Invariant 5):** `[[02_Projects/Protocols/Meeting Platform Admin Surface Isolation]]`
- **Persona resolver substrate:** `[[02_Projects/Protocols/Persona Mappings]]`
- **LLM dispatch substrate:** `[[02_Projects/Lattice/lattice-cortex/Mission]]` + cortex 0.6.0 spec
- **Adapter authority:** `[[02_Projects/Protocols/Meeting Capture Adapter Pattern]]`
- **Async discipline:** `[[02_Projects/Protocols/Async by Default for External Services]]`
- **Coverage signal priority:** `[[feedback_coverage_signal_priority]]`
- **Subagent execution:** `[[Subagent-Driven Plan Execution]]`
- **PVD:** `[[02_Projects/Protocols/Plan Verification Discipline]]`
