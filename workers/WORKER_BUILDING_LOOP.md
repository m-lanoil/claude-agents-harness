# Worker-Building Loop

Run these steps in order when creating or extending a worker. Wait for explicit approval at step 4 before writing any files.

1. **Identify**: State the worker's mandate — what it handles and what it does not.
2. **Extend or Create**: Extend an existing worker if mandate fits. Only create when genuinely distinct.
3. **Define tool surface**: List MCP servers the worker gets. Err toward fewer tools.
4. **Draft `CLAUDE.md`**: Verify every item in `workers/WORKER_STANDARDS.md` is present before presenting the draft. Wait for explicit approval before writing any files.
5. **Scaffold**: Create `workers/[name]/` and subdirectories (e.g. `kb/`, `sandbox/`).
6. **Log**: Record in `TOOL_LOG.md` under **Workers** with timestamp, name, mandate, tool surface.
7. **Update Workers table**: Add a row to the Workers table in `CLAUDE.md`.
