"""Merge orchestration: git records the merge, vit supplies the merged timeline."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..diff import _frames_to_timecode
from ..git import GitError
from ..project import VitProject
from ..timeline.store import DOMAIN_FILES, DomainFiles
from ..validation import _find_overlapping_pairs
from .suggest import AUTO_APPLY_THRESHOLD, Suggestion, suggest_resolutions
from .three_way import Conflict, three_way_merge_domains

MERGED = "merged"
CONFLICTS = "conflicts"
UP_TO_DATE = "up_to_date"
TIMELINE_OVERLAP = "timeline_overlap"


@dataclass
class MergeOutcome:
    """Result of perform_merge.

    status is MERGED, CONFLICTS (nothing was changed — ask the user and call
    again with resolutions) or UP_TO_DATE.
    """

    status: str
    conflicts: List[Conflict] = field(default_factory=list)
    commit: str = ""
    git_text_conflicts: List[str] = field(default_factory=list)
    base_files: DomainFiles = field(default_factory=dict)
    ours_files: DomainFiles = field(default_factory=dict)
    theirs_files: DomainFiles = field(default_factory=dict)
    merged_files: DomainFiles = field(default_factory=dict)


@dataclass
class MergePreview:
    """What a merge of `branch` would do, computed without touching the repo.

    `conflicts` is what's left AFTER auto-apply — what a human will actually
    be asked to decide. `auto_applied` is what a suggestion source resolved
    on its own (confidence >= AUTO_APPLY_THRESHOLD); every entry there is
    still fully visible and reversible in the UI, never silent. `suggestions`
    carries hints (below-threshold or category-excluded) for the conflicts
    that do still need a human, keyed the same way.
    """

    base: Optional[str]
    base_files: DomainFiles
    ours_files: DomainFiles
    theirs_files: DomainFiles
    conflicts: List[Conflict]
    git_text_conflicts: List[str]
    up_to_date: bool
    auto_applied: Dict[str, Suggestion] = field(default_factory=dict)
    suggestions: Dict[str, Suggestion] = field(default_factory=dict)


def _overlap_conflicts(merged_cuts: dict, fps: float) -> List[Conflict]:
    """Two DIFFERENT clip ids landing on the same time range of the same track.

    Id-keyed field merging never sees this: two freshly-added ids just both
    get added, since `_merge_value` only ever compares values at the *same*
    key. This runs on the tentative merged result — after field conflicts are
    resolved — because the overlap only exists once both branches' clips are
    actually combined; neither branch alone is wrong.
    """
    conflicts: List[Conflict] = []
    for track in merged_cuts.get("video_tracks", []):
        for clip_a, clip_b in _find_overlapping_pairs(track):
            start = max(clip_a["record_start_frame"], clip_b["record_start_frame"])
            end = min(clip_a["record_end_frame"], clip_b["record_end_frame"])
            conflicts.append({
                "path": f"cuts/video_tracks/{track.get('index')}/overlap/{clip_a['id']}~{clip_b['id']}",
                "domain": "cuts",
                "category": TIMELINE_OVERLAP,
                "track": track.get("index"),
                "clip_a": clip_a, "clip_b": clip_b,
                "base": None, "ours": None, "theirs": None,
                "time_range": {
                    "start_frame": start, "end_frame": end,
                    "start_tc": _frames_to_timecode(start, fps),
                    "end_tc": _frames_to_timecode(end, fps),
                },
            })
    return conflicts


def _apply_overlap_resolution(cuts: dict, conflict: Conflict, choice: dict) -> None:
    """Mutate `cuts` in place per the chosen resolution for one overlap conflict.

    Both clips are already fully present in the merge, so there's nothing to
    "pick" the way a field conflict does — only how to arrange (or drop) them.
    """
    track = next((t for t in cuts.get("video_tracks", []) if t.get("index") == conflict["track"]), None)
    if track is None:
        return
    a_id, b_id = conflict["clip_a"]["id"], conflict["clip_b"]["id"]
    op = choice.get("op")

    if op == "keep_a":
        track["items"] = [i for i in track["items"] if i.get("id") != b_id]
    elif op == "keep_b":
        track["items"] = [i for i in track["items"] if i.get("id") != a_id]
    elif op == "keep_both":
        order = choice.get("order", "a_first")
        first_id, second_id = (a_id, b_id) if order == "a_first" else (b_id, a_id)
        first = next(i for i in track["items"] if i.get("id") == first_id)
        second = next(i for i in track["items"] if i.get("id") == second_id)
        duration = second["record_end_frame"] - second["record_start_frame"]
        gap_start = first["record_end_frame"]
        second["record_start_frame"] = gap_start
        second["record_end_frame"] = gap_start + duration
        for item in track["items"]:
            if item.get("id") in (first_id, second_id):
                continue
            if item.get("record_start_frame", 0) >= gap_start:
                item["record_start_frame"] += duration
                item["record_end_frame"] += duration
    elif op == "keep_both_new_track":
        order = choice.get("order", "a_first")
        move_id = b_id if order == "a_first" else a_id
        new_idx = max((t.get("index", 1) for t in cuts.get("video_tracks", [])), default=0) + 1
        target = next((t for t in cuts["video_tracks"] if t.get("index") == new_idx), None)
        if target is None:
            target = {"index": new_idx, "items": []}
            cuts["video_tracks"].append(target)
        moved = next(i for i in track["items"] if i.get("id") == move_id)
        track["items"] = [i for i in track["items"] if i.get("id") != move_id]
        target["items"].append(moved)


def _resolve_overlaps(merged_files: DomainFiles, resolutions: Dict[str, object], fps: float) -> List[Conflict]:
    """Apply any overlap resolutions the caller already supplied; return what's left."""
    cuts = merged_files.get("cuts", {})
    conflicts = _overlap_conflicts(cuts, fps)
    remaining = []
    for c in conflicts:
        choice = resolutions.get(c["path"])
        if isinstance(choice, dict) and choice.get("op") in ("keep_a", "keep_b", "keep_both", "keep_both_new_track"):
            _apply_overlap_resolution(cuts, c, choice)
        else:
            remaining.append(c)
    return remaining


