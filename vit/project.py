"""A vit project: a git repository whose content is domain-split timeline JSON.

    my-project/
    ├── .git/
    ├── .vit/config.json
    ├── timeline/   cuts.json, color.json, audio.json, effects.json, markers.json, metadata.json
    └── assets/     manifest.json (media paths and metadata, never media bytes)
"""

import json
import os
from typing import Optional

from .git import GitRepository
from .timeline.store import DOMAIN_FILES, DomainFiles, TimelineStore, parse_domain_file

CONFIG_VERSION = "0.1.0"

# Paths `stage()` adds: everything vit owns in the project.
TRACKED_PATHS = ["timeline/", "assets/", ".vit/", ".gitignore"]

_PROJECT_GITIGNORE = """\
# OS files
.DS_Store
Thumbs.db
Desktop.ini

# Media files — vit tracks metadata, not binaries
*.mov
*.mp4
*.mxf
*.avi
*.mkv
*.webm
*.wav
*.aif
*.aiff
*.mp3
*.aac

# Environment / secrets
.env
.env.*
"""


class VitProject:
    """Git repository + timeline files for one project directory."""

    def __init__(self, path: str):
        self.path = path
        self.repo = GitRepository(path)
        self.store = TimelineStore(path)

    @classmethod
    def create(cls, path: str) -> "VitProject":
        """Initialise a project at `path` (safe to call on an existing one)."""
        os.makedirs(path, exist_ok=True)
        project = cls(path)
        project.repo.init()
        for sub in ("timeline", "assets"):
            os.makedirs(os.path.join(path, sub), exist_ok=True)

        config_path = os.path.join(path, ".vit", "config.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            json.dump({"version": CONFIG_VERSION}, f, indent=2, sort_keys=True)

        gitignore = os.path.join(path, ".gitignore")
        if not os.path.exists(gitignore):
            with open(gitignore, "w") as f:
                f.write(_PROJECT_GITIGNORE)
        return project

    def exists(self) -> bool:
        return os.path.isdir(os.path.join(self.path, ".git"))

    def working_files(self) -> DomainFiles:
        """Domain files as they are on disk now."""
        return self.store.read_all()

    def files_at(self, ref: Optional[str]) -> DomainFiles:
        """Domain files at a git ref. Domains absent at that ref are omitted."""
        files: DomainFiles = {}
        if not ref:
            return files
        for domain, relpath in DOMAIN_FILES.items():
            raw = self.repo.show_file(ref, relpath)
            if raw is not None:
                files[domain] = parse_domain_file(relpath, raw, ref)
        return files

    def stage(self) -> None:
        self.repo.add(TRACKED_PATHS)

    def commit_if_changed(self, message: str) -> Optional[str]:
        """Stage and commit. Returns the short hash, or None if nothing changed."""
        self.stage()
        if not self.repo.has_staged_changes():
            return None
        return self.repo.commit(message)
