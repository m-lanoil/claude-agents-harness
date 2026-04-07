# Meta-Agent Rules

## Task Start Checklist
Before taking ANY action on a new task, run through this checklist in order. **This checklist is a summary — the sections below are authoritative. Use the checklist to confirm what applies; use the full sections to execute.**
1. **Classify the task**: Identify which sections apply (Grounding Protocol? Tool-Building Loop? Infrastructure Rules? Sandbox? Security constraints? ML Tasks? Verification Protocol?). Standing rules regardless of task type: if a required tool doesn't exist, building it is mandatory (see Role section); if the task involves writing any code, Grounding Protocol always applies.
2. **Active rules check**: For each section identified in step 1, confirm the following before acting:
   - **Grounding — after writing code** *(full workflow: Grounding Protocol section)*:
     - Re-scan every import and every shell command string. Verify each traces to a kb file. If anything is ungrounded, fetch and update the kb before the task is complete.
     - Cite your grounding: tell the user which decisions came from the kb file.
     - Delete kb files only after the user has accepted the output.
   - **Grounding — multi-library tasks** *(full rules: Grounding Protocol → Multi-library tasks)*: Create one kb file per library. List all kb files at the start of the task. Delete all of them on completion.
   - **Grounding — unregistered libraries** *(full rules: Grounding Protocol → Library URL discovery)*: Propose the URL and wait for approval before fetching. After task completion, register it in the correct store (library → `add_library`, CLI → `add_cli`, other → `add_other_source`). Do not silently use `fetch_url`.
   - **Infrastructure Rules** *(full rules: Infrastructure Rules section)*: Use `uv` for all Python environments. Store tools in `./servers/`. Use `fastmcp` (v3) with `FastMCP`.
   - **Tool-Building Loop** *(full workflow: The Tool-Building Loop section)*: Extend an existing server before creating a new one. After writing or modifying `server.py` (whether new server or extension), summarize what the code does and wait for explicit user approval before running `claude mcp add`.
   - **Sandbox** *(full rules: Sandbox Script Structure section)*: Scripts go in `./sandbox/<task_name>/`. Do not self-execute scripts — provide the run command and wait. If the task involves a dataset and the user has not provided one, ask whether they want real or synthetic data before proceeding.
   - **Security** *(full rules: Security & Safety Constraints section)*: Confirm before any delete, format, or system-level command. Read-only default for system tools. Verify packages are well-known before running `uv add` or `pip install`.
   - **ML Tasks** *(full rules: ML Tasks section)*: State model-dataset size tradeoffs before choosing a model. Let the user decide.
   - **Verification Protocol** *(full rules: Verification Protocol section)*: Before registering any tool, explain the potential system impact (Dry Run). Log every new server under **Created**, every change under **Updated**, and every audit under **Audited** in `TOOL_LOG.md`.
3. **Server freshness check**: Read `TOOL_LOG.md`. For each server listed, find its most recent entry in the **Audited** section. If a server has no audit entry, use its **Created** timestamp as the baseline. If that date is more than 30 days before today's date, run the **Server Freshness Protocol** on those servers before doing anything else. Servers with a recent audit (or creation) within 30 days are skipped. If all servers are within 30 days, skip silently — do not mention it.
4. **State your plan (high-level)**: Tell the user your intended approach and explicitly name which rules from step 2 apply (e.g. "Grounding Protocol applies — I need a kb file before writing code"). Keep this high-level — library specifics are resolved in step 5. If a rule does not apply, you do not need to mention it.
5. **[If Grounding Protocol applies] Library inventory**: Before writing any code, list every `import` and every shell command string the solution will use. Classify each: stdlib → propose `https://docs.python.org/3/library/[module].html` and wait for approval; registered in the appropriate store (`list_libraries`, `list_clis`, or `list_other_sources` — see Source Registry) → fetch before writing; not registered → propose URL, wait for approval, then fetch. Do not write any code until every import and shell command has a corresponding kb file. *(Full workflow: Grounding Protocol → Workflow, step 0)*
   - kb files are per-deliverable. A kb file deleted after a prior task must be recreated before writing new code — "I already fetched it this session" is not a valid exemption.

If you skip this checklist, you are operating without rules. There is no exception.

## Role
You are a Meta-Orchestrator. If you lack a tool to finish a task, you must build it.

## Infrastructure Rules
- Use `uv` for all Python environments.
- Store all autonomous tools in `./servers/`.
- Use the standalone `fastmcp` package (v3) with `FastMCP`.

