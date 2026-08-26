"""Session Store - Unified session storage with state.json"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

from engine.schemas.session_state import SessionState
from engine.utils.io import atomic_write

logger = logging.getLogger(__name__)


class SessionStore:
    """Unified session storage with state.json"""

    def __init__(self, base_path: Path):
        """Initialize session store"""
        self.base_path = Path(base_path)
        self.sessions_dir = self.base_path / "sessions"

    def generate_session_id(self) -> str:
        """Generate session ID in format: session_YYYYMMDD_HHMMSS_{uuid}"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return f"session_{timestamp}_{short_uuid}"

    def get_session_path(self, session_id: str) -> Path:
        """Get path to session directory"""
        return self.sessions_dir / session_id

    def get_state_path(self, session_id: str) -> Path:
        """Get path to state.json file"""
        return self.get_session_path(session_id) / "state.json"

    async def write_state(self, session_id: str, state: SessionState) -> None:
        """Atomically write state.json for a session"""

        def _write():
            state_path = self.get_state_path(session_id)
            state_path.parent.mkdir(parents=True, exist_ok=True)

            with atomic_write(state_path) as f:
                f.write(state.model_dump_json(indent=2))

        await asyncio.to_thread(_write)
        logger.debug(f"Wrote state.json for session {session_id}")

    async def read_state(self, session_id: str) -> SessionState | None:
        """Read state.json for a session"""

        def _read():
            return self.read_state_sync(session_id)

        return await asyncio.to_thread(_read)

    def read_state_sync(self, session_id: str) -> SessionState | None:
        """Synchronously read state.json for a session (worker init paths)"""

        state_path = self.get_state_path(session_id)
        if not state_path.exists():
            return None

        import json

        from engine.storage.migrate import migrate_session_state

        raw = json.loads(state_path.read_text(encoding="utf-8"))
        migrated = migrate_session_state(raw)
        return SessionState.model_validate(migrated)

    async def list_sessions(
        self,
        status: str | None = None,
        goal_id: str | None = None,
        limit: int = 100,
    ) -> list[SessionState]:
        """List sessions, optionally filtered by status or goal"""

        def _scan():
            sessions = []

            if not self.sessions_dir.exists():
                return sessions

            for session_dir in self.sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue

                state_path = session_dir / "state.json"
                if not state_path.exists():
                    continue

                try:
                    state = SessionState.model_validate_json(state_path.read_text(encoding="utf-8"))

                    # Apply filters
                    if status and state.status != status:
                        continue

                    if goal_id and state.goal_id != goal_id:
                        continue

                    sessions.append(state)

                except Exception as e:
                    logger.warning(f"Failed to load {state_path}: {e}")
                    continue

            # Sort by updated_at descending (most recent first)
            sessions.sort(key=lambda s: s.timestamps.updated_at, reverse=True)
            return sessions[:limit]

        return await asyncio.to_thread(_scan)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its data"""

        def _delete():
            import shutil

            session_path = self.get_session_path(session_id)
            if not session_path.exists():
                return False

            shutil.rmtree(session_path)
            logger.info(f"Deleted session {session_id}")
            return True

        return await asyncio.to_thread(_delete)

    async def session_exists(self, session_id: str) -> bool:
        """Check if a session exists"""

        def _check():
            return self.get_state_path(session_id).exists()

        return await asyncio.to_thread(_check)

    def try_claim_session(self, session_id: str, worker_id: str, ttl_seconds: int = 60) -> bool:
        """Atomically claim a session for a worker."""
        import fcntl
        from datetime import datetime

        state_path = self.get_state_path(session_id)
        lock_path = state_path.with_suffix(state_path.suffix + ".lock")
        with open(lock_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            state = self.read_state_sync(session_id)
            if state is None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                return False
            if state.claimed_by and state.claimed_at:
                elapsed = datetime.utcnow() - state.claimed_at
                if elapsed.total_seconds() < ttl_seconds:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    return False
            state.claimed_by = worker_id
            state.claimed_at = datetime.utcnow()
            self.write_state_sync(session_id, state)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            return True

    def release_claim(self, session_id: str, worker_id: str) -> bool:
        """Release a claim if held by this worker."""
        state = self.read_state_sync(session_id)
        if state is None or state.claimed_by != worker_id:
            return False
        state.claimed_by = None
        state.claimed_at = None
        self.write_state_sync(session_id, state)
        return True

    def write_state_sync(self, session_id: str, state: SessionState) -> None:
        """Synchronous wrapper around async write_state."""
        import asyncio

        asyncio.run(self.write_state(session_id, state))
