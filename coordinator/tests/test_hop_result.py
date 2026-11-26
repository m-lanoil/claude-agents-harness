"""Tests for the result entries of the brief record in coordinator.orchestrator.

After every worker invocation (routing, acceptance correction, semantic
correction, blocked-fetch resume) the hop's brief-record file gets a result
entry under "## Result N: <kind> — <timestamp>": the returned fields
(self_critique verbatim) and the context-use signals read from the message
stream. Validator invocations are not recorded.

No live SDK calls and no network. A fake `query` plays the workers and the
Validator and yields real claude_agent_sdk message objects. Worker dirs sit two
levels under tmp_path so the code's `../../output/...` paths land in
tmp_path/output.

Run from the repo root:
    uv run --with claude-agent-sdk --with pytest python -m pytest coordinator/tests/test_hop_result.py
"""
import asyncio
import json
import re
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ConversationResetMessage,
    HookEventMessage,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TaskNotificationMessage,
)

from coordinator import orchestrator, worker_registry
from coordinator.tests.test_brief_record import parse_record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KIND_ROUTING = "routing prompt"
KIND_ACCEPTANCE = "acceptance correction prompt"
KIND_SEMANTIC = "semantic correction prompt"
KIND_RESUME = "blocked-fetch resume prompt"

_STAMP = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
_PROMPT_HEADING_RE = re.compile(rf"^## (\d+)\. (.+) — {_STAMP}$")
_RESULT_HEADING_RE = re.compile(rf"^## Result (\d+): (.+) — {_STAMP}$")
_FENCE_RE = re.compile(r"^(`{3,})(\w*)$")
_EXPECTED_RE = re.compile(r"^Expected output: (.+)$", re.MULTILINE)


def _fence(data: dict) -> str:
    return "Some prose.\n\n```json\n" + json.dumps(data) + "\n```"


PASS = _fence({"verdict": "pass", "issues": [], "confidence": 0.9, "summary": "fine"})


def parse_entries(path: Path) -> list[dict]:
    """Every entry of a record file, in file order, skipping fenced content.

    Each entry: {"type": "prompt" | "result", "n": int, "kind": str, "stamp": str,
    "body": list[str]}.
    """
    entries: list[dict] = []
    fence = None
    for line in path.read_text(encoding="utf-8").split("\n"):
        if fence is not None:
            if line == fence:
                fence = None
            if entries:
                entries[-1]["body"].append(line)
            continue
        opening = _FENCE_RE.match(line)
        if opening:
            fence = opening.group(1)
            if entries:
                entries[-1]["body"].append(line)
            continue
        for kind, regex in (("prompt", _PROMPT_HEADING_RE), ("result", _RESULT_HEADING_RE)):
            m = regex.match(line)
            if m:
                entries.append({
                    "type": kind, "n": int(m.group(1)), "kind": m.group(2),
                    "stamp": m.group(3), "body": [],
                })
                break
        else:
            if entries:
                entries[-1]["body"].append(line)
    return entries


def fenced_after(body: list[str], label: str) -> str:
    """Text of the first code fence after the line equal to label."""
    i = body.index(label)
    while not _FENCE_RE.match(body[i]):
        i += 1
    fence = _FENCE_RE.match(body[i]).group(1)
    end = body.index(fence, i + 1)
    return "\n".join(body[i + 1:end])


def results(path: Path) -> list[dict]:
    return [e for e in parse_entries(path) if e["type"] == "result"]


def body_text(entry: dict) -> str:
    return "\n".join(entry["body"])


def _init(session_id="s1") -> SystemMessage:
    return SystemMessage(subtype="init", data={"session_id": session_id})


def _result(text, session_id="s1", **overrides) -> ResultMessage:
    fields = dict(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
        num_turns=1, session_id=session_id, result=text,
    )
    fields.update(overrides)
    return ResultMessage(**fields)


def _step(message_id, input_tokens, cache_read, cache_creation, model="claude-x", parent=None):
    return AssistantMessage(
        content=[], model=model, parent_tool_use_id=parent, message_id=message_id,
        usage={
            "input_tokens": input_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_creation,
            "output_tokens": 1,
        },
    )