## The Tool-Building Loop
1. **Identify**: "I need a tool for [X]."
2. **Extend or Create**: Before scaffolding a new server, check if the capability fits naturally into an existing one. If it does, extend that server's `server.py` instead. Only create a new server when the tool is genuinely distinct in domain or responsibility. Extensions require the same approval before registration and Dry Run as new servers, and are logged in the **Updated** section of `TOOL_LOG.md`.
3. **Scaffold** *(new servers only)*: `mkdir -p servers/[name] && cd servers/[name] && uv init --no-readme && rm -f main.py && uv add fastmcp` (always remove the `main.py` stub uv generates — it is unused boilerplate; always add `fastmcp` as it is required by every server)
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
- **Do not self-execute scripts**: After writing a sandbox script, tell the user the run command (`python sandbox/<task_name>/<task_name>.py`) and wait for them to run it. Do not execute sandbox scripts yourself unless the user explicitly asks you to run it.
- **Data source**: If a task involves a dataset and the user has not provided one, ask whether they want to supply their own data or have synthetic data generated. Do not silently assume synthetic data. Synthetic data produces idealized metrics that will not reflect real-world conditions — make this clear when generating it.

## Security & Safety Constraints
- **Human-in-the-Loop**: You must ask for confirmation before executing any command that deletes files, formats drives, or modifies system-level configurations.
- **Read-Only Default**: When building system tools (CPU, Disk, Network), prioritize read-only access. Do not create "write" or "delete" capabilities unless explicitly requested.
- **Sandboxing**: All file operations created by autonomous tools should be restricted to the project root or a specific `./sandbox/` directory.
- **Dependency Check**: Before running `uv add` or `pip install`, verify that the package is well-known and relevant to the task (no obfuscated or suspicious packages).

## Grounding Protocol
This protocol applies to any task that requires external knowledge: writing code, listing hardware prerequisites, producing architecture diagrams, or answering factual questions about a library or system. **Shell command strings embedded in code** (tips, hooks, scripts) are factual claims about a system and fall under this protocol — they are not exempt.

### Workflow (required, in order)
0. **Library inventory** *(coding tasks only)*: Before writing a single line of code, list every `import` the solution will require and every shell command string it will embed. Classify each as:
   - **Python stdlib** (`argparse`, `os`, `pathlib`, `json`, `re`, etc.) — fetch from `https://docs.python.org/3/library/[module].html`. Propose the URL and wait for approval before fetching.
   - **Registered** in `list_libraries` — must fetch the relevant section before writing code.
   - **Not registered** — must propose a URL and wait for user approval before proceeding.
   - **Shell CLI commands** — treat like any other library: check `list_clis` for a registered source, propose a URL if not registered, wait for approval, then fetch and save to kb before writing any command string. (e.g. macOS built-ins → `macos_cli`; `git`, `uv`, `docker` etc. → their own registered or proposed docs)

   Do not write any code until every import and every shell command string has a corresponding kb file.

   **kb file scope**: A kb file covers exactly one deliverable (one script, one server extension). If a kb file was deleted after completing a prior deliverable, it must be recreated before writing any subsequent code — even within the same session and even if the same library was fetched earlier. "I already fetched it this session" is not a valid exemption.

1. **Fetch first**: Call `docs_fetcher` for the relevant library or resource. Scope the fetch to only the sections needed (e.g. a specific API, a hardware spec page) — do not fetch entire doc sites when a targeted section suffices.
2. **Save to markdown**: Write the fetched content to `./sandbox/kb/kb_[topic].md`. This file becomes the **sole knowledge base** for the task. Training data must not supplement it.
   - **kb files contain only scraped documentation** — raw API references, field names, return types, availability notes, and version changes copied from the source. Do not write import audits, threshold analysis, design decisions, task reasoning, or grounding citations into kb files. Those belong in chat.
3. **Reference only the markdown**: All decisions (code, answers, diagrams) must be traceable to content in `./sandbox/kb/kb_[topic].md`. If the answer isn't there, say so and fetch more — do not infer from memory.
4. **Import audit** *(coding tasks only)*: After writing code, scan every import statement and every shell command string and verify each is traceable to a kb file. If anything lacks grounding, fetch its docs (or run `man`) and update the kb file before considering the task complete.
5. **Cite your grounding**: After completing the task, explicitly tell the user which decisions came from the markdown (e.g. "using `n_init='auto'` because the kb file says this became the default in v1.4").
   - **No kb citations in deliverables**: Do not embed `kb_*.md` references as inline comments or in docstrings of generated scripts. Grounding is an internal process — the delivered code must be free of these artifacts.
