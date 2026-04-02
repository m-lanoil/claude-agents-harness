import json
import re
import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("docs_fetcher")

LIBRARIES_PATH = Path(__file__).parent / "libraries.json"

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


def _fetch_html(url: str) -> str | dict:
    """Fetch raw HTML for a URL, using the session cache. Returns HTML string or error dict."""
    if url in _cache:
        return _cache[url]
    try:
        response = httpx.get(url, follow_redirects=True, timeout=15)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} fetching {url}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {e}"}
    _cache[url] = response.text
    return response.text


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_="document")
        or soup.find(class_="content")
        or soup.body
    )
    text = (main or soup).get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


if __name__ == "__main__":
    mcp.run()
