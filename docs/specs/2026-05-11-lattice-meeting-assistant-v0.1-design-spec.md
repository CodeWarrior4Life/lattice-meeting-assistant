---
title: lattice-meeting-assistant v0.1 - Design Spec
project: Lattice
library: lattice-meeting-assistant
type: spec
status: released-v0.1.0-rc1
version: '0.1'
date: '2026-05-11'
session: S25
authors:
  - Cyril Grosse III (ratifier)
  - Cody (Claude Opus 4.7 1M, S25 session-9e307b5296b9)
authority:
  - "[[02_Projects/Lattice/Family]]"
  - "[[02_Projects/Lattice/lattice-meeting-assistant/Mission]]"
  - "[[02_Projects/Protocols/Plan Verification Discipline]]"
  - "[[02_Projects/Protocols/Meeting Capture Adapter Pattern]]"
  - "[[02_Projects/Protocols/Meeting Platform Admin Surface Isolation]]"
  - "[[02_Projects/Protocols/Cody Voice Identity]]"
  - "[[02_Projects/Protocols/Persona Mappings]]"
  - "[[02_Projects/Protocols/Multi-Modal Persona Reconciliation]]"
  - "[[02_Projects/Protocols/Async by Default for External Services]]"
  - "[[02_Projects/Protocols/Telegram Paging Protocol]]"
related:
  - "[[02_Projects/Lattice/lattice-meetbot/Specifications/2026-05-09 lattice-meetbot v0.2 - Streaming Participation Spec]]"
  - "[[02_Projects/Lattice/lattice-meeting/Specifications/2026-05-11 lattice-meeting v0.1 Mapping Primitive - Design Spec]]"
  - "[[02_Projects/Lattice/lattice-meeting-contracts]]"
  - "[[02_Projects/Lattice/lattice-cortex/Specifications/2026-05-10 lattice-cortex 0.6.0 Tier 2 Hoist Completion - Design Spec]]"
  - "[[02_Projects/Lattice/lattice-meeting-assistant/Research/2026-05-11 Meeting-Platform Capability Comparison - Zoom Meet Teams]]"
  - "[[02_Projects/Lattice/lattice-meeting-assistant/Decisions/2026-05-11 Public @cody mentions included in v0.1]]"
tags:
  - spec
  - lattice
  - lattice-meeting-assistant
  - v0.1
  - assistant
  - private-chat
  - public-mention
  - cortex-tool-use
  - privacy
  - pvd-conformant
aliases:
  - lattice-meeting-assistant v0.1 Spec
  - Private chat to Cody primitive spec
created: '2026-05-11'
updated: '2026-05-11'
pvd_conformant: true
blocks_on: spec
execution_mode: superpowers:subagent-driven-development
---

# lattice-meeting-assistant v0.1 — Design Spec

> **Scope.** New sibling library under the Lattice family. Implements the in-meeting AI assistant primitive consumed in-process by `lattice-meetbot` (Zoom v0.2) and future Meet/Teams sidecars. Two transports (in-meeting DM + TG-owner); two thread types (private DM per-participant + public @-mention per-meeting); single `Assistant` instance per meeting. Realizes Cyril S24 verbatim: *"i really really want the ability to add cody to a private chat. this will unlock an assistant tool ... that nobody has."*
>
> **Status.** Draft authored S25 2026-05-11. PVD-conformant after spec-self-review (§12) + lattice-pvd-preflight pass. Awaiting Cyril spec review then implementation-plan write via `superpowers:writing-plans`.

## §1 Mission, scope, filter

**Project name:** `lattice-meeting-assistant`
**Type:** Sibling library (Python ≥ 3.11), async-first
**Canonical repo:** `G:/My Drive/Projects Merge/lattice-meeting-assistant/` (per Project Registry §93 — Google Drive canonical)
**Vault folder:** `02_Projects/Lattice/lattice-meeting-assistant/`
**License:** Apache 2.0 (Lattice default). Author: CodeWarrior4Life.
**Family inheritance:** Lattice — single-purpose substrate consumed by bespokes; not a product itself.

### Mission

`lattice-meeting-assistant` is the **in-meeting AI assistant primitive** that any Lattice meeting-platform adapter (`lattice-meetbot` for Zoom; future `lattice-meet-google`, `lattice-meet-teams`) instantiates per session to receive chat messages from meeting participants, dispatch them through `lattice-cortex` with transport-bound knowledge access, and reply back in the originating channel (private DM or public meeting chat). It is the library realization of Cyril S24 verbatim feature: *"i really really want the ability to add cody to a private chat. this will unlock an assistant tool ... that nobody has."*

### Mission filter

> **"Does this preserve transport-bound knowledge isolation, per-thread message integrity, and adapter-agnostic chat routing while keeping consumers off the LLM-provider hot path?"**

Every design decision answers YES or it doesn't ship. Four components map directly:

- **Transport-bound knowledge isolation** — in-meeting DM never gets personal vault; TG-owner does (§4)
- **Per-thread message integrity** — memory keys + actor model = no cross-contamination (§5, §7)
- **Adapter-agnostic chat routing** — capability flags + `AdminTransport` ABC = Meet/Teams slot in (§2, §3)
- **Off the LLM-provider hot path** — cortex registry, never direct provider SDK (§2 cortex Axiom 1)

### v0.1 ships

- Zoom adapter (only)
- TG-owner + in-meeting-DM transports (both)
- Private DM per-participant thread + Public @-mention single-thread-per-meeting
- Curated cortex tool set for in-meeting; conservative full-Nexus surface for TG-owner
- 26-item scope enumerated in §8

### v0.1 explicitly does NOT ship

- Meet or Teams adapters (capability scaffolding lands in `lattice-meeting-contracts`; concrete adapters defer)
- Voice/TTS replies in main meeting from private prompts
- Mid-flight cancellation
- RAG layer for large public references
- Cross-meeting memory persistence default-on (opt-in flag exists but defaults off)
- Host-announcement of Cody's presence on meeting start

## §2 Architecture + library boundary

### Two-layer architecture

```
                  ┌───────────────────────────────────┐
                  │  Telegram (Cyril → @HeyCody_bot)  │
                  │  /join <url>  /admin allowlist .. │
                  └─────────────┬─────────────────────┘
                                │
                  ┌─────────────▼─────────────────────┐
                  │  Brain (obsidian-nexus)           │
                  │  /join dispatch                   │
                  │  • spawn meetbot if not joined    │
                  │  • attach TG thread → session     │
                  │  • implements AdminTransport      │
                  └─────────────┬─────────────────────┘
                                │ ENV: ASSISTANT_ADMIN_*
                                │
       ┌────────────────────────▼──────────────────────────────┐
       │  lattice-meetbot sidecar (Zoom adapter)               │
       │                                                       │
       │  ┌──────────────────────────────────────────────────┐ │
       │  │  Zoom Web SDK → chat event stream                │ │
       │  │  • is_private classifier (receiver=botUserId)    │ │
       │  │  • PUBLIC events → transcript fanout (Q4b sink)  │ │
       │  │  • PUBLIC + @mention(self) → Assistant.public    │ │
       │  │  • PRIVATE events → Assistant.private            │ │
       │  └─────────────────────┬────────────────────────────┘ │
       │                        │                              │
       │  ┌─────────────────────▼────────────────────────────┐ │
       │  │  lattice_meeting_assistant.Assistant             │ │
       │  │  (THIS LIBRARY)                                  │ │
       │  │                                                  │ │
       │  │  per-thread ChatThreadActor[(mtg, persona)]      │ │
       │  │  per-meeting ChatThreadActor[(mtg, "public")]    │ │
       │  │       │                                          │ │
       │  │       └─→ cortex.registry.call(                  │ │
       │  │              consumer="lattice-meeting-assistant"│ │
       │  │              task=<tier from msg flag>           │ │
       │  │              tools=resolve_tool_set(transport)   │ │
       │  │              cache_ns=(mtg, persona|"public")    │ │
       │  │           )                                      │ │
       │  └─────────────────────┬────────────────────────────┘ │
       │                        │                              │
       │  ┌─────────────────────▼────────────────────────────┐ │
       │  │  MeetingSession.send_chat(to_user_id, text)      │ │
       │  │     OR send_chat_public(text)                    │ │
       │  │  (NEVER broadcast; explicit positional receiver) │ │
       │  └──────────────────────────────────────────────────┘ │
       └───────────────────────────────────────────────────────┘
                                │
                                ▼
                  ┌───────────────────────────────────┐
                  │  lattice-cortex 0.6.0+ substrate  │
                  │  AgentSession, tool-use, prompt-  │
                  │  cache, 5-provider fallback       │
                  └───────────────────────────────────┘
```

