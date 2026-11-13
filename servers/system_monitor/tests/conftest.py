import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
HEALTH_HOOK = SERVER_DIR / "health_check_hook.py"
REMINDER_HOOK = SERVER_DIR / "claude_md_reminder_hook.py"
SERVER_FILE = SERVER_DIR / "server.py"

DATA_MOUNT = "/System/Volumes/Data"
GB = 1024 ** 3
MB = 1024 ** 2


class FakeProc:
    """Stand-in for a psutil.Process yielded by process_iter(attrs)."""

    def __init__(self, name="", exe=""):
        self.info = {"name": name, "exe": exe}


def partition(mountpoint=DATA_MOUNT):
    return SimpleNamespace(device="/dev/disk3s1", mountpoint=mountpoint, fstype="apfs", opts="rw")


def disk_usage(free_pct, total_gb=500):
    total = total_gb * GB
    used_pct = round(100 - free_pct, 1)
    return SimpleNamespace(
        total=total,
        used=int(total * used_pct / 100),
        free=int(total * free_pct / 100),
        percent=used_pct,
    )


def battery(percent, plugged):
    return SimpleNamespace(percent=percent, secsleft=-1, power_plugged=plugged)


@pytest.fixture
def healthy(monkeypatch):
    """Patch psutil to a healthy machine; returns a setter for individual readings."""
    state = {
        "cpu": 10.0,
        "swap_mb": 0,
        "procs": [],
        "partitions": [partition()],
        "usage": disk_usage(50.0),
        "battery": battery(80, True),
    }

    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None, percpu=False: state["cpu"])
    monkeypatch.setattr(
        psutil, "swap_memory", lambda: SimpleNamespace(used=state["swap_mb"] * MB, total=8 * GB, percent=0.0)
    )
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None, ad_value=None: iter(state["procs"]))
    monkeypatch.setattr(psutil, "disk_partitions", lambda all=False: state["partitions"])

    def fake_disk_usage(path):
        if isinstance(state["usage"], Exception):
            raise state["usage"]
        return state["usage"]

    monkeypatch.setattr(psutil, "disk_usage", fake_disk_usage)
    monkeypatch.setattr(psutil, "sensors_battery", lambda: state["battery"])

    def set_(**kwargs):
        state.update(kwargs)
        return state

    return set_


@pytest.fixture
def run_hook(capsys):
    """Execute a hook script and return (parsed JSON payload, raw stdout, script globals)."""

    def _run(path):
        namespace = runpy.run_path(str(path), run_name="hook_under_test")
        out = capsys.readouterr().out
        return json.loads(out), out, namespace

    return _run
