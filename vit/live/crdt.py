"""A minimal, dependency-free CRDT for the live (uncommitted) timeline.

Not Yjs, not a general-purpose CRDT library — a purpose-built composition of
LWW-Registers (last-writer-wins) over the exact same normalized shape vit's
own three-way merge already uses (`vit.merge.three_way._normalize_domain`),
so live-edited state round-trips cleanly into a real commit.

Design
------
The whole `DomainFiles` tree is flattened into independent cells keyed by a
path tuple, each holding `(value, timestamp, deleted)`. A cell is itself a
plain LWW-Register:

    merge(a, b) = a if a.timestamp >= b.timestamp else b

which is commutative, associative and idempotent — the three properties a
CRDT needs (apply the same set of updates in any order, any number of times,
and every replica converges to the same state). The whole document is the
product of these per-cell registers, which is itself a CRDT: independent
CRDTs merged pointwise (cell by cell) compose into a CRDT.

Timestamps are **Lamport clocks** (`(counter, client_id)`), not wall-clock:
every local edit increments the local counter; every remote update advances
the local counter to `max(local, remote)`. This makes ordering independent of
clock skew between clients — the only thing that matters is causal ordering,
which a Lamport clock captures, and `client_id` breaks ties deterministically
when two edits land on the same counter value.

Deletion is **delete-wins**: removing a clip/track/etc. writes an explicit
`__exists__` cell (LWW like everything else). If the latest `__exists__`
write for an item says "gone," the item stays out of the snapshot regardless
of any field edit — including a field edit with a *later* timestamp that
never saw the deletion. This is a deliberate, simple default (not the only
possible one): it avoids a "zombie clip" reappearing from a stale field edit
that raced a delete, at the cost of a field edit "not un-deleting" something
another client's next add would re-create under a new id anyway.

Known limitation: only dict nesting is flattened into per-field cells. A
list value (e.g. a color grade's `nodes` array) is one atomic cell — two
concurrent edits to two different elements of the same list resolve as one
whole-list last-writer-wins, not a per-element merge. That's an acceptable
simplification for a *live, pre-commit* editing layer whose only job is to
produce a normal commit when the user saves; the real per-clip/per-field
merge for actual branch merges already lives in `vit.merge.three_way`.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

from ..merge.three_way import _denormalize_domain, _normalize_domain
from ..timeline.store import DOMAIN_FILES, DomainFiles

Timestamp = Tuple[int, str]  # (lamport_counter, client_id)
Path = Tuple[str, ...]

_EXISTS = "__exists__"
_GENESIS: Timestamp = (0, "")  # any real local edit (counter >= 1) outranks this


@dataclass
class Cell:
    value: object
    timestamp: Timestamp


def _flatten(prefix: Path, node: object) -> List[Tuple[Path, object]]:
    """Recursively flatten a normalized domain dict into (path, leaf) pairs.

    A non-empty dict recurses; anything else — including an empty dict
    (nothing to recurse into, but still a real value worth keeping, e.g. a
    clip's unset `transform: {}`) and lists — is a leaf value.
    """
    if isinstance(node, dict) and node:
        pairs: List[Tuple[Path, object]] = []
        for key, value in node.items():
            pairs.extend(_flatten(prefix + (str(key),), value))
        return pairs
    return [(prefix, node)]


def _assign(root: dict, path: Path, value: object) -> None:
    node = root
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value


class CRDTDoc:
    """One live document: every domain, flattened into LWW cells."""

    def __init__(self, client_id: str):
        self.client_id = client_id
        self.counter = 0
        self.cells: Dict[Path, Cell] = {}

    # ── Seeding ──────────────────────────────────────────────────────────

    def load_from_files(self, files: DomainFiles) -> None:
        """Seed every cell from on-disk state, at a genesis timestamp any
        real local edit will naturally outrank."""
        self.cells = {}
        for domain in DOMAIN_FILES:
            normalized = _normalize_domain(domain, files.get(domain, {}))
            if not normalized:
                # A wholly empty domain needs no cell: snapshot() already
                # defaults an untouched domain to {}, and a cell at the bare
                # domain-root path (length 1) can't be reconstructed by
                # _assign, which always expects at least one field below it.
                continue
            for path, value in _flatten((domain,), normalized):
                self.cells[path] = Cell(value=value, timestamp=_GENESIS)

    # ── Local edits ──────────────────────────────────────────────────────

    def apply_local(self, path: Path, value: object) -> dict:
        """Record a local edit; returns the wire update to broadcast."""
        self.counter += 1
        ts: Timestamp = (self.counter, self.client_id)
        self.cells[path] = Cell(value=value, timestamp=ts)
        return {"path": list(path), "value": value, "timestamp": list(ts)}

    def delete_item(self, item_path: Path) -> dict:
        """Mark an item (a clip, a track, ...) deleted. See module docstring
        for why this is a dedicated tombstone cell, not just removing fields."""
        return self.apply_local(item_path + (_EXISTS,), False)

    # ── Remote updates ───────────────────────────────────────────────────

    def apply_remote(self, update: dict) -> bool:
        """Merge one remote cell update. Returns True if it actually changed
        this doc's state — a caller uses that to decide whether to
        re-render / rebroadcast. Applying the same update twice, or an
        update that's already stale, is a safe no-op (idempotence)."""
        path = tuple(update["path"])
        ts: Timestamp = tuple(update["timestamp"])  # type: ignore[assignment]
        current = self.cells.get(path)
        if current is not None and current.timestamp >= ts:
            return False
        self.cells[path] = Cell(value=update["value"], timestamp=ts)
        self.counter = max(self.counter, ts[0])
        return True

    def merge_doc(self, other: "CRDTDoc") -> None:
        """Merge another whole document into this one, cell by cell —
        used when reconciling two replicas directly (e.g. tests), not on
        the per-update wire path."""
        for path, cell in other.cells.items():
            current = self.cells.get(path)
            if current is None or cell.timestamp > current.timestamp:
                self.cells[path] = Cell(value=cell.value, timestamp=cell.timestamp)
        self.counter = max(self.counter, other.counter)

    # ── Reading ──────────────────────────────────────────────────────────

    def snapshot(self) -> DomainFiles:
        """Current state as plain domain files, ready for
        `TimelineStore.write_files`."""
        deleted_items = {
            path[:-1] for path, cell in self.cells.items()
            if path and path[-1] == _EXISTS and cell.value is False
        }
        by_domain: Dict[str, dict] = {}
        for path, cell in self.cells.items():
            if not path or path[-1] == _EXISTS:
                continue
            if any(path[: len(item_path)] == item_path for item_path in deleted_items):
                continue
            domain = path[0]
            _assign(by_domain.setdefault(domain, {}), path[1:], cell.value)
        return {
            domain: _denormalize_domain(domain, by_domain.get(domain, {}))
            for domain in DOMAIN_FILES
        }
