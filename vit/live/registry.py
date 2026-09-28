"""One LiveSession per project path, created lazily, kept for the process
lifetime (or until explicitly closed when the last client disconnects)."""

import threading
from typing import Dict

from ..project import VitProject
from .session import LiveSession

_sessions: Dict[str, LiveSession] = {}
_guard = threading.Lock()


def get_or_create(project: VitProject) -> LiveSession:
    with _guard:
        if project.path not in _sessions:
            _sessions[project.path] = LiveSession(project)
        return _sessions[project.path]


def close(project_path: str) -> None:
    with _guard:
        _sessions.pop(project_path, None)


def reset_all() -> None:
    """Testing convenience: drop every session, forcing a fresh load_from_disk
    on next use."""
    with _guard:
        _sessions.clear()
