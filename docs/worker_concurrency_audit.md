# Worker Concurrency Audit

## Goal
Identify blocking operations in the worker runtime that may cause event‑loop or thread starvation, and propose solutions.

## Findings

### 1. Synchronous wrappers (`asyncio.run()`)
- **`core/engine/storage/session_store.py:182`** – `write_state_sync()` uses `asyncio.run()` which blocks the event loop.
- **`core/engine/runtime/shared_state.py:229`** – `_sync_persist()` uses `asyncio.run()`.
- **CLI and runner** – Several places use `asyncio.run()` inside synchronous functions (e.g., `cli.py:443`, `cli.py:579`, etc.) – these are acceptable because they run in a separate process, but they indicate sync boundaries.
- **Tests** – Many tests use `asyncio.run()` – not a production concern.

**Risk**: High when these sync wrappers are called from an async context (e.g., inside an event‑loop node or a tool). They will block the entire event loop.

### 2. File‑based locking (`fcntl.flock`)
- **`core/engine/storage/session_store.py:143‑165`** – `try_claim_session()` uses `fcntl.flock()` with `LOCK_EX | LOCK_NB` (non‑blocking) and then releases. The lock acquisition itself is **non‑blocking** (due to `LOCK_NB`), but if it fails (BlockingIOError), it returns `False` immediately. However, the `fcntl.flock` call itself is a syscall and could block if the file is already locked by another process – but with `LOCK_NB` it returns immediately. The main risk is the **`with open(lock_path, "w")`** which is a blocking file open. That could block if the file system is slow.

**Risk**: Low – because `LOCK_NB` prevents indefinite blocking. But still a synchronous I/O call.

### 3. Sync file I/O in storage
- **`core/engine/storage/backend.py:68,81,174`** – `with open(...)` for reading/writing run summaries and indices – these are blocking.
- **`core/engine/storage/conversation_store.py:23,30`** – sync file operations for conversation persistence.
- **`core/engine/storage/session_store.py:148`** – `with open(lock_path, "w")` – blocking.

**Risk**: Medium – file I/O can block the event loop if called from an async context.

### 4. Tool implementations
- No obvious `requests.get/post` found in `core/engine/tools/` – but we need to check each tool module for blocking HTTP or DB calls.
- Potential risk: tools that use `subprocess`, `pandas`, or other CPU‑intensive operations.

### 5. Shared state persistence
- **`core/engine/runtime/shared_state.py:149,153,212,229`** – uses `asyncio.run_coroutine_threadsafe()` and `asyncio.run()` – this runs in a separate thread/loop, so it shouldn't block the main event loop. The design seems okay.

### 6. Event‑loop nodes
- Unknown – need to inspect `core/engine/graph/event_loop/node.py` to see if they use async I/O or blocking calls. Likely they are async.

## Recommendations

### Short‑term (low‑hanging fixes)
1. **Replace `asyncio.run()` in `write_state_sync()` with `asyncio.to_thread()` or a dedicated executor** – offload the synchronous write to a thread pool.
2. **Use `aiofiles` for file I/O** in storage layers – this would make file operations async and non‑blocking.
3. **Wrap `fcntl.flock` in `run_in_executor`** if we want to guarantee it never blocks, but with `LOCK_NB` it's probably fine.

### Medium‑term (refactoring)
4. **Make `SessionStore` and `CheckpointStore` fully async** – all methods should be async, and the sync wrappers should be removed or moved to a separate sync‑only interface.
5. **Introduce a thread pool executor** for blocking operations (file I/O, CPU‑bound tasks) and use `asyncio.get_running_loop().run_in_executor()` for them.
6. **Review all tools** for blocking calls and either make them async or offload to threads.

### Long‑term (design)
7. **Adopt a purely async architecture** – ensure every layer (storage, LLM, tools, etc.) is async‑native, so the event loop never blocks.
8. **Add concurrency tests** – simulate many sessions and workers to detect blocking and measure throughput.

## Next Steps
- [ ] Implement short‑term fixes for `write_state_sync()` and other sync wrappers.
- [ ] Add integration tests for concurrent session handling.
- [ ] Audit tool implementations for blocking calls.
- [ ] Document best practices for writing async‑safe tools.
