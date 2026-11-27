"""Tests for coordinator.worker_registry (build_options, build_validator_options),
orchestrator._preregister_urls and the coordinator.__main__ command-line flags.

No live SDK calls and no network. ClaudeAgentOptions objects are only constructed,
never run. Registry files and the run() entry point are redirected or stubbed.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests
"""
import asyncio
import json
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from coordinator import __main__ as cli
from coordinator import orchestrator, worker_registry
from coordinator.worker_registry import build_options, build_validator_options

REPO_ROOT = Path(worker_registry.__file__).parent.parent
WORKERS = ("developer", "architect", "content", "researcher", "scout")


# ---------------------------------------------------------------------------
# worker_registry: tables are consistent
# ---------------------------------------------------------------------------

def test_registry_tables_cover_the_same_workers():
    assert set(worker_registry.WORKER_DIRS) == set(WORKERS)
    assert set(worker_registry._WORKER_TOOLS) == set(WORKERS)
    assert set(worker_registry._WORKER_MCP_NAMES) == set(WORKERS)


def test_every_worker_mcp_name_has_a_server_definition():
    for worker, names in worker_registry._WORKER_MCP_NAMES.items():
        for name in names:
            assert name in worker_registry._ALL_MCP, (worker, name)


def test_worker_dirs_and_server_files_exist_in_the_repo():
    for worker, path in worker_registry.WORKER_DIRS.items():
        assert path == REPO_ROOT / "workers" / worker
        assert (path / "CLAUDE.md").is_file(), worker
    for name in worker_registry._ALL_MCP:
        assert (REPO_ROOT / "servers" / name / "server.py").is_file(), name


def test_uv_server_definition_shape():
    cfg = worker_registry._uv_server("docs_fetcher")
    server_dir = REPO_ROOT / "servers" / "docs_fetcher"
    assert cfg["command"] == "uv"
    assert cfg["args"] == ["--project", str(server_dir), "run", str(server_dir / "server.py")]


# ---------------------------------------------------------------------------
# build_options
# ---------------------------------------------------------------------------

def test_build_options_returns_agent_options_with_worker_cwd():
    for worker in WORKERS:
        opts = build_options(worker)
        assert isinstance(opts, ClaudeAgentOptions)
        assert opts.cwd == str(worker_registry.WORKER_DIRS[worker].resolve())
        assert opts.permission_mode == "acceptEdits"
        assert opts.resume is None


def test_build_options_resume_is_passed_through():
    assert build_options("developer", resume="sess-1").resume == "sess-1"


def test_build_options_tools_per_worker():
    assert build_options("developer").allowed_tools == ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    for worker in ("architect", "content", "researcher", "scout"):
        assert build_options(worker).allowed_tools == ["Read", "Glob", "Grep", "Write"], worker


def test_only_developer_has_bash_or_edit():
    for worker in WORKERS:
        tools = build_options(worker).allowed_tools
        if worker == "developer":
            assert "Bash" in tools and "Edit" in tools
        else:
            assert "Bash" not in tools and "Edit" not in tools, worker


def test_build_options_mcp_servers_per_worker():
    expected = {
        "developer": {"docs_fetcher", "system_monitor"},
        "architect": {"docs_fetcher"},
        "content": {"docs_fetcher"},
        "researcher": {"docs_fetcher"},
        "scout": {"web_search"},
    }
    for worker, names in expected.items():
        assert set(build_options(worker).mcp_servers) == names, worker


def test_only_scout_has_web_search():
    for worker in WORKERS:
        has = "web_search" in build_options(worker).mcp_servers
        assert has == (worker == "scout"), worker


def test_build_options_mcp_server_configs_use_uv():
    servers = build_options("developer").mcp_servers
    assert servers["system_monitor"] == worker_registry._uv_server("system_monitor")
    assert servers["docs_fetcher"]["command"] == "uv"


def test_build_options_unknown_worker_raises_key_error():
    try:
        build_options("wizard")
    except KeyError:
        return
    raise AssertionError("expected KeyError for an unknown worker")


# ---------------------------------------------------------------------------
# build_validator_options
# ---------------------------------------------------------------------------

