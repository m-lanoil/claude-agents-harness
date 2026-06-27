from pathlib import Path
from typing import Optional
from claude_agent_sdk import ClaudeAgentOptions

# Repo root: coordinator/worker_registry.py → coordinator/ → repo root
_REPO_ROOT = Path(__file__).parent.parent
_SERVERS = _REPO_ROOT / "servers"

WORKER_DIRS: dict[str, Path] = {
    "developer": _REPO_ROOT / "workers" / "developer",
    "architect": _REPO_ROOT / "workers" / "architect",
    "content": _REPO_ROOT / "workers" / "content",
}

_WORKER_TOOLS: dict[str, list[str]] = {
    "developer": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    "architect": ["Read", "Glob", "Grep", "Write"],
    "content": ["Read", "Glob", "Grep", "Write"],
}

_WORKER_MCP_NAMES: dict[str, list[str]] = {
    "developer": ["docs_fetcher", "system_monitor"],
    "architect": ["docs_fetcher"],
    "content": ["docs_fetcher"],
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
}


def build_options(worker_name: str, resume: Optional[str] = None) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions for a worker.

    cwd is set to the worker's directory so the SDK subprocess loads the worker's
    CLAUDE.md automatically (setting_sources=None default preserves this behavior).
    """
    worker_dir = WORKER_DIRS[worker_name]
    mcp = {name: _ALL_MCP[name] for name in _WORKER_MCP_NAMES[worker_name]}
    return ClaudeAgentOptions(
        allowed_tools=_WORKER_TOOLS[worker_name],
        mcp_servers=mcp,
        permission_mode="acceptEdits",
        cwd=str(worker_dir.resolve()),
        resume=resume,
    )
