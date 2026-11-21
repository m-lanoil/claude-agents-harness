# coordinator/

Automated orchestration loop for the `claude_agents` multi-agent harness.
Behaviour and design decisions are documented below.

## How to run

From the repo root:

```bash
# Pre-specify all routing values (Meta-Orchestrator form — skips three interactive prompts):
uv run --with claude-agent-sdk python -m coordinator "Your task description here" \
  --workers developer \
  --output ../../output/final_outputs/<topic>/report.md \
  --sections "Section 1,Section 2"

# Multi-hop chain example:
uv run --with claude-agent-sdk python -m coordinator "Your task description here" \
  --workers architect,developer \
  --output ../../output/final_outputs/<topic>/report.md \
  --sections "Summary,Tradeoffs,Implementation Plan"

# Interactive fallback — omit any or all of --workers/--output/--sections to be prompted:
uv run --with claude-agent-sdk python -m coordinator "Your task description here"

# Interactive task prompt (all args omitted):
uv run --with claude-agent-sdk python -m coordinator
```

When `--workers`, `--output`, and `--sections` are provided, the coordinator skips the
three interactive routing prompts (worker chain, output path, required sections).
When any of those flags are omitted, the coordinator falls back to the interactive `input()`
prompt for that value — backward-compatible with the original interactive workflow.

## Pre-registering approved URLs (`--approved-urls`)

The `--approved-urls` flag lets the Meta-Orchestrator inject URLs into the Source Registry
**before** any worker is invoked, so workers can fetch them without needing mid-task approval.

**Format** — a JSON string with up to three optional keys:

```json
{"libraries": {"name": "url"}, "clis": {"name": "url"}, "other": {"name": "url"}}
```

Each key maps to the corresponding registry file in `servers/docs_fetcher/`:

| JSON key | Registry file |
|---|---|
| `libraries` | `libraries.json` |
| `clis` | `clis.json` |
| `other` | `other_sources.json` |

Any key may be omitted. The operation is **idempotent** — names already present in the
registry are not overwritten. A log line is printed for each type showing how many entries
were added.

**Example** — register a new library and an "other" reference before running a task:

```bash
uv run --with claude-agent-sdk python -m coordinator "Fetch and summarise the httpx changelog" \
  --workers developer \
  --output ../../output/final_outputs/<topic>/httpx_summary.md \
  --sections "Summary,Key Changes" \
  --approved-urls '{"libraries": {"httpx-changelog": "https://www.python-httpx.org/changelog/"}}'
```

The coordinator will write `httpx-changelog` into `servers/docs_fetcher/libraries.json`
before invoking the Developer worker, so `fetch_docs` / `add_library` calls for that name
succeed without an interactive pause.

## Output path conventions

**`--output` paths are worker-relative.** The coordinator resolves them against the final
worker's directory (`workers/<worker>/`) before passing them to the acceptance check.
Use `../../output/...` notation so the path resolves correctly from the worker cwd:

| Path type | Location | Example |
|---|---|---|
| Final deliverable | `output/final_outputs/<topic>/` | `../../output/final_outputs/<topic>/report.md` |
| Intermediate hop files and brief records (auto-managed) | `output/intermediate_outputs/<topic>/` | *(set by coordinator)* |

Final deliverables must include a **topic subfolder** (e.g. `<client-name>/`, `<project-name>/`)
— reuse an existing one under `output/final_outputs/` where it fits rather than writing loose
to the top level. See `CLAUDE.md` → Output Conventions.

Intermediate hop files are written automatically by the coordinator for each non-final hop
in a multi-hop chain. They are named `coordinator_hop_{N}_{worker}.md` and placed in
`output/intermediate_outputs/<topic>/`, where `<topic>` is parsed from the final hop's
`--output` path (`orchestrator.py::_topic_from_output_path`). If `--output` omits a topic
subfolder, hop files fall back to `output/intermediate_outputs/misc/` and a warning is
printed — always pass a topic-qualified `--output` to avoid this. These are gitignored
and not committed.

**Brief record.** For every hop of every run (single-hop runs included) the coordinator also
writes `coordinator_hop_{N}_{worker}_brief_{YYYYMMDD-HHMMSS}.md` into the same
`output/intermediate_outputs/<topic>/` folder. It holds every prompt sent to that hop's worker,
in send order, each under a numbered heading with its kind and a `YYYY-MM-DD HH:MM:SS`
timestamp, so you can audit the hop and write Track-record entries afterwards. The kinds are
the routing prompt (the text you approved, so your edits are kept), the acceptance correction
prompt, the semantic correction prompt, and the blocked-fetch resume prompt (which has no
approval gate). Each prompt is written verbatim inside a code fence longer than any backtick
run in it, so prompts that contain fences stay recoverable, and it is written before the worker
is invoked with it. Validator prompts and prompts you abort at the approval gate are not
recorded. The `YYYYMMDD-HHMMSS` part is taken once at the start of the run and shared by all
its hops; a rerun gets a new stamp and never overwrites an earlier file (if a name is already
taken, `_2`, `_3`, ... is appended). `<topic>` comes from `--output` as above, and this applies
to a `--output` under `intermediate_outputs/<topic>/` too. If a record cannot be written
(for example an `OSError`), the coordinator prints a `[brief record] WARNING`, adds a line to
`logs/worker_updates.md`, and continues the hop; the next successful write of that hop's
record includes the entry that failed.

