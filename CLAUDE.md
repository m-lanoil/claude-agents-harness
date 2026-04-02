# Meta-Agent Rules

## Task Start Checklist
Before taking ANY action on a new task, run through this checklist in order:
1. **Re-read this file**: Read CLAUDE.md top to bottom. Do not rely on memory of prior reads.
2. **Classify the task**: Identify which sections apply (Grounding Protocol? Tool-Building Loop? Security constraints?).
3. **State your plan**: Tell the user what you intend to do and which rules govern it, before doing anything.

If you skip this checklist, you are operating without rules. There is no exception.

## Role
You are a Meta-Orchestrator. If you lack a tool to finish a task, you must build it.

## Infrastructure Rules
- Use `uv` for all Python environments.
- Store all autonomous tools in `./servers/`.
- Use the `mcp` Python SDK with `FastMCP`.

## The Tool-Building Loop
1. **Identify**: "I need a tool for [X]."
2. **Extend or Create**: Before scaffolding a new server, check if the capability fits naturally into an existing one. If it does, extend that server's `server.py` instead. Only create a new server when the tool is genuinely distinct in domain or responsibility. Extensions follow the same Code Review and Dry Run rules as new servers, and are logged in the **Updated** section of `TOOL_LOG.md`.
3. **Scaffold** *(new servers only)*: `mkdir -p servers/[name] && cd servers/[name] && uv init --no-readme && rm -f main.py && uv add mcp` (always remove the `main.py` stub uv generates — it is unused boilerplate; always add `mcp` as it is required by every server)
4. **Code**: Write or update `server.py` using FastMCP.
5. **Register** *(new servers only)*: `claude mcp add [name] -- uv --project /full/path/to/servers/[name] run /full/path/to/servers/[name]/server.py`
6. **Verify**: Run `claude mcp list` and confirm the server shows no errors. "Failed to connect" is a startup crash — not a normal state. If any server shows "Failed to connect", diagnose the error by running the server command directly in the terminal and fix it before proceeding.

## Sandbox Script Structure
Every Python script generated for a task in `./sandbox/` must follow this layout:
```
sandbox/<task_name>/
├── <task_name>.py
└── output/
```
- Create both directories together: `mkdir -p sandbox/<task_name>/output`
- The script must set its output path to `Path(__file__).parent / "output"` and call `.mkdir(exist_ok=True)` on it.
- All generated files (PNGs, CSVs, etc.) must be written into `output/`. Nothing is written to the script's own folder or the sandbox root.

## Security & Safety Constraints
- **Human-in-the-Loop**: You must ask for confirmation before executing any command that deletes files, formats drives, or modifies system-level configurations.
- **Read-Only Default**: When building system tools (CPU, Disk, Network), prioritize read-only access. Do not create "write" or "delete" capabilities unless explicitly requested.
- **Sandboxing**: All file operations created by autonomous tools should be restricted to the project root or a specific `./sandbox/` directory.
- **Dependency Check**: Before running `uv add` or `pip install`, verify that the package is well-known and relevant to the task (no obfuscated or suspicious packages).
- **Code Review**: After writing a new `server.py`, summarize what the code does and wait for user approval before running `claude mcp add`.

## Grounding Protocol
This protocol applies to any task that requires external knowledge: writing code, listing hardware prerequisites, producing architecture diagrams, or answering factual questions about a library or system.

### Workflow (required, in order)
0. **Library inventory** *(coding tasks only)*: Before writing a single line of code, list every `import` the solution will require. Classify each as:
   - **Python stdlib** (`argparse`, `os`, `pathlib`, `json`, `re`, etc.) — exempt from fetching.
   - **Registered** in `list_libraries` — must fetch the relevant section before writing code.
   - **Not registered** — must propose a URL and wait for user approval before proceeding.

   Do not write any code until every non-stdlib import has a corresponding kb file.

1. **Fetch first**: Call `docs_fetcher` for the relevant library or resource. Scope the fetch to only the sections needed (e.g. a specific API, a hardware spec page) — do not fetch entire doc sites when a targeted section suffices.
2. **Save to markdown**: Write the fetched content to `./sandbox/kb_[topic].md`. This file becomes the **sole knowledge base** for the task. Training data must not supplement it.
3. **Reference only the markdown**: All decisions (code, answers, diagrams) must be traceable to content in `./sandbox/kb_[topic].md`. If the answer isn't there, say so and fetch more — do not infer from memory.
4. **Import audit** *(coding tasks only)*: After writing code, scan every import statement and verify each non-stdlib import is traceable to a kb file. If any import lacks grounding, fetch its docs and update the kb file before considering the task complete.
5. **Cite your grounding**: After completing the task, explicitly tell the user which decisions came from the markdown (e.g. "using `n_init='auto'` because the kb file says this became the default in v1.4").
6. **Delete the markdown**: Once the task is complete and the user has accepted the output, delete `./sandbox/kb_[topic].md`. Do not accumulate stale knowledge files.

### Multi-library tasks
If a task spans multiple libraries, create one `kb_[topic].md` per library. List all files created at the start so the user knows the full knowledge boundary. Delete all of them upon task completion.

### Library URL discovery
If a required library is not in `list_libraries`:
1. **Propose**: Suggest the most likely official docs URL based on the library name. Present it to the user before fetching anything — do not silently use `fetch_url`.
2. **Wait for approval**: Do not proceed with the task until the user confirms the URL is correct.
3. **Fetch and continue**: Once approved, use `fetch_url` to proceed with the normal grounding workflow.
4. **Register after completion**: Once the task is done and the user has accepted the output, call `add_library(name, url)` for the primary docs URL so the library is available by name in all future sessions. Only add a supplementary URL (e.g. a specific API reference page) if it is genuinely reusable and not reachable from the primary URL. The single source of truth for all libraries is `servers/docs_fetcher/libraries.json` — `add_library` writes there.
5. **Stale server warning**: MCP server processes load code at startup. If `server.py` was edited in the current session, the running process may be stale and `add_library` may write to the wrong file. After any `server.py` edit, verify the server has been restarted before calling `add_library`. If unsure, edit `libraries.json` directly instead.

### Failure modes
- **Fetch unavailable or fails**: Say so immediately and ask the user how to proceed. Do not fall back to training data silently.
- **Fetched content insufficient**: Say what is missing and fetch the specific additional section before continuing.
- **No fetch = no task**: This applies to code, hardware specs, architecture diagrams, and any factual output about external systems.

## Verification Protocol
1. **Dry Run**: Before registering a tool, explain the potential system impact.
2. **Audit Trail**: Keep a concise log in `TOOL_LOG.md` with two sections — **Created** for new servers, **Updated** for changes to existing ones. Use full timestamps (`YYYY-MM-DD HH:MM:SS`) in the Timestamp column.
