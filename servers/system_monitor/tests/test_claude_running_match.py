import pytest

from conftest import HEALTH_HOOK, FakeProc

VSCODE_EXE = "/Users/x/.vscode/extensions/anthropic.claude-code-2.1.323-darwin-arm64/resources/native-binary/claude"


def swap_status(message):
    for line in message.splitlines():
        stripped = line.strip()
        if "] Swap:" in stripped:
            return stripped[1 : stripped.index("]")]
    return None


@pytest.mark.parametrize(
    "name, exe",
    [
        ("claude", VSCODE_EXE),
        ("2.1.323", "/Users/x/.local/share/claude/versions/2.1.323"),
        ("Claude", "/Applications/Claude.app/Contents/MacOS/Claude"),
        ("claude", ""),
        ("node", "/usr/local/bin/CLAUDE"),
        ("tool", "/opt/Claude/bin/tool"),
    ],
)
def test_claude_process_downgrades_swap_stop_to_warn(healthy, run_hook, name, exe):
    healthy(swap_mb=2000, procs=[FakeProc(name=name, exe=exe)])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert swap_status(payload["systemMessage"]) == "WARN"


@pytest.mark.parametrize(
    "name, exe",
    [
        ("sync", "/Users/x/claude-notes/sync"),
        ("tool", "/opt/anthropic.claude-code-1/bin/tool"),
        ("claudette", "/usr/bin/claudette"),
        ("python", ""),
    ],
)
def test_unrelated_process_does_not_downgrade_swap_stop(healthy, run_hook, name, exe):
    healthy(swap_mb=2000, procs=[FakeProc(name=name, exe=exe)])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert swap_status(payload["systemMessage"]) == "STOP"


def test_missing_name_and_exe_do_not_count_as_claude(healthy, run_hook):
    healthy(swap_mb=2000, procs=[FakeProc(name=None, exe=None)])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert swap_status(payload["systemMessage"]) == "STOP"
