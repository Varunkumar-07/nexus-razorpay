"""In-memory session store for the Web Chat UI.

Purely additive on top of Phase 6: each entry wraps one unmodified
ChatSession instance (app.chat_adapter.adapter.ChatSession, reused
exactly as scripts/chat_cli.py uses it) plus a running message history
list, keyed by a random session_id.

In-memory dict is fine for this build — sessions live for the lifetime of
the server process, which matches the demo/single-process deployment.
"""

import uuid
from typing import Dict, List, Optional

from app.chat_adapter.adapter import ChatSession


class SessionRecord:
    def __init__(self) -> None:
        self.chat_session = ChatSession()
        self.history: List[dict] = []  # [{"role": "user" | "agent", "text": str}]


_SESSIONS: Dict[str, SessionRecord] = {}


def create_session() -> str:
    """Create a new session and return its id."""
    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = SessionRecord()
    return session_id


def get_session(session_id: str) -> Optional[SessionRecord]:
    """Look up a session by id, or None if it doesn't exist."""
    return _SESSIONS.get(session_id)
