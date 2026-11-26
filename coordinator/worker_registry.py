import json
from pathlib import Path
from typing import Any, Optional
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

# Repo root: coordinator/worker_registry.py → coordinator/ → repo root
_REPO_ROOT = Path(__file__).parent.parent
_SERVERS = _REPO_ROOT / "servers"

WORKER_DIRS: dict[str, Path] = {
    "developer": _REPO_ROOT / "workers" / "developer",
    "architect": _REPO_ROOT / "workers" / "architect",
    "content": _REPO_ROOT / "workers" / "content",
    "researcher": _REPO_ROOT / "workers" / "researcher",
    "scout": _REPO_ROOT / "workers" / "scout",
}

_WORKER_TOOLS: dict[str, list[str]] = {
    "developer": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    "architect": ["Read", "Glob", "Grep", "Write"],
    "content": ["Read", "Glob", "Grep", "Write"],
    "researcher": ["Read", "Glob", "Grep", "Write"],
    "scout": ["Read", "Glob", "Grep", "Write"],
}

_WORKER_MCP_NAMES: dict[str, list[str]] = {
    "developer": ["docs_fetcher", "system_monitor"],
    "architect": ["docs_fetcher"],
    "content": ["docs_fetcher"],
    "researcher": ["docs_fetcher"],
    "scout": ["web_search"],
}


def _uv_server(name: str) -> dict:
    server_dir = _SERVERS / name
    return {
        "command": "uv",
        "args": [
            "--project", str(server_dir),
            "run", str(server_dir / "server.py"),
        ],
    }


_ALL_MCP: dict[str, dict] = {
    "docs_fetcher": _uv_server("docs_fetcher"),
    "system_monitor": _uv_server("system_monitor"),
    "web_search": _uv_server("web_search"),
}


class PreCompactCounter:
    """Counts the PreCompact hook events of one worker invocation.

    Its on_pre_compact method is registered as the worker's PreCompact hook
    callback. It only counts the event and keeps its trigger ("manual" or
    "auto"); it returns an empty dict, which is no decision, so the worker's
    behaviour is unchanged. It never raises.
    """

    def __init__(self) -> None:
        self.count = 0
        self.triggers: list[str] = []

    async def on_pre_compact(self, input_data: Any, tool_use_id: Optional[str], context: Any) -> dict:
        self.count += 1
        try:
            trigger = input_data.get("trigger")
        except Exception:
            trigger = None
        self.triggers.append(str(trigger) if trigger is not None else "not reported")
        return {}


def precompact_counter(options: Any) -> Optional[PreCompactCounter]:
    """Return the PreCompactCounter registered in options by build_options, else None.

    Any options object without that registration (a test double, or options
    built elsewhere) gives None. Never raises.
    """
    try:
        for matcher in (getattr(options, "hooks", None) or {}).get("PreCompact", []):
            for callback in getattr(matcher, "hooks", []):
                owner = getattr(callback, "__self__", None)
                if isinstance(owner, PreCompactCounter):
                    return owner
    except Exception:
        return None
    return None


def build_validator_options() -> ClaudeAgentOptions:
    """Build read-only ClaudeAgentOptions for the Validator internal process.

    The Validator is not a routable worker — it is an internal coordinator process.
    It receives no MCP servers and no write tools to prevent any modification to
    the deliverable under review (grounded: kb_claude_agent_sdk.md, §ClaudeAgentOptions).
    cwd is set to repo root so the Validator can access deliverables at any output/ path.
    """
    return ClaudeAgentOptions(
        allowed_tools=["Read", "Glob", "Grep"],
        mcp_servers={},
        permission_mode="acceptEdits",
        cwd=str(_REPO_ROOT.resolve()),
        setting_sources=[],
    )


def build_options(worker_name: str, resume: Optional[str] = None) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions for a worker.

    cwd is set to the worker's directory so the SDK subprocess loads the worker's
    CLAUDE.md automatically (setting_sources=None default preserves this behavior).
    The root CLAUDE.md (Meta-Orchestrator rules, an ancestor of the worker dir) and
    the owner's auto-memory are excluded via inline settings so a worker sees only
    its own rules.
    Context-use signals: a fresh PreCompactCounter is registered as the PreCompact
    hook callback (it counts, never decides; find it with precompact_counter), and
    include_hook_events=True puts hook lifecycle events in the message stream.
    """
    worker_dir = WORKER_DIRS[worker_name]
    mcp = {name: _ALL_MCP[name] for name in _WORKER_MCP_NAMES[worker_name]}
    return ClaudeAgentOptions(
        allowed_tools=_WORKER_TOOLS[worker_name],
        mcp_servers=mcp,
        permission_mode="acceptEdits",
        cwd=str(worker_dir.resolve()),
        resume=resume,
        settings=json.dumps({
            "claudeMdExcludes": [str((_REPO_ROOT / "CLAUDE.md").resolve())],
            "autoMemoryEnabled": False,
        }),
        hooks={"PreCompact": [HookMatcher(hooks=[PreCompactCounter().on_pre_compact])]},
        include_hook_events=True,
    )
