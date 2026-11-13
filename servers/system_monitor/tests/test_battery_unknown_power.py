import pytest

from conftest import HEALTH_HOOK, battery
from test_health_check_hook import line_of, status_of, verdict_of


@pytest.mark.parametrize(
    "percent, expected",
    [(5, "WARN"), (15, "WARN"), (20, "WARN"), (21, "GO"), (80, "GO")],
)
def test_unknown_power_state_status(healthy, run_hook, percent, expected):
    healthy(battery=battery(percent, None))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert status_of(payload["systemMessage"], "Battery") == expected


@pytest.mark.parametrize("percent", [5, 15, 20, 21, 80])
def test_unknown_power_state_detail_says_power_state_unknown(healthy, run_hook, percent):
    healthy(battery=battery(percent, None))
    payload, _, _ = run_hook(HEALTH_HOOK)
    line = line_of(payload["systemMessage"], "Battery")
    assert f"Battery at {percent}%, power state unknown" in line
    assert "unplugged" not in line


@pytest.mark.parametrize("percent", [5, 15, 20])
def test_unknown_power_state_at_or_below_20_suggests_charger(healthy, run_hook, percent):
    healthy(battery=battery(percent, None))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Fix: Connect charger soon" in payload["systemMessage"]


@pytest.mark.parametrize("percent", [21, 80])
def test_unknown_power_state_above_20_has_no_tip(healthy, run_hook, percent):
    healthy(battery=battery(percent, None))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert "Fix:" not in payload["systemMessage"]


def test_unknown_power_state_never_stops_the_verdict(healthy, run_hook):
    healthy(battery=battery(5, None))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert verdict_of(payload["systemMessage"]) == "WARN"
