"""The Studio's project workspace: one VitProject plus the media library.

Holds the version-control workflow the editor needs — save the working
timeline, commit it under the current user's name, auto-save before switching
branches or merging, reset to a fresh project.
"""

import os
import re
import shutil
import stat
import sys
from typing import List, Optional

from vit.diff import diff_working_tree
from vit.project import VitProject
from vit.timeline import DomainFiles
from vit.validation import validate

from .config import StudioConfig
from .media import MediaLibrary
from .serializer import timeline_from_browser
from .starter import starter_files

DEFAULT_AUTHOR = "Vit Demo"


def _force_remove(func, path, _exc):
    # git marks object files read-only; Windows refuses to delete those.
    os.chmod(path, stat.S_IWRITE)
    func(path)


class Workspace:
    def __init__(self, config: StudioConfig, library: MediaLibrary):
        self.config = config
        self.library = library
        self.project = VitProject(config.project_dir)

    @property
    def repo(self):
        return self.project.repo

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def ensure(self) -> None:
        """Create the demo project on first run."""
        os.makedirs(self.config.media_dir, exist_ok=True)
        if not self.project.exists():
            self.reset()

    def reset(self) -> None:
        """Delete the demo repo and start again from the starter timeline."""
        workspace = os.path.abspath(self.config.workspace)
        target = os.path.abspath(self.config.project_dir)
        if os.path.commonpath([workspace, target]) != workspace:
            raise RuntimeError(f"Refusing to delete {target}: outside demo workspace")
        if os.path.exists(target):
            if sys.version_info >= (3, 12):
                shutil.rmtree(target, onexc=_force_remove)
            else:
                shutil.rmtree(target, onerror=_force_remove)
        self.project = VitProject.create(target)
        self.write_working(starter_files())
        self.commit("vit: initial snapshot", DEFAULT_AUTHOR)

    # ── Working timeline ─────────────────────────────────────────────────────

    def write_working(self, files: DomainFiles) -> None:
        """Write the browser's timeline through vit's models (round-trip validated)."""
        self.project.store.write_timeline(timeline_from_browser(files, self.library))

    def is_dirty(self) -> bool:
        return not self.repo.is_clean()

    def unsaved_diff(self) -> str:
        return diff_working_tree(self.project, "HEAD")

    def issues(self) -> List[dict]:
        return [issue.to_dict() for issue in validate(self.project.working_files())]

    # ── Versions ─────────────────────────────────────────────────────────────

    def set_author(self, author: Optional[str]) -> None:
        name = (author or "").strip() or DEFAULT_AUTHOR
        slug = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".") or "user"
        self.repo.set_config("user.name", name)
        self.repo.set_config("user.email", f"{slug}@vit.demo")

    def commit(self, message: str, author: Optional[str]) -> Optional[str]:
        """Commit the working timeline. Returns the short hash, or None if unchanged."""
        self.set_author(author)
        return self.project.commit_if_changed(message)

    def autosave_if_dirty(self, reason: str, author: Optional[str]) -> Optional[str]:
        if self.is_dirty():
            return self.commit(f"vit: auto-save before {reason}", author)
        return None