def _task_notification(usage):
    return TaskNotificationMessage(
        subtype="task_notification", data={}, task_id="t1", status="completed",
        output_file="", summary="done", uuid="u1", session_id="s1", usage=usage,
    )


class FireHook:
    """Script marker: call the options' PreCompact callbacks, as the CLI would."""

    def __init__(self, trigger):
        self.trigger = trigger


class Env:
    def __init__(self, tmp_path):
        self.dirs = {}
        for name in ("architect", "developer"):
            d = tmp_path / "workers" / name
            d.mkdir(parents=True)
            self.dirs[name] = d
        self.log_path = tmp_path / "worker_updates.md"
        self.output_root = tmp_path / "output"
        self.final = self.output_root / "final_outputs" / "topic_x" / "report.md"
        self.expected = str(self.final)
        self.script: list = []          # one item per worker call (see fake_query)
        self.validator: list[str] = []
        self.validator_prompts: list[str] = []
        self.inputs: list[str] = []
        self.hook_outputs: list = []

    def complete_text(self, self_critique="ok", gaps=None, write=True) -> str:
        if write:
            target = Path(self.expected)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Summary\nbody\n", encoding="utf-8")
        return _fence({
            "deliverable_path": self.expected,
            "status": "complete",
            "self_critique": self_critique,
            "gaps": gaps if gaps is not None else [],
        })

    def record_file(self) -> Path:
        files = sorted(self.output_root.glob("intermediate_outputs/*/*_brief_*.md"))
        assert len(files) == 1, files
        return files[0]

    def log_text(self) -> str:
        return self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)

    async def fake_query(*, prompt, options):
        if options == {"validator": True}:
            e.validator_prompts.append(prompt)
            yield _result(e.validator.pop(0))
            return
        match = _EXPECTED_RE.search(prompt)
        if match:
            e.expected = match.group(1).strip()
        item = e.script.pop(0)
        # An item is "complete" / "noop" (no deliverable written) / "blocked",
        # or a callable taking env and returning a list of messages and FireHook markers.
        if item == "complete":
            messages = [_init(), _result(e.complete_text())]
        elif item == "noop":
            messages = [_init(), _result(e.complete_text(write=False))]
        elif item == "blocked":
            messages = [_init(), _result(_fence({
                "status": "blocked",
                "blocked_sources": [{"source": "lib_docs", "reason": "paywall", "candidates": ["https://x"]}],
            }))]
        else:
            messages = item(e)
        for message in messages:
            if isinstance(message, FireHook):
                for matcher in (getattr(options, "hooks", None) or {}).get("PreCompact", []):
                    for callback in matcher.hooks:
                        e.hook_outputs.append(await callback(
                            {"hook_event_name": "PreCompact", "trigger": message.trigger,
                             "custom_instructions": None, "session_id": "s1",
                             "transcript_path": "/t", "cwd": "/c"},
                            None,
                            {"signal": None},
                        ))
                continue
            yield message

    def fake_input(prompt=""):
        assert e.inputs, f"unexpected input() call: {prompt!r}"
        return e.inputs.pop(0)

    monkeypatch.setattr(orchestrator, "query", fake_query)
    monkeypatch.setattr(
        orchestrator, "build_options",
        lambda worker, resume=None: {"worker": worker, "resume": resume},
    )
    monkeypatch.setattr(orchestrator, "build_validator_options", lambda: {"validator": True})
    monkeypatch.setattr(orchestrator, "input", fake_input, raising=False)
    monkeypatch.setattr(orchestrator, "WORKER_DIRS", dict(e.dirs))
    monkeypatch.setattr(orchestrator, "_WORKER_UPDATES_LOG", e.log_path)
    return e


@pytest.fixture
def real_options(monkeypatch):
    """Use the real worker_registry.build_options (no SDK call is made)."""
    monkeypatch.setattr(orchestrator, "build_options", worker_registry.build_options)


def _chain(env, task="Produce the thing."):
    return asyncio.run(orchestrator._execute_chain(
        hop_workers=["developer"],
        task=task,
        expected_output_path=str(env.final),
        required_sections=["Summary"],
        run_stamp="20261126-120000",
    ))


