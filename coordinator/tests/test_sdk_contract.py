"""Contract tests against the real claude_agent_sdk.

The other coordinator tests replace `query` with a fake, so a rename or signature
change in the installed SDK never reaches them. These tests use the real SDK
classes (`query`, `ClaudeAgentOptions`, `SystemMessage`, `ResultMessage`).

Offline part (always runs, no network, no model call): the signature of `query`,
the exact fields each options builder sets, and real message objects flowing
through `_invoke_worker` and `_invoke_validator`. The fake `query` binds its
arguments with `inspect.signature` of the real `query`, so a wrong keyword fails.

Live part (opt-in): one real call that costs a few tokens and needs the owner's
authentication. It is skipped unless COORDINATOR_LIVE_SDK=1.

Edge cases the SDK types allow are pinned too: a `ResultMessage.result` of None
counts as empty text, and a missing init session id falls back to the
ResultMessage session id.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests/test_sdk_contract.py
Live part:
    COORDINATOR_LIVE_SDK=1 uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests/test_sdk_contract.py -k live -rs
"""
import asyncio
import dataclasses
import inspect
import json
import os

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, SystemMessage, query

from coordinator import orchestrator, worker_registry
from coordinator.schemas import RoutingPrompt, WorkerResult

WORKERS = ("developer", "architect", "content", "researcher", "scout")

# Fields each builder passes to ClaudeAgentOptions(...), by keyword.
WORKER_PASSED = {"allowed_tools", "mcp_servers", "permission_mode", "cwd", "resume"}
VALIDATOR_PASSED = {"allowed_tools", "mcp_servers", "permission_mode", "cwd", "setting_sources"}

# Fields whose value differs from the dataclass default on the returned object.
# mcp_servers={} equals the default, so it only shows in the passed-keyword sets.
WORKER_NON_DEFAULT = {"allowed_tools", "mcp_servers", "permission_mode", "cwd"}
VALIDATOR_NON_DEFAULT = {"allowed_tools", "permission_mode", "cwd", "setting_sources"}

_QUERY_SIG = inspect.signature(query)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init(session_id="sess-1") -> SystemMessage:
    return SystemMessage(subtype="init", data={"session_id": session_id})


def _result(text="done", session_id="sess-1") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        result=text,
    )


def _fence(data: dict) -> str:
    return "Some prose.\n\n```json\n" + json.dumps(data) + "\n```"


def _verdict_text() -> str:
    return _fence({"verdict": "pass", "issues": [], "confidence": 0.9, "summary": "fine"})


def _fake_query(messages, calls):
    """Async-generator fake whose arguments are bound with the real query() signature."""
    async def fake(*args, **kwargs):
        bound = _QUERY_SIG.bind(*args, **kwargs)  # TypeError on a wrong keyword
        calls.append(dict(bound.arguments))
        for message in messages:
            yield message
    return fake


def _default_of(field: dataclasses.Field):
    if field.default is not dataclasses.MISSING:
        return field.default
    if field.default_factory is not dataclasses.MISSING:
        return field.default_factory()
    return dataclasses.MISSING


def _non_default_fields(options) -> set:
    return {
        f.name for f in dataclasses.fields(options)
        if getattr(options, f.name) != _default_of(f)
    }


@pytest.fixture
def spy_options(monkeypatch):
    """Record the keyword names worker_registry passes to the real ClaudeAgentOptions."""
    seen: list[set] = []

    class SpyOptions(ClaudeAgentOptions):
        def __init__(self, *args, **kwargs):
            assert not args, "builders must pass options by keyword"
            seen.append(set(kwargs))
            super().__init__(**kwargs)

    monkeypatch.setattr(worker_registry, "ClaudeAgentOptions", SpyOptions)
    return seen


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    path = tmp_path / "worker_updates.md"
    monkeypatch.setattr(orchestrator, "_WORKER_UPDATES_LOG", path)
    return path


def _invoke_worker(messages, calls, monkeypatch, resume=None):
    monkeypatch.setattr(orchestrator, "query", _fake_query(messages, calls))
    return asyncio.run(orchestrator._invoke_worker("developer", "the prompt", resume))


def _routing_and_result(tmp_path):
    deliverable = tmp_path / "deliverable.md"
    deliverable.write_text("# Summary\nbody\n", encoding="utf-8")
    routing = RoutingPrompt(
        worker="developer",
        prompt_text="the task",
        expected_output_path=str(deliverable),
        required_sections=["Summary"],
    )
    result = WorkerResult(
        raw_text="", deliverable_path=str(deliverable), status="complete",
        self_critique="ok", gaps=[], session_id="sess-1",
    )
    return routing, result


# ---------------------------------------------------------------------------
# query() signature
# ---------------------------------------------------------------------------

def test_query_is_an_async_generator_function():
    assert inspect.isasyncgenfunction(query)


