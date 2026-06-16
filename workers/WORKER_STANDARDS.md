# Worker Standards

**Workers: read this file at the start of every task.** All shared rules live here — do not rely on copies in your own `CLAUDE.md`. Your `CLAUDE.md` contains only mandate-specific content.

**Meta-Orchestrator**: This file is the canonical source for worker rules. The Worker-Building Loop (step 4) and Worker Gap Protocol both reference it. No worker draft is complete until all items below are present.

## Worker Security Baseline
Every worker `CLAUDE.md` must include all six items, regardless of mandate.

| # | Requirement | What it must say |
|---|---|---|
| 1 | **URL approval gate** | Before fetching any URL not already registered in the Source Registry (`list_libraries`, `list_clis`, `list_other_sources`), propose it to the user and wait for explicit approval. No silent fetches. |
| 2 | **Failure modes** | If a fetch fails or returns insufficient content, stop immediately, say so, and ask how to proceed. No silent fallback to training data or unverified content. |
| 3 | **Citation requirement** | Every factual claim, benchmark, or recommendation must trace to a named `kb/` file — not just a URL. "Cite sources inline" alone is not sufficient. |
| 4 | **No unverified data** | If a claim cannot be traced to a fetched source in `kb/`, flag it explicitly in the deliverable rather than including it as fact. |
| 5 | **Sandboxing** | File writes explicitly scoped based on worker type. **Deliverable workers** (Architect, Content): `./kb/` and `../../output/` only. **Code workers** (Developer): all work (scripts, data, outputs, requirements) lives in `./sandbox/<project_name>/`; final deliverables (PDFs, structured outputs for the user) to `../../output/`. Never put files directly in the sandbox root. Use `lowercase_snake_case` for all folder and file names. |
| 6 | **Human-in-the-loop** | Confirm before any action that is hard to reverse or that fetches from an unregistered external source. |

These six items must appear as explicit rules — not implied by other sections. If a worker's mandate makes one item not applicable, note that explicitly rather than omitting the section.

## Worker Standard Components
These reusable process patterns govern correctness and consistency, not safety. Every worker `CLAUDE.md` must include all of them.

### Task Start Checklist minimum structure
Every worker's checklist must follow this order:
1. **Classify** the task type and identify which sections apply.
2. **Active rules check** — confirm relevant protocols are active for this task type.
3. **Source inventory** — list every source (import, technology, topic) the task will need. For each, apply the KB staleness check before reaching for `docs_fetcher`.
4. **State the plan** — describe approach and name which rules apply.

### KB staleness check (three-branch logic)
Before using any kb file, and before any fetch, consult `KB_STALENESS_LOG.md` at the project root for a pre-computed staleness overview (updated by weekly cron, Mondays 9am). Then apply this logic to each source you will actually use:
- **kb file exists, `fetched:` ≤30 days** → use directly. Do not re-fetch.
- **kb file exists, `fetched:` >30 days** → stale. Re-fetch and update before using.
- **kb file missing** → fetch (subject to URL approval gate). Save before proceeding.

### KB file naming convention
All kb files must use the prefix `kb_` followed by a lowercase snake_case topic slug: `kb_[topic].md` (e.g., `kb_fastmcp.md`, `kb_ev_charging_market.md`). No other naming scheme is permitted — do not use suffixes like `_grounding` or `_sources`.

### KB frontmatter format
All kb files must use this header — adapt the primary key name to the worker's domain:
```
---
[library / technology / topic]: [name]
source: [url]
fetched: YYYY-MM-DD
---
```

### Token Budget Protocol
1. **Pre-task declaration** — before any fetch, list expected call count, sources, and any planned `crawl_docs`. Wait for user acknowledgment.
1a. **Budget conflict gate** — immediately after the library inventory and before making any fetches: count the fetches the inventory requires and compare to the budget. If required fetches exceed the budget, STOP. Do not fetch. Do not write code. Report to the user using this structure:

   > **Budget conflict — cannot proceed without approval.**
   >
   > Imports requiring kb files: `[list each one]`
   > Fetches needed: N | Budget remaining: M
   >
   > Options:
   > A. Approve N additional fetches — I will ground all imports then write the code.
   > B. Approve fetches for required imports only; optional deps stay ungrounded and their features are excluded.
   > C. Restructure the script to reduce the import surface — tell me which deps to drop.
   >
   > Which option?

   Wait for explicit selection before taking any further action. The structured options are required — a vague "can I fetch more?" prompt is not sufficient.

2. **Checkpoint rule** — every 3 fetch calls, call `get_fetch_stats` and report one-line summary. Wait for "continue."
3. **Large-fetch gate** — `crawl_docs` requires explicit approval with URL and `max_pages` stated.
4. **Budget cap** — the routing prompt's suggested fetch budget is a hard cap; worker must ask before exceeding it.

### Handoff Rule
When you identify a dependency on another worker mid-task — or when your task is complete and further work requires a different mandate — do not generate a routing prompt for that worker yourself. The Meta-Orchestrator is responsible for all routing decisions and prompt construction.

Required behaviour at a handoff boundary:
1. Complete your portion of the task within your mandate.
2. State explicitly what is needed next and which worker handles it (e.g. *"This requires Developer work: [description of what is needed]"*).
3. Instruct the user to return to the Meta-Orchestrator session with that context.
4. Stop there. Do not draft the next worker's prompt.

Generating cross-worker routing prompts bypasses the orchestrator's classification step, skips routing protocol checks, and breaks the audit trail.

### Source Registry
After any session that fetches new content, register each new source URL in the correct JSON in `../../servers/docs_fetcher/`:

| File | What belongs here |
|---|---|
| `libraries.json` | External Python packages, language SDKs (e.g. PyTorch, sklearn, FastMCP) |
| `clis.json` | CLI tools invoked as shell commands |
| `other_sources.json` | Hardware specs, RFCs, platform docs, REST APIs, model cards, datasets, reports, reference pages |

**How to register**: Edit the JSON file directly — add `"name": "url"` to the object and save. If the file does not exist yet, create it with `{}` first. Do not rely solely on the MCP tools (`add_library`, `add_cli`, `add_other_source`) — these files are gitignored and may not be present; direct editing is always safe.

**Python stdlib exemption**: `docs.python.org` sources are exempt from Source Registry registration only — do not add stdlib modules to any JSON. The kb file is still mandatory: propose the `docs.python.org` URL, wait for approval, fetch, and write `kb_[module].md` before writing any code that uses the module. All other KB rules (staleness check, frontmatter format, naming convention) still apply.

Register only sources fetched this session — not existing kb files.

## Task-Type Protocols
Workers: when your task matches a type below, read and follow the protocol file before proceeding.
- **Bug fix** → `../developer/BUG_FIX_PROTOCOL.md` | **Documentation** → `DOCUMENTATION_PROTOCOL.md` | **Mid-task context received** → `CONTEXT_INTAKE_PROTOCOL.md`