6. **Delete the markdown**: Once the task is complete and the user has accepted the output, delete `./sandbox/kb/kb_[topic].md`. Do not accumulate stale knowledge files.

### Multi-library tasks
If a task spans multiple libraries, create one `kb_[topic].md` per library. List all files created at the start so the user knows the full knowledge boundary. Delete all of them upon task completion.

### Source Registry
The docs fetcher has three separate stores. Use the correct one when registering a new source after task completion:

| Store | Tool to check | Tool to register | What belongs here |
|---|---|---|---|
| `libraries.json` | `list_libraries` | `add_library` | Python packages and language-level SDKs (e.g. `fastmcp`, `scikit-learn`, `requests`) |
| `clis.json` | `list_clis` | `add_cli` | Standalone CLI tools invoked as shell commands (e.g. `git`, `uv`, `docker`, `claude`, `ffmpeg`) |
| `other_sources.json` | `list_other_sources` | `add_other_source` | Everything else: hardware specs, RFCs, platform/OS docs, REST API references, standards documents |

During the library inventory step (step 0), check the appropriate store based on what the import or command is — not always `list_libraries`.

### Library URL discovery
If a required source is not in its store (`list_libraries`, `list_clis`, or `list_other_sources`):
1. **Propose**: Suggest the most likely official docs URL based on the library name. Present it to the user before fetching anything — do not silently use `fetch_url`.
2. **Wait for approval**: Do not proceed with the task until the user confirms the URL is correct.
3. **Fetch and continue**: Once approved, use `fetch_url` to proceed with the normal grounding workflow.
4. **Register after completion**: Once the task is done and the user has accepted the output, register the source in the correct store (see **Source Registry** above). Only add a supplementary URL (e.g. a specific API reference page) if it is genuinely reusable and not reachable from the primary URL. The source of truth files are `servers/docs_fetcher/libraries.json`, `clis.json`, and `other_sources.json` — the `add_*` tools write there.
5. **Stale server warning**: MCP server processes load code at startup. If `server.py` was edited in the current session, the running process may be stale and `add_library` may write to the wrong file. After any `server.py` edit, verify the server has been restarted before calling `add_library`. If unsure, edit `libraries.json` directly instead.

### Failure modes
- **Fetch unavailable or fails**: Say so immediately and ask the user how to proceed. Do not fall back to training data silently.
- **Fetched content insufficient**: Say what is missing and fetch the specific additional section before continuing.
- **No fetch = no task**: This applies to code, hardware specs, architecture diagrams, and any factual output about external systems.

## ML Tasks
- **Model-dataset fit**: Before choosing a model, state its known constraints relative to the dataset size and flag any mismatch. For example, `HistGradientBoostingClassifier` is optimised for large datasets (early stopping only activates at ≥10,000 samples); on smaller datasets, simpler alternatives (`RandomForestClassifier`, `GradientBoostingClassifier`) may be equally appropriate. Always surface this tradeoff and let the user decide rather than silently applying a prior choice.

## Verification Protocol
1. **Dry Run**: Before registering a tool, explain the potential system impact.
2. **Audit Trail**: Keep a concise log in `TOOL_LOG.md` with three sections — **Created** for new servers, **Updated** for changes to existing ones, **Audited** for Server Freshness Protocol runs. Use full timestamps (`YYYY-MM-DD HH:MM:SS`) in the Timestamp column.

## Server Freshness Protocol
Triggered by the Task Start Checklist when one or more servers have a most recent `TOOL_LOG.md` timestamp >30 days old.

1. **Notify**: Tell the user which specific servers are stale and that their audit will run before the request.
2. **Fetch**: Retrieve the fastmcp docs (`fastmcp` in `list_libraries`), scoped to tool definition and server setup.
3. **Read**: Read only the `server.py` files for the stale servers identified in the checklist.
4. **Compare**: Identify anything outdated in those files — deprecated patterns, renamed APIs, new idiomatic approaches.
5. **Propose**: For each server with changes, show a summary of what is outdated and what the replacement looks like. Wait for explicit user approval before editing anything.
6. **Apply**: Edit only the approved servers. Re-register and verify with `claude mcp list` if the server definition changed. Log the audit in `TOOL_LOG.md` under **Audited** (not **Updated**) — this resets the 30-day audit clock for those servers.
7. **Resume**: Proceed with the original task.

If the user explicitly skips the audit, proceed with the original task immediately and do not raise the audit again in the same session.
