# lattice-meeting-assistant

In-meeting AI assistant primitive for Lattice meeting-platform adapters.

`lattice-meeting-assistant` is the library realization of the in-meeting Cody primitive: a meeting-platform adapter (`lattice-meetbot` for Zoom; future `lattice-meet-google`, `lattice-meet-teams`) instantiates one `Assistant` per session to receive chat messages from meeting participants, dispatch them through `lattice-cortex` with transport-bound knowledge access, and reply back in the originating channel (private DM or public @-mention thread).

## Install

```bash
pip install --upgrade lattice-meeting-assistant
```

(Pre-PyPI; install from git tag in the meantime.)

## Status

Pre-implementation. v0.1 scaffold in flight as of S27 (2026-05-11). Spec + plan canonical in the Lattice vault.

## Canonical documents

- **Mission:** vault `02_Projects/Lattice/lattice-meeting-assistant/Mission.md`
- **Design Spec:** vault `02_Projects/Lattice/lattice-meeting-assistant/Specifications/2026-05-11 lattice-meeting-assistant v0.1 - Design Spec.md`
- **Implementation Plan:** vault `02_Projects/Lattice/lattice-meeting-assistant/Plans/2026-05-11 lattice-meeting-assistant v0.1 - Implementation Plan.md`

## License

Apache 2.0. Author: CodeWarrior4Life. See `LICENSE`.