def preview_merge(
    project: VitProject, branch: str, exclude_auto: Optional[set] = None,
) -> MergePreview:
    """Compare HEAD with `branch` against their merge base.

    Runs every conflict (field + timeline-overlap) through the suggestion
    pass: anything at or above AUTO_APPLY_THRESHOLD confidence is applied and
    reported in `auto_applied` instead of `conflicts`, so a human only ever
    sees what's actually still contested. `exclude_auto` lets a caller force
    specific paths to stay as normal conflicts even if a high-confidence
    suggestion exists for them — the "undo, let me choose" flow in the UI.
    """
    theirs_hash = project.repo.rev_parse(branch)
    if theirs_hash is None:
        raise ValueError(f"Unknown branch '{branch}'")
    exclude_auto = exclude_auto or set()
    base = project.repo.merge_base("HEAD", branch)
    base_f, ours_f, theirs_f = project.files_at(base), project.files_at("HEAD"), project.files_at(branch)

    merged, conflicts = three_way_merge_domains(base_f, ours_f, theirs_f)
    fps = merged.get("metadata", {}).get("frame_rate", 24.0)
    conflicts = conflicts + _overlap_conflicts(merged.get("cuts", {}), fps)

    suggestions = suggest_resolutions(conflicts)
    # Structural guard, not just a convention: timeline_overlap conflicts
    # never auto-apply, no matter what confidence any source (including a
    # network-backed one) reports. `keep_both` ripples the rest of the track —
    # too large a silent side effect for the auto-apply threshold alone to
    # gate; a source manually capping its own confidence isn't something we
    # can rely on once more than one source exists.
    category_by_path = {c["path"]: c.get("category", "field") for c in conflicts}
    auto_applied = {
        path: s for path, s in suggestions.items()
        if s.confidence >= AUTO_APPLY_THRESHOLD
        and path not in exclude_auto
        and category_by_path.get(path, "field") != TIMELINE_OVERLAP
    }
    if auto_applied:
        resolutions = {path: s.as_resolution() for path, s in auto_applied.items()}
        merged, conflicts = three_way_merge_domains(base_f, ours_f, theirs_f, resolutions)
        fps = merged.get("metadata", {}).get("frame_rate", 24.0)
        # Recompute: overlaps and hints for whatever's left, since auto-apply
        # could in principle surface a different set (cheap — pure functions
        # over the already-merged cuts domain).
        conflicts = conflicts + _overlap_conflicts(merged.get("cuts", {}), fps)
        suggestions = suggest_resolutions(conflicts)

    return MergePreview(
        base=base,
        base_files=base_f,
        ours_files=ours_f,
        theirs_files=theirs_f,
        conflicts=conflicts,
        git_text_conflicts=project.repo.merge_tree_conflicts("HEAD", branch) or [],
        up_to_date=base == theirs_hash,
        auto_applied=auto_applied,
        suggestions=suggestions,
    )


