import psutil
import pytest

from conftest import HEALTH_HOOK, DATA_MOUNT, FakeProc, battery, disk_usage, partition


def status_of(message, component):
    """Return the [STATUS] shown on the line for a component, or None if it has no line."""
    for line in message.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and f"] {component}:" in stripped:
            return stripped[1 : stripped.index("]")]
    return None


def line_of(message, component):
    for line in message.splitlines():
        if f"] {component}:" in line:
            return line
    return None


def verdict_of(message):
    first = message.splitlines()[0]
    return first.split(" ")[2]


# ---------------------------------------------------------------- output shape


def test_output_is_one_json_object_with_session_start_payload(healthy, run_hook):
    healthy()
    payload, raw, _ = run_hook(HEALTH_HOOK)
    assert raw.count("\n") == 1
    assert set(payload) == {"systemMessage", "hookSpecificOutput"}
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert payload["hookSpecificOutput"]["additionalContext"] == payload["systemMessage"]


def test_summary_first_line_and_component_order(healthy, run_hook):
    healthy()
    payload, _, _ = run_hook(HEALTH_HOOK)
    message = payload["systemMessage"]
    assert message.splitlines()[0] == "System Health: GO — All systems healthy — good to go."
    components = [
        line.split("] ", 1)[1].split(":", 1)[0]
        for line in message.splitlines()
        if line.startswith("  [")
    ]
    assert components == ["CPU", "Swap", "Disk", "Battery"]


def test_fix_line_only_printed_when_a_tip_exists(healthy, run_hook):
    healthy(cpu=99.0)
    payload, _, _ = run_hook(HEALTH_HOOK)
    lines = payload["systemMessage"].splitlines()
    cpu_index = next(i for i, line in enumerate(lines) if "] CPU:" in line)
    assert lines[cpu_index + 1].strip().startswith("Fix: Kill runaway processes")
    assert not any("Fix:" in line for line in lines[cpu_index + 2 :])


# ------------------------------------------------------------------------ CPU


@pytest.mark.parametrize(
    "cpu, expected",
    [(0.0, "GO"), (79.9, "GO"), (80.0, "WARN"), (95.0, "WARN"), (95.1, "STOP"), (100.0, "STOP")],
)
def test_cpu_thresholds(healthy, run_hook, cpu, expected):
    healthy(cpu=cpu)
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert status_of(payload["systemMessage"], "CPU") == expected


def test_cpu_reading_is_formatted_to_one_decimal(healthy, run_hook):
    healthy(cpu=82.456)
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "CPU at 82.5%" in payload["systemMessage"]


# ----------------------------------------------------------------------- swap


@pytest.mark.parametrize(
    "swap_mb, expected",
    [(0, "GO"), (499, "GO"), (500, "WARN"), (1024, "WARN"), (1025, "STOP")],
)
def test_swap_thresholds_without_claude(healthy, run_hook, swap_mb, expected):
    healthy(swap_mb=swap_mb)
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert status_of(payload["systemMessage"], "Swap") == expected


def test_swap_over_1024_is_only_warn_when_claude_is_running(healthy, run_hook):
    healthy(swap_mb=2000, procs=[FakeProc(name="Claude", exe="/Applications/Claude.app/Contents/MacOS/Claude")])
    payload, _, _ = run_hook(HEALTH_HOOK)
    message = payload["systemMessage"]
    assert status_of(message, "Swap") == "WARN"
    assert "active Claude Code session" in line_of(message, "Swap")


def test_swap_tip_lists_heavy_apps_once_each(healthy, run_hook):
    healthy(
        swap_mb=600,
        procs=[
            FakeProc(name="Google Chrome"),
            FakeProc(name="Google Chrome Helper"),
            FakeProc(name="Slack"),
            FakeProc(name="python"),
        ],
    )
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Fix: Close if not in use: Chrome, Slack" in payload["systemMessage"]


def test_swap_tip_matches_heavy_app_by_exe_path(healthy, run_hook):
    healthy(swap_mb=600, procs=[FakeProc(name="helper", exe="/Applications/zoom.us.app/Contents/MacOS/zoom.us")])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Close if not in use: Zoom" in payload["systemMessage"]


def test_swap_over_1024_without_heavy_apps_or_claude_suggests_finding_hogs(healthy, run_hook):
    healthy(swap_mb=2000, procs=[FakeProc(name="python")])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Fix: Find hogs: ps aux -m | head -10" in payload["systemMessage"]


def test_swap_below_500_has_no_tip_even_with_heavy_apps(healthy, run_hook):
    healthy(swap_mb=100, procs=[FakeProc(name="Slack")])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Close if not in use" not in payload["systemMessage"]


def test_processes_with_missing_name_or_exe_are_tolerated(healthy, run_hook):
    healthy(swap_mb=600, procs=[FakeProc(name=None, exe=None), FakeProc(name="Discord")])
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Close if not in use: Discord" in payload["systemMessage"]


