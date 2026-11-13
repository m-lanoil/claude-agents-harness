import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "<YOUR_PROJECT_ROOT>"
WORKERS = ["architect", "content", "developer", "researcher", "scout"]

MCP_TEMPLATES = [".mcp.template.json", "workers/scout/.mcp.template.json"]
SETTINGS_TEMPLATES = [".claude/settings.template.json", ".claude/settings.local.template.json"]
WORKER_TEMPLATES = [f"workers/{w}/.claude/settings.local.template.json" for w in WORKERS]
REGISTRY_TEMPLATES = [
    "servers/docs_fetcher/clis.template.json",
    "servers/docs_fetcher/libraries.template.json",
    "servers/docs_fetcher/other_sources.template.json",
]
ALL_TEMPLATES = MCP_TEMPLATES + SETTINGS_TEMPLATES + WORKER_TEMPLATES + REGISTRY_TEMPLATES

SERVER_DIRS = ["docs_fetcher", "system_monitor", "web_search"]


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def resolve(text):
    return Path(text.replace(PLACEHOLDER, str(ROOT)))


def server_tool_names(server):
    source = (ROOT / "servers" / server / "server.py").read_text(encoding="utf-8")
    return set(re.findall(r"^(?:async )?def (\w+)\(", source, re.MULTILINE))