def test_query_prompt_and_options_are_keyword_only():
    params = _QUERY_SIG.parameters
    for name in ("prompt", "options"):
        assert name in params, f"query() has no '{name}' parameter"
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["prompt"].default is inspect.Parameter.empty


def test_orchestrator_uses_the_sdk_query():
    assert orchestrator.query is query


def test_fake_query_rejects_a_wrong_keyword():
    fake = _fake_query([], [])

    async def drive():
        async for _ in fake(prompt="p", option=None):
            pass

    with pytest.raises(TypeError):
        asyncio.run(drive())


def test_fake_query_rejects_positional_arguments():
    fake = _fake_query([], [])

    async def drive():
        async for _ in fake("p", None):
            pass

    with pytest.raises(TypeError):
        asyncio.run(drive())


# ---------------------------------------------------------------------------
# Options builders return real ClaudeAgentOptions with an exact field set
# ---------------------------------------------------------------------------

def test_the_five_workers_are_registered():
    assert set(worker_registry.WORKER_DIRS) == set(WORKERS)


@pytest.mark.parametrize("worker", WORKERS)
def test_build_options_passes_exactly_the_expected_fields(worker, spy_options):
    options = worker_registry.build_options(worker)
    assert isinstance(options, ClaudeAgentOptions)
    assert spy_options == [WORKER_PASSED]
    sdk_fields = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
    assert WORKER_PASSED <= sdk_fields


@pytest.mark.parametrize("worker", WORKERS)
def test_build_options_sets_exactly_the_expected_non_default_fields(worker):
    options = worker_registry.build_options(worker)
    assert isinstance(options, ClaudeAgentOptions)
    assert _non_default_fields(options) == WORKER_NON_DEFAULT
    assert options.resume is None


@pytest.mark.parametrize("worker", WORKERS)
def test_build_options_resume_is_set_when_given(worker):
    options = worker_registry.build_options(worker, resume="sess-9")
    assert options.resume == "sess-9"
    assert _non_default_fields(options) == WORKER_NON_DEFAULT | {"resume"}


def test_build_validator_options_passes_exactly_the_expected_fields(spy_options):
    options = worker_registry.build_validator_options()
    assert isinstance(options, ClaudeAgentOptions)
    assert spy_options == [VALIDATOR_PASSED]
    sdk_fields = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
    assert VALIDATOR_PASSED <= sdk_fields


def test_build_validator_options_sets_exactly_the_expected_non_default_fields():
    options = worker_registry.build_validator_options()
    assert _non_default_fields(options) == VALIDATOR_NON_DEFAULT
    assert options.mcp_servers == {}
    assert options.allowed_tools == ["Read", "Glob", "Grep"]
    assert options.setting_sources == []


# ---------------------------------------------------------------------------
# _invoke_worker with real SDK message objects
# ---------------------------------------------------------------------------

def test_invoke_worker_returns_result_text_and_session_id(monkeypatch):
    calls = []
    text, session_id = _invoke_worker([_init("sess-1"), _result("hello")], calls, monkeypatch)
    assert (text, session_id) == ("hello", "sess-1")
    assert len(calls) == 1
    assert calls[0]["prompt"] == "the prompt"
    assert isinstance(calls[0]["options"], ClaudeAgentOptions)
    assert calls[0]["options"].resume is None


def test_invoke_worker_passes_resume_through_to_the_options(monkeypatch):
    calls = []
    _invoke_worker([_init("sess-2"), _result()], calls, monkeypatch, resume="sess-1")
    assert calls[0]["options"].resume == "sess-1"


def test_invoke_worker_ignores_a_non_init_system_message(monkeypatch):
    other = SystemMessage(subtype="status", data={"session_id": "not-this-one"})
    _, session_id = _invoke_worker([other, _init("sess-1"), _result()], [], monkeypatch)
    assert session_id == "sess-1"


def test_invoke_worker_init_without_session_id_falls_back_to_the_result_session_id(monkeypatch):
    bare = SystemMessage(subtype="init", data={})
    _, session_id = _invoke_worker([bare, _result(session_id="sess-from-result")], [], monkeypatch)
    assert session_id == "sess-from-result"


def test_invoke_worker_init_session_id_wins_over_the_result_session_id(monkeypatch):
    _, session_id = _invoke_worker(
        [_init("sess-init"), _result(session_id="sess-from-result")], [], monkeypatch
    )
    assert session_id == "sess-init"


def test_invoke_worker_result_none_is_empty_text(monkeypatch):
    # ResultMessage.result is `str | None`; the orchestrator treats None as "".
    text, session_id = _invoke_worker([_init("sess-1"), _result(text=None)], [], monkeypatch)
    assert text == ""
    assert session_id == "sess-1"


