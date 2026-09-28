"""HTTP transport for the Studio: routing, local-only security, static and media files."""

import json
import os
import re
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Dict, Type
from urllib.parse import parse_qs, unquote, urlparse

from vit.git import GitError

from .api import Handler, StudioApi
from .config import StudioConfig
from .media import MediaLibrary

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".m4v": "video/mp4", ".ogv": "video/ogg",
}
CLIENT_ERRORS = (GitError, ValueError, KeyError, RuntimeError)
WRITE_HEADER = "X-Vit-Demo"
_CHUNK = 1 << 16

# One lock per project path, not one global lock. Today's Studio pins a
# single project per process, so in practice there's only ever one key — but
# keying it now means a future multi-project router doesn't serialize
# unrelated projects' requests behind each other, and it already helps this
# process: a slow multi-branch call (e.g. /api/branches/status, which runs
# preview_merge() once per branch) only ever blocks requests to the *same*
# project, never a different one addressed later.
_project_locks: Dict[str, threading.Lock] = {}
_registry_guard = threading.Lock()  # protects the dict itself, held only briefly


def _lock_for(project_path: str) -> threading.Lock:
    with _registry_guard:
        if project_path not in _project_locks:
            _project_locks[project_path] = threading.Lock()
        return _project_locks[project_path]


def make_handler(config: StudioConfig, api: StudioApi, library: MediaLibrary) -> Type[BaseHTTPRequestHandler]:
    """Build a request handler class bound to this Studio's config and services.

    Every API call is serialised per-project: they all read or write the same
    git working tree for that project, and git is not safe to drive
    concurrently — but two different projects' requests don't block each other.
    """
    get_routes, post_routes = api.get_routes(), api.post_routes()

    class StudioRequestHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if "/api/" in self.path and not self.path.startswith("/api/working"):
                sys.stderr.write(f"  {self.command} {self.path.split('?')[0]}\n")

        # ── Entry points ─────────────────────────────────────────────────────

        def do_GET(self):
            if not self._trusted(write=False):
                return
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                return self._dispatch(get_routes, None)
            if path.startswith("/media/"):
                return self._serve_file(config.media_dir, unquote(path[len("/media/"):]))
            return self._serve_file(config.static_dir, "index.html" if path == "/" else path.lstrip("/"))

        def do_POST(self):
            if not self._trusted(write=True):
                return
            if urlparse(self.path).path == "/api/media":
                return self._upload()
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as e:
                return self._json({"error": f"Invalid JSON body: {e}"}, HTTPStatus.BAD_REQUEST)
            self._dispatch(post_routes, body)

        # ── Security ─────────────────────────────────────────────────────────

        def _trusted(self, write: bool) -> bool:
            """Block other websites from driving this local server.

            The Host check stops DNS-rebinding pages from reading the API; the
            custom header on writes can't be sent cross-origin without a CORS
            preflight (which this server never approves), so a malicious page
            can't POST /api/reset or commit on the user's behalf.
            """
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in config.allowed_hosts:
                self._json({"error": "Forbidden host"}, HTTPStatus.FORBIDDEN)
                return False
            if write and self.headers.get(WRITE_HEADER) != "1":
                self._json({"error": f"Missing {WRITE_HEADER} header"}, HTTPStatus.FORBIDDEN)
                return False
            return True

        # ── API ──────────────────────────────────────────────────────────────

        def _query(self) -> Dict[str, str]:
            return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

        def _dispatch(self, routes: Dict[str, Handler], body):
            handler = routes.get(urlparse(self.path).path)
            if handler is None:
                return self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            try:
                with _lock_for(config.project_dir):
                    result = handler(self._query(), body)
                self._json(result)
            except CLIENT_ERRORS as e:
                self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

        def _json(self, payload, status=HTTPStatus.OK):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _upload(self):
            """Raw-body upload of a video file into the media folder (not into git)."""
            q = self._query()
            try:
                entry = library.import_stream(
                    self.rfile,
                    int(self.headers.get("Content-Length") or 0),
                    name=q.get("name", "clip.mp4"),
                    duration_frames=float(q.get("duration_frames", 240)),
                    width=float(q.get("width", 1920)),
                    height=float(q.get("height", 1080)),
                )
            except ValueError as e:
                return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            self._json(entry)

        # ── Static files and media (with Range support for <video> seeking) ──

        def _serve_file(self, root: str, rel: str):
            root = os.path.abspath(root)
            full = os.path.abspath(os.path.join(root, rel))
            if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
                return self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            size = os.path.getsize(full)
            start, end = self._byte_range(size)
            self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream"))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                with open(full, "rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk = f.read(min(remaining, _CHUNK))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass  # browser cancelled a range request while seeking — normal for <video>

        def _byte_range(self, size: int):
            """Send the status line for a full or partial response; return (start, end)."""
            start, end = 0, size - 1
            match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if match and size:
                if match.group(1):
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else size - 1
                else:
                    start = max(0, size - int(match.group(2)))
                end = min(end, size - 1)
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(HTTPStatus.OK)
            return start, end

    return StudioRequestHandler