# ---------------------------------------------------------------------------
# Order and returned fields
# ---------------------------------------------------------------------------

def test_result_entry_follows_each_invocation_in_send_order(env):
    # routing (claims a file it never wrote) -> acceptance correction (complete) -> Validator pass
    env.script = ["noop", "complete"]
    env.validator = [PASS]
    env.inputs = ["yes", "yes", "yes"]

    assert _chain(env) is True

    path = env.record_file()
    order = [(e["type"], e["n"], e["kind"]) for e in parse_entries(path)]
    assert order == [
        ("prompt", 1, KIND_ROUTING),
        ("result", 1, KIND_ROUTING),
        ("prompt", 2, KIND_ACCEPTANCE),
        ("result", 2, KIND_ACCEPTANCE),
    ]
    for entry in parse_entries(path):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", entry["stamp"])
    # The prompt entries still read exactly as before (existing parser).
    assert [k for k, _, _ in parse_record(path)] == [KIND_ROUTING, KIND_ACCEPTANCE]
    # Validator invocations are not recorded.
    assert len(env.validator_prompts) == 1
    assert "You are a Validator" not in path.read_text(encoding="utf-8")


def test_returned_fields_are_recorded(env):
    env.script = [lambda e: [_init(), _result(e.complete_text("fine", ["gap one", "gap two"]))]]
    env.validator = [PASS]
    env.inputs = ["yes", ""]  # approve; acknowledge gaps

    assert _chain(env) is True

    (entry,) = results(env.record_file())
    text = body_text(entry)
    assert "- status: complete" in text
    assert f"- deliverable_path: {env.expected}" in text
    assert fenced_after(entry["body"], "- self_critique (verbatim):") == "fine"
    assert json.loads(fenced_after(entry["body"], "- gaps:")) == ["gap one", "gap two"]
    assert "blocked_sources" not in text


def test_self_critique_is_written_verbatim_including_backtick_fences(env):
    critique = "Used ```python\nprint('x')\n``` here, a ````` run, and a bare\n```\nline."
    env.script = [lambda e: [_init(), _result(e.complete_text(critique))]]
    env.validator = [PASS]
    env.inputs = ["yes"]

    assert _chain(env) is True

    (entry,) = results(env.record_file())
    assert fenced_after(entry["body"], "- self_critique (verbatim):") == critique


def test_malformed_return_is_recorded_with_its_gap_line(env):
    env.script = [lambda e: [_init(), _result("No JSON block at all.")]]
    env.inputs = ["yes", "abort"]  # approve routing; decline the acceptance retry

    assert _chain(env) is False

    (entry,) = results(env.record_file())
    assert "- status: malformed" in body_text(entry)
    assert json.loads(fenced_after(entry["body"], "- gaps:")) == [
        "Worker return block missing or malformed — JSON block not found"
    ]


def test_blocked_return_is_recorded_with_blocked_sources(env):
    env.script = ["blocked", "complete"]
    env.validator = [PASS]
    env.inputs = ["yes", "3"]  # approve routing; continue without the source

    assert _chain(env) is True

    first, second = results(env.record_file())
    assert (first["n"], first["kind"], second["n"], second["kind"]) == (1, KIND_ROUTING, 2, KIND_RESUME)
    assert "- status: blocked" in body_text(first)
    assert json.loads(fenced_after(first["body"], "- blocked_sources:")) == [
        {"source": "lib_docs", "reason": "paywall", "candidates": ["https://x"]}
    ]
    assert "- status: complete" in body_text(second)


# ---------------------------------------------------------------------------
# Context-use signals
# ---------------------------------------------------------------------------