### Library boundary — what `lattice-meeting-assistant` owns

✅ **Owned:**

- `Assistant` class — main entry point; per-meeting instance
- `ChatThreadActor` — per-(meeting, persona) and per-(meeting, "public") FIFO actor
- `KnowledgeAccessConfig` + `resolve_tool_set(transport, profile)` — tool registration policy
- `SeriesMatcher` — explicit recurring-id + implicit host-cohort matching
- `AssistantConfig` + `AssistantProfile` (YAML loader for recurring-series profiles)
- Per-transport admin command parser (`Assistant.admin_command()`)
- Cortex tool implementations: `SearchMeetingTranscriptTool`, `ReadMeetingTranscriptWindowTool`, `SearchPastMeetingsTool`, `SearchPublicReferencesTool`, `WebSearchTool`, plus TG-owner-only Nexus wrappers
- Privacy invariants in code (`is_private` filter enforcement, send-method separation, `BLOCKED_IN_MEETING_TOOLS` constant)
- Public-mention handler (`PublicMentionHandler`) + public-variant system prompt
- Filler-pool resolver (loaded at boot from `Cody Voice Identity`-derived hardcoded subset for v0.1; vault-load defers to v0.2 — see §9 OQ4)

❌ **Not owned (consumed from elsewhere):**

- LLM dispatch — `lattice-cortex` (≥ 0.6.0; tool-use hard dep — see §9 OQ2)
- Persona resolution — `lattice-meeting` (≥ 0.2.0; consumer of `lattice_meeting.persona`)
- Chat send/receive primitives + capability flags + `AdminTransport` ABC — `lattice-meeting-contracts` (next release — see §9 OQ1)
- Concrete chat platform integration — the consuming adapter (`lattice-meetbot` v0.2+ for Zoom; future siblings)
- Concrete admin transport — Brain owns the TG transport (`BrainTGAdminTransport`); other deployments BYO
- Vault read/write — Brain Nexus API / MCP tools (`nx_vault_*`, `nx_references_search`, etc.)
- Meeting transcript pipeline — meetbot owns; this library subscribes to an in-process `TranscriptBuffer` protocol meetbot exposes

### Dependency graph (v0.1)

```
lattice-meetbot v0.2+
    │ imports
    ▼
lattice-meeting-assistant v0.1
    │ imports
    ├─→ lattice-meeting-contracts >= 0.3.0-rc1  (NEW: capability flags + AdminTransport + TranscriptBuffer)  [V:OQ1]
    ├─→ lattice-meeting           >= 0.2.0      (persona resolver)
    └─→ lattice-cortex            >= 0.6.0      (LLM dispatch + tool-use)                                    [V:OQ2]
```

### Library shape

- Pure Python ≥ 3.11, async-first (per `[[Async by Default for External Services]]`)
- No FastAPI / HTTP surface of its own — library, not a service; runs in-process in consuming sidecar
- No vault write paths directly — TG-transport admin commands that mutate profile YAMLs go through Brain MCP `nx_vault_write` (uniformity + audit log; see §9 OQ8)
- Production host: Cypher (matches meetbot v0.2)
- Testing tier: `pytest` + `pytest-asyncio` + `pytest-cov`; 90% coverage on critical paths per `[[feedback_coverage_signal_priority]]`

## §3 Public API surface

Small surface — instantiation, lifecycle, message handling, admin commands. Internal types (actor, queue) are private.

### Top-level package: `lattice_meeting_assistant`

```python
# Public re-exports — single import point for consumers
from lattice_meeting_assistant import (
    Assistant,
    AssistantConfig,
    AssistantProfile,
    KnowledgeAccessConfig,
    SeriesMatcher, SeriesMatch,
    AdminCommandResult,
    PrivacyBoundaryViolation,         # exception
    AdminAuthorizationDenied,         # exception
    CapabilityNotSupported,           # exception
    TierName,                         # Literal["interactive", "research"]
)
```

### `Assistant` — the primary entry point

One instance per meeting session. Consuming sidecar creates, drives, and reaps.

```python
class Assistant:
    """In-meeting AI assistant primitive.

    Async-first. One instance per meeting. Consuming sidecar feeds chat
    events via on_private_chat() / on_public_mention() and admin events
    via admin_command(). Outbound replies go through the MeetingSession
    callbacks (never via this class directly).
    """

    def __init__(
        self,
        *,
        meeting_id: str,
        session: MeetingSession,                  # from lattice-meeting-contracts
        persona_resolver: PersonaResolver,        # from lattice_meeting.persona
        transcript_buffer: TranscriptBuffer,      # from lattice-meeting-contracts; meetbot impls
        cortex_registry: CortexRegistry,          # from lattice-cortex
        brain_mcp: BrainMCPClient | None,         # None disables Brain-backed tools
        admin_transport: AdminTransport | None,   # None = capture-only, no admin surface
        config: AssistantConfig,
        profile: AssistantProfile,
    ) -> None: ...

    async def on_private_chat(self, event: ChatEvent) -> None:
        """Route private DM into per-(meeting, persona) actor. Returns
        immediately; reply lands on session.send_chat() when ready.
        Raises PrivacyBoundaryViolation if event lacks is_private tag
        (Invariant 4 fail-closed)."""

    async def on_public_mention(self, event: ChatEvent) -> None:
        """Route public @-mention into per-(meeting, 'public') actor.
        Returns immediately; reply lands on session.send_chat_public()
        when ready. Subject to profile.public_mentions_enabled +
        public_mention_allowlist + public_mention_rate_limit_per_meeting_s."""

    async def admin_command(
        self,
        cmd: str,
        ratifying_user_canonical_id: str,
        transport_handle: AdminTransportHandle,
    ) -> AdminCommandResult:
        """Parse + dispatch admin command. Validates ratifying user is
        in profile.admins (else raises AdminAuthorizationDenied). Mutates
        allowlist/state in-process and (for `persistent` flag) writes back
        to profile YAML via Brain MCP nx_vault_write. Returns structured
        response for the transport to relay back."""

    async def start(self) -> None:
        """Wire transcript-buffer subscription, register cortex tools per
        transport, run tool-resolver self-test (asserts BLOCKED set is
        disjoint from in-meeting-dm tools), init actor pool."""

    async def shutdown(self, *, drain_timeout_s: float = 30.0) -> None:
        """Drain in-flight actors; reap; flush observability."""

    @property
    def stats(self) -> AssistantStats:
        """Observability surface — actor count, in-flight cortex calls,
        per-thread queue depths, total tokens consumed (cost-attributed
        per cortex Axiom 4). Wired into meetbot /metrics (see §9 OQ9)."""
```

### `AssistantConfig` — behavioral knobs

