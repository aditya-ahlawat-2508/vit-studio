"""Clip-level three-way merge of domain files. Pure functions — no git, no disk.

A line-based text merge of cuts.json reports a conflict whenever both
branches touch nearby lines, e.g. two editors each adding a clip. Here lists of
clips and markers are first keyed by a stable id, then merged field by field,
so only the *same field changed differently on both sides* is a conflict.
"""

import copy
from typing import Dict, List, Optional, Tuple

from ..diff import _frames_to_timecode
from ..timeline.store import DomainFiles

Conflict = Dict[str, object]  # {path, domain, base, ours, theirs, time_range?}

# Sentinel for "key absent on this side" (distinct from a JSON null).
_MISSING = object()

# Marker key: a resolved-but-not-yet-unpacked "keep both" pair, consumed by
# _unkeyed_tracks. Never appears in a real clip/item, so it's safe as a flag.
_KEEP_BOTH = "__keep_both__"


# ── Normalisation: track lists ⇄ dicts keyed by stable ids ──────────────────

def _keyed_items(tracks: list, id_key: str, track_field: str) -> Dict[str, dict]:
    """Flatten track lists into {item_id: item}, remembering the track index."""
    items = {}
    for track in tracks:
        for item in track.get("items", []):
            entry = copy.deepcopy(item)
            entry[track_field] = track.get("index", 1)
            items[str(entry[id_key])] = entry
    return items


def _track_existence(tracks: list) -> Dict[str, bool]:
    """{track index: True} for every track in a raw track list, empty tracks included.

    Merged through the same base/ours/theirs machinery as clips, so a track
    deleted on one side and untouched on the other is a clean deletion, and a
    track deleted on one side but edited on the other is a real conflict —
    instead of being decided by comparing track counts.
    """
    return {str(t.get("index", 1)): True for t in tracks}


def _unkeyed_tracks(items: Dict[str, dict], track_field: str, start_key: str, end_key: str,
                    keep_field: bool, track_indices: Dict[str, bool]) -> list:
    """Rebuild a sorted track list from {item_id: item}.

    `track_indices` is the merged set of tracks that should exist (including
    empty ones); any index still referenced by a surviving item is kept too,
    as a safety net against an item outliving its track marker.

    Also the one place a `_KEEP_BOTH` marker (see `_resolve_keep_both`) gets
    unpacked: the pair's second clip is placed immediately after the first
    (a new id, `<id>__b`, since the pair shared one id going in), and every
    other item on that track starting at or after the insertion point ripples
    forward by the second clip's duration so nothing overlaps.
    """
    by_track: Dict[int, list] = {int(i): [] for i in track_indices}
    ripples: Dict[int, List[Tuple[int, int]]] = {}
    inserted_ids: Dict[int, set] = {}

    def _place(entry: dict, idx: int) -> None:
        if keep_field:
            entry[track_field] = idx
        else:
            entry.pop(track_field, None)
        by_track.setdefault(idx, []).append(entry)

    for item in items.values():
        if isinstance(item, dict) and _KEEP_BOTH in item:
            pair = item[_KEEP_BOTH]
            first, second = copy.deepcopy(pair["first"]), copy.deepcopy(pair["second"])
            idx = int(first.get(track_field, 1))
            gap_start = first.get(end_key, 0)
            duration = second.get(end_key, 0) - second.get(start_key, 0)
            second[start_key] = gap_start
            second[end_key] = gap_start + duration
            second["id"] = f"{second.get('id', first.get('id'))}__b"
            _place(first, idx)
            _place(second, idx)
            ripples.setdefault(idx, []).append((gap_start, duration))
            inserted_ids.setdefault(idx, set()).update({first.get("id"), second.get("id")})
            continue
        entry = copy.deepcopy(item)
        idx = int(entry.get(track_field, 1))
        if not keep_field:
            entry.pop(track_field, None)
        by_track.setdefault(idx, []).append(entry)

    for idx, track_ripples in ripples.items():
        keep = inserted_ids.get(idx, set())
        for gap_start, duration in track_ripples:
            for entry in by_track.get(idx, []):
                if entry.get("id") in keep:
                    continue
                if entry.get(start_key, 0) >= gap_start:
                    entry[start_key] = entry.get(start_key, 0) + duration
                    if end_key in entry:
                        entry[end_key] = entry[end_key] + duration

    return [
        {
            "index": idx,
            "items": sorted(by_track[idx], key=lambda i: (i.get(start_key, 0), str(i.get("id", "")))),
        }
        for idx in sorted(by_track)
    ]