def perform_merge(
    project: VitProject,
    branch: str,
    resolutions: Optional[Dict[str, str]] = None,
    message: Optional[str] = None,
) -> MergeOutcome:
    """Merge `branch` into the current branch at clip/field granularity.

    git records the merge (a real two-parent commit); the content comes from
    three_way_merge_domains, so independent edits to the same JSON file combine
    instead of one side overwriting the other. If the same property changed
    differently on both sides, returns CONFLICTS without touching the repo —
    pass the user's choices back as `resolutions`.

    The working tree must be clean (auto-save first).
    """
    repo = project.repo
    theirs_hash = repo.rev_parse(branch)
    if theirs_hash is None:
        raise GitError(f"Unknown branch '{branch}'")
    base = repo.merge_base("HEAD", branch)
    if base == theirs_hash:
        return MergeOutcome(status=UP_TO_DATE)

    base_f, ours_f, theirs_f = project.files_at(base), project.files_at("HEAD"), project.files_at(branch)
    merged, conflicts = three_way_merge_domains(base_f, ours_f, theirs_f, resolutions)
    outcome = MergeOutcome(
        status=CONFLICTS, conflicts=conflicts,
        base_files=base_f, ours_files=ours_f, theirs_files=theirs_f, merged_files=merged,
    )
    if conflicts:
        return outcome

    # Field conflicts are clear, but two DIFFERENT clips from either branch can
    # still land on the same time range once actually combined — check (and
    # apply any resolutions for) that before committing anything.
    fps = merged.get("metadata", {}).get("frame_rate", 24.0)
    overlap_conflicts = _resolve_overlaps(merged, resolutions or {}, fps)
    if overlap_conflicts:
        outcome.conflicts = overlap_conflicts
        return outcome

    outcome.git_text_conflicts = repo.merge_tree_conflicts("HEAD", branch) or []
    current = repo.current_branch()
    _, output = repo.merge_no_commit(branch)
    if repo.rev_parse("MERGE_HEAD") is None:
        raise GitError(f"git could not start merging '{branch}': {output.strip()}")

    try:
        _write_merge_result(project, merged)
        outcome.commit = repo.commit(message or f"vit: merge '{branch}' into '{current}'")
    except Exception:
        repo.merge_abort()
        raise

    outcome.status = MERGED
    return outcome


def _write_merge_result(project: VitProject, merged: DomainFiles) -> None:
    """Replace git's (possibly conflicted) domain files with vit's merge and stage them."""
    project.store.write_files(merged)
    domain_paths = {DOMAIN_FILES[d] for d in merged if d in DOMAIN_FILES}
    outside = [p for p in project.repo.conflicted_files() if p not in domain_paths]
    if outside:
        raise GitError(f"Conflict outside the timeline needs manual resolution: {', '.join(outside)}")
    project.repo.add(sorted(domain_paths))
    remaining = project.repo.conflicted_files()
    if remaining:
        raise GitError(f"Unresolved conflicts: {', '.join(remaining)}")