def test_result_none_makes_the_hop_malformed(monkeypatch):
    monkeypatch.setattr(
        orchestrator, "query", _fake_query([_init("sess-1"), _result(text=None)], [])
    )
    routing = RoutingPrompt(worker="developer", prompt_text="t", expected_output_path="x.md")
    check, result = asyncio.run(orchestrator._run_single_hop(routing, "the prompt"))
    assert result.status == "malformed"
    assert result.raw_text == ""
    assert result.session_id == "sess-1"
    assert check is not None
    assert check.passed is False


def test_no_init_message_uses_the_result_session_id(monkeypatch):
    result = _result("hello", session_id="sess-from-result")
    text, session_id = _invoke_worker([result], [], monkeypatch)
    assert text == "hello"
    assert session_id == "sess-from-result"


def test_no_init_message_blocked_return_keeps_the_session_to_resume(monkeypatch):
    blocked = _fence({"status": "blocked", "blocked_sources": [{"source": "s", "reason": "paywall"}]})
    monkeypatch.setattr(
        orchestrator, "query", _fake_query([_result(blocked, session_id="sess-from-result")], [])
    )
    routing = RoutingPrompt(worker="developer", prompt_text="t", expected_output_path="x.md")
    check, result = asyncio.run(orchestrator._run_single_hop(routing, "the prompt"))
    assert check is None
    assert result.status == "blocked"
    assert result.session_id == "sess-from-result"


def test_message_without_a_session_id_attribute_gives_none(monkeypatch):
    class Bare:
        result = "hello"

    _, session_id = _invoke_worker([Bare()], [], monkeypatch)
    assert session_id is None


# ---------------------------------------------------------------------------
# _invoke_validator with real SDK message objects
# ---------------------------------------------------------------------------

def _invoke_validator(messages, calls, monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "query", _fake_query(messages, calls))
    routing, result = _routing_and_result(tmp_path)
    return asyncio.run(orchestrator._invoke_validator(routing, result))


def test_invoke_validator_parses_a_real_result_message(monkeypatch, tmp_path, log_path):
    calls = []
    verdict = _invoke_validator([_init("v-1"), _result(_verdict_text())], calls, monkeypatch, tmp_path)
    assert verdict.verdict == "pass"
    assert verdict.confidence == 0.9
    assert len(calls) == 1
    assert isinstance(calls[0]["options"], ClaudeAgentOptions)
    assert calls[0]["options"].allowed_tools == ["Read", "Glob", "Grep"]
    assert calls[0]["options"].mcp_servers == {}
    assert "Original Task" in calls[0]["prompt"]


def test_invoke_validator_works_without_an_init_message(monkeypatch, tmp_path, log_path):
    verdict = _invoke_validator([_result(_verdict_text())], [], monkeypatch, tmp_path)
    assert verdict.verdict == "pass"


def test_invoke_validator_text_without_json_is_a_fail(monkeypatch, tmp_path, log_path):
    verdict = _invoke_validator([_result("no json here")], [], monkeypatch, tmp_path)
    assert verdict.verdict == "fail"
    assert verdict.confidence == 0.0
    assert "validator_fail: parse error" in log_path.read_text(encoding="utf-8")


def test_validator_result_none_is_a_parse_error_fail(monkeypatch, tmp_path, log_path):
    verdict = _invoke_validator([_result(text=None)], [], monkeypatch, tmp_path)
    assert verdict.verdict == "fail"
    assert verdict.confidence == 0.0
    assert "validator_fail: parse error" in log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Live part (opt-in)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("COORDINATOR_LIVE_SDK") != "1",
    reason=(
        "live SDK test: set COORDINATOR_LIVE_SDK=1 to run it. It makes one real call "
        "(a few tokens) and needs the owner's Claude authentication."
    ),
)
def test_live_invoke_worker_returns_session_id_and_text(monkeypatch, tmp_path):
    def minimal_options(worker_name, resume=None):
        options = worker_registry.build_validator_options()  # no MCP servers, no setting sources
        options.max_turns = 1
        options.allowed_tools = []
        options.cwd = str(tmp_path)  # no worker CLAUDE.md in reach
        options.resume = resume
        return options

    monkeypatch.setattr(orchestrator, "build_options", minimal_options)

    init_data: list[dict] = []
    real_query = orchestrator.query

    async def recording_query(*, prompt, options):
        async for message in real_query(prompt=prompt, options=options):
            if getattr(message, "subtype", None) == "init":
                init_data.append(message.data)
            yield message

    monkeypatch.setattr(orchestrator, "query", recording_query)

    text, session_id = asyncio.run(
        orchestrator._invoke_worker("developer", "Reply with the single word OK.")
    )

    assert init_data, "the CLI emitted no init SystemMessage"
    init_session = init_data[0].get("session_id")
    assert isinstance(init_session, str) and init_session, (
        f"init message data had no usable session_id: {init_data[0]!r}"
    )
    assert isinstance(session_id, str) and session_id
    assert session_id == init_session
    assert isinstance(text, str) and text.strip()