Final deliverables should be directed to `output/final_outputs/<topic>/` via `--output`. These
are also gitignored (local-only) but are the permanent output for the user.

**Interactive HITL checks that always fire regardless of pre-specified args:**
1. **Prompt approval gate** — shown before each worker invocation; you can approve, edit, or abort.
2. **Gap acknowledgment** — pauses if the worker reports any gaps; must be acknowledged before continuing.
3. **Correction retry gate** — if acceptance fails, you approve or abort before the retry attempt.

## Q2 — MCP Server Path Resolution

MCP server paths are resolved at import time from `__file__` in `worker_registry.py`:

```python
_REPO_ROOT = Path(__file__).parent.parent   # coordinator/ → repo root
_SERVERS = _REPO_ROOT / "servers"

def _uv_server(name: str) -> dict:
    server_dir = _SERVERS / name
    return {
        "command": "uv",
        "args": ["--project", str(server_dir), "run", str(server_dir / "server.py")],
    }
```

This makes the coordinator portable — no hardcoded absolute paths, no env vars required, no config file.
The `__file__`-relative approach matches how the worker `CLAUDE.md` files are scoped.

## Q3 — Gap Severity Threshold

**Decision: all gaps surface to user, no silent close.**

When a worker's JSON return block includes a non-empty `gaps` list, the coordinator prints each gap and pauses for user acknowledgment before continuing. There is no severity filter. Rationale: the coordinator's job is to surface worker judgment to the human, not to make editorial calls about what is "low-severity."

## Q5 — Session Persistence for Correction Loops

**Decision: session resumption enabled.**

When an acceptance check fails and the user approves a retry, the coordinator passes the original `session_id` (captured from the SDK `init` message) into the correction `query()` call via `ClaudeAgentOptions(resume=session_id)`. This preserves the worker's prior context, improving correction quality on the retry.

One retry is allowed per hop. If the retry also fails, the coordinator escalates to the user and does not auto-close the task.

## Blocked fetch (stop, report, resume)

A worker that cannot fetch a required source ends its run with `"status": "blocked"` and a `blocked_sources` list (`source`, `reason`, optional `candidates`), per the Human-Retrieved Source Protocol in `workers/WORKER_STANDARDS.md`. The coordinator then skips the acceptance check and Validator for that run and asks you, per source: (1) a local file path, (2) a replacement `https://` URL or candidate number, (3) continue without it, (4) abort.

- A local file is **copied** (never moved, never overwriting; `_2`, `_3` on a name clash) into `workers/<worker>/human-retrieved-sources/`.
- A replacement URL is registered under `<source>_replacement` in `other_sources.json`.
- The same worker session is resumed with your answers, then the normal acceptance and Validator path runs.
- At most 2 block-resume cycles per hop (shared with the correction retry). A third block, a missing session ID, or a block during a Validator correction retry stops the hop and prints the manual-mode fallback.
- Tests: `coordinator/tests/` (270 passed, 2 skipped on 2026-11-20; stubbed `query` plus SDK contract tests, no network). The 2 skips are live SDK smoke tests, enabled with `COORDINATOR_LIVE_SDK=1` (one real call each). Run from the repo root: `uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests`. Live: three single-hop Developer runs on 2026-11-12 and one single-hop Scout run on 2026-11-13; the blocked-fetch resume has not run live.

## Module structure

| File | Responsibility |
|---|---|
| `orchestrator.py` | `run(task)` async — main loop, multi-hop sequencing, logging, brief record (`_BriefRecord`) |
| `worker_registry.py` | Per-worker `ClaudeAgentOptions`; MCP paths resolved from `__file__` |
| `acceptance.py` | `parse_worker_result()`, `acceptance_check()` |
| `schemas.py` | `RoutingPrompt`, `WorkerResult` (incl. `blocked_sources`), `AcceptanceResult` dataclasses |
| `__main__.py` | Thin CLI wrapper (`python -m coordinator`) |
| `tests/` | Offline pytest suite (stubbed `query`, SDK contract tests, opt-in live smoke tests) |

## CLAUDE.md loading

Workers' `CLAUDE.md` files are loaded automatically. The SDK subprocess runs with `cwd` set to the worker's directory (`workers/developer/`, etc.), and `setting_sources` is left at its default (`None`), which loads all settings sources including `CLAUDE.md`. This is confirmed by `kb/kb_claude_agent_sdk.md`.

The root `CLAUDE.md` (the Meta-Orchestrator rules) is an ancestor of every worker directory, so `build_options` passes inline `settings` with `claudeMdExcludes` for it and `autoMemoryEnabled: false`; a worker sees only its own rules. Covered by offline contract tests; not checked in a live session. The Validator runs from the repo root with `setting_sources=[]`.

## Prerequisites

- `uv` available on PATH
- `claude` CLI authenticated (existing Claude Code session is sufficient — no separate `ANTHROPIC_API_KEY` needed)
- MCP servers present at `servers/docs_fetcher/`, `servers/system_monitor/` and `servers/web_search/` (the Scout gets `web_search` only; it needs `BRAVE_SEARCH_API_KEY` exported in the shell that runs the coordinator)
