"""JSON API for the Studio editor.

Each handler takes (query, body) and returns a JSON-serialisable dict; raising
ValueError / GitError / KeyError becomes a 400 with the message. Transport
concerns (HTTP, security, locking) live in `handler.py`.
"""

import os
import re
from typing import Callable, Dict, Optional

from vit.diff import format_diff
from vit.live import registry as live_registry
from vit.merge import CONFLICTS, UP_TO_DATE, perform_merge, preview_merge
from vit.merge.suggest import suggest_resolutions
from vit.timeline import DOMAIN_FILES

from .workspace import Workspace

Handler = Callable[[Dict[str, str], Optional[dict]], dict]

BRANCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")


class StudioApi:
    def __init__(self, workspace: Workspace):
        self.ws = workspace

    def get_routes(self) -> Dict[str, Handler]:
        return {
            "/api/state": self.state,
            "/api/log": self.log,
            "/api/files": self.files,
            "/api/commit": self.commit_detail,
            "/api/raw": self.raw,
            "/api/compare": self.compare,
            "/api/branches/status": self.branches_status,
        }

    def post_routes(self) -> Dict[str, Handler]:
        return {
            "/api/working": self.save_working,
            "/api/commit": self.commit,
            "/api/branch": self.create_branch,
            "/api/checkout": self.checkout,
            "/api/merge": self.merge,
            "/api/restore": self.restore,
            "/api/reset": self.reset,
            "/api/live/save": self.live_save,
        }

    # ── Reads ────────────────────────────────────────────────────────────────

    def state(self, _q, _body) -> dict:
        repo = self.ws.repo
        branch = repo.current_branch()
        return {
            "branch": branch,
            "detached": branch == "HEAD",
            "branches": repo.branches(),
            "head": (repo.rev_parse("HEAD") or "")[:7],
            "dirty": self.ws.is_dirty(),
            "files": self.ws.project.working_files(),
            "library": self.ws.library.entries(),
            "diff": self.ws.unsaved_diff(),
            "issues": self.ws.issues(),
            "project_dir": self.ws.project.path,
            # Live co-editing (vit/live/) runs its own WebSocket server on a
            # separate port, since plain http.server can't speak WebSocket.
            # Same host as this HTTP request, different port — see
            # docs/ARCHITECTURE.md for why this is a single-port limitation
            # on PaaS platforms that only forward one public port.
            "live_ws_port": int(os.environ.get("VIT_LIVE_PORT", 8766)),
        }

    def log(self, _q, _body) -> dict:
        return {"commits": self.ws.repo.log_graph(), "branch": self.ws.repo.current_branch()}

    def files(self, q, _body) -> dict:
        return {"files": self._files_at(q["ref"])}

    def commit_detail(self, q, _body) -> dict:
        ref = q["ref"]
        parent = self.ws.repo.rev_parse(f"{ref}^")
        return {"diff": format_diff(self._files_at(parent), self._files_at(ref))}

    def raw(self, q, _body) -> dict:
        path = q["path"]
        return {
            "content": self.ws.project.store.read_text(path),
            "git_diff": self.ws.repo.diff("HEAD", [path]),
        }

    def branches_status(self, _q, _body) -> dict:
        """Every other branch's merge status at once — no per-branch selection needed
        to see whether it's clean or how many conflicts it carries."""
        current = self.ws.repo.current_branch()
        results = []
        for branch in self.ws.repo.branches():
            if branch == current or self.ws.repo.rev_parse(branch) is None:
                continue
            p = preview_merge(self.ws.project, branch)
            results.append({
                "branch": branch,
                "conflict_count": len(p.conflicts),
                "clean": len(p.conflicts) == 0,
                "up_to_date": p.up_to_date,
            })
        return {"branches": results}

    def compare(self, q, _body) -> dict:
        exclude_auto = set(filter(None, (q.get("exclude_auto") or "").split(",")))
        p = preview_merge(self.ws.project, q["branch"], exclude_auto=exclude_auto)
        return {
            "ours_diff": format_diff(p.base_files, p.ours_files),
            "theirs_diff": format_diff(p.base_files, p.theirs_files),
            "conflicts": p.conflicts,
            "git_text_conflicts": p.git_text_conflicts,
            "up_to_date": p.up_to_date,
            "dirty": self.ws.is_dirty(),
            # Auto-resolved conflicts (never silent — always shown, always
            # undoable) plus hints for whatever's left. `auto_resolutions` is
            # ready to pass straight through to /api/merge so the actual merge
            # matches exactly what this preview showed as auto-applied.
            "auto_applied": [s.to_dict() for s in p.auto_applied.values()],
            "auto_resolutions": {path: s.as_resolution() for path, s in p.auto_applied.items()},
            "suggestions": {path: s.to_dict() for path, s in p.suggestions.items()},
        }

    # ── Writes ───────────────────────────────────────────────────────────────

    def save_working(self, _q, body) -> dict:
        self.ws.write_working(body["files"])
        return {"dirty": self.ws.is_dirty(), "diff": self.ws.unsaved_diff(), "issues": self.ws.issues()}

    def commit(self, _q, body) -> dict:
        message = (body.get("message") or "").strip() or "save version"
        if not message.startswith("vit:"):
            message = f"vit: {message}"
        return {"hash": self.ws.commit(message, body.get("author")), "message": message}

    def create_branch(self, _q, body) -> dict:
        name = (body.get("name") or "").strip()
        if not BRANCH_NAME.fullmatch(name):
            raise ValueError("Branch names may use letters, numbers, '.', '_', '-' and '/'.")
        self.ws.repo.create_branch(name)
        return {"branch": name}

    def checkout(self, _q, body) -> dict:
        ref = body["ref"]
        saved = self.ws.autosave_if_dirty(f"switching to '{ref}'", body.get("author"))
        self.ws.repo.checkout(ref)
        return {"branch": self.ws.repo.current_branch(), "autosaved": saved}

    def merge(self, _q, body) -> dict:
        branch = body["branch"]
        author = body.get("author")
        current = self.ws.repo.current_branch()
        if branch == current:
            raise ValueError("Can't merge a branch into itself.")
        self.ws.autosave_if_dirty(f"merging '{branch}'", author)
        self.ws.set_author(author)

        outcome = perform_merge(self.ws.project, branch, body.get("resolutions"))
        if outcome.status == UP_TO_DATE:
            return {"status": "up_to_date"}
        if outcome.status == CONFLICTS:
            # perform_merge() itself doesn't auto-apply (only preview_merge()
            # does, since compare()'s auto_resolutions are what actually gets
            # sent here) — but it's still worth surfacing suggestion hints on
            # whatever's left, e.g. when a merge was attempted without going
            # through compare() first.
            hints = suggest_resolutions(outcome.conflicts)
            return {
                "status": "conflicts", "conflicts": outcome.conflicts, "ours": current, "theirs": branch,
                # Full snapshots, not just diffs, so the conflict view can render actual
                # frames for "ours" vs "theirs" instead of only JSON values.
                "ours_files": outcome.ours_files, "theirs_files": outcome.theirs_files,
                "suggestions": {path: s.to_dict() for path, s in hints.items()},
            }
        return {
            "status": "merged",
            "hash": outcome.commit,
            "git_text_conflicts": outcome.git_text_conflicts,
            "diff": format_diff(outcome.ours_files, self._files_at("HEAD")),
            "issues": self.ws.issues(),
        }

    def restore(self, _q, body) -> dict:
        ref = body["ref"]
        self.ws.write_working(self._files_at(ref))
        return {"hash": self.ws.commit(f"vit: restore version {ref}", body.get("author"))}

    def reset(self, _q, _body) -> dict:
        self.ws.reset()
        return {"ok": True}

    def live_save(self, _q, body) -> dict:
        """Explicit save from the live co-editing layer: flushes the shared
        CRDT state (vit/live/) to disk and commits it exactly as a single
        editor's /api/commit does — same TimelineStore/VitProject path, same
        JSON formatting, a completely ordinary vit commit either way."""
        message = (body.get("message") or "").strip() or "live save"
        if not message.startswith("vit:"):
            message = f"vit: {message}"
        self.ws.set_author(body.get("author"))
        session = live_registry.get_or_create(self.ws.project)
        return {"hash": session.flush_to_disk_and_commit(message), "message": message}

    def _files_at(self, ref: Optional[str]) -> dict:
        """Every domain at `ref`, with {} for domains that don't exist there (what the editor expects)."""
        files = self.ws.project.files_at(ref)
        return {domain: files.get(domain, {}) for domain in DOMAIN_FILES}

