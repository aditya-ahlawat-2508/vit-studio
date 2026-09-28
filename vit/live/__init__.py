"""Live (pre-commit) collaborative editing.

Scope boundary: this package never touches `vit/merge/`, `vit/git.py`, or
`vit/diff.py` — it only concerns the *uncommitted* working state multiple
connected editors are looking at simultaneously. The only integration points
with the rest of `vit/` are `TimelineStore.write_files()` and
`VitProject.commit_if_changed()`, exactly as a single editor's save works
today. Once a `LiveSession` flushes to a commit, that commit is a normal vit
commit in every respect — diffable, branchable, mergeable through the
existing (unmodified) three-way merge.
"""

from .crdt import CRDTDoc
from .session import LiveSession

__all__ = ["CRDTDoc", "LiveSession"]