```python
@dataclass(frozen=True)
class AssistantConfig:
    # Identity-in-chat (Q3)
    auto_intro: bool = False
    disclose_ai: bool = False                            # default OFF per Cody Voice Identity §Banned
    address_by_canonical_name: bool = True
    canonical_name_min_confidence: float = 0.85          # see §9 OQ5

    # Latency + degradation (Q5)
    default_tier: TierName = "interactive"               # Sonnet
    deep_tier: TierName = "research"                     # Opus
    deep_tier_message_flag: str = "/think"               # opt-in syntax
    holding_message_after_ms: int = 3000
    max_response_tokens: int = 200
    per_sender_rate_min_interval_ms: int = 2000

    # Concurrency (Q7)
    per_thread_queue_depth: int = 5
    per_meeting_global_concurrency: int = 4
    actor_post_leave_grace_s: int = 60
    actor_history_max_tokens: int = 16000

    # Memory (Q4c + Q6)
    remember_across_meetings: bool = False               # opt-in only

    # Series matching (Q6 overlay)
    series_ratification_timeout_s: int = 120             # see §9 OQ10

    # Observability
    debug_chat_content: bool = False                     # if True, DEBUG logs include content
```

### `AssistantProfile` — per-meeting/series policy

```python
@dataclass(frozen=True)
class AssistantProfile:
    profile_id: str                                      # slug; matches YAML file
    schema_version: int = 1                              # see §9 OQ6
    series_id: str | None                                # explicit recurring or implicit-bound

    # Whitelist policy (Q4a)
    dm_allowlist: tuple[CanonicalPersonaId, ...]
    admins: tuple[CanonicalPersonaId, ...]
    dm_min_confidence: float = 0.85
    allow_mapped_dm: bool = True
    allow_anonymous_dm: bool = False

    # Public mentions (Q4 overlay — Section 8 §24-26)
    public_mentions_enabled: bool = True
    public_mention_allowlist: tuple[CanonicalPersonaId, ...] | None = None  # None = anyone-can-mention
    public_mention_rate_limit_per_meeting_s: int = 30

    # Knowledge access (Q6)
    knowledge: KnowledgeAccessConfig

    # Series matching context
    series_match_binding: Literal["explicit", "implicit-host-cohort", "none"] = "none"
    series_match_confidence: Literal["high", "medium", "ratified-low", None] = None

    # Provenance
    source_vault_note: str | None
    in_memory_mutations_history: tuple[ProfileMutation, ...] = ()
```

### `KnowledgeAccessConfig`

```python
@dataclass(frozen=True)
class KnowledgeAccessConfig:
    # Architectural Invariant #2 — in-meeting DM hard-deny on personal vault
    allow_personal_vault: bool = False                   # MUST be False for in-meeting-dm transport

    # Transcript (Q6 overlay — ALWAYS ON for in-meeting DM; cannot disable)
    transcript_hot_window_seconds: int = 300
    enable_transcript_search_tool: bool = True

    # Past meetings (series-scoped, configurable)
    enable_past_meetings_search: bool = True

    # Public references
    public_references: tuple[str, ...] = ()              # vault paths
    enable_public_references_tool: bool = True

    # Web search
    enable_web_search: bool = True
```

### `SeriesMatcher` (see §6)

```python
class SeriesMatcher:
    async def match(self, meeting_metadata: MeetingMetadata) -> SeriesMatch | None: ...

@dataclass(frozen=True)
class SeriesMatch:
    series_id: str
    binding: Literal["explicit", "implicit-host-cohort"]
    confidence: Literal["high", "medium"]
    requires_ratification: bool
    cohort_overlap_score: float | None
    profile_vault_path: str
```

### `AdminTransport` ABC

Lands in `lattice-meeting-contracts` (see §9 OQ1):

```python
class AdminTransport(Protocol):
    """Contract for routing admin command responses out of the Assistant.

    Concrete impls (NOT in this library):
      - BrainTGAdminTransport (lives in Brain — Cyril's deployment)
      - LocalAdminTransport (HTTP /admin route — v0.2)
      - SlackAdminTransport (BYO — v0.2+)
    """

    kind: Literal["tg-owner", "tg-cohost", "in-meeting-dm", ...]

    async def post_admin_response(
        self,
        handle: AdminTransportHandle,
        response_text: str,
    ) -> None: ...
```

### Admin command syntax

All admin commands route through TG transport per `[[Meeting Platform Admin Surface Isolation]]`. In-meeting DM handler explicitly rejects strings matching the admin grammar — surfaces user-facing *"admin commands not supported here"* reply.

```
allowlist add <canonical-persona-id>                      # session-scoped
allowlist add <canonical-persona-id> persistent           # writes back to profile YAML
allowlist remove <canonical-persona-id>
allowlist show

mode <interactive|research>                               # session-scoped tier change
mute                                                      # toggle assistant off mid-meeting
unmute
help                                                      # list available commands
status                                                    # actor count, in-flight, recent activity
```

### Exceptions

```python
class PrivacyBoundaryViolation(Exception):
    """Raised when a chat event lacks an is_private tag (Invariant 4 fail-closed)."""

class AdminAuthorizationDenied(Exception):
    """Raised when admin_command() called with non-admin ratifying user."""

class CapabilityNotSupported(Exception):
    """Raised when caller invokes a method gated on a platform capability flag
    that the current platform's PlatformChatCapability denies."""
```

## §4 Knowledge access tiers + cortex tool registration

This is the operational heart of Architectural Invariant #2.

### Resolver

```python
def resolve_tool_set(
    transport: AdminTransport,
    profile: AssistantProfile,
    *,
    transcript_buffer: TranscriptBuffer,
    brain_mcp: BrainMCPClient | None,
) -> list[CortexTool]:
    """Default-deny: explicitly enumerate tools per transport."""

    if transport.kind == "tg-owner":
        return _resolve_tg_owner_tools(profile, transcript_buffer, brain_mcp)
    elif transport.kind == "in-meeting-dm":
        return _resolve_in_meeting_dm_tools(profile, transcript_buffer, brain_mcp)
    else:
        raise CapabilityNotSupported(
            f"No tool set defined for transport.kind={transport.kind!r}"
        )
```

### v0.1 in-meeting-dm tool set (curated)

| Tool | Source | v0.1 default | Profile knob |
|---|---|---|---|
| `search_meeting_transcript(query, time_range?)` | In-process `TranscriptBuffer` (current meeting) | always enabled (hard invariant) | `enable_transcript_search_tool` |
| `read_meeting_transcript_window(seconds=300)` | In-process buffer; returns formatted recent slice | always enabled | n/a |
| `search_past_meetings(query, series_id?, time_range?)` | Brain `nx_vault_search` filtered by `series_id` frontmatter | enabled | `enable_past_meetings_search` |
| `search_public_references(query)` | Brain `nx_references_search` scoped to `profile.public_references` paths | enabled | `enable_public_references_tool` |
| `web_search(query)` | Brain `deep_research` (lightweight mode) — see §9 OQ3 | enabled | `enable_web_search` |

### `BLOCKED_IN_MEETING_TOOLS` (hard deny — Architectural Invariant #2 enforcement)

Enumerated as `frozenset[str]` constant in code. Resolver asserts disjointness at boot.

```
search_vault              # full personal vault
read_note                  # full personal vault read (any path)
search_email
read_email
nx_calendar_read
nx_calendar_write
create_calendar_event
nx_contacts_read
nx_contacts_search
nx_contacts_add
nx_contacts_update
nx_db_query
nx_vault_multi_read
nx_vault_multi_search
nx_vault_query
nx_vault_write
deep_research             # full mode — only lightweight via web_search wrapper
nx_context_gather
download_media
instagram_ingest
x_status
x_sync_bookmarks
youtube_playlists
youtube_sync_playlist
search_whatsapp
bible_lookup              # not blocked semantically; just out of v0.1 in-meeting scope
strongs_lookup            # same
create_note
create_reminder
create_ticket
flush_note_queue
ingest_url
share_note
update_note
update_ticket
list_tickets
brain_chat                # would be a circular dispatch
vault_ask                 # full vault Q&A — TG-only
```

### v0.1 tg-owner tool set (conservative full surface)

