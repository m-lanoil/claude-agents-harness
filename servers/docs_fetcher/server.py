import json
import re
import shutil
import subprocess
import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from fastmcp import FastMCP

mcp = FastMCP("docs_fetcher")

# Sites commonly block httpx's default User-Agent (403 or a redirect to google.com). Identify honestly instead.
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; docs_fetcher/1.0; research-tool)",
    "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8",
}
# A content container smaller than this (and under a quarter of the page text) is treated as a menu/widget, not the article.
MIN_CONTENT_CHARS = 1500
MANUAL_HINT = "Save the page/PDF into the worker's human-retrieved-sources/ folder and read it from there."


class _PlainText(str):
    """Text already extracted from a non-HTML response (e.g. a PDF); _clean_html passes it through."""

LIBRARIES_PATH = Path(__file__).parent / "libraries.json"
CLIS_PATH = Path(__file__).parent / "clis.json"
OTHER_SOURCES_PATH = Path(__file__).parent / "other_sources.json"

# Session-scoped in-memory cache: URL -> raw HTML
_cache: dict[str, str] = {}


def _load_libraries() -> dict:
    if LIBRARIES_PATH.exists():
        return json.loads(LIBRARIES_PATH.read_text())
    return {}


def _save_libraries(libs: dict) -> None:
    LIBRARIES_PATH.write_text(json.dumps(libs, indent=2))


def _all_libraries() -> dict:
    return _load_libraries()


def _load_clis() -> dict:
    if CLIS_PATH.exists():
        return json.loads(CLIS_PATH.read_text())
    return {}


def _save_clis(clis: dict) -> None:
    CLIS_PATH.write_text(json.dumps(clis, indent=2))


def _load_other_sources() -> dict:
    if OTHER_SOURCES_PATH.exists():
        return json.loads(OTHER_SOURCES_PATH.read_text())
    return {}


def _save_other_sources(sources: dict) -> None:
    OTHER_SOURCES_PATH.write_text(json.dumps(sources, indent=2))


def _pdf_to_text(data: bytes) -> "_PlainText | dict":
    """Extract text from PDF bytes with pdftotext (reads stdin, writes stdout). Returns text or error dict."""
    if shutil.which("pdftotext") is None:
        return {"error": f"PDF returned but pdftotext is not installed (install poppler). {MANUAL_HINT}"}
    try:
        proc = subprocess.run(["pdftotext", "-nopgbrk", "-", "-"], input=data, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"error": f"pdftotext timed out after 60s. {MANUAL_HINT}"}
    text = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0 or not text.strip():
        return {"error": f"pdftotext could not read this PDF (exit {proc.returncode}; scanned, encrypted or malformed?). {MANUAL_HINT}"}
    return _PlainText(text)


def _fetch_html(url: str) -> str | dict:
    """Fetch a URL, using the session cache. Returns HTML (or PDF-extracted plain text) as a string, or an error dict."""
    if url in _cache:
        return _cache[url]
    try:
        response = httpx.get(url, headers=REQUEST_HEADERS, follow_redirects=True, timeout=30)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        msg = f"HTTP {code} fetching {url}"
        if code in (401, 403):
            msg += f" - the site is blocking automated requests or requires access. {MANUAL_HINT}"
        return {"error": msg}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {e}"}
    content_type = response.headers.get("content-type", "").lower()
    if "application/pdf" in content_type or response.content[:5] == b"%PDF-":
        result = _pdf_to_text(response.content)
        if isinstance(result, dict):
            return result
    else:
        result = response.text
    _cache[url] = result
    return result


def _element_text(element) -> str:
    text = element.get_text(separator="\n")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _clean_html(html: str) -> str:
    if isinstance(html, _PlainText):
        return "\n".join(line.strip() for line in html.splitlines() if line.strip())
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    articles = soup.find_all("article")
    body_text = _element_text(soup.body or soup)
    candidates = []
    if len(articles) == 1:
        candidates.append(articles[0])
    candidates += [soup.find("main"), soup.find(class_="document"), soup.find(class_="content")]
    if len(articles) > 1:
        # Several <article> tags = listing/related-post widgets plus the real article; the largest is the real one.
        candidates.append(max(articles, key=lambda a: len(a.get_text())))
    for element in candidates:
        if element is None:
            continue
        text = _element_text(element)
        if len(text) >= MIN_CONTENT_CHARS or len(text) >= len(body_text) / 4:
            return text
    return body_text