def test_validator_options_are_read_only_and_serverless():
    opts = build_validator_options()
    assert isinstance(opts, ClaudeAgentOptions)
    assert opts.allowed_tools == ["Read", "Glob", "Grep"]
    assert opts.mcp_servers == {}
    for forbidden in ("Write", "Edit", "Bash"):
        assert forbidden not in opts.allowed_tools


def test_validator_options_cwd_is_repo_root_and_no_setting_sources():
    opts = build_validator_options()
    assert opts.cwd == str(REPO_ROOT.resolve())
    assert opts.setting_sources == []
    assert opts.resume is None


def test_validator_options_each_call_is_independent():
    first = build_validator_options()
    first.allowed_tools.append("Write")
    assert build_validator_options().allowed_tools == ["Read", "Glob", "Grep"]


# ---------------------------------------------------------------------------
# _preregister_urls
# ---------------------------------------------------------------------------

@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "_DOCS_FETCHER_DIR", tmp_path)
    return tmp_path


def _read(reg, name):
    return json.loads((reg / name).read_text(encoding="utf-8"))


def test_preregister_none_and_empty_do_nothing(reg, capsys):
    orchestrator._preregister_urls(None)
    orchestrator._preregister_urls("")
    assert list(reg.iterdir()) == []
    assert capsys.readouterr().out == ""


def test_preregister_creates_missing_files_for_each_key(reg, capsys):
    payload = {
        "libraries": {"lib": "https://l.example"},
        "clis": {"tool": "https://c.example"},
        "other": {"spec": "https://o.example"},
    }
    orchestrator._preregister_urls(json.dumps(payload))
    assert _read(reg, "libraries.json") == {"lib": "https://l.example"}
    assert _read(reg, "clis.json") == {"tool": "https://c.example"}
    assert _read(reg, "other_sources.json") == {"spec": "https://o.example"}
    out = capsys.readouterr().out
    assert out.count("Registered 1") == 3


def test_preregister_omitted_and_empty_keys_create_no_file(reg):
    orchestrator._preregister_urls(json.dumps({"libraries": {"a": "https://a"}, "clis": {}}))
    assert sorted(p.name for p in reg.iterdir()) == ["libraries.json"]


def test_preregister_merges_and_never_overwrites_existing_names(reg, capsys):
    (reg / "libraries.json").write_text(json.dumps({"keep": "https://old", "other": "https://x"}), encoding="utf-8")
    orchestrator._preregister_urls(json.dumps({"libraries": {"keep": "https://NEW", "added": "https://a"}}))
    assert _read(reg, "libraries.json") == {"keep": "https://old", "other": "https://x", "added": "https://a"}
    assert "Registered 1 libraries URL(s): ['added']" in capsys.readouterr().out


def test_preregister_is_idempotent(reg, capsys):
    payload = json.dumps({"other": {"a": "https://a"}})
    orchestrator._preregister_urls(payload)
    before = (reg / "other_sources.json").read_text(encoding="utf-8")
    capsys.readouterr()
    orchestrator._preregister_urls(payload)
    assert (reg / "other_sources.json").read_text(encoding="utf-8") == before
    assert "No new other URLs to register" in capsys.readouterr().out


def test_preregister_invalid_json_warns_and_writes_nothing(reg, capsys):
    orchestrator._preregister_urls("{not json")
    assert list(reg.iterdir()) == []
    assert "WARNING: could not parse --approved-urls JSON" in capsys.readouterr().out


def test_preregister_unknown_keys_are_ignored(reg):
    orchestrator._preregister_urls(json.dumps({"misc": {"a": "https://a"}}))
    assert list(reg.iterdir()) == []


def test_preregister_non_object_json_warns_instead_of_crashing(reg, capsys):
    for payload in ("[1, 2]", "null", '"text"', "3"):
        orchestrator._preregister_urls(payload)  # must not raise
    assert list(reg.iterdir()) == []


def test_preregister_entries_not_an_object_warns_instead_of_crashing(reg):
    orchestrator._preregister_urls(json.dumps({"libraries": ["https://a"]}))  # must not raise
    assert list(reg.iterdir()) == []