| Tool | Source | v0.1 default |
|---|---|---|
| All in-meeting-dm tools | (above) | enabled |
| `search_vault(query)` | Brain `nx_vault_search` | enabled |
| `read_note(path)` | Brain `nx_vault_read` | enabled |
| `search_references(query)` | Brain `nx_references_search` (full, not scoped) | enabled |
| `nx_calendar_read(query)` | Brain calendar | enabled |
| `nx_email_search(query)` | Brain email search | enabled |
| `vault_ask(question)` | Brain `vault_ask` (Q&A) | enabled |

**Deferred to v0.2 for tg-owner:** `deep_research` (full mode — cost gate; spike + verify first), `nx_contacts_*`, `nx_db_query`, `download_media`, `instagram_ingest`, `x_*`, `youtube_*`, `bible_lookup`, `strongs_lookup`, `read_email` (full), `nx_calendar_write`, vault-mutating tools (`create_note`, `update_note`, `share_note`, `create_ticket`, `update_ticket`, `create_reminder`, `create_calendar_event`).

### Tool implementation pattern

```python
class SearchMeetingTranscriptTool(CortexTool):
    name = "search_meeting_transcript"
    description = (
        "Search the current meeting's transcript (everything said so far) "
        "for content matching the query. Returns matching utterances with "
        "timestamps. Use when the user asks about something said earlier."
    )

    def __init__(self, transcript_buffer: TranscriptBuffer) -> None:
        self._buf = transcript_buffer

    async def invoke(self, query: str, time_range: str | None = None) -> dict:
        results = self._buf.search(query, time_range=time_range)
        return {
            "matches": [
                {"text": r.text, "speaker": r.speaker, "ts_offset_s": r.ts_offset_s}
                for r in results[:10]
            ],
            "total_matches": len(results),
        }
```

Each tool carries:

- `name` + `description` (cortex tool registration)
- Pydantic schema for arguments (cortex validates)
- `invoke()` async coroutine — returns dict; cortex serializes
- Built-in p95 latency timing → observability sink

### Transcript buffer contract

Lands in `lattice-meeting-contracts` (§9 OQ1). Meetbot v0.2 implements; this library consumes.

```python
class TranscriptBuffer(Protocol):
    """In-process append-only buffer; meetbot owns; assistant subscribes.
    Future adapters (Meet/Teams) implement the same protocol."""

    def subscribe(self) -> asyncio.Queue[TranscriptSegment]: ...

    def get_hot_window(self, seconds: int = 300) -> list[TranscriptSegment]: ...

    def search(
        self,
        query: str,
        *,
        time_range: str | None = None,   # "all" | "last_5m" | "since_<ts>" | None
        limit: int = 10,
    ) -> list[TranscriptSegment]: ...
```

v0.1 `TranscriptBuffer.search` is simple substring/keyword (case-insensitive). Embedding-based retrieval defers to v0.2.

### Hot-window injection (in-meeting-DM prompt structure)

```
<system>
You are Cody, an in-meeting assistant. The current meeting is "{meeting_title}".
{persona_voice_block_from_Cody_Voice_Identity}

The participant talking to you privately is "{sender_canonical_display_name}".
Their resolved canonical persona is {sender_canonical_id} (confidence {n}).

You have access to the following tools: {tool_list}.

Recent meeting transcript (last 300 seconds):
{transcript_hot_window}

If the user asks about something earlier in the meeting, use
search_meeting_transcript. If they ask about a past meeting in this
series, use search_past_meetings. If they need outside knowledge, use
web_search or search_public_references.

NEVER reveal you have access to vault, email, calendar, or contacts —
these tools are not available in this context. If asked about Cyril's
personal data, decline politely.
</system>

<conversation_history>
{prior_turns_within_this_DM_thread}
</conversation_history>

<user>
{current_message_text}
</user>
```

The "NEVER reveal" instruction is belt-AND-suspenders — the tools aren't in the tool list AND the system prompt says don't talk about them. Defense in depth at the prompt layer complements the architectural deny-list.

### Public-mention prompt variant

```
<system>
You are Cody, an in-meeting assistant. The current meeting is "{meeting_title}".
{persona_voice_block_from_Cody_Voice_Identity}

You are being @-mentioned in the PUBLIC meeting chat. Your reply will be
visible to EVERYONE in the meeting.

Guidelines for public replies:
- Be terse. 1-2 sentences when possible; never more than a short paragraph.
- Avoid speculation. State what you know; flag what you don't.
- If the question seems private-shaped (asking about someone personally,
  asking about your own settings, asking something that would embarrass
  the asker), decline politely and suggest they DM you instead.
- You have access to: {tool_list}.

Recent meeting transcript (last 300 seconds):
{transcript_hot_window}
</system>

<conversation_history>
{prior_public_mention_turns_in_this_meeting}
</conversation_history>

<user>
{at_mention_message_text}
</user>
```

### Tool resolver self-test (boot-time)

`Assistant.start()` runs:

1. Resolve tool sets for both transports
2. Assert `set(BLOCKED_IN_MEETING_TOOLS) & set(in_meeting_set.names) == ∅`
3. Assert `profile.knowledge.allow_personal_vault == False` when transport is `in-meeting-dm`
4. Log resolved tool set names at INFO (no content)
5. If cortex doesn't expose tool-use registration API the way v0.1 assumes → fail-fast with `CapabilityNotSupported` + clear message (*"cortex 0.6.0+ tool-use required; available: 0.x"*) — see §9 OQ2

## §5 Privacy invariants + boundary tests

### Five Architectural Invariants

> **Invariant 1 — Separated Send Paths.**
> `MeetingSession.send_chat(to_user_id: str, message: str)` is required-positional on `to_user_id`. `MeetingSession.send_chat_public(message: str)` is a separate method on a separate code path. There is no `broadcast=True` flag, no default broadcast, no fallback. The Zoom adapter implements both; in-meeting-DM replies route exclusively through `send_chat`; public-mention replies route exclusively through `send_chat_public`. Lands in `lattice-meeting-contracts`.

> **Invariant 2 — Transport-Bound Knowledge Access.**
> The `Assistant` resolves its cortex tool set based on the originating transport at session-start time. The in-meeting DM transport receives only the curated tool set (transcript-search + web + public-refs + optional past-meetings-in-series); the TG-owner transport receives the full Nexus surface. Tool sets are explicitly enumerated per transport (default-deny on new tools). Same `Assistant` instance can serve both transports concurrently within a meeting; tool sets do not commingle.

> **Invariant 3 — Per-Thread Memory Isolation.**
> Conversation memory keys on `(meeting_id, canonical_persona_id)` for private DMs and `(meeting_id, "public")` for public mentions. Two participants in the same meeting → two completely separate memory contexts; private and public threads from the same sender → two completely separate memory contexts. Cortex prompt-cache namespace mirrors the same key, ensuring no cache crossover. Cross-meeting persistence requires explicit `remember_across_meetings: True` opt-in per profile; default OFF.

> **Invariant 4 — Visibility-Tag Fail-Closed.**
> Every chat event reaching the Assistant carries an `is_private: bool` tag (or platform equivalent — Zoom: `receiver == self.bot_user_id`). Events without a tag are REJECTED at ingest with `PrivacyBoundaryViolation` raised + observability event fired. No silent default; ambiguity = refuse.

> **Invariant 5 — Admin Surface Isolation (lattice-wide protocol).**
> Per `[[Meeting Platform Admin Surface Isolation]]`, admin commands route exclusively through TG transport. In-meeting DM handler explicitly rejects strings matching the admin command grammar — surfaces user-facing "admin commands not supported here" reply.

### Boundary tests (12 — must pass at v0.1 ship)

`tests/test_privacy_boundary_*.py`:

