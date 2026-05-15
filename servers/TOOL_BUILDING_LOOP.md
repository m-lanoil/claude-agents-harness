# Tool-Building Loop

Run these steps in order when creating or extending a server.

1. **Identify**: "I need a tool for [X]."
2. **Extend or Create**: Fit into an existing server if possible. Extensions need the same approval and Dry Run as new servers. Extensions logged in **Updated** in `logs/[server].md`; new servers in **Created** in both `TOOL_LOG.md` and `logs/[server].md`.
3. **Scaffold** *(new only)*: `mkdir -p servers/[name] && cd servers/[name] && uv init --no-readme && rm -f main.py && uv add fastmcp`
4. **Code**: Run the **Server Code Grounding Protocol** below before writing `server.py`.
5. **Register** *(new only)*: `claude mcp add --scope project [name] -- uv --project /full/path/to/servers/[name] run /full/path/to/servers/[name]/server.py`
6. **Verify**: Run `claude mcp list`. "Failed to connect" = startup crash — diagnose and fix before proceeding.

## Server Code Grounding Protocol

Applies when writing or extending `server.py`. Meta-Orchestrator cannot call `docs_fetcher` — route all fetches to Developer worker.

**Grounding store**: `./servers/kb/` — one file per library (`kb_[library].md`). Frontmatter: `library`, `source`, `fetched: YYYY-MM-DD`.

**Pre-write gate** (required, in order):
1. List every `import` the planned `server.py` will use.
2. For each import, check `./servers/kb/` for a kb file with `fetched:` ≤30 days. If missing or stale, route to Developer: *"Fetch docs for [library] and write to `../../servers/kb/kb_[library].md`."* Read before proceeding.
3. Do not write `server.py` until every import is grounded.

**Post-write audit**: Re-scan every import and tool call signature against its kb file. If any pattern is absent, route back to Developer and resolve before finalising.
