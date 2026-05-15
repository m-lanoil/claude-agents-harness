# Worker Gap Protocol

Triggered when the user reports a gap in any worker's behavior.

1. **Classify**: Security/auditability gap → fix `workers/WORKER_STANDARDS.md`. Reusable process gap → same. Worker-specific → that worker's `CLAUDE.md` only. If in doubt, treat as reusable.
2. **Fix canonical source first**: Edit `workers/WORKER_STANDARDS.md` before touching any worker file.
3. **Backfill** *(mandate-specific gaps only)*: Workers read `WORKER_STANDARDS.md` at task start — shared rule fixes propagate automatically with no backfill. Only edit individual worker files when the gap is mandate-specific (i.e. it belongs in that worker's `CLAUDE.md` because it doesn't apply to other workers).
4. **Consistency check**: For mandate-specific edits, re-read the updated worker file to confirm the fix is present and non-contradictory. For shared-rule edits, re-read `WORKER_STANDARDS.md` only.
5. **Log**: Add entry to `logs/worker_updates.md`.
