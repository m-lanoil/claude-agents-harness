import json
import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("docs_fetcher")

BUILT_IN_LIBRARIES = {
    "pytorch": "https://pytorch.org/docs/stable/",
    "huggingface": "https://huggingface.co/docs/transformers/",
    "sklearn": "https://scikit-learn.org/stable/modules/",
    "numpy": "https://numpy.org/doc/stable/reference/",
    "pandas": "https://pandas.pydata.org/docs/reference/",
    "mlflow": "https://mlflow.org/docs/latest/",
    "wandb": "https://docs.wandb.ai/",
    "jax": "https://jax.readthedocs.io/en/latest/",
}

USER_LIBRARIES_PATH = Path(__file__).parent / "user_libraries.json"


def _load_user_libraries() -> dict:
    if USER_LIBRARIES_PATH.exists():
        return json.loads(USER_LIBRARIES_PATH.read_text())
    return {}


def _save_user_libraries(libs: dict) -> None:
    USER_LIBRARIES_PATH.write_text(json.dumps(libs, indent=2))


def _all_libraries() -> dict:
    return {**BUILT_IN_LIBRARIES, **_load_user_libraries()}


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
    """List all available documentation libraries, split by built-in and user-added."""
    return {
        "built_in": BUILT_IN_LIBRARIES,
        "user_added": _load_user_libraries(),
    }


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
    if name in BUILT_IN_LIBRARIES:
        return {"error": f"'{name}' is a built-in library and cannot be overwritten."}

    user_libs = _load_user_libraries()
    user_libs[name] = url
    _save_user_libraries(user_libs)

    return {"saved": True, "name": name, "url": url}


@mcp.tool()
def fetch_docs(library: str, topic: str = "") -> dict:
    """
    Fetch documentation for a given library and optional topic/path.

    Args:
        library: A built-in or user-added library key (e.g. 'pytorch', 'isaac_sim').
        topic: Optional sub-path appended to the base URL (e.g. 'torch.nn').
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

    try:
        response = httpx.get(url, follow_redirects=True, timeout=15)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} fetching {url}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {e}"}

    content = _clean_html(response.text)
    if len(content) > 8000:
        content = content[:8000] + "\n\n[... truncated. Use a more specific topic path to narrow results.]"

    return {"url": url, "library": library, "content": content}


@mcp.tool()
def crawl_docs(url: str, max_pages: int = 10, same_prefix: bool = True) -> dict:
    """
    Crawl a documentation site starting from a base URL, following links up to max_pages.

    Args:
        url: Starting URL (must be https).
        max_pages: Maximum number of pages to fetch (default 10, max 30).
        same_prefix: If True, only follow links under the same URL path prefix (default True).
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

    while queue and len(pages) < max_pages:
        current_url = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)

        try:
            response = httpx.get(current_url, follow_redirects=True, timeout=15)
            response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError):
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        # Extract and queue links
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

        content = _clean_html(response.text)
        if len(content) > 3000:
            content = content[:3000] + "\n[... truncated]"

        pages.append({"url": current_url, "content": content})

    return {
        "pages_fetched": len(pages),
        "pages": pages,
    }


@mcp.tool()
def fetch_url(url: str) -> dict:
    """
    Fetch and clean any documentation URL directly.

    Args:
        url: The full URL to fetch (must be https).
    """
    if not url.startswith("https://"):
        return {"error": "Only https:// URLs are permitted."}

    try:
        response = httpx.get(url, follow_redirects=True, timeout=15)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} fetching {url}"}
    except httpx.RequestError as e:
        return {"error": f"Request failed: {e}"}

    content = _clean_html(response.text)
    if len(content) > 8000:
        content = content[:8000] + "\n\n[... truncated. Try a more specific URL.]"

    return {"url": url, "content": content}


if __name__ == "__main__":
    mcp.run()
