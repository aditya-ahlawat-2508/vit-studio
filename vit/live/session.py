"""One live-editing session per project: a CRDT doc plus the two integration
points with the rest of vit — nothing else in vit/ is touched.
"""

import threading
from typing import Optional

from ..project import VitProject
from .crdt import CRDTDoc


class LiveSession:
    def __init__(self, project: VitProject, client_id: str = "server"):
        self.project = project
        self.doc = CRDTDoc(client_id=client_id)
        self._lock = threading.Lock()
        self.doc.load_from_files(project.working_files())

    def apply_remote_update(self, update: dict) -> bool:
        """Merge one update from a connected client. Returns True if it
        actually changed this session's state (worth rebroadcasting)."""
        with self._lock:
            return self.doc.apply_remote(update)

    def snapshot(self) -> dict:
        """Current live state as plain domain files — what a newly
        connecting client is sent to start in sync."""
        with self._lock:
            return self.doc.snapshot()

    def flush_to_disk_and_commit(self, message: str) -> Optional[str]:
        """Explicit save: write the current CRDT state through the existing
        TimelineStore/VitProject path, unchanged from how a single editor's
        save works today. Returns the short commit hash, or None if nothing
        changed since the last commit."""
        with self._lock:
            files = self.doc.snapshot()
        self.project.store.write_files(files)
        return self.project.commit_if_changed(message)