def _normalize_domain(domain: str, data: dict) -> dict:
    """Turn a domain file into nested dicts keyed by stable ids.

    Clips are keyed by id, markers by frame; color grades and effects are
    already dicts keyed by clip id. Track *existence* (including empty
    tracks) is captured separately under `_tracks` so it merges through the
    same base/ours/theirs rules as everything else, rather than being decided
    afterwards by comparing track counts.
    """
    data = copy.deepcopy(data or {})
    if domain == "cuts":
        raw_tracks = data.get("video_tracks", [])
        data["video_tracks"] = _keyed_items(raw_tracks, "id", "track_index")
        data["_tracks"] = _track_existence(raw_tracks)
    elif domain == "audio":
        raw_tracks = data.get("audio_tracks", [])
        data["audio_tracks"] = _keyed_items(raw_tracks, "id", "_track")
        data["_tracks"] = _track_existence(raw_tracks)
    elif domain == "markers":
        data["markers"] = {str(m["frame"]): m for m in data.get("markers", [])}
    return data


def _denormalize_domain(domain: str, data: dict) -> dict:
    """Inverse of _normalize_domain."""
    data = copy.deepcopy(data)
    if domain == "cuts":
        track_indices = data.pop("_tracks", {})
        data["video_tracks"] = _unkeyed_tracks(
            data.get("video_tracks", {}), "track_index", "record_start_frame", "record_end_frame",
            True, track_indices,
        )
    elif domain == "audio":
        track_indices = data.pop("_tracks", {})
        data["audio_tracks"] = _unkeyed_tracks(
            data.get("audio_tracks", {}), "_track", "start_frame", "end_frame",
            False, track_indices,
        )
    elif domain == "markers":
        data["markers"] = sorted(data.get("markers", {}).values(), key=lambda m: m["frame"])
    return data


# ── Recursive value merge ───────────────────────────────────────────────────

def _resolve_keep_both(ours: dict, theirs: dict, choice: dict) -> dict:
    """Not a value — a structural marker consumed by `_unkeyed_tracks`, which
    splits it into two adjacent clips and ripples the rest of the track.
    Only meaningful where both sides are still whole clip dicts (the
    resolution path names the clip itself, e.g. `cuts/video_tracks/<id>`).
    """
    order = choice.get("order", "ours_first")
    first, second = (ours, theirs) if order == "ours_first" else (theirs, ours)
    return {_KEEP_BOTH: {"first": copy.deepcopy(first), "second": copy.deepcopy(second)}}


def _merge_value(base, ours, theirs, path: tuple, conflicts: List[Conflict],
                 resolutions: Dict[str, object]):
    """Recursive 3-way merge. Returns the merged value, or _MISSING (deleted)."""
    path_key = "/".join(str(p) for p in path)
    choice = resolutions.get(path_key)
    if isinstance(choice, dict) and choice.get("op") == "keep_both" \
            and isinstance(ours, dict) and isinstance(theirs, dict):
        return _resolve_keep_both(ours, theirs, choice)

    if ours == theirs:
        return ours
    if ours == base:
        return theirs
    if theirs == base:
        return ours
    if all(isinstance(v, dict) for v in (ours, theirs)) and (base is _MISSING or isinstance(base, dict)):
        base_d = base if isinstance(base, dict) else {}
        merged = {}
        for key in sorted(set(base_d) | set(ours) | set(theirs)):
            value = _merge_value(
                base_d.get(key, _MISSING), ours.get(key, _MISSING), theirs.get(key, _MISSING),
                path + (key,), conflicts, resolutions,
            )
            if value is not _MISSING:
                merged[key] = value
        return merged

    if isinstance(choice, dict) and "value" in choice:
        return choice["value"]  # manual override: an explicit value, not a side
    if choice == "ours":
        return ours
    if choice == "theirs":
        return theirs
    conflicts.append({
        "path": path_key,
        "domain": path[0],
        "base": None if base is _MISSING else base,
        "ours": None if ours is _MISSING else ours,
        "theirs": None if theirs is _MISSING else theirs,
    })
    return ours