@mcp.tool(annotations={"readOnlyHint": True})
def list_libraries() -> dict:
    """List all registered documentation libraries."""
    return {"libraries": _load_libraries()}


@mcp.tool()
def add_library(name: str, url: str) -> dict:
    """
    Save a new library URL so it can be referenced by name in future sessions.

    Args:
        name: Short key to reference this library (e.g. 'isaac_sim').
        url: Base documentation URL (must be https).
    """
    if not url.startswith("https://"):
        return {"error": "Only https:// URLs are permitted."}

    name = name.lower().strip()
    libs = _load_libraries()
    action = "updated" if name in libs else "saved"
    libs[name] = url
    _save_libraries(libs)

    return {action: True, "name": name, "url": url}


@mcp.tool(annotations={"readOnlyHint": True})
def list_clis() -> dict:
    """List all registered CLI tool documentation sources."""
    return {"clis": _load_clis()}


@mcp.tool()
def add_cli(name: str, url: str) -> dict:
    """
    Save a CLI tool documentation URL so it can be referenced by name in future sessions.

    Args:
        name: Short key to reference this CLI (e.g. 'git', 'macos_cli').
        url: Base documentation URL (must be https).
    """
    if not url.startswith("https://"):
        return {"error": "Only https:// URLs are permitted."}
    name = name.lower().strip()
    clis = _load_clis()
    action = "updated" if name in clis else "saved"
    clis[name] = url
    _save_clis(clis)
    return {action: True, "name": name, "url": url}


@mcp.tool(annotations={"readOnlyHint": True})
def list_other_sources() -> dict:
    """List all registered other reference sources (e.g. Apple support pages)."""
    return {"other_sources": _load_other_sources()}


@mcp.tool()
def add_other_source(name: str, url: str) -> dict:
    """
    Save a reference source URL so it can be referenced by name in future sessions.

    Args:
        name: Short key to reference this source (e.g. 'apple_activity_monitor_cpu').
        url: Documentation URL (must be https).
    """
    if not url.startswith("https://"):
        return {"error": "Only https:// URLs are permitted."}
    name = name.lower().strip()
    sources = _load_other_sources()
    action = "updated" if name in sources else "saved"
    sources[name] = url
    _save_other_sources(sources)
    return {action: True, "name": name, "url": url}


