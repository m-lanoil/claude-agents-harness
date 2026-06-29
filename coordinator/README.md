# coordinator/

Automated orchestration loop for the `claude_agents` multi-agent harness.
Implements the architecture described in `output/coordinator_loop_architecture.md`.

## How to run

From the repo root:

```bash
# Pre-specify all routing values (Meta-Orchestrator form — skips three interactive prompts):
uv run --with claude-agent-sdk python -m coordinator "Your task description here" \
  --workers developer \
  --output ../../output/final_outputs/report.md \
  --sections "Section 1,Section 2"

# Multi-hop chain example:
uv run --with claude-agent-sdk python -m coordinator "Your task description here" \
  --workers architect,developer \
  --output ../../output/final_outputs/report.md \
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
  --output ../../output/final_outputs/httpx_summary.md \
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
| Final deliverable | `output/final_outputs/` | `../../output/final_outputs/report.md` |
| Intermediate hop files (auto-managed) | `output/intermediate_outputs/` | *(set by coordinator)* |

Intermediate hop files are written automatically by the coordinator for each non-final hop
in a multi-hop chain. They are named `coordinator_hop_{N}_{worker}.md` and placed in
`output/intermediate_outputs/`. These are gitignored and not committed.

Final deliverables should be directed to `output/final_outputs/` via `--output`. These are
also gitignored (local-only) but are the permanent output for the user.

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

## Module structure

| File | Responsibility |
|---|---|
| `orchestrator.py` | `run(task)` async — main loop, multi-hop sequencing, logging |
| `worker_registry.py` | Per-worker `ClaudeAgentOptions`; MCP paths resolved from `__file__` |
| `acceptance.py` | `parse_worker_result()`, `acceptance_check()` |
| `schemas.py` | `RoutingPrompt`, `WorkerResult`, `AcceptanceResult` dataclasses |
| `__main__.py` | Thin CLI wrapper (`python -m coordinator`) |

## CLAUDE.md loading

Workers' `CLAUDE.md` files are loaded automatically. The SDK subprocess runs with `cwd` set to the worker's directory (`workers/developer/`, etc.), and `setting_sources` is left at its default (`None`), which loads all settings sources including `CLAUDE.md`. This is confirmed by `kb/kb_claude_agent_sdk.md`.

## Prerequisites

- `uv` available on PATH
- `claude` CLI authenticated (existing Claude Code session is sufficient — no separate `ANTHROPIC_API_KEY` needed)
- MCP servers present at `servers/docs_fetcher/` and `servers/system_monitor/`
