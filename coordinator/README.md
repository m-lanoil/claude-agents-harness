# coordinator/

Automated orchestration loop for the `claude_agents` multi-agent harness.
Implements the architecture described in `output/coordinator_loop_architecture.md`.

## How to run

From the repo root:

```bash
# With a task string:
uv run --with claude-agent-sdk python -m coordinator "Your task description here"

# Interactive task prompt:
uv run --with claude-agent-sdk python -m coordinator
```

The coordinator will interactively ask for:
1. **Worker chain** — e.g. `developer`, `architect`, or `architect,developer` for multi-hop
2. **Expected output path** — e.g. `../../output/report.md`
3. **Required sections** — comma-separated header names to verify in acceptance check

One **human approval gate** is shown before each worker is invoked. You can approve, edit, or abort.

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