def test_preregister_url_in_another_file_is_not_duplicated(reg, capsys):
    url = "https://docs.pytest.org/en/stable/how-to/skipping.html"
    (reg / "libraries.json").write_text(json.dumps({"pytest_skipping": url}), encoding="utf-8")
    before = (reg / "libraries.json").read_text(encoding="utf-8")
    orchestrator._preregister_urls(json.dumps({"other": {"pytest_skip": url}}))
    assert not (reg / "other_sources.json").exists()
    assert (reg / "libraries.json").read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert f"Skipped other 'pytest_skip': {url} is already registered in libraries.json as 'pytest_skipping'." in out
    assert "Registered" not in out


def test_preregister_url_in_target_file_under_another_name_is_not_duplicated(reg, capsys):
    (reg / "libraries.json").write_text(json.dumps({"old_name": "https://u"}), encoding="utf-8")
    orchestrator._preregister_urls(json.dumps({"libraries": {"new_name": "https://u"}}))
    assert _read(reg, "libraries.json") == {"old_name": "https://u"}
    out = capsys.readouterr().out
    assert "already registered in libraries.json as 'old_name'" in out
    assert "all already present" not in out


def test_preregister_name_with_different_url_keeps_old_and_warns(reg, capsys):
    (reg / "libraries.json").write_text(json.dumps({"wandb": "https://docs.wandb.ai/"}), encoding="utf-8")
    orchestrator._preregister_urls(json.dumps({"libraries": {"wandb": "https://docs.wandb.ai/guides"}}))
    assert _read(reg, "libraries.json") == {"wandb": "https://docs.wandb.ai/"}
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "kept https://docs.wandb.ai/, did not register https://docs.wandb.ai/guides" in out
    assert "all already present" not in out


def test_preregister_name_and_url_both_present_is_skipped_quietly(reg, capsys):
    (reg / "clis.json").write_text(json.dumps({"git": "https://git-scm.com/docs"}), encoding="utf-8")
    before = (reg / "clis.json").read_text(encoding="utf-8")
    orchestrator._preregister_urls(json.dumps({"clis": {"git": "https://git-scm.com/docs"}}))
    assert (reg / "clis.json").read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "No new clis URLs to register (all already present)." in out
    assert "WARNING" not in out and "Skipped" not in out


def test_preregister_same_url_twice_in_one_payload_is_written_once(reg, capsys):
    payload = {"libraries": {"a": "https://same"}, "other": {"b": "https://same"}}
    orchestrator._preregister_urls(json.dumps(payload))
    assert _read(reg, "libraries.json") == {"a": "https://same"}
    assert not (reg / "other_sources.json").exists()
    assert "already registered in libraries.json as 'a'" in capsys.readouterr().out


def test_preregister_url_match_is_exact_string(reg):
    (reg / "libraries.json").write_text(json.dumps({"x": "https://a.example/"}), encoding="utf-8")
    orchestrator._preregister_urls(json.dumps({"other": {"y": "https://a.example"}}))
    assert _read(reg, "other_sources.json") == {"y": "https://a.example"}


def test_preregister_mixed_payload_writes_only_new_entries(reg, capsys):
    (reg / "other_sources.json").write_text(json.dumps({"held": "https://dup"}), encoding="utf-8")
    orchestrator._preregister_urls(json.dumps({"other": {"copy": "https://dup", "fresh": "https://new"}}))
    assert _read(reg, "other_sources.json") == {"held": "https://dup", "fresh": "https://new"}
    assert "Registered 1 other URL(s): ['fresh']" in capsys.readouterr().out


def test_preregister_returns_empty_when_nothing_is_processed(reg):
    assert orchestrator._preregister_urls(None) == {}
    assert orchestrator._preregister_urls("") == {}
    assert orchestrator._preregister_urls("{not json") == {}
    assert orchestrator._preregister_urls("[1, 2]") == {}
    assert orchestrator._preregister_urls(json.dumps({"misc": {"a": "https://a"}})) == {}
    assert orchestrator._preregister_urls(json.dumps({"libraries": ["https://a"], "clis": {}})) == {}


def test_preregister_returns_target_file_and_name_for_new_entries(reg):
    payload = {"libraries": {"lib": "https://l.example"}, "other": {"spec": "https://o.example"}}
    assert orchestrator._preregister_urls(json.dumps(payload)) == {
        "libraries": {"lib": ("libraries.json", "lib")},
        "other": {"spec": ("other_sources.json", "spec")},
    }