| # | Test | Asserts | Tier |
|---|---|---|---|
| **T1** | Two parallel DMs from senders A and B in same meeting | Memory contexts isolated; distinct cortex cache namespaces; replies to correct sender's `userId` only | unit |
| **T2** | Private DM → meetbot transcript callback | Private DM text never appears in `/segments` POST body; only `is_private=False` events flow | unit |
| **T3** | Private DM → wrap-up summary generation | Private DM text never appears in wrap-up source corpus | integration (with `lattice-meeting-wrapup` mock) |
| **T4** | Attempt `send_chat()` without `to_user_id` positional | Raises `TypeError` at type-check time (contract); no runtime broadcast path exists | unit |
| **T5** | Chat event with missing `is_private` field | Raises `PrivacyBoundaryViolation`; observability event fires; reply NOT sent | unit |
| **T6** | Same prompt from sender A and sender B | Two independent cortex calls; no cache hit cross-sender; verified via cortex `cost_records` row count | unit + cortex integration |
| **T7** | In-meeting DM containing `allowlist add X` | Reply: "admin commands not supported here"; allowlist NOT mutated; no admin response sent | unit |
| **T8** | TG-transport tool resolver returns `search_vault`; in-meeting-DM resolver does NOT | Resolver self-test; `BLOCKED_IN_MEETING_TOOLS ∩ resolved_for_in_meeting_dm == ∅` | unit |
| **T9** | Profile YAML attempts to enable `search_vault` for in-meeting-dm transport | `KnowledgeAccessConfig` load raises `ValueError` at parse time | unit |
| **T10** | Per-thread queue depth exceeded (6 msgs from one sender) | 6th msg triggers backpressure reply; 1-5 still processed in FIFO; cortex calls bounded by global semaphore | unit |
| **T11** | Public mention reply lands in public chat only | Sent via `send_chat_public`, never via `send_chat`; no private-thread mutation | unit |
| **T12** | Private DM + public mention from same sender in same meeting | Two independent `ChatThreadActor` instances; cortex calls in independent cache namespaces; replies do not commingle | unit |

### AQH integration (Task B from S25 prompt)

AQH validates T2 + T3 + T11 against a real Zoom meeting:

- Spawn meetbot + Assistant
- Inject reference audio (LibriVox) for transcript content
- Playwright-controlled second account sends a private DM ("what was just discussed?")
- Playwright-controlled third account (or same second account after the DM) sends a public @cody mention
- Assertions:
  - Assistant replies in private DM (PASS)
  - Assistant replies publicly to @-mention (PASS)
  - Public meeting transcript (sidecar `/segments` payload + final vault note) does NOT contain DM text (privacy boundary)
  - Wrap-up summary does NOT contain DM text
  - DM reply text does NOT appear in public-mention thread context
- AQH emits `[AQH] PASS — privacy boundary verified` if all pass; FAIL with details otherwise

### Test-coverage gate

Per S15 coverage-signal-priority: v0.1 = 90% on critical paths with real-consumer-integration evidence. Critical paths = privacy invariant enforcement code (Invariants 1-5). Acceptable line-coverage % on glue code is lower; what matters is the 12 boundary tests + AQH PASS.

## §6 Series matching

### Two paths

```
┌─ Path 1: explicit (recurring meeting ID) ─────────────────┐
│  zoom_recurring_meeting_id = "81050295086"                 │
│  → Query vault: Meeting Series/ frontmatter match          │
│  → HIGH confidence, no ratification                        │
│  → Apply series profile at session start                   │
└────────────────────────────────────────────────────────────┘

┌─ Path 2: implicit (host + cohort overlap) ────────────────┐
│  recurring_id   = None (ad-hoc URL)                        │
│  host_canonical = "cyril-grosse"                           │
│  → Query vault: Meeting Series/ host_canonical match       │
│  → For each candidate:                                     │
│       overlap = jaccard(this_mtg.attendees,                │
│                         candidate.typical_participants)    │
│  → Best where overlap_score >= 0.5:                        │
│       MEDIUM, requires_ratification = True                 │
│  → Else: no match, treat as one-off                        │
│                                                            │
│  → Ratification flow (refinement-event pattern):           │
│       1. SeriesMatcher emits TG ping to admin              │
│       2. Admin replies in same TG thread (y/n/new-series)  │
│       3. Until ratified, profile = default                 │
│          (allowlist=[cyril], default-deny everywhere)      │
│       4. On `yes`: apply series profile; append to vault   │
│          note ratifications log                            │
│       5. On `no` or timeout: stay on default               │
│       6. On `new-series <slug>`: create new vault note     │
└────────────────────────────────────────────────────────────┘
```

### Series vault note shape

```yaml
# 02_Projects/Lattice/lattice-meetbot/Meeting Series/sabbath-school-class.yaml
---
series_id: sabbath-school-class
series_name: "Sabbath School class"
binding_type: explicit                         # explicit | implicit-host-cohort
host_canonical_id: cyril-grosse
zoom_recurring_meeting_id: "81050295086"
typical_participants:
  - cyril-grosse
  - helen-christopherson
  - helen-brager
  - pat-grauer
  # ... more
assistant_profile: "Profiles/sabbath-school.yaml"
created: 2026-05-11
created_session: S25
ratifications:
  - { ts: "2026-05-11T17:00:00Z", action: "created", by: "cyril-grosse", binding: "explicit", session: "S25" }
---

# Sabbath School class

Series for Cyril's recurring Sabbath School class on Zoom.

Host: Cyril. Typical attendance ~10-20 regulars listed in `typical_participants`.

This file is owned by `lattice-meeting-assistant` SeriesMatcher; mutations
flow through ratified TG admin commands or direct vault edits.
```

### Edge cases

- **No `host_canonical_id` resolved** (host is anonymous joiner with no persona mapping) → SeriesMatcher returns `None`; treat as one-off; default profile only.
- **Multiple Path-2 candidates above threshold** → pick highest overlap; secondary candidates listed in ratification ask.
- **Path 1 match exists but profile YAML is missing** → log WARNING; treat as one-off; surface to admin via TG so they can rebuild the profile.

### v0.1 scope

- Path 1 (explicit recurring ID) — ships
- Path 2 (implicit host-cohort) — ships, BUT only with TG ratification (no silent auto-binding)
- `typical_participants` updated automatically per ratification (additive on `yes`; no auto-removal). Decay/aging logic defers to v0.2.

### v0.2+ deferrals