@mcp.tool(annotations={"readOnlyHint": True})
def fetch_docs(library: str, topic: str = "", char_offset: int = 0) -> dict:
    """
    Fetch documentation for a given library and optional topic/path.

    Args:
        library: A built-in or user-added library key (e.g. 'pytorch', 'isaac_sim').
        topic: Optional sub-path appended to the base URL (e.g. 'torch.nn').
        char_offset: Character offset to start reading from (use to paginate past the 8000-char window).
    """
    library = library.lower()
    all_libs = _all_libraries()

    if library not in all_libs:
        return {
            "error": f"Unknown library '{library}'. Available: {list(all_libs.keys())}"
        }

    url = all_libs[library].rstrip("/")
    if topic:
        url = f"{url}/{topic.strip('/')}"

    result = _fetch_html(url)
    if isinstance(result, dict):
        return result

    content = _clean_html(result)
    total_chars = len(content)
    window = content[char_offset:char_offset + 8000]

    if len(window) == 8000 and char_offset + 8000 < total_chars:
        remaining = total_chars - char_offset - 8000
        window += f"\n\n[... truncated. {remaining} chars remaining. Call again with char_offset={char_offset + 8000}]"

    return {
        "url": url,
        "library": library,
        "content": window,
        "total_chars": total_chars,
        "char_offset": char_offset,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def fetch_url(url: str, char_offset: int = 0) -> dict:
    """
    Fetch and clean any documentation URL directly.

    Args:
        url: The full URL to fetch (must be https).
        char_offset: Character offset to start reading from (use to paginate past the 8000-char window).
    """
    if not url.startswith("https://"):
        return {"error": "Only https:// URLs are permitted."}

    result = _fetch_html(url)
    if isinstance(result, dict):
        return result

    content = _clean_html(result)
    total_chars = len(content)
    window = content[char_offset:char_offset + 8000]

    if len(window) == 8000 and char_offset + 8000 < total_chars:
        remaining = total_chars - char_offset - 8000
        window += f"\n\n[... truncated. {remaining} chars remaining. Call again with char_offset={char_offset + 8000}]"

    return {
        "url": url,
        "content": window,
        "total_chars": total_chars,
        "char_offset": char_offset,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def search_docs(library: str, query: str, topic: str = "") -> dict:
    """
    Search for a query term within a library's documentation page and return matching snippets.

    Args:
        library: A built-in or user-added library key (e.g. 'pytorch').
        query: Text or regex pattern to search for (case-insensitive).
        topic: Optional sub-path to narrow the search to a specific page.
    """
    library = library.lower()
    all_libs = _all_libraries()

    if library not in all_libs:
        return {
            "error": f"Unknown library '{library}'. Available: {list(all_libs.keys())}"
        }

    url = all_libs[library].rstrip("/")
    if topic:
        url = f"{url}/{topic.strip('/')}"

    result = _fetch_html(url)
    if isinstance(result, dict):
        return result

    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error as e:
        return {"error": f"Invalid regex pattern: {e}"}

    soup = BeautifulSoup(result, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    matches = soup.find_all(string=pattern)
    if not matches:
        return {"url": url, "query": query, "snippets": [], "total_matches": 0}

    snippets = []
    seen = set()
    for match in matches[:20]:
        parent_text = match.parent.get_text(separator=" ").strip()
        parent_text = " ".join(parent_text.split())
        if parent_text in seen or not parent_text:
            continue
        seen.add(parent_text)
        snippets.append(parent_text[:400])
        if len(snippets) >= 10:
            break

    return {
        "url": url,
        "query": query,
        "total_matches": len(matches),
        "snippets_returned": len(snippets),
        "snippets": snippets,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def crawl_docs(url: str, max_pages: int = 10, same_prefix: bool = True, keywords: list[str] = []) -> dict:
    """
    Crawl a documentation site starting from a base URL, following links up to max_pages.

    Args:
        url: Starting URL (must be https).
        max_pages: Maximum number of pages to visit (default 10, max 30).
        same_prefix: If True, only follow links under the same URL path prefix (default True).
        keywords: If provided, only include pages whose content contains at least one keyword (case-insensitive).
    """
    if not url.startswith("https://"):
        return {"error": "Only https:// URLs are permitted."}

    max_pages = min(max_pages, 30)
    from urllib.parse import urljoin, urlparse

    parsed_base = urlparse(url)
    base_domain = parsed_base.netloc
    base_prefix = parsed_base.path if same_prefix else "/"

    visited = set()
    queue = [url]
    pages = []
    pages_visited = 0

    while queue and pages_visited < max_pages:
        current_url = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)
        pages_visited += 1

        result = _fetch_html(current_url)
        if isinstance(result, dict):
            continue

        soup = BeautifulSoup(result, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.startswith("#") or href.startswith("mailto:"):
                continue
            full_url = urljoin(current_url, href).split("#")[0]
            parsed = urlparse(full_url)
            if parsed.netloc != base_domain:
                continue
            if same_prefix and not parsed.path.startswith(base_prefix):
                continue
            if full_url not in visited:
                queue.append(full_url)

        content = _clean_html(result)

        if keywords:
            content_lower = content.lower()
            if not any(kw.lower() in content_lower for kw in keywords):
                continue

        if len(content) > 3000:
            content = content[:3000] + "\n[... truncated]"

        pages.append({"url": current_url, "content": content})

    return {
        "pages_visited": pages_visited,
        "pages_matched": len(pages),
        "pages": pages,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_fetch_stats() -> dict:
    """Return statistics about URLs fetched in this session."""
    urls_fetched = list(_cache.keys())
    fetch_count = len(urls_fetched)
    total_chars = sum(len(html) for html in _cache.values())
    estimated_tokens = total_chars // 4
    session_note = f"{fetch_count} URL{'s' if fetch_count != 1 else ''} fetched, ~{estimated_tokens:,} estimated tokens this session."
    return {
        "urls_fetched": urls_fetched,
        "fetch_count": fetch_count,
        "total_chars": total_chars,
        "estimated_tokens": estimated_tokens,
        "session_note": session_note,
    }


if __name__ == "__main__":
    mcp.run()