def test_preregister_returns_existing_entry_when_name_and_url_present(reg):
    (reg / "clis.json").write_text(json.dumps({"git": "https://git-scm.com/docs"}), encoding="utf-8")
    result = orchestrator._preregister_urls(json.dumps({"clis": {"git": "https://git-scm.com/docs"}}))
    assert result == {"clis": {"git": ("clis.json", "git")}}


def test_preregister_returns_holder_when_url_is_registered_under_another_name(reg):
    url = "https://docs.pytest.org/en/stable/how-to/skipping.html"
    (reg / "libraries.json").write_text(json.dumps({"pytest_skipping": url}), encoding="utf-8")
    result = orchestrator._preregister_urls(json.dumps({"other": {"pytest_skip": url}}))
    assert result == {"other": {"pytest_skip": ("libraries.json", "pytest_skipping")}}


def test_preregister_returns_none_when_name_is_held_by_a_different_url(reg):
    (reg / "libraries.json").write_text(json.dumps({"wandb": "https://docs.wandb.ai/"}), encoding="utf-8")
    result = orchestrator._preregister_urls(json.dumps({"libraries": {"wandb": "https://docs.wandb.ai/guides"}}))
    assert result == {"libraries": {"wandb": None}}


def test_preregister_returns_first_name_for_same_url_twice_in_one_payload(reg):
    payload = {"libraries": {"a": "https://same"}, "other": {"b": "https://same"}}
    assert orchestrator._preregister_urls(json.dumps(payload)) == {
        "libraries": {"a": ("libraries.json", "a")},
        "other": {"b": ("libraries.json", "a")},
    }


def test_preregister_returns_one_outcome_per_name_in_mixed_payload(reg):
    (reg / "other_sources.json").write_text(
        json.dumps({"held": "https://dup", "taken": "https://old"}), encoding="utf-8"
    )
    payload = {"other": {"copy": "https://dup", "fresh": "https://new", "taken": "https://other"}}
    assert orchestrator._preregister_urls(json.dumps(payload)) == {
        "other": {
            "copy": ("other_sources.json", "held"),
            "fresh": ("other_sources.json", "fresh"),
            "taken": None,
        }
    }


UNREADABLE = ["", "{not json", "[]"]  # empty file, invalid JSON, a JSON array


@pytest.mark.parametrize("content", UNREADABLE)
def test_preregister_unreadable_non_target_file_warns_and_other_entries_are_handled(reg, capsys, content):
    (reg / "clis.json").write_text(content, encoding="utf-8")
    result = orchestrator._preregister_urls(json.dumps({"libraries": {"lib": "https://l.example"}}))
    assert result == {"libraries": {"lib": ("libraries.json", "lib")}}
    assert _read(reg, "libraries.json") == {"lib": "https://l.example"}
    assert (reg / "clis.json").read_text(encoding="utf-8") == content  # never written
    out = capsys.readouterr().out
    assert "WARNING" in out and "clis.json" in out


@pytest.mark.parametrize("content", UNREADABLE)
def test_preregister_unreadable_target_file_is_not_written(reg, capsys, content):
    (reg / "other_sources.json").write_text(content, encoding="utf-8")
    payload = {"other": {"spec": "https://o.example"}, "libraries": {"lib": "https://l.example"}}
    result = orchestrator._preregister_urls(json.dumps(payload))
    assert result == {
        "libraries": {"lib": ("libraries.json", "lib")},
        "other": {"spec": None},
    }
    assert (reg / "other_sources.json").read_text(encoding="utf-8") == content  # never written
    assert _read(reg, "libraries.json") == {"lib": "https://l.example"}
    out = capsys.readouterr().out
    assert "other_sources.json" in out and "WARNING" in out
    assert "did not register other URL(s): ['spec']" in out
    assert "Registered 1 other" not in out


def test_preregister_unreadable_target_reports_holder_in_a_readable_file(reg):
    (reg / "other_sources.json").write_text("", encoding="utf-8")
    (reg / "libraries.json").write_text(json.dumps({"held": "https://dup"}), encoding="utf-8")
    result = orchestrator._preregister_urls(json.dumps({"other": {"copy": "https://dup"}}))
    assert result == {"other": {"copy": ("libraries.json", "held")}}
    assert (reg / "other_sources.json").read_text(encoding="utf-8") == ""


