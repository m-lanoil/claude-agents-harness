import asyncio
import runpy

from fastmcp.client import Client
from fastmcp.exceptions import ToolError

from conftest import SERVER_FILE


def load_mcp():
    """Execute server.py without running it and return its FastMCP instance."""
    return runpy.run_path(str(SERVER_FILE), run_name="server_under_test")["mcp"]


def call_tool(name, arguments=None):
    """Call a tool through the in-memory FastMCP client and return the result object."""
    mcp = load_mcp()

    async def _call():
        async with Client(transport=mcp) as client:
            return await client.call_tool(name, arguments or {})

    return asyncio.run(_call())


def list_tool_names():
    mcp = load_mcp()

    async def _list():
        async with Client(transport=mcp) as client:
            return [tool.name for tool in await client.list_tools()]

    return asyncio.run(_list())


def call_tool_error(name, arguments=None):
    """Return the error message of a failing tool call, whether the client raises or returns an error result."""
    try:
        result = call_tool(name, arguments)
    except ToolError as error:
        return str(error)
    assert result.is_error, f"expected {name} to fail, got {result!r}"
    return " ".join(getattr(block, "text", "") for block in result.content)