def _clip_by_id(cuts_file: Optional[dict], clip_id: str) -> Optional[dict]:
    for track in (cuts_file or {}).get("video_tracks", []):
        for item in track.get("items", []):
            if str(item.get("id")) == clip_id:
                return item
    return None


def _attach_time_ranges(
    conflicts: List[Conflict],
    base_files: DomainFiles, ours_files: DomainFiles, theirs_files: DomainFiles,
) -> None:
    """Label every cuts-domain conflict with the timecode range it falls in.

    A conflict path looks like `cuts/video_tracks/<clip id>[/field]`; the clip
    itself (start/end frame) is looked up from whichever side still has it —
    a field-level conflict (e.g. only `record_end_frame` differs) doesn't
    carry the clip's frames in `ours`/`theirs` directly, so this re-fetches
    the whole clip rather than trying to read them off the conflict value.
    """
    fps = (
        (ours_files.get("metadata") or {}).get("frame_rate")
        or (theirs_files.get("metadata") or {}).get("frame_rate")
        or (base_files.get("metadata") or {}).get("frame_rate")
        or 24.0
    )
    for c in conflicts:
        if c["domain"] != "cuts":
            continue
        parts = c["path"].split("/")
        if len(parts) < 3 or parts[1] != "video_tracks":
            continue
        clip_id = parts[2]
        clip = (
            _clip_by_id(ours_files.get("cuts"), clip_id)
            or _clip_by_id(theirs_files.get("cuts"), clip_id)
            or _clip_by_id(base_files.get("cuts"), clip_id)
        )
        if clip and "record_start_frame" in clip and "record_end_frame" in clip:
            start, end = clip["record_start_frame"], clip["record_end_frame"]
            c["time_range"] = {
                "start_frame": start, "end_frame": end,
                "start_tc": _frames_to_timecode(start, fps),
                "end_tc": _frames_to_timecode(end, fps),
            }


def three_way_merge_domains(
    base_files: DomainFiles,
    ours_files: DomainFiles,
    theirs_files: DomainFiles,
    resolutions: Optional[Dict[str, object]] = None,
) -> Tuple[DomainFiles, List[Conflict]]:
    """Merge domain files at clip/field granularity.

    Clips are matched by id, markers by frame, grades by clip id; track
    existence (including empty tracks) is matched by index. Changes to
    different clips or tracks — or different fields of the same clip — combine
    cleanly. Only the same field changed differently on both sides is a
    conflict. Every cuts-domain conflict is labelled with the timecode range
    it falls in, so a caller can show "00:00:16 → 00:00:21" instead of a bare
    clip id.

    Args:
        resolutions: {conflict_path: "ours" | "theirs"
            | {"value": <override>}              — an explicit value, neither side
            | {"op": "keep_both", "order": "ours_first" | "theirs_first"}}
                                                   — cuts-domain only: place both
            clips back to back and ripple later clips on that track.

    Returns:
        (merged_files, conflicts). Each conflict is a dict with path, domain,
        base, ours, theirs, and — for cuts conflicts — time_range. Unresolved
        conflicts keep "ours" in merged_files.
    """
    resolutions = resolutions or {}
    merged_files: DomainFiles = {}
    conflicts: List[Conflict] = []
    for domain in sorted(set(base_files) | set(ours_files) | set(theirs_files)):
        base = _normalize_domain(domain, base_files.get(domain, {}))
        ours = _normalize_domain(domain, ours_files.get(domain, {}))
        theirs = _normalize_domain(domain, theirs_files.get(domain, {}))
        merged = _merge_value(base, ours, theirs, (domain,), conflicts, resolutions)
        if merged is _MISSING:
            merged = {}
        merged_files[domain] = _denormalize_domain(domain, merged)
    _attach_time_ranges(conflicts, base_files, ours_files, theirs_files)
    return merged_files, conflicts
