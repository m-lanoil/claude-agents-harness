# Taste

Standing preferences applied by every pipeline phase (see `pipeline/PIPELINE.md`).
**User-editable** — change anything here; phases obey the current version. Seeded from
conventions already enforced in this repo; items marked *(default)* are assumptions to
confirm or overwrite.

## Stack & tooling
- Python environments: `uv` only — no bare `pip install`, no manual `venv`.
- MCP servers: standalone `fastmcp` (v3) with `FastMCP`.
- Prefer stdlib and already-installed dependencies over new ones; a new dependency needs
  a one-line justification in the plan.

## Code style
- `lowercase_snake_case` for files and folders; no spaces or special characters.
- No agent artifacts in code: no kb references, grounding notes, internal paths, or
  orchestration metadata in comments or docstrings.
- Comments state constraints the code can't show — not narration. *(default)*
- Boring over clever; shortest working diff; delete before adding. *(default)*

## Documentation
- Rule/instruction markdown stays ≤100 non-empty lines (`scripts/check_markdown_length.py`).
- Match existing docs' voice and depth when editing them.
- Full timestamps `YYYY-MM-DD HH:MM:SS` in logs.

## Process
- Human-in-the-loop before anything destructive, system-level, or outward-facing
  (push, PR, publish, delete).
- Claims trace to sources; failed fetches are reported, never papered over.
- Plans state what was rejected and why, in one line each.
- Speculative features go to Out of Scope, not into the build. *(default)*
