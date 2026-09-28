"""Domain-split JSON on disk: where each domain file lives and how it is written.

JSON is always written with `indent=2, sort_keys=True` and a trailing newline,
so the same timeline always produces byte-identical files and git diffs stay
minimal.
"""

import json
import os
from typing import Dict

from .models import Timeline

# domain name → path relative to the project root. The single source of truth
# for the on-disk layout; everything else looks paths up here.
DOMAIN_FILES: Dict[str, str] = {
    "cuts": "timeline/cuts.json",
    "color": "timeline/color.json",
    "audio": "timeline/audio.json",
    "effects": "timeline/effects.json",
    "markers": "timeline/markers.json",
    "metadata": "timeline/metadata.json",
    "manifest": "assets/manifest.json",
}

DomainFiles = Dict[str, dict]


def read_json(filepath: str) -> dict:
    """Read a JSON file, returning {} if it doesn't exist."""
    if not os.path.exists(filepath):
        return {}
    with open(filepath) as f:
        return json.load(f)


def write_json(filepath: str, data: dict) -> None:
    """Write JSON with the canonical formatting."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def timeline_to_files(timeline: Timeline) -> DomainFiles:
    """Split a Timeline into its per-domain JSON documents."""
    return {
        "cuts": {"video_tracks": [t.to_dict() for t in timeline.video_tracks]},
        "color": {"grades": {k: v.to_dict() for k, v in timeline.color_grades.items()}},
        "audio": {"audio_tracks": [t.to_dict() for t in timeline.audio_tracks]},
        "effects": timeline.effects,
        "markers": {"markers": [m.to_dict() for m in timeline.markers]},
        "metadata": timeline.metadata.to_dict(),
        "manifest": {"assets": {k: v.to_dict() for k, v in timeline.assets.items()}},
    }


def parse_domain_file(relpath: str, raw: str, origin: str) -> dict:
    """Parse a domain file's text, naming the file and its origin on failure."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{relpath} at {origin} is not valid JSON: {e}") from e


class TimelineStore:
    """Reads and writes the domain files in a project's working tree."""

    def __init__(self, project_dir: str):
        self.project_dir = project_dir

    def path(self, domain: str) -> str:
        return os.path.join(self.project_dir, DOMAIN_FILES[domain])

    def read_all(self) -> DomainFiles:
        """Every domain file in the working tree ({} for missing ones)."""
        return {domain: read_json(self.path(domain)) for domain in DOMAIN_FILES}

    def write_files(self, files: DomainFiles) -> None:
        """Write the given domains; domains not in `files` are left untouched."""
        for domain, data in files.items():
            if domain in DOMAIN_FILES:
                write_json(self.path(domain), data)

    def write_timeline(self, timeline: Timeline) -> None:
        self.write_files(timeline_to_files(timeline))

    def read_text(self, relpath: str) -> str:
        """Raw text of a domain file ("" if missing). Only known domain paths are allowed."""
        if relpath not in DOMAIN_FILES.values():
            raise ValueError(f"Unknown file {relpath}")
        full = os.path.join(self.project_dir, relpath)
        if not os.path.exists(full):
            return ""
        with open(full) as f:
            return f.read()
