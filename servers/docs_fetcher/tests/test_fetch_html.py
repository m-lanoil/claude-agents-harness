import subprocess

import httpx
import pytest

import server
from conftest import FakeResponse

URL = "https://example.dev/page"
PDF_BYTES = b"%PDF-1.4 fake pdf body"


def test_success_returns_response_text_and_caches_it(web):
    web.add_html(URL, "<html><body>hello</body></html>")

    result = server._fetch_html(URL)

    assert result == "<html><body>hello</body></html>"
    assert server._cache == {URL: "<html><body>hello</body></html>"}
    assert web.calls == [
        (URL, {"headers": server.REQUEST_HEADERS, "follow_redirects": True, "timeout": 30})
    ]


def test_cache_hit_returns_cached_text_without_a_request(web):
    server._cache[URL] = "<p>cached</p>"

    assert server._fetch_html(URL) == "<p>cached</p>"
    assert web.calls == []


def test_second_call_for_same_url_makes_only_one_request(web):
    web.add_html(URL, "<p>once</p>")

    server._fetch_html(URL)
    server._fetch_html(URL)

    assert web.urls == [URL]


@pytest.mark.parametrize("code", [401, 403])
def test_auth_status_codes_add_manual_hint(web, code):
    web.pages[URL] = FakeResponse(status_code=code)

    result = server._fetch_html(URL)

    assert result == {
        "error": (
            f"HTTP {code} fetching {URL} - the site is blocking automated requests "
            f"or requires access. {server.MANUAL_HINT}"
        )
    }
    assert URL not in server._cache


@pytest.mark.parametrize("code", [404, 429, 500, 503])
def test_other_status_codes_return_short_error(web, code):
    web.pages[URL] = FakeResponse(status_code=code)

    assert server._fetch_html(URL) == {"error": f"HTTP {code} fetching {URL}"}
    assert URL not in server._cache


def test_request_error_is_reported_with_its_message(web):
    web.pages[URL] = httpx.ConnectError("boom", request=httpx.Request("GET", URL))

    assert server._fetch_html(URL) == {"error": "Request failed: boom"}
    assert URL not in server._cache


def test_timeout_is_a_request_error_too(web):
    web.pages[URL] = httpx.TimeoutException("slow", request=httpx.Request("GET", URL))

    assert server._fetch_html(URL) == {"error": "Request failed: slow"}


def test_pdf_without_pdftotext_returns_install_hint_and_is_not_cached(web, monkeypatch):
    web.pages[URL] = FakeResponse(
        content=PDF_BYTES, headers={"content-type": "application/pdf"}
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: None)

    expected = {
        "error": f"PDF returned but pdftotext is not installed (install poppler). {server.MANUAL_HINT}"
    }
    assert server._fetch_html(URL) == expected
    assert server._fetch_html(URL) == expected
    assert URL not in server._cache
    assert web.urls == [URL, URL]


def test_pdf_timeout_returns_error(web, monkeypatch):
    web.pages[URL] = FakeResponse(
        content=PDF_BYTES, headers={"content-type": "application/pdf"}
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/pdftotext")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="pdftotext", timeout=60)

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    assert server._fetch_html(URL) == {
        "error": f"pdftotext timed out after 60s. {server.MANUAL_HINT}"
    }
    assert URL not in server._cache


@pytest.mark.parametrize(
    "returncode, stdout",
    [(1, b""), (1, b"some text"), (0, b""), (0, b"  \n \t\n")],
    ids=["exit1-empty", "exit1-with-text", "exit0-empty", "exit0-whitespace"],
)
def test_pdf_bad_exit_or_blank_output_returns_error(web, monkeypatch, returncode, stdout):
    web.pages[URL] = FakeResponse(
        content=PDF_BYTES, headers={"content-type": "application/pdf"}
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a[0], returncode=returncode, stdout=stdout, stderr=b""
        ),
    )

    assert server._fetch_html(URL) == {
        "error": (
            f"pdftotext could not read this PDF (exit {returncode}; "
            f"scanned, encrypted or malformed?). {server.MANUAL_HINT}"
        )
    }
    assert URL not in server._cache


@pytest.mark.parametrize(
    "headers, content",
    [
        ({"content-type": "application/pdf"}, b"not starting with magic"),
        ({"content-type": "APPLICATION/PDF; charset=binary"}, b"not starting with magic"),
        ({"content-type": "text/html"}, PDF_BYTES),
        ({}, PDF_BYTES),
    ],
    ids=["content-type", "content-type-mixed-case", "magic-bytes-only", "no-content-type"],
)
def test_pdf_is_detected_by_content_type_or_magic_bytes(web, monkeypatch, headers, content):
    web.pages[URL] = FakeResponse(content=content, headers=headers)
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a[0], returncode=0, stdout=b"extracted", stderr=b""
        ),
    )

    result = server._fetch_html(URL)

    assert result == "extracted"
    assert isinstance(result, server._PlainText)


def test_pdf_success_runs_pdftotext_on_stdin_and_caches_plain_text(web, monkeypatch):
    web.pages[URL] = FakeResponse(
        content=PDF_BYTES, headers={"content-type": "application/pdf"}
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/pdftotext")
    run_calls = []

    def fake_run(*args, **kwargs):
        run_calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout=b"page one\npage two", stderr=b""
        )

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    result = server._fetch_html(URL)

    assert result == "page one\npage two"
    assert isinstance(server._cache[URL], server._PlainText)
    assert run_calls == [
        ((["pdftotext", "-nopgbrk", "-", "-"],), {"input": PDF_BYTES, "capture_output": True, "timeout": 60})
    ]


def test_pdf_output_is_decoded_as_utf8_with_replacement(web, monkeypatch):
    web.pages[URL] = FakeResponse(
        content=PDF_BYTES, headers={"content-type": "application/pdf"}
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a[0], returncode=0, stdout=b"ok \xff end", stderr=b""
        ),
    )

    assert server._fetch_html(URL) == "ok � end"
