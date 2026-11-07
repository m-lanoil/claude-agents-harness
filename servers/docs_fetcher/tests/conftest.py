import httpx
import pytest

import server


class FakeResponse:
    """Minimal stand-in for httpx.Response exposing only what server._fetch_html reads."""

    def __init__(self, status_code=200, text="", content=None, headers=None):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = headers if headers is not None else {"content-type": "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://example.com/"),
                response=self,
            )
        return self


class FakeWeb:
    """Records httpx.get calls and answers from a url -> FakeResponse | Exception mapping."""

    def __init__(self):
        self.pages = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url not in self.pages:
            raise AssertionError(f"unexpected request to {url}")
        outcome = self.pages[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def add_html(self, url, html):
        self.pages[url] = FakeResponse(text=html)

    @property
    def urls(self):
        return [url for url, _ in self.calls]


@pytest.fixture(autouse=True)
def isolated_server(monkeypatch, tmp_path):
    server._cache.clear()
    server._seen_content.clear()
    monkeypatch.setattr(server, "LIBRARIES_PATH", tmp_path / "libraries.json")
    monkeypatch.setattr(server, "CLIS_PATH", tmp_path / "clis.json")
    monkeypatch.setattr(server, "OTHER_SOURCES_PATH", tmp_path / "other_sources.json")
    yield
    server._cache.clear()
    server._seen_content.clear()


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(server.httpx, "get", fake.get)
    return fake