def _full_stream(e):
    return [
        _init(),
        _step("m1", 100, 1000, 50),
        _step("m1", 100, 1000, 50),                    # parallel tool call: same message_id
        _step("m2", 10, 4990, 0),
        _step("sub1", 900000, 900000, 0, parent="tu1"),  # subagent message: skipped
        FireHook("auto"),
        HookEventMessage(subtype="hook_started", data={}, hook_event_name="PreCompact"),
        SystemMessage(subtype="compact_boundary", data={}),
        _task_notification({"total_tokens": 300, "tool_uses": 2, "duration_ms": 5}),
        _task_notification(None),
        ConversationResetMessage(new_conversation_id="c2", uuid="u2", session_id="s1"),
        _result(
            e.complete_text(),
            total_cost_usd=0.42, num_turns=7, terminal_reason="completed",
            model_usage={"claude-x": {
                "inputTokens": 10, "outputTokens": 800, "cacheReadInputTokens": 6000,
                "cacheCreationInputTokens": 50, "webSearchRequests": 0, "costUSD": 0.42,
                "contextWindow": 200000, "maxOutputTokens": 32000,
            }},
        ),
    ]


def test_each_of_the_six_signals_is_recorded(env, real_options):
    env.script = [_full_stream]
    env.validator = [PASS]
    env.inputs = ["yes"]

    assert _chain(env) is True

    (entry,) = results(env.record_file())
    text = body_text(entry)
    # 1. Result totals
    assert ("Result totals (last ResultMessage): total_cost_usd 0.42, num_turns 7, "
            "subtype success, terminal_reason completed") in text
    assert ("claude-x: input + cache-read + cache-creation tokens 6060 (10 + 6000 + 50), "
            "output tokens 800, contextWindow 200000") in text
    # 2. Peak context estimate
    assert "Peak context estimate (inferred, not a documented formula): 5000 / 200000 = 2.5%" in text
    # 3. Compaction flag from the PreCompact callback
    assert ("Compaction flag (PreCompact hook callback; not yet seen live): "
            "compacted, 1 event(s), triggers: auto") in text
    # 4. Stream side
    assert ("Stream side (include_hook_events=True; unverified live): "
            "PreCompact HookEventMessage: 1 (hook_started); "
            "other SystemMessage subtypes: compact_boundary x1") in text
    # 5. Subagent tokens
    assert ("Subagent tokens (sum of TaskNotificationMessage.usage.total_tokens; unverified live): "
            "300 from 2 notification(s), 1 without usage skipped") in text
    # 6. Guards
    assert "Guards: zeroed usage: no (result subtype success); ConversationResetMessage: arrived (1)" in text
    assert "Signal-collection errors: none" in text
    # The callback made no decision.
    assert env.hook_outputs == [{}]


def test_duplicate_message_id_counted_once_and_subagent_messages_skipped(env, real_options):
    env.script = [_full_stream]
    env.validator = [PASS]
    env.inputs = ["yes"]
    _chain(env)

    text = body_text(results(env.record_file())[0])
    assert ("2 top-level step(s) counted (deduplicated by message_id), "
            "1 duplicate(s) and 1 subagent message(s) skipped") in text
    assert "900000" not in text.split("Peak context estimate")[1].split("\n")[0]


def test_error_during_execution_flags_zeroed_usage(env):
    env.script = [lambda e: [_init(), _result("", subtype="error_during_execution", is_error=True)]]
    env.inputs = ["yes", "abort"]

    assert _chain(env) is False

    text = body_text(results(env.record_file())[0])
    assert "- status: malformed" in text
    assert "zeroed usage: usage may be zeroed (result subtype error_during_execution)" in text
    assert "ConversationResetMessage: did not arrive" in text


def test_missing_fields_are_written_as_not_reported(env):
    # No usage on the step, no cost / model_usage / terminal_reason on the result,
    # and options without a PreCompact callback (the env's fake build_options).
    def stream(e):
        return [
            _init(),
            AssistantMessage(content=[], model="claude-x", message_id="m1", usage=None),
            _result(e.complete_text()),
        ]

    env.script = [stream]
    env.validator = [PASS]
    env.inputs = ["yes"]
    _chain(env)

    text = body_text(results(env.record_file())[0])
    assert "total_cost_usd not reported" in text
    assert "terminal_reason not reported" in text
    assert "model_usage: not reported" in text
    assert "Peak context estimate (inferred, not a documented formula): not reported" in text
    assert "not reported (no PreCompact callback registered)" in text
    assert "no TaskNotificationMessage arrived" in text
    assert "total_cost_usd 0" not in text


