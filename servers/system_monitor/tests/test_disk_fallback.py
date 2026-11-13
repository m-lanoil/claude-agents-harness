import psutil
import pytest

from conftest import HEALTH_HOOK, DATA_MOUNT, disk_usage, partition


def disk_line(message):
    for line in message.splitlines():
        if "] Disk:" in line:
            return line.strip()
    return None


def record_usage(monkeypatch, seen, free_pct=50.0):
    def fake_usage(path):
        seen.append(path)
        return disk_usage(free_pct)

    monkeypatch.setattr(psutil, "disk_usage", fake_usage)


def test_root_is_checked_when_no_data_volume_exists(healthy, run_hook, monkeypatch):
    seen = []
    healthy(partitions=[partition("/"), partition("/Volumes/Backup")])
    record_usage(monkeypatch, seen, free_pct=50.0)
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert seen == ["/"]
    assert disk_line(payload["systemMessage"]).startswith("[GO] Disk:")


def test_root_fallback_reports_its_own_thresholds(healthy, run_hook, monkeypatch):
    seen = []
    healthy(partitions=[partition("/")])
    record_usage(monkeypatch, seen, free_pct=5.0)
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert disk_line(payload["systemMessage"]).startswith("[STOP] Disk:")


def test_data_volume_wins_over_root_and_only_it_is_checked(healthy, run_hook, monkeypatch):
    seen = []
    healthy(partitions=[partition("/"), partition(DATA_MOUNT)])
    record_usage(monkeypatch, seen)
    run_hook(HEALTH_HOOK)
    assert seen == [DATA_MOUNT]


def test_no_disk_line_when_neither_mount_exists(healthy, run_hook, monkeypatch):
    seen = []
    healthy(partitions=[partition("/Volumes/Backup"), partition("/home")])
    record_usage(monkeypatch, seen)
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert seen == []
    assert disk_line(payload["systemMessage"]) is None


def test_oserror_on_root_fallback_drops_the_disk_line(healthy, run_hook):
    healthy(partitions=[partition("/")], usage=OSError("gone"))
    payload, _, _ = run_hook(HEALTH_HOOK)
    assert disk_line(payload["systemMessage"]) is None
    assert "[GO] Battery:" in payload["systemMessage"]