def test_preregister_unreadable_file_warns_once_per_call(reg, capsys):
    (reg / "clis.json").write_text("[]", encoding="utf-8")
    payload = {"libraries": {"a": "https://a"}, "other": {"b": "https://b"}}
    orchestrator._preregister_urls(json.dumps(payload))
    assert capsys.readouterr().out.count("clis.json does not hold a JSON object") == 1


# ---------------------------------------------------------------------------
# __main__ flags
# ---------------------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, task, **kwargs):
        self.calls.append((task, kwargs))


@pytest.fixture
def main_env(monkeypatch):
    rec = _Recorder()
    inputs = []
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        assert inputs, f"unexpected input() call: {prompt!r}"
        return inputs.pop(0)

    monkeypatch.setattr(cli, "run", rec)
    monkeypatch.setattr(cli, "input", fake_input, raising=False)
    rec.inputs = inputs
    rec.prompts = prompts
    return rec


def _argv(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["coordinator", *args])


def test_cli_all_flags_are_forwarded_to_run(main_env, monkeypatch):
    _argv(
        monkeypatch, "my task",
        "--workers", "architect,developer",
        "--output", "../../output/final_outputs/t/r.md",
        "--sections", "Summary,Results",
        "--approved-urls", '{"other": {"a": "https://a"}}',
    )
    cli.main()
    assert main_env.calls == [("my task", {
        "workers": "architect,developer",
        "output": "../../output/final_outputs/t/r.md",
        "sections": "Summary,Results",
        "approved_urls": '{"other": {"a": "https://a"}}',
    })]
    assert main_env.prompts == []


def test_cli_defaults_are_none_so_run_prompts_interactively(main_env, monkeypatch):
    _argv(monkeypatch, "only a task")
    cli.main()
    assert main_env.calls == [("only a task", {
        "workers": None, "output": None, "sections": None, "approved_urls": None,
    })]


def test_cli_task_is_prompted_when_omitted(main_env, monkeypatch):
    _argv(monkeypatch, "--workers", "developer")
    main_env.inputs.append("  typed task  ")
    cli.main()
    assert main_env.prompts == ["Task: "]
    assert main_env.calls[0][0] == "typed task"
    assert main_env.calls[0][1]["workers"] == "developer"


def test_cli_empty_sections_value_is_not_collapsed_to_none(main_env, monkeypatch):
    # run() skips its sections prompt only when sections is not None, so "" must survive.
    _argv(monkeypatch, "t", "--sections", "")
    cli.main()
    assert main_env.calls[0][1]["sections"] == ""


def test_cli_flag_order_does_not_matter(main_env, monkeypatch):
    _argv(monkeypatch, "--output", "o.md", "--workers", "scout", "the task")
    cli.main()
    task, kwargs = main_env.calls[0]
    assert task == "the task" and kwargs["workers"] == "scout" and kwargs["output"] == "o.md"


def test_cli_unknown_flag_exits_with_usage_error(main_env, monkeypatch, capsys):
    _argv(monkeypatch, "t", "--nope")
    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")
    assert main_env.calls == []
    assert "unrecognized arguments" in capsys.readouterr().err


def test_cli_flag_without_value_exits_with_usage_error(main_env, monkeypatch):
    _argv(monkeypatch, "t", "--workers")
    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")
    assert main_env.calls == []


def test_cli_help_lists_every_flag(main_env, monkeypatch, capsys):
    _argv(monkeypatch, "--help")
    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    for flag in ("--workers", "--output", "--sections", "--approved-urls"):
        assert flag in out
    assert "python -m coordinator" in out
    assert main_env.calls == []


def test_cli_run_is_awaited_to_completion(main_env, monkeypatch):
    finished = []

    async def slow_run(task, **kwargs):
        await asyncio.sleep(0)
        finished.append(task)

    monkeypatch.setattr(cli, "run", slow_run)
    _argv(monkeypatch, "t")
    cli.main()
    assert finished == ["t"]