def test_missing_model_usage_keys_are_not_reported(env):
    def stream(e):
        return [
            _init(),
            _step("m1", 10, 20, 30),
            _result(e.complete_text(), total_cost_usd=0.1, model_usage={
                "claude-x": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 20},
            }),
        ]

    env.script = [stream]
    env.validator = [PASS]
    env.inputs = ["yes"]
    _chain(env)

    text = body_text(results(env.record_file())[0])
    assert ("claude-x: input + cache-read + cache-creation tokens not reported "
            "(10 + 20 + not reported), output tokens 5, contextWindow not reported") in text
    assert "60 / contextWindow not reported" in text


# ---------------------------------------------------------------------------
# The PreCompact callback and its registration
# ---------------------------------------------------------------------------

def test_precompact_callback_counts_and_returns_no_decision():
    counter = worker_registry.PreCompactCounter()
    hook_input = {"hook_event_name": "PreCompact", "trigger": "manual", "custom_instructions": None,
                  "session_id": "s", "transcript_path": "/t", "cwd": "/c"}

    out = asyncio.run(counter.on_pre_compact(hook_input, None, {"signal": None}))
    assert out == {}
    out = asyncio.run(counter.on_pre_compact({"hook_event_name": "PreCompact"}, None, {"signal": None}))
    assert out == {}
    out = asyncio.run(counter.on_pre_compact(None, None, {"signal": None}))  # odd input: no raise
    assert out == {}

    assert counter.count == 3
    assert counter.triggers == ["manual", "not reported", "not reported"]


def test_build_options_registers_a_fresh_counter_and_hook_events():
    first = worker_registry.build_options("developer")
    second = worker_registry.build_options("developer", resume="s1")

    assert first.include_hook_events is True
    assert list(first.hooks) == ["PreCompact"]
    (matcher,) = first.hooks["PreCompact"]
    assert isinstance(matcher, HookMatcher) and matcher.matcher is None
    counter = worker_registry.precompact_counter(first)
    assert isinstance(counter, worker_registry.PreCompactCounter)
    assert worker_registry.precompact_counter(second) is not counter
    assert worker_registry.precompact_counter({"worker": "developer"}) is None


def test_validator_options_are_unchanged():
    options = worker_registry.build_validator_options()
    assert options.hooks is None
    assert options.include_hook_events is False


# ---------------------------------------------------------------------------
# Failures never stop the hop
# ---------------------------------------------------------------------------

class _ExplodingUsage(dict):
    def get(self, *args, **kwargs):
        raise RuntimeError("boom")


def test_signal_collection_error_is_noted_and_the_hop_continues(env):
    def stream(e):
        return [
            _init(),
            AssistantMessage(content=[], model="claude-x", message_id="m1",
                             usage=_ExplodingUsage(input_tokens=1)),
            _result(e.complete_text()),
        ]

    env.script = [stream]
    env.validator = [PASS]
    env.inputs = ["yes"]

    assert _chain(env) is True

    text = body_text(results(env.record_file())[0])
    assert "Signal-collection errors: AssistantMessage: RuntimeError: boom" in text
    assert "- status: complete" in text
    assert "Hop 1/1 accepted" in env.log_text()


def test_result_write_failure_warns_logs_and_lets_the_hop_finish(env, monkeypatch, capsys):
    real_write = orchestrator._BriefRecord._write

    def failing_write(self):
        if self._entries[-1].startswith("\n## Result"):
            raise OSError("disk full")
        real_write(self)

    monkeypatch.setattr(orchestrator._BriefRecord, "_write", failing_write)
    env.script = ["complete"]
    env.validator = [PASS]
    env.inputs = ["yes"]

    assert _chain(env) is True

    out = capsys.readouterr().out
    assert "[brief record] WARNING" in out
    assert "The routing prompt result was NOT recorded; the hop continues." in out
    log = env.log_text()
    assert "brief record write failed" in log and "routing prompt result" in log and "disk full" in log
    assert "Hop 1/1 accepted" in log
    # The prompt entry that was written is still there.
    assert [k for k, _, _ in parse_record(env.record_file())] == [KIND_ROUTING]