def workers_table():
    """Parse the Workers table in CLAUDE.md into {worker_dir: [tool, ...]}."""
    table = {}
    for line in (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines():
        match = re.search(r"\./workers/(\w+)/", line)
        if not line.startswith("|") or not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        table[match.group(1)] = re.findall(r"`(\w+)`", cells[-1])
    return table


# ------------------------------------------------------------------ every file


@pytest.mark.parametrize("relative", ALL_TEMPLATES)
def test_template_exists_and_parses_as_a_json_object(relative):
    assert (ROOT / relative).is_file()
    assert isinstance(load(relative), dict)


@pytest.mark.parametrize("relative", ALL_TEMPLATES)
def test_template_has_no_hardcoded_home_directory(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "/Users/" not in text and "/home/" not in text


@pytest.mark.parametrize("relative", MCP_TEMPLATES + SETTINGS_TEMPLATES + WORKER_TEMPLATES)
def test_project_paths_use_the_placeholder_not_a_real_root(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert str(ROOT) not in text


# ------------------------------------------------------------- .mcp templates


@pytest.mark.parametrize("relative", MCP_TEMPLATES)
def test_mcp_servers_point_at_existing_project_and_script(relative):
    servers = load(relative)["mcpServers"]
    assert servers
    for name, spec in servers.items():
        assert spec["type"] == "stdio"
        assert spec["command"] == "uv"
        args = spec["args"]
        assert args[0] == "--project" and args[2] == "run" and len(args) == 4
        project, script = resolve(args[1]), resolve(args[3])
        assert (project / "pyproject.toml").is_file(), f"{name}: no pyproject.toml in {project}"
        assert script.is_file(), f"{name}: missing {script}"
        assert script == project / "server.py"
        assert project.name == name


def test_root_mcp_template_registers_system_monitor_and_docs_fetcher():
    assert set(load(".mcp.template.json")["mcpServers"]) == {"system_monitor", "docs_fetcher"}


def test_scout_mcp_template_registers_only_web_search_with_env_reference_for_the_key():
    servers = load("workers/scout/.mcp.template.json")["mcpServers"]
    assert set(servers) == {"web_search"}
    assert servers["web_search"]["env"] == {"BRAVE_SEARCH_API_KEY": "${BRAVE_SEARCH_API_KEY}"}


# ------------------------------------------------------------ settings (root)


def test_session_start_hooks_run_existing_scripts_and_never_fail_the_session():
    entries = load(".claude/settings.template.json")["hooks"]["SessionStart"]
    commands = [hook["command"] for entry in entries for hook in entry["hooks"]]
    assert len(commands) == 2
    scripts = []
    for command in commands:
        assert command.rstrip().endswith("|| true")
        paths = [resolve(token) for token in command.split() if PLACEHOLDER in token]
        assert paths and all(p.exists() for p in paths), command
        scripts.append(paths[-1].name)
    assert scripts == ["health_check_hook.py", "claude_md_reminder_hook.py"]


def test_root_local_template_enables_servers_from_the_root_mcp_template():
    enabled = set(load(".claude/settings.local.template.json")["enabledMcpjsonServers"])
    assert enabled == set(load(".mcp.template.json")["mcpServers"])


# ----------------------------------------------------- worker settings vs table


def test_workers_table_in_claude_md_lists_all_five_workers():
    assert sorted(workers_table()) == sorted(WORKERS)


@pytest.mark.parametrize("worker", WORKERS)
def test_enabled_servers_match_the_tools_in_the_workers_table(worker):
    settings = load(f"workers/{worker}/.claude/settings.local.template.json")
    assert set(settings["enabledMcpjsonServers"]) == set(workers_table()[worker])


@pytest.mark.parametrize("worker", WORKERS)
def test_disabled_servers_never_overlap_the_table_and_are_real_servers(worker):
    settings = load(f"workers/{worker}/.claude/settings.local.template.json")
    disabled = set(settings.get("disabledMcpjsonServers", []))
    assert not disabled & set(workers_table()[worker])
    assert disabled <= set(SERVER_DIRS)


@pytest.mark.parametrize("worker", WORKERS)
def test_allowed_mcp_tools_belong_to_an_enabled_server_and_exist(worker):
    settings = load(f"workers/{worker}/.claude/settings.local.template.json")
    allowed = [entry for entry in settings.get("permissions", {}).get("allow", []) if entry.startswith("mcp__")]
    for entry in allowed:
        rest = entry[len("mcp__"):]
        server = next((s for s in SERVER_DIRS if rest.startswith(s + "__")), None)
        assert server is not None, f"{entry}: unknown server"
        assert server in workers_table()[worker], f"{entry}: server not in the Workers table for {worker}"
        assert rest[len(server) + 2:] in server_tool_names(server), f"{entry}: no such tool function"


def test_scout_cannot_use_native_web_tools_or_bash():
    deny = load("workers/scout/.claude/settings.local.template.json")["permissions"]["deny"]
    assert {"WebFetch", "WebSearch", "Bash"} <= set(deny)


def test_scout_allows_exactly_the_web_search_tool():
    allow = load("workers/scout/.claude/settings.local.template.json")["permissions"]["allow"]
    assert allow == ["mcp__web_search__web_search"]


@pytest.mark.parametrize("relative", WORKER_TEMPLATES)
def test_worker_sandbox_settings_are_strict_where_present(relative):
    sandbox = load(relative).get("sandbox")
    if sandbox is None:
        pytest.skip("template defines no sandbox block")
    assert sandbox["enabled"] is True
    assert sandbox["failIfUnavailable"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert all(path.startswith(PLACEHOLDER) for path in sandbox["filesystem"]["allowWrite"])


@pytest.mark.parametrize("relative", WORKER_TEMPLATES)
def test_edit_deny_rules_use_the_placeholder_root(relative):
    deny = load(relative).get("permissions", {}).get("deny", [])
    for entry in deny:
        if entry.startswith("Edit("):
            assert entry.startswith(f"Edit(/{PLACEHOLDER}/"), entry


# ------------------------------------------------------- docs_fetcher registries


@pytest.mark.parametrize("relative", REGISTRY_TEMPLATES)
def test_registry_templates_map_names_to_https_urls(relative):
    data = load(relative)
    assert data
    for name, url in data.items():
        assert isinstance(name, str) and name
        assert isinstance(url, str) and url.startswith("https://"), f"{name}: {url}"
