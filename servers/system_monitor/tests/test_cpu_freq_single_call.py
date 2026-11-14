from types import SimpleNamespace

import psutil

from mcp_helpers import call_tool


def patch_cpu(monkeypatch, cpu_freq):
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None, percpu=False: [1.0] if percpu else 1.0)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 2)
    monkeypatch.setattr(psutil, "cpu_freq", cpu_freq)


def counting_freq(calls):
    """Each call returns a different reading, so mixed readings are detectable."""

    def fake_cpu_freq(percpu=False):
        calls.append(percpu)
        n = len(calls)
        return SimpleNamespace(current=1000.0 + n, min=100.0 + n, max=2000.0 + n)

    return fake_cpu_freq


def test_cpu_freq_is_read_once_per_call(monkeypatch):
    calls = []
    patch_cpu(monkeypatch, counting_freq(calls))

    call_tool("get_cpu_stats")

    assert len(calls) == 1


def test_current_min_and_max_come_from_the_same_reading(monkeypatch):
    calls = []
    patch_cpu(monkeypatch, counting_freq(calls))

    data = call_tool("get_cpu_stats").data

    assert data["cpu_freq_mhz"] == {"current": 1001.0, "min": 101.0, "max": 2001.0}


def test_unavailable_frequency_is_read_once_and_reported_as_none(monkeypatch):
    calls = []

    def fake_cpu_freq(percpu=False):
        calls.append(percpu)
        return None

    patch_cpu(monkeypatch, fake_cpu_freq)

    data = call_tool("get_cpu_stats").data

    assert data["cpu_freq_mhz"] is None
    assert len(calls) == 1
