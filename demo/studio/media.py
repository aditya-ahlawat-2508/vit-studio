"""Media library: built-in procedural sources plus videos the user imports.

Media lives on disk outside git, like real footage; the timeline only ever
stores references to it (`media_ref`).
"""

import hashlib
import json
import os
import tempfile
import threading
from typing import BinaryIO, Dict, List

# Built-in footage. Frames are drawn procedurally in the browser from
# (kind, source_frame), so the demo needs no media files at all.
SYNTHETIC_SOURCES = [
    {"ref": "demo:interview", "name": "Interview_A.mov", "kind": "interview", "duration_frames": 1440, "color": "#c9a227"},
    {"ref": "demo:sunset", "name": "Sunset_Beach.mov", "kind": "sunset", "duration_frames": 720, "color": "#e8804a"},
    {"ref": "demo:city", "name": "City_Night.mov", "kind": "city", "duration_frames": 960, "color": "#6b7bff"},
    {"ref": "demo:forest", "name": "Forest_Drone.mov", "kind": "forest", "duration_frames": 720, "color": "#3fa36b"},
    {"ref": "demo:ocean", "name": "Ocean_Waves.mov", "kind": "ocean", "duration_frames": 600, "color": "#2aa4c8"},
    {"ref": "demo:bars", "name": "Color_Bars.mov", "kind": "bars", "duration_frames": 480, "color": "#9a9a9a"},
]

IMPORTED_KIND = "video"
_CHUNK = 1 << 20


def synthetic_source(kind: str) -> dict:
    return next(s for s in SYNTHETIC_SOURCES if s["kind"] == kind)


class MediaLibrary:
    """Every source the editor can place on the timeline."""

    def __init__(self, media_dir: str):
        self.media_dir = media_dir
        self.index_file = os.path.join(media_dir, "library.json")
        self._index_lock = threading.Lock()

    def entries(self) -> List[dict]:
        """Built-in sources, then imported videos (flagged unavailable if the file is gone)."""
        library = [dict(s, available=True) for s in SYNTHETIC_SOURCES]
        for entry in self._imported():
            entry = dict(entry, kind=IMPORTED_KIND)
            entry["available"] = os.path.exists(os.path.join(self.media_dir, entry["file"]))
            library.append(entry)
        return library

    def by_ref(self) -> Dict[str, dict]:
        return {s["ref"]: s for s in self.entries()}

    def file_path(self, entry: dict) -> str:
        return os.path.join(self.media_dir, entry["file"]).replace("\\", "/")

    def import_stream(self, stream: BinaryIO, length: int, name: str,
                      duration_frames: float, width: float, height: float) -> dict:
        """Copy an uploaded video into the media folder, named by its SHA-256.

        Streaming happens outside any lock so a large upload doesn't block
        the editor; only the library index update is serialised.
        """
        name = os.path.basename(name)
        ext = os.path.splitext(name)[1].lower() or ".mp4"
        sha = self._store_upload(stream, length, ext)
        hue = int(sha[:2], 16) * 360 // 256
        entry = {
            "ref": f"sha256:{sha}",
            "name": name,
            "file": f"{sha[:16]}{ext}",
            "duration_frames": max(1, int(duration_frames)),
            "width": int(width),
            "height": int(height),
            "color": f"hsl({hue}, 55%, 55%)",
        }
        self._save_imported(entry)
        return dict(entry, kind=IMPORTED_KIND, available=True)

    def _store_upload(self, stream: BinaryIO, length: int, ext: str) -> str:
        os.makedirs(self.media_dir, exist_ok=True)
        digest = hashlib.sha256()
        fd, tmp_path = tempfile.mkstemp(dir=self.media_dir, suffix=".part")
        with os.fdopen(fd, "wb") as out:
            remaining = length
            while remaining > 0:
                chunk = stream.read(min(remaining, _CHUNK))
                if not chunk:
                    break
                digest.update(chunk)
                out.write(chunk)
                remaining -= len(chunk)
        sha = digest.hexdigest()
        os.replace(tmp_path, os.path.join(self.media_dir, f"{sha[:16]}{ext}"))
        return sha

    def _imported(self) -> List[dict]:
        if not os.path.exists(self.index_file):
            return []
        with open(self.index_file) as f:
            return json.load(f)

    def _save_imported(self, entry: dict) -> None:
        with self._index_lock:
            entries = [e for e in self._imported() if e["ref"] != entry["ref"]] + [entry]
            with open(self.index_file, "w") as f:
                json.dump(entries, f, indent=2, sort_keys=True)