- Participant-specific scoping (new attendee doesn't see meetings from before their join date)
- Auto-decay of `typical_participants` who haven't shown up recently
- Cross-platform series merging (same series held on Zoom AND in-person → unified series ID)
- Calendar-based explicit recurring ID for Meet/Teams (spec landings alongside those adapters)

## §7 Concurrency + lifecycle

### Three concurrency layers

```
┌─ Layer 1: Per-meeting Assistant ───────────────────────────┐
│  One async task for boot/shutdown                          │
│  Owns: actor pool, global semaphore, shared cortex client  │
│  Coordinates with meetbot lifespan via start()/shutdown()  │
└────────────────────┬───────────────────────────────────────┘
                     │
                     ▼
┌─ Layer 2: Per-thread ChatThreadActor ──────────────────────┐
│  Keys: (meeting_id, persona_id) or (meeting_id, "public")  │
│  Bounded FIFO queue (depth=5 default)                      │
│  Single worker task: drain → dispatch → reply              │
│  Strict serialization within thread; parallel across       │
│  Holds conversation history up to 16k tokens               │
└────────────────────┬───────────────────────────────────────┘
                     │ acquires
                     ▼
┌─ Layer 3: Global semaphore (per Assistant instance) ───────┐
│  asyncio.Semaphore(max_concurrent=4)                       │
│  Caps simultaneous cortex.registry.call across all threads │
│  Prevents one meeting from saturating cortex / cost budget │
└────────────────────────────────────────────────────────────┘
```

### `ChatThreadActor` internals

```python
class ChatThreadActor:
    """One per (meeting_id, persona_id) or (meeting_id, 'public').
    Single worker task drains a bounded FIFO queue and dispatches to
    cortex serially."""

    def __init__(
        self,
        *,
        key: tuple[str, CanonicalPersonaId | Literal["public"]],
        cortex_call: Callable,                  # closure with shared semaphore
        session: MeetingSession,
        config: AssistantConfig,
        tool_set: list[CortexTool],
        system_prompt_renderer: Callable[[], str],
    ) -> None:
        self.key = key
        self._queue: asyncio.Queue[ChatEvent] = asyncio.Queue(
            maxsize=config.per_thread_queue_depth
        )
        self._history: list[ConversationTurn] = []
        self._worker: asyncio.Task | None = None
        self._idle_since: float | None = None
        ...

    async def enqueue(self, event: ChatEvent) -> bool:
        """Returns False if queue full (caller surfaces backpressure reply)."""
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

    async def _worker_loop(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                reply = await self._dispatch_with_holding_message(event)
                if self.key[1] == "public":
                    await self._session.send_chat_public(reply)
                else:
                    await self._session.send_chat(
                        to_user_id=event.sender_user_id,
                        message=reply,
                    )
            except CortexUnavailable:
                fallback = _filler("having_trouble_thinking_right_now")
                if self.key[1] == "public":
                    await self._session.send_chat_public(fallback)
                else:
                    await self._session.send_chat(
                        to_user_id=event.sender_user_id,
                        message=fallback,
                    )
            except Exception:
                log.exception("actor %s dispatch error", self.key)
                # graceful user-facing fallback; never expose stack

    async def _dispatch(self, event: ChatEvent) -> str:
        if self._history_token_count() > config.actor_history_max_tokens:
            self._history = await _compact_history(self._history)

        result = await self._cortex_call(
            consumer="lattice-meeting-assistant",
            task=event.tier or config.default_tier,
            cache_namespace=self.key,
            system_prompt=self._system_prompt_renderer(),
            conversation=self._history + [event_to_turn(event)],
            tools=self._tool_set,
        )

        self._history.append(event_to_turn(event))
        self._history.append(assistant_turn(result))
        return result.text
```

### Holding-message logic

```python
async def _dispatch_with_holding_message(self, event):
    dispatch_task = asyncio.create_task(self._dispatch(event))
    try:
        return await asyncio.wait_for(
            dispatch_task,
            timeout=config.holding_message_after_ms / 1000.0,
        )
    except asyncio.TimeoutError:
        filler = _filler("one_moment")  # from Cody Voice Identity §Suggested
        if self.key[1] == "public":
            await self._session.send_chat_public(filler)
        else:
            await self._session.send_chat(
                to_user_id=event.sender_user_id,
                message=filler,
            )
        return await dispatch_task  # await the real reply, send when ready
```

### Backpressure on burst

```python
async def on_private_chat(self, event):
    # Invariant 4 fail-closed check
    if not hasattr(event, "is_private") or event.is_private is None:
        raise PrivacyBoundaryViolation(f"event lacks is_private tag: {event.id}")

    # Q4a tier check + allowlist
    if not self._is_allowed(event.sender_canonical_id):
        return  # silent deny — no reply, no spam

    actor = self._get_or_spawn_actor(event)
    if not await actor.enqueue(event):
        await self._session.send_chat(
            to_user_id=event.sender_user_id,
            message="I'm catching up on your earlier messages — give me a sec.",
        )
        return
```

### Actor lifecycle

| Event | Action |
|---|---|
| First DM from sender | Spawn private-DM actor, start worker |
| First @-mention in meeting | Spawn public-mention actor (singleton per meeting), start worker |
| Sender leaves meeting | Mark `idle_since=now()`; start 60s reap timer (private actor only; public stays) |
| Sender rejoins within 60s | Cancel timer; same actor continues (memory preserved) |
| 60s reap fires | Drain queue; cancel worker; remove from actor pool |
| Meeting ends (`Assistant.shutdown()`) | Drain all queues (timeout=30s); cancel all workers; flush observability |
| History exceeds 16k tokens | Cortex `ContextCompactor` summarizes oldest half → `[prior context: ...]` turn; recent verbatim retained |

### Global concurrency semaphore

```python
async def _cortex_call_with_semaphore(self, **kwargs):
    async with self._global_semaphore:  # max=4 concurrent
        return await self._cortex_registry.call(**kwargs)
```

### Cancellation (deferred to v0.2)

v0.1 does not interrupt in-flight cortex calls when a sender sends "nm" or `/cancel`. The cancel message queues behind the in-flight one. v0.2: cortex `CooperativeCancelToken` plumbed through `_dispatch()`; sender's cancel message triggers `.cancel()`; cortex aborts mid-stream; user gets a short ack.

## §8 v0.1 scope, deferred, acceptance criteria

### v0.1 IN scope (26 items)

**Core message flow:**

1. Private DM receive via Zoom Web SDK chat callback, filtered to `is_private=True`
2. Sender identity resolution via `lattice_meeting.persona` (canonical persona + confidence)
3. Allowlist enforcement per Q4a tiers: T1 (explicit) / T2 (mapped ≥ confidence) / T3 (anonymous, default-deny)
4. Per-`(meeting_id, canonical_persona_id)` conversation memory (in-process, lost at sidecar exit)
5. Multi-turn DM context within a single thread for a single meeting
6. Cortex dispatch via `registry.call(consumer="lattice-meeting-assistant", task=<tier>)`
7. Sonnet default + Opus opt-in via per-message `/think` flag
8. Private reply via `MeetingSession.send_chat(to_user_id, message)` — required-positional
9. Holding message + rate limiting + graceful degradation defaults

**Configuration + admin:**

10. `AssistantConfig` with overridable behavioral knobs
11. `AssistantProfile` with `dm_allowlist`, knowledge access policy, series binding
12. Profile YAML loader for recurring series (`02_Projects/Lattice/{project}/Profiles/{slug}.yaml`)
13. Session-only allowlist mutation via TG admin commands (`allowlist add X`)
14. Persistent allowlist mutation via TG admin commands (`allowlist add X persistent`) — writes back to profile YAML via Brain MCP

**Knowledge access (Architectural Invariant #2):**

15. `KnowledgeAccessConfig` enforced transport-bound — hard `allow_personal_vault=False` for in-meeting DM
16. Live transcript hot window (default 300s, configurable per profile; cannot disable)
17. Cortex tool registration — curated set for in-meeting DM, full Nexus surface for TG-owner
18. v0.1 tool set: `search_meeting_transcript`, `read_meeting_transcript_window`, `search_past_meetings`, `search_public_references`, `web_search` (in-meeting); plus `search_vault`, `read_note`, `search_references`, `nx_calendar_read`, `nx_email_search`, `vault_ask` (TG-owner only)
19. `BLOCKED_IN_MEETING_TOOLS` constant + resolver self-test at boot

**Series matching:**

20. `SeriesMatcher` — Path 1 (explicit recurring ID, HIGH, no ratification) + Path 2 (implicit host-cohort, MEDIUM, requires TG ratification)
21. Series vault notes at `02_Projects/Lattice/{project}/Meeting Series/{slug}.yaml`

**Adapter integration:**

22. `AdminTransport` ABC in `lattice-meeting-contracts` (next release)
23. Meetbot spawn config carries admin-transport identity (Brain populates at spawn time)

**Public @cody mentions:**

24. Public @cody mention path — `is_private=False AND @mention(bot_user_id)` events route to `PublicMentionHandler` + new `(meeting_id, "public")` ChatThreadActor
25. `public_mentions_enabled` + `public_mention_allowlist` + `public_mention_rate_limit_per_meeting_s` config knobs on `AssistantProfile`
26. Public-reply system prompt variant — terser register, public-visibility instructions, decline-private-shaped-questions guidance

### v0.1 explicitly DEFERRED

| Deferred | Reason | Target |
|---|---|---|
| Tool use beyond curated set + Nexus search wrappers (e.g., `deep_research` full, `nx_contacts_*`, `download_media`) | Cost + scope; v0.1 ships minimal viable knowledge access | v0.2 / v0.3 |
| Voice/TTS replies from private prompts into main meeting audio | Audio-pipeline coupling + new privacy surface | v0.3+ |
| Cross-meeting memory persistence default-on | Privacy posture; opt-in flag exists but defaults off | v0.2 (review flag default) |
| Meet adapter | Capability flags + AdminTransport ABC ship in v0.1 contracts; concrete adapter is its own library | v0.2 (`lattice-meet-google`) |
| Teams adapter | Same | v0.2 (`lattice-meet-teams`) |
| Cancellation (`/cancel`, "nm") mid-flight | Cortex `CooperativeCancelToken` exists; UX threading work doesn't pay v0.1 | v0.2 |
| Brain `/join` end-to-end wiring | Brain-side work (handler listening on `@HeyCody_bot`, threading TG ↔ meetbot spawn) | v0.1 parallel (Brain repo) |
| RAG layer for large public references | Public refs that don't fit in cortex prompt cache need retrieval | v0.2 |
| Participant-specific scoping in series | Privacy enhancement; spec when use-case emerges | v0.2+ |
| Auto-decay of `typical_participants` for stale series members | Aging logic + ratification flow | v0.2 |
| Cross-platform series merging (Zoom + in-person → one series) | Requires offline meeting capture path first | v0.3+ |
| Conversation handoff between sessions | Memory persistence + restart semantics | v0.2+ |
| In-meeting visible status indicator (Cody is typing / Cody is thinking) | Platform-specific UX; API survey | v0.2+ |
| Host-announcement of Cody's presence on meeting start | Cody Voice Identity tuning needed | v0.2 |
| Auto-detection of private-shaped questions in public chat → proactive DM-suggestion | Heuristic + UX work | v0.2 |
| Mention-disambiguation across multiple bots in same meeting | Multi-bot meetings rare | v0.2+ |
| Cross-thread memory bridge (public ↔ private same sender) | Privacy implications | v0.2 |

### Acceptance criteria (v0.1 GA gates)

Eight gates, modeled after `lattice-meeting v0.2.0` Spec A §10:

| Gate | Definition | How verified |
|---|---|---|
| **AC-1: Public API stable** | All exports in `__init__.py` present + typed; `mypy --strict src/` clean | CI |
| **AC-2: Boundary tests pass** | All 12 boundary tests (T1-T12 in §5) green | `pytest tests/test_privacy_boundary_*.py` |
| **AC-3: Configuration round-trip** | `AssistantConfig`, `AssistantProfile`, `KnowledgeAccessConfig` all round-trip via YAML load + dump without loss | unit tests |
| **AC-4: Cortex tool registration** | All 11 v0.1 in-meeting + TG-owner tools register with cortex 0.6.0; tool-use loop completes for each | integration tests against cortex 0.6.0 |
| **AC-5: Coverage on critical paths** | 90%+ on `privacy/`, `actor.py`, `tools/`, `series.py`; no specific line-% gate elsewhere (per S15 coverage-signal-priority) | `pytest --cov` |
| **AC-6: Series-match ratification flow** | Path 1 binds without prompt; Path 2 emits TG ask + applies default profile until ratified | integration test with mock `AdminTransport` |
| **AC-7: Real-consumer-integration evidence** | AQH harness (Task B from S25 prompt) drives a real Zoom meeting with Assistant + injects a private DM + a public @-mention + asserts privacy boundary holds across transcript/wrap-up/public-mention-thread sinks. PASS = AC-7 green. | AQH PASS |
| **AC-8: PVD-clean** | Spec + plan pass `lattice-pvd-preflight` skill; foundational claims carry `[V:*]` or `[U]` tags | spec author + spec self-review |

## §9 Open questions for spec authoring

| # | Open question | Spec author default + verification |
|---|---|---|
| **OQ1** | `lattice-meeting-contracts` version bump for `AdminTransport` ABC + `PlatformChatCapability` + `TranscriptBuffer` Protocol — minor (`0.2.1-rc1`) or new minor (`0.3.0-rc1`)? | Lean `0.3.0-rc1` because `TranscriptBuffer` is a new protocol; spec author can downgrade to 0.2.1 if reviewer judges additive. [V:read:lattice-meeting-contracts/CHANGELOG.md current state] |
| **OQ2** | Cortex 0.6.0 tool-use registration API — exact entry point and tool schema shape | Spec author runs `python -c "import lattice_cortex; ..."` against canonical 0.6.0 install to confirm; failure → spec carries `defer_until_cortex_tool_use` flag for v0.1.5. [V:lattice-cortex 0.6.0 public_api] |
| **OQ3** | `web_search` tool source — Brain `deep_research` (full) heavyweight; cortex 0.6.0 may have a search tool; or Tavily/Brave direct | Recommend Brain `deep_research` with `mode=lightweight` if param exists; otherwise Tavily direct via httpx. [V:Brain `/api/research` schema] |
| **OQ4** | Filler pool source of truth (Q5 holding message) — load from vault `Cody Voice Identity` at startup, or hardcode v0.1 subset | Recommend hardcode v0.1 subset (`one moment` / `let me think` / `checking`); vault-load defers to v0.2. |
| **OQ5** | Persona-name addressing threshold — `canonical_name_min_confidence: float = 0.85` — validate against current persona-mapping data | Spec author samples Sabbath School persona mappings; adjust to 0.80 if too restrictive. [V:vault Persona Mappings/Zoom.md current state] |
| **OQ6** | Profile YAML schema versioning — should the YAML carry a `schema_version: 1` field for v0.2 migrations? | Yes; cheap insurance. |
| **OQ7** | Test fixtures — anonymized vault Persona Mappings snapshot for unit tests (mirroring lattice-meeting v0.2.0's approach) | Yes — copy the anonymized fixture pattern from lattice-meeting; RFC 3966 PSTN + RFC 2606 `example.org`. |
| **OQ8** | Profile YAML write-back path — Brain MCP `nx_vault_write` or direct filesystem write? | Recommend Brain MCP `nx_vault_write` (uniformity, audit log, no FS race). |
| **OQ9** | `AssistantStats` exposed to consuming sidecar — meetbot exposes on `/health` or `/metrics`? | Spec author wires meetbot v0.2's `/metrics` Prometheus endpoint to expose assistant histograms (per-thread depth, in-flight cortex calls, total tokens cost-attributed). |
| **OQ10** | Series ratification timeout — `series_ratification_timeout_s: int = 120` — too short or too long? | 120s feels right for active-meeting context. Spec author can adjust to 300s if Cyril prefers; the timeout falls back to default profile, so erring long is cheap. |

### Cross-repo follow-ups

- **FU1** (Brain repo) — Verify Brain `/join` handler is wired to `@HeyCody_bot` webhook; if mismatched, file obsidian-nexus ticket via Nexus MCP.
- **FU2** (vault `[[Telegram Paging Protocol]]`) — Draft Rule 6 clarifying amendment distinguishing autonomous status pings (`@ObsidianNexusAI_bot`) from interactive conversational + assistant admin (`@HeyCody_bot` in Cyril's deployment).
- **FU3** (lattice-meeting-contracts repo) — Cut next contracts release with `AdminTransport`, `PlatformChatCapability`, `TranscriptBuffer` — version per OQ1.

## §10 Acceptance criteria (consolidated)

Re-stated for crisp reference; matches §8 table:

- **AC-1:** Public API stable + `mypy --strict` clean
- **AC-2:** 12 boundary tests T1-T12 green
- **AC-3:** Config round-trip via YAML lossless
- **AC-4:** All 11 v0.1 tools register and complete tool-use loop against cortex 0.6.0
- **AC-5:** 90%+ coverage on critical paths
- **AC-6:** Series-match ratification flow integration-tested
- **AC-7:** AQH PASS with real Zoom meeting + private DM + public mention privacy assertion
- **AC-8:** PVD-clean spec + plan

## §11 Risk register

| # | Risk | Severity | Mitigation | Owner |
|---|---|---|---|---|
| **R1** | Cortex 0.6.0 tool-use API differs from §3/§4 assumptions | HIGH (gates v0.1 dispatch) | OQ2 verification first task in W1; spec carries fallback to `defer_until_cortex_tool_use` for v0.1.5 | spec author / W1 subagent |
| **R2** | `lattice-meeting-contracts` next-version cut blocks W1 work | HIGH (gates assistant work) | OQ1 verification + contracts release as W0 task in implementation plan | spec author / contracts release |
| **R3** | Zoom Web SDK chat event name uncertainty (research note flagged) | MEDIUM | W0 task verifies live `@zoom/meetingsdk` TypeScript definitions; payload shape well-established across forums | meetbot v0.2 W0 |
| **R4** | Privacy boundary leak through unanticipated path | HIGH | Architectural Invariants 1-5 + 12 boundary tests + AQH integration. Defense in depth at architecture, code, prompt, and test layers | code + AQH harness |
| **R5** | Public mention reply triggers another participant's @cody → infinite loop | MEDIUM | `public_mention_rate_limit_per_meeting_s` default 30s + bot @-mention detection (don't reply to other bots' mentions) | code |
| **R6** | Cost overrun if a meeting has many active DM threads | MEDIUM | Global semaphore = 4 concurrent cortex calls + per-sender rate limit + max-200-token replies + cortex cost-attribution surfaces overrun in observability | config |
| **R7** | Profile YAML write-back race (two admins mutating concurrently) | LOW | TG admin is single-user-per-deployment; Brain MCP `nx_vault_write` likely serializes; v0.2 add optimistic-concurrency check if needed | n/a v0.1 |
| **R8** | Series ratification ping lost (Cyril doesn't see TG message) | LOW | Default profile is conservative (allowlist=[cyril], default-deny); ratification timeout falls back to default; re-ratification on next meeting is free | by design |
| **R9** | Brain `/join` handler listening on wrong bot (FU1) | LOW (operational, not architectural) | FU1 verification before AC-7 AQH run; if mismatched, file ticket + Brain-side fix | obsidian-nexus session |
| **R10** | Future Meet/Teams adapter discovers capability flag set is insufficient | LOW | Capability flags additive (frozen dataclass); new flag is a contracts minor bump; assistant resolver default-deny posture absorbs unknown flags gracefully | v0.2 spec |

## §12 Spec self-review

Per `superpowers:brainstorming` skill self-review block:

### Placeholder scan

- All `TBD` / `TODO` resolved or moved to §9 OQs with explicit verification path. PASS.
- All Cody Voice Identity references cite `[[Cody Voice Identity]]` vault protocol (no inlined drift).
- All cortex / meeting-contracts / meeting / persona references cite specific version constraints.

### Internal consistency

- Architectural Invariant #2 (transport-bound) referenced in §1 mission filter + §3 (`Assistant.__init__` parameters) + §4 (resolver + BLOCKED set) + §5 (Invariant 2 + boundary tests T8/T9). Consistent.
- `(meeting_id, canonical_persona_id)` vs `(meeting_id, "public")` thread keys appear in §3, §5 (Invariant 3 + T1, T12), §7 (actor internals). Consistent.
- `BLOCKED_IN_MEETING_TOOLS` constant declared in §4 + enforced via `Assistant.start()` self-test (§4) + boundary tests T8 + T9 (§5). Consistent.
- Public-mention path: §3 (`on_public_mention` API) + §4 (public-mention prompt variant + tool set) + §5 (T11, T12) + §7 (actor key `"public"`) + §8 (scope items 24-26). Consistent.

### Scope check

- v0.1 scope = 26 items, single library, single Zoom adapter. Reasonable for a single implementation plan dispatch (subagent-driven, W1-W6 estimated similar to lattice-meetbot v0.2 plan shape).
- Deferred list scoped per item to v0.2 / v0.2+ / v0.3+ with rationale. No items "deferred forever."
- Cross-repo follow-ups isolated to FU1-FU3 (Brain + vault protocol + contracts release).

### Ambiguity check

- "Series" defined in §6 as Path 1 (explicit recurring meeting ID, HIGH) + Path 2 (implicit host-cohort, MEDIUM). Sabbath School is Path 1. Clear.
- "Admin" defined per `[[Meeting Platform Admin Surface Isolation]]`: configures behavior → admin → TG. Queries information → user-facing. Clear; cited in Invariant 5.
- "Private-shaped question" in public-mention system prompt is intentionally fuzzy (model judgment) — acceptable v0.1 ambiguity; spec author should NOT pre-define rigid heuristics here.
- "Sender canonical persona" reliably resolves only at confidence ≥ `dm_min_confidence`; below threshold = T3 anonymous tier. Clear.
- "Bot @-mention detection" (R5 mitigation) — needs explicit definition in plan: detect `@<self.bot_display_name>` literal in message text. Spec author owns.

### Verification tags

Foundational claims tagged for PVD:

- `[V:read:lattice-meeting-contracts/CHANGELOG.md current state]` — OQ1 contract version
- `[V:lattice-cortex 0.6.0 public_api]` — OQ2 cortex tool-use API
- `[V:Brain `/api/research` schema]` — OQ3 web search source
- `[V:vault Persona Mappings/Zoom.md current state]` — OQ5 confidence threshold validation
- All `BLOCKED_IN_MEETING_TOOLS` entries verifiable against deferred-tool list in S25 session-init context (tool names from `mcp__claude_ai_Nexus__*` namespace).

Self-review complete; no inline fixes required beyond items already captured in OQs.

## §13 Triple Write status

Per `[[Triple Write Protocol]]`:

- **Vault canonical (THIS NOTE):** `D:/Vaults/Mainframe/02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec.md` — full content; this is the source of truth.
- **Repo mirror:** Pending repo scaffold (`/new-project lattice-meeting-assistant`) — will land at `docs/specs/2026-05-11-lattice-meeting-assistant-v0.1-design-spec.md` byte-aligned with this vault note.
- **Memory pointer:** `~/.claude/projects/G--My-Drive-Projects-Merge-lattice-meeting/memory/spec_lattice_meeting_assistant_v0_1.md` + `MEMORY.md` index entry.

## §14 Cross-references

- Mission: `[[02_Projects/Lattice/lattice-meeting-assistant/Mission]]` (pending creation in Triple Write closure)
- Research note: `[[02_Projects/Lattice/lattice-meeting-assistant/Research/2026-05-11 Meeting-Platform Capability Comparison - Zoom Meet Teams]]`
- Decision note: `[[02_Projects/Lattice/lattice-meeting-assistant/Decisions/2026-05-11 Public @cody mentions included in v0.1]]`
- Lattice-wide admin protocol: `[[02_Projects/Protocols/Meeting Platform Admin Surface Isolation]]` (authored S25 in parallel)
- Project Registry: `[[02_Projects/Lattice/Project Registry]]` (pending row addition)
- Family doc: `[[02_Projects/Lattice/Family]]`

## §15 Amendment log

### v0.1.0-rc1 release (2026-05-12, S30)

- HEAD: `2939948` (`release(assistant): 0.1.0-rc1 -- first release candidate (7/8 ACs; AC-7 rc1->GA gate)`)
- Tag: `v0.1.0-rc1` (pushed to `origin`)
- AC tally: 7/8 (AC-7 deferred to v0.1.0 final gate -- requires real-Zoom AQH evidence; blockers are meetbot v0.2 W6 hardening + Cyril availability during AQH run)
- Test counts: 260 PASS / 0 xfail / 0 fail; mypy --strict clean on 26 src files
- 12/12 boundary tests T1-T12 PASS (T2 + T3 backed via mock transcript/wrap-up consumer contracts in HEAD~1 `f7b3981`)
- Critical-path coverage: privacy/ 91-100%, actor.py 94%, tools/ 93-100%, series.py 99%
- Open OQs (deferred to v0.1.x / v0.2): TKT-c775d84e (prompt-renderer stubs need lattice-persona-profile v0.1 dep), TKT-5d89d16d (contracts AdminTransport receive method for Path 2 ratification)
- Promotion gate: rc1 -> v0.1.0 = AC-7 PASS via real Zoom meeting through the AQH (Autonomous Meeting QA Harness)
