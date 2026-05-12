"""SeriesMatcher -- bind a meeting to a recurring series profile.

Spec §6 (Design Spec lines 741-826). Two paths:

* **Path 1 (explicit)** -- ``zoom_recurring_meeting_id`` matches a
  ``Meeting Series/`` vault note's frontmatter. HIGH confidence; no
  ratification. Spec §6 lines 746-751.
* **Path 2 (implicit host-cohort)** -- meeting has no recurring id;
  Jaccard overlap between current attendee canonical-id set and a
  candidate series's ``typical_participants`` >= 0.5. MEDIUM confidence;
  requires TG ratification before the profile applies. Spec §6 lines
  753-773.

The matcher is async-only -- vault queries cross a service boundary per
:doc:`Async by Default for External Services`. ``BrainMCPClient`` is the
single dependency for vault lookups (``nx_vault_search`` with structured
``filters``).

Ratification (Path 2) is delegated to an :class:`AdminTransport` per
spec §3 line 401+. When ``admin_transport=None`` the matcher silently
falls back to default profile -- this is the documented v0.1 graceful
degradation when no transport is wired (e.g. unit-test runs without TG).
The W5 ratification flow scripts ``yes`` / ``no`` / ``new-series X`` /
timeout against ``admin_transport.post_admin_response`` + a paired
response-receive primitive on the same transport handle; the concrete
shape lives on the transport (production: BrainTGAdminTransport).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

from .brain_client import BrainMCPClient

logger = logging.getLogger(__name__)


# Path 2 Jaccard threshold (spec §6 line 760 -- "overlap_score >= 0.5").
PATH_2_JACCARD_THRESHOLD: float = 0.5

# Spec §3 line 323 default; mirrored here so the matcher can run without
# explicitly receiving an ``AssistantConfig`` (it doesn't need the rest).
DEFAULT_RATIFICATION_TIMEOUT_S: float = 120.0


SeriesBinding = Literal["explicit", "implicit-host-cohort"]
SeriesConfidence = Literal["high", "medium"]


@dataclass(frozen=True)
class SeriesMatch:
    """Result of a successful series lookup. See spec §3 lines 391-398.

    * ``series_id`` -- canonical series slug (matches the YAML
      frontmatter on the Meeting Series/ note).
    * ``binding`` -- ``"explicit"`` (Path 1) or ``"implicit-host-cohort"``
      (Path 2).
    * ``confidence`` -- ``"high"`` (Path 1) or ``"medium"`` (Path 2
      before ratification). Spec §3 line 395 enumerates these two; the
      ``"ratified-low"`` value in profile.py belongs to the YAML
      frontmatter (a different shape) and is not a SeriesMatch state.
    * ``requires_ratification`` -- ``True`` only for Path 2 pre-ratification.
    * ``cohort_overlap_score`` -- the Jaccard score for Path 2; ``None``
      for Path 1 (no cohort comparison performed).
    * ``profile_vault_path`` -- vault-relative path of the Meeting
      Series/ note that matched. Caller passes this to the profile
      loader.
    """

    series_id: str
    binding: SeriesBinding
    confidence: SeriesConfidence
    requires_ratification: bool
    cohort_overlap_score: float | None
    profile_vault_path: str


@runtime_checkable
class _RatificationTransport(Protocol):
    """Subset of :class:`AdminTransport` the matcher needs for Path 2.

    The full Protocol lives in ``lattice_meeting_contracts.AdminTransport``;
    we restate the surface we depend on here so the matcher does not
    have to import the runtime contracts package at type-check time
    (and so a test can substitute a minimal duck-typed stub).

    The matcher uses:

    * ``post_admin_response(handle, response_text)`` -- send the
      ratification prompt to the owner.
    * ``await_admin_reply(handle, timeout_s)`` -- await the owner's
      reply. This is **not** on the rc2 ``AdminTransport`` contract
      (rc2 is one-way). The matcher uses ``getattr`` + a fallback so
      ratification degrades gracefully when the transport does not
      yet implement the await side (v0.1 ships the prompt-only path
      and treats missing reply as a timeout fallback).
    """

    async def post_admin_response(self, handle: Any, response_text: str) -> None: ...


class SeriesMatcher:
    """Match a meeting to a series profile via vault frontmatter lookup.

    Construction:

    * ``brain_mcp`` -- required; Brain MCP client for ``nx_vault_search``.
    * ``admin_transport`` -- optional; required only for Path 2
      ratification. ``None`` makes ratification a silent no-op
      (matcher returns ``None`` from :meth:`ratify`).
    * ``ratification_timeout_s`` -- override the default 120s budget.
    """

    def __init__(
        self,
        *,
        brain_mcp: BrainMCPClient,
        admin_transport: _RatificationTransport | None = None,
        ratification_timeout_s: float = DEFAULT_RATIFICATION_TIMEOUT_S,
    ) -> None:
        self._brain_mcp = brain_mcp
        self._admin_transport = admin_transport
        self._ratification_timeout_s = ratification_timeout_s

    # -----------------------------------------------------------------
    # Path 1 -- explicit recurring meeting id
    # -----------------------------------------------------------------

    async def match_path_1(
        self,
        *,
        zoom_recurring_meeting_id: str,
    ) -> SeriesMatch | None:
        """Look up a Meeting Series/ note by recurring meeting id.

        Brain ``nx_vault_search`` is called with a structured filter on
        ``zoom_recurring_meeting_id`` (frontmatter exact-match). The
        envelope shape is the Brain canonical
        ``{"results": [{"path": ..., "frontmatter": {...}}, ...]}``.

        Behavior:

        * 0 results -> ``None`` (treat as one-off; default profile).
        * 1 result -> :class:`SeriesMatch` HIGH explicit.
        * >1 results -> pick the first deterministically; collisions
          should never happen (Zoom recurring ids are unique per series).
        """
        envelope = await self._brain_mcp.nx_vault_search(
            query=f"zoom_recurring_meeting_id={zoom_recurring_meeting_id}",
            filters={"zoom_recurring_meeting_id": zoom_recurring_meeting_id},
            limit=10,
        )
        results = _extract_results(envelope)
        if not results:
            return None
        # Deterministic pick: first result. Spec §6 edge case "multiple
        # Path-1 candidates" is out-of-scope for v0.1 (recurring ids are
        # globally unique per Zoom).
        first = results[0]
        return _build_path1_match(first)

    # -----------------------------------------------------------------
    # Path 2 -- implicit host-cohort overlap
    # -----------------------------------------------------------------

    async def match_path_2(
        self,
        *,
        host_canonical_id: str,
        attendee_canonical_ids: frozenset[str],
    ) -> SeriesMatch | None:
        """Look up candidates by host + score by Jaccard overlap.

        Spec §6 Path 2 (lines 753-773):

        1. Query Meeting Series/ notes where
           ``host_canonical_id == host_canonical_id``.
        2. For each candidate, compute Jaccard overlap between the
           current attendee set and the candidate's
           ``typical_participants``.
        3. Return the highest-overlap candidate with overlap >=
           :data:`PATH_2_JACCARD_THRESHOLD` as a MEDIUM-confidence
           match with ``requires_ratification=True``. Ties broken by
           descending ``last_updated`` frontmatter (most recent wins);
           absent ``last_updated`` sorts last.
        4. Return ``None`` if no candidate clears the threshold.
        """
        envelope = await self._brain_mcp.nx_vault_search(
            query=f"host_canonical_id={host_canonical_id}",
            filters={"host_canonical_id": host_canonical_id},
            limit=25,
        )
        results = _extract_results(envelope)
        if not results:
            return None

        # Score each candidate.
        scored: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
        for r in results:
            fm = _safe_frontmatter(r)
            typical = _as_str_set(fm.get("typical_participants") or [])
            if not typical:
                continue
            overlap = _jaccard(attendee_canonical_ids, typical)
            if overlap >= PATH_2_JACCARD_THRESHOLD:
                scored.append((overlap, str(fm.get("last_updated") or ""), r, fm))

        if not scored:
            return None

        # Sort: overlap DESC, then last_updated DESC (string sort works
        # for ISO 8601). Empty last_updated sorts last because empty
        # string < any non-empty ISO timestamp.
        scored.sort(key=lambda t: (-t[0], _negate_iso(t[1])))
        best_overlap, _last_updated, best_result, best_fm = scored[0]

        series_id_raw = best_fm.get("series_id")
        if not isinstance(series_id_raw, str) or not series_id_raw:
            # Malformed candidate -- skip rather than crash.
            logger.warning(
                "SeriesMatcher.match_path_2: candidate missing series_id at path=%s",
                best_result.get("path"),
            )
            return None
        profile_vault_path = str(best_result.get("path") or "")

        return SeriesMatch(
            series_id=series_id_raw,
            binding="implicit-host-cohort",
            confidence="medium",
            requires_ratification=True,
            cohort_overlap_score=best_overlap,
            profile_vault_path=profile_vault_path,
        )

    # -----------------------------------------------------------------
    # Ratification (Path 2 only)
    # -----------------------------------------------------------------

    async def ratify(
        self,
        match: SeriesMatch,
        *,
        admin_handle: Any | None = None,
        timeout_s: float | None = None,
    ) -> SeriesMatch | None:
        """Send a ratification prompt; await yes/no/new-series/timeout.

        Returns:

        * A new :class:`SeriesMatch` with ``requires_ratification=False``
          on ``yes`` (keeps the original series id + binding).
        * A new :class:`SeriesMatch` carrying the user-supplied series
          slug on ``new-series X`` (binding stays
          ``implicit-host-cohort``; confidence ``"medium"``;
          ``requires_ratification=False``).
        * ``None`` on ``no``, on timeout, or when no transport is wired
          -- caller falls back to the default profile.

        Implementation note: the spec ratification UX is a TG round-trip
        (prompt sent + reply received). The rc2 ``AdminTransport``
        contract only exposes the send half (``post_admin_response``);
        the receive half is delegated via an optional duck-typed
        ``await_admin_reply`` method on the transport. Concrete
        production transports (BrainTGAdminTransport) implement both;
        when absent we conservatively treat ratification as a timeout.
        """
        if self._admin_transport is None:
            logger.info(
                "SeriesMatcher.ratify: no admin_transport wired; "
                "falling back to default profile for series_id=%s",
                match.series_id,
            )
            return None

        budget = timeout_s if timeout_s is not None else self._ratification_timeout_s

        prompt = _format_ratification_prompt(match)
        try:
            await self._admin_transport.post_admin_response(admin_handle, prompt)
        except Exception:
            logger.exception(
                "SeriesMatcher.ratify: send failed for series_id=%s",
                match.series_id,
            )
            return None

        # await_admin_reply is the receive half -- duck-typed because
        # the rc2 AdminTransport contract is one-way (send only). When
        # the concrete transport implements it (BrainTGAdminTransport),
        # we await; otherwise we treat the ratification as a timeout.
        await_reply = getattr(self._admin_transport, "await_admin_reply", None)
        if await_reply is None:
            logger.info(
                "SeriesMatcher.ratify: admin_transport has no await_admin_reply; "
                "treating series_id=%s as timeout-fallback",
                match.series_id,
            )
            return None

        try:
            reply = await asyncio.wait_for(
                await_reply(admin_handle, timeout_s=budget),
                timeout=budget,
            )
        except asyncio.TimeoutError:
            logger.info(
                "SeriesMatcher.ratify: timeout after %.1fs for series_id=%s; "
                "falling back to default profile",
                budget,
                match.series_id,
            )
            return None
        except Exception:
            logger.exception(
                "SeriesMatcher.ratify: receive failed for series_id=%s",
                match.series_id,
            )
            return None

        return _parse_ratification_reply(reply, match)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_results(envelope: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Pull the ``results`` list out of a Brain envelope; tolerate the
    common variants (missing key, None, non-list)."""
    if not envelope:
        return []
    raw = envelope.get("results")
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]


