import pytest

from conftest import HEALTH_HOOK, FakeProc


def tip_line(message):
    for line in message.splitlines():
        if "Close if not in use" in line:
            return line.strip()
    return None


@pytest.mark.parametrize(
    "name, exe, label",
    [
        ("Google Chrome Helper", "", "Chrome"),
        ("helper", "/Applications/zoom.us.app/Contents/MacOS/zoom.us", "Zoom"),
        ("Messages", "", "Messages"),
        ("slack", "", "Slack"),
        ("Slack Helper (Renderer)", "", "Slack"),
        ("helper", "/Applications/Slack.app/Contents/Frameworks/helper", "Slack"),
        ("helper", "/Applications/SLACK.APP/Contents/MacOS/x", "Slack"),
    ],
)
def test_heavy_app_is_reported(healthy, run_hook, name, exe, label):
    healthy(swap_mb=600, procs=[FakeProc(name=name, exe=exe)])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert tip_line(payload["systemMessage"]) == f"Fix: Close if not in use: {label}"


@pytest.mark.parametrize(
    "name, exe",
    [
        ("MessagesBlastDoorService", ""),
        ("helper", "/Users/x/Slack-notes/run"),
        ("Slackbot", ""),
        ("helper", "/Users/x/Slack.app.bak/run"),
    ],
)
def test_lookalike_process_is_not_reported(healthy, run_hook, name, exe):
    healthy(swap_mb=600, procs=[FakeProc(name=name, exe=exe)])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert tip_line(payload["systemMessage"]) is None
