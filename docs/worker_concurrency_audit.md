# Worker Concurrency Audit

## Goal
Identify blocking operations in the worker runtime that may cause event‑loop or thread starvation, and propose solutions.

## Areas to investigate
- **Event‑loop nodes**: Are they using sync I/O or heavy CPU work?
- **LLM calls**: Do they block the event loop? (LiteLLM is async, but check retry logic and fallback.)
- **Storage operations**: File I/O (session store, checkpoints) – are they async or blocking?
- **Tool execution**: Some tools may use blocking libraries (e.g., requests, pandas, etc.).
- **Shared state persistence**: Does `_persist()` block the loop?
- **Claim locking**: Uses `fcntl.flock` – does it block the event loop? If so, we should offload to a thread.

## Findings
(To be filled after code review)

### Potential Blocking Calls
- [ ] `SessionStore.write_state_sync()` – uses `asyncio.run()` which blocks.
- [ ] `CheckpointStore` methods – likely sync file I/O.
- [ ] `fcntl.flock` in `try_claim_session()` – blocks the event loop if not wrapped.
- [ ] `AgentRunner.run()` – may have sync operations.
- [ ] Tool implementations – check for sync HTTP calls, DB queries, etc.

## Recommendations
(To be filled after findings)
