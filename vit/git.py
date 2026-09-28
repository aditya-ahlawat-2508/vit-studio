"""Git repository wrapper. Every git operation in vit goes through this class.

It shells out to the system `git` binary and knows nothing about timelines:
the timeline layer (`vit.timeline`) and the merge layer (`vit.merge`) build on
top of it.
"""

import subprocess
from typing import Dict, List, Optional, Tuple


class GitError(Exception):
    """Raised when a git command fails."""


class GitRepository:
    """A git working tree at `path`."""

    def __init__(self, path: str):
        self.path = path

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(["git", *args], cwd=self.path, capture_output=True, text=True)
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise GitError(f"git {' '.join(args)} failed: {detail}")
        return result

    # ── Setup ────────────────────────────────────────────────────────────────

    def init(self) -> None:
        """`git init`, naming the first branch 'main' whatever init.defaultBranch says.

        HEAD is only moved in a repo without commits, so re-running init on an
        existing project never orphans its history.
        """
        self._run("init")
        if self.rev_parse("HEAD") is None:
            self._run("symbolic-ref", "HEAD", "refs/heads/main")

    def set_config(self, key: str, value: str) -> None:
        self._run("config", key, value)

    # ── Working tree ─────────────────────────────────────────────────────────

    def add(self, paths: List[str]) -> None:
        self._run("add", *paths)

    def has_staged_changes(self) -> bool:
        return self._run("diff", "--cached", "--quiet", check=False).returncode != 0

    def commit(self, message: str) -> str:
        """Commit the index. Returns the short hash of the new commit."""
        self._run("commit", "-m", message)
        return self._run("rev-parse", "--short", "HEAD").stdout.strip()

    def is_clean(self) -> bool:
        """True when there are no staged, unstaged or untracked changes."""
        return not self._run("status", "--porcelain", check=False).stdout.strip()

    def diff(self, ref: Optional[str] = None, paths: Optional[List[str]] = None) -> str:
        args = ["diff"] + ([ref] if ref else []) + (["--", *paths] if paths else [])
        return self._run(*args).stdout

    # ── Refs and branches ────────────────────────────────────────────────────

    def create_branch(self, name: str) -> None:
        """Create `name` at HEAD and switch to it."""
        self._run("checkout", "-b", name)

    def checkout(self, ref: str) -> None:
        self._run("checkout", ref)

    def current_branch(self) -> str:
        """Current branch name, or "HEAD" when detached."""
        return self._run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def branches(self) -> List[str]:
        out = self._run("branch", "--list").stdout
        return [line.strip().lstrip("* ") for line in out.splitlines() if line.strip()]

    def rev_parse(self, ref: str) -> Optional[str]:
        """Full commit hash for `ref`, or None if it doesn't resolve to a commit."""
        result = self._run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def merge_base(self, ref1: str, ref2: str) -> Optional[str]:
        result = self._run("merge-base", ref1, ref2, check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def show_file(self, ref: str, relpath: str) -> Optional[str]:
        """Content of `relpath` at `ref`, or None if the file doesn't exist there."""
        result = self._run("show", f"{ref}:{relpath}", check=False)
        return result.stdout if result.returncode == 0 else None

    def log_graph(self, max_count: int = 200) -> List[Dict]:
        """Commits on all branches in topological order, newest first.

        Each entry: hash, parents, message, author, date, refs, is_head.
        """
        result = self._run(
            "log", "--all", "--topo-order", f"--max-count={max_count}",
            "--pretty=format:%h%x1f%p%x1f%s%x1f%an%x1f%ar%x1f%D",
            check=False,
        )
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) < 6:
                continue
            refs, is_head = [], False
            for ref in parts[5].split(","):
                ref = ref.strip()
                if ref == "HEAD" or ref.startswith("HEAD -> "):
                    is_head = True
                ref = ref.replace("HEAD -> ", "")
                if ref and ref != "HEAD":
                    refs.append(ref)
            commits.append({
                "hash": parts[0],
                "parents": parts[1].split(),
                "message": parts[2],
                "author": parts[3],
                "date": parts[4],
                "refs": refs,
                "is_head": is_head,
            })
        return commits

    # ── Merging ──────────────────────────────────────────────────────────────

    def merge_no_commit(self, branch: str) -> Tuple[bool, str]:
        """Start merging `branch` but stop before committing (even on fast-forward).

        Returns (clean, output). A conflicted merge is still "in progress" so
        the caller can write resolved files and commit it.
        """
        result = self._run("merge", "--no-ff", "--no-commit", branch, check=False)
        return result.returncode == 0, result.stdout + result.stderr

    def merge_abort(self) -> None:
        self._run("merge", "--abort")

    def conflicted_files(self) -> List[str]:
        out = self._run("diff", "--name-only", "--diff-filter=U", check=False).stdout
        return [f for f in out.splitlines() if f.strip()]

    def merge_tree_conflicts(self, ours: str, theirs: str) -> Optional[List[str]]:
        """Files a plain line-based git merge of the two refs would conflict on.

        Uses `git merge-tree --write-tree`, which touches neither the index nor
        the working tree. Returns None when git is too old to support it
        (< 2.38); this is diagnostic information only, so merges must not
        depend on it.
        """
        result = self._run(
            "merge-tree", "--write-tree", "--name-only", "--no-messages", ours, theirs,
            check=False,
        )
        if result.returncode == 0:
            return []
        if result.returncode != 1:
            return None
        # First line is the tree id; the rest are conflicted paths.
        paths = [line for line in result.stdout.splitlines()[1:] if line.strip()]
        return list(dict.fromkeys(paths))