def _safe_frontmatter(result: Mapping[str, Any]) -> dict[str, Any]:
    """Pull a result's ``frontmatter`` dict out; return {} when missing."""
    fm = result.get("frontmatter")
    if not isinstance(fm, dict):
        return {}
    return dict(fm)


def _as_str_set(seq: Any) -> frozenset[str]:
    """Coerce an iterable of strings to a frozenset; tolerate non-strings."""
    if not isinstance(seq, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(str(x) for x in seq if x is not None)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity |a ∩ b| / |a ∪ b|. Returns 0.0 on empty union."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _negate_iso(ts: str) -> str:
    """Sort key that puts the latest ISO timestamp first.

    Python's ``sorted`` is ascending; to get the latest timestamp at
    position 0 we negate-by-pad: longer strings sort later, but ISO 8601
    sorts lexically. Returning the reversed-codepoint-rank approximation
    is overkill -- the cleanest is to use a fixed-width inverted form.
    Here we just return a value such that descending order on the
    original is ascending order on the returned key: invert with
    ``"".join(chr(255 - ord(c)) for c in ts)``.
    """
    return "".join(chr(255 - ord(c)) for c in ts)


def _build_path1_match(result: Mapping[str, Any]) -> SeriesMatch | None:
    """Translate a vault search result into a Path 1 SeriesMatch.

    Returns ``None`` (logged) when the candidate is missing required
    frontmatter fields so the caller can fall back gracefully.
    """
    fm = _safe_frontmatter(result)
    series_id_raw = fm.get("series_id")
    if not isinstance(series_id_raw, str) or not series_id_raw:
        logger.warning(
            "SeriesMatcher.match_path_1: result missing series_id at path=%s",
            result.get("path"),
        )
        return None
    return SeriesMatch(
        series_id=series_id_raw,
        binding="explicit",
        confidence="high",
        requires_ratification=False,
        cohort_overlap_score=None,
        profile_vault_path=str(result.get("path") or ""),
    )


def _format_ratification_prompt(match: SeriesMatch) -> str:
    """Build the TG ratification ask for an unratified Path 2 match.

    Spec §6 lines 763-773 sketch the UX. The matcher does not enforce
    any specific wording -- the prompt is plain prose the admin reads
    and replies to with ``yes`` / ``no`` / ``new-series X``.
    """
    overlap = match.cohort_overlap_score
    overlap_pct = f"{overlap:.0%}" if overlap is not None else "n/a"
    return (
        f"Cody noticed this meeting looks like the series "
        f"'{match.series_id}' (cohort overlap {overlap_pct}). "
        f"Bind this meeting to that series? Reply 'yes', 'no', "
        f"or 'new-series <slug>'."
    )


def _parse_ratification_reply(reply: str, match: SeriesMatch) -> SeriesMatch | None:
    """Translate a yes/no/new-series-X reply into the resulting match.

    Unknown replies are treated as ``no`` -- conservative for v0.1; v0.2
    can ask a follow-up.
    """
    text = (reply or "").strip().lower()
    if text in ("yes", "y", "yeah", "yep", "confirm", "ok"):
        return SeriesMatch(
            series_id=match.series_id,
            binding=match.binding,
            confidence=match.confidence,
            requires_ratification=False,
            cohort_overlap_score=match.cohort_overlap_score,
            profile_vault_path=match.profile_vault_path,
        )
    if text in ("no", "n", "deny", "skip"):
        return None
    if text.startswith("new-series "):
        slug = text[len("new-series ") :].strip()
        if not slug:
            return None
        return SeriesMatch(
            series_id=slug,
            binding="implicit-host-cohort",
            confidence="medium",
            requires_ratification=False,
            cohort_overlap_score=match.cohort_overlap_score,
            profile_vault_path=match.profile_vault_path,
        )
    # Unknown reply -> conservative fallback (default profile).
    logger.info(
        "SeriesMatcher: unrecognised ratification reply %r; treating as deny",
        reply,
    )
    return None


__all__ = [
    "SeriesMatcher",
    "SeriesMatch",
    "PATH_2_JACCARD_THRESHOLD",
    "DEFAULT_RATIFICATION_TIMEOUT_S",
]
