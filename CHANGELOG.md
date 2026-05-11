# Changelog

All notable changes to this project will be documented here. Format roughly Keep-a-Changelog; versions follow PEP 440.

## [Unreleased]

## [0.1.0.dev0] - 2026-05-11

### Added
- Initial scaffold (W1.1): `LICENSE` (Apache 2.0), `README.md`, `.gitignore` (Lattice security block + Python), `.gitleaks.toml`, pre-commit hook, `src/lattice_meeting_assistant/` + `tests/` skeletons.
- `pyproject.toml` + `requirements.txt` (W1.2). Pinned to git tags pending sibling-package PyPI publish; intended semantic ranges are `lattice-meeting-contracts >=0.3.0rc2,<0.4`, `lattice-meeting >=0.2.0,<0.3`, `lattice-cortex >=0.6.0,<0.7`. Swap to PEP 440 version specifiers when the sibling packages publish to PyPI.