# ----------------------------------------------------------------------- disk


@pytest.mark.parametrize(
    "free_pct, expected",
    [(50.0, "GO"), (20.0, "GO"), (19.9, "WARN"), (10.0, "WARN"), (9.9, "STOP"), (1.0, "STOP")],
)
def test_disk_thresholds(healthy, run_hook, free_pct, expected):
    healthy(usage=disk_usage(free_pct))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert status_of(payload["systemMessage"], "Disk") == expected


def test_disk_detail_reports_free_gb_and_percent(healthy, run_hook):
    healthy(usage=disk_usage(25.0, total_gb=400))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Disk healthy — 100.0 GB (25.0%) free" in payload["systemMessage"]


def test_disk_only_checks_the_data_volume(healthy, run_hook, monkeypatch):
    seen = []
    healthy(partitions=[partition("/"), partition("/Volumes/Backup")], usage=disk_usage(1.0))
    monkeypatch.setattr(psutil, "disk_usage", lambda path: seen.append(path))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert seen == []
    assert status_of(payload["systemMessage"], "Disk") is None


def test_disk_usage_is_requested_for_the_data_mountpoint(healthy, run_hook, monkeypatch):
    seen = []
    healthy(partitions=[partition("/"), partition(DATA_MOUNT)])

    def fake_usage(path):
        seen.append(path)
        return disk_usage(50.0)

    monkeypatch.setattr(psutil, "disk_usage", fake_usage)
    run_hook(HEALTH_HOOK)
    assert seen == [DATA_MOUNT]


def test_disk_oserror_drops_the_disk_line_without_failing(healthy, run_hook):
    healthy(usage=OSError("gone"))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert status_of(payload["systemMessage"], "Disk") is None
    assert status_of(payload["systemMessage"], "Battery") == "GO"


# -------------------------------------------------------------------- battery


def test_no_battery_is_go(healthy, run_hook):
    healthy(battery=None)
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "[GO] Battery: No battery detected" in payload["systemMessage"]


@pytest.mark.parametrize(
    "percent, plugged, expected",
    [
        (80, False, "GO"),
        (20.1, False, "GO"),
        (20, False, "WARN"),
        (10.1, False, "WARN"),
        (10, False, "STOP"),
        (1, False, "STOP"),
        (1, True, "GO"),
        (15, True, "GO"),
    ],
)
def test_battery_thresholds(healthy, run_hook, percent, plugged, expected):
    healthy(battery=battery(percent, plugged))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert status_of(payload["systemMessage"], "Battery") == expected


def test_battery_detail_says_plugged_in_or_unplugged(healthy, run_hook):
    healthy(battery=battery(90, True))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Battery at 90%, plugged in" in payload["systemMessage"]
    healthy(battery=battery(90, False))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Battery at 90%, unplugged" in payload["systemMessage"]


# ----------------------------------------------------------------- escalation


def test_all_healthy_gives_go_verdict(healthy, run_hook):
    healthy()
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert verdict_of(payload["systemMessage"]) == "GO"


def test_single_warn_gives_warn_verdict(healthy, run_hook):
    healthy(cpu=85.0)
    payload, _, _ = run_hook(HEALTH_HOOK)
    message = payload["systemMessage"]
    assert verdict_of(message) == "WARN"
    assert "proceed with caution" in message.splitlines()[0]


def test_stop_beats_warn_regardless_of_order(healthy, run_hook):
    healthy(cpu=85.0, swap_mb=2000)
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert verdict_of(payload["systemMessage"]) == "STOP"
    assert "resolve before starting work" in payload["systemMessage"].splitlines()[0]


def test_late_stop_is_not_downgraded_by_healthy_components(healthy, run_hook):
    healthy(battery=battery(5, False))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert verdict_of(payload["systemMessage"]) == "STOP"


def test_each_component_reports_its_own_status_while_verdict_is_the_worst(healthy, run_hook):
    healthy(cpu=85.0, swap_mb=100, usage=disk_usage(5.0), battery=battery(15, False))
    payload, _, _ = run_hook(HEALTH_HOOK)
    message = payload["systemMessage"]
    assert [status_of(message, c) for c in ("CPU", "Swap", "Disk", "Battery")] == ["WARN", "GO", "STOP", "WARN"]
    assert verdict_of(message) == "STOP"


@pytest.mark.parametrize(
    "current, new, expected",
    [
        ("GO", "GO", "GO"),
        ("GO", "WARN", "WARN"),
        ("WARN", "GO", "WARN"),
        ("WARN", "STOP", "STOP"),
        ("STOP", "WARN", "STOP"),
        ("STOP", "GO", "STOP"),
        ("WARN", "UNKNOWN", "WARN"),
    ],
)
def test_escalate_keeps_the_worst_level(healthy, run_hook, current, new, expected):
    healthy()
    _, _, namespace = run_hook(HEALTH_HOOK)
    assert namespace["_escalate"](current, new) == expected
