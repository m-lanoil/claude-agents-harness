from pathlib import Path

import httpx
import pytest

SERVER_FILE = Path(__file__).resolve().parent.parent / "server.py"
API_KEY = "test-key-not-real"


class FakeResponse:
    """Minimal stand-in for httpx.Response exposing only what the server reads."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://example.invalid/"),
                response=self,
            )
        return self

    def json(self):
        return self._payload


class FakeBrave:
    """Replaces httpx.get: records calls and answers with a response or raises an exception."""

    def __init__(self):
        self.outcome = FakeResponse()
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    @property
    def params(self):
        return self.calls[-1][1]["params"]

    @property
    def headers(self):
        return self.calls[-1][1]["headers"]


@pytest.fixture(autouse=True)
def brave_api_key(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", API_KEY)


@pytest.fixture
def brave(monkeypatch):
    fake = FakeBrave()
    monkeypatch.setattr(httpx, "get", fake.get)
    return fake
