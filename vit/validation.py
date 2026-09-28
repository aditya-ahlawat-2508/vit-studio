"""Timeline validation — orphaned refs, overlaps, audio/video sync, track counts.

Runs after every merge (and on every edit in Vit Studio). All checks are pure:
they take domain files (as returned by `TimelineStore.read_all`) and return
issues; nothing here touches disk or git.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Set, Tuple

from .timeline.store import DomainFiles


@dataclass
class ValidationIssue:
    severity: str  # "error" or "warning"
    category: str  # "orphaned_ref", "overlap", "sync", "track_count", "speed_duration", "speed_sync"
    message: str
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:
        icon = "ERROR" if self.severity == "error" else "WARN"
        return f"[{icon}] {self.category}: {self.message}"

    def to_dict(self) -> dict:
        return {"severity": self.severity, "category": self.category,
                "message": self.message, "details": self.details}


def validate(files: DomainFiles) -> List[ValidationIssue]:
    """Run every check on a timeline. An empty list means the timeline is valid."""
    cuts = files.get("cuts", {})
    color = files.get("color", {})
    audio = files.get("audio", {})
    metadata = files.get("metadata", {})
    effects = files.get("effects", {})

    video_ids = _video_item_ids(cuts)
    return [
        *_check_orphaned_refs(color.get("grades", {}), video_ids, "Color grade", "color"),
        *_check_orphaned_refs(effects.get("clip_effects", {}), video_ids, "Effect", "effects"),
        *_check_overlapping_clips(cuts),
        *_check_audio_video_sync(cuts, audio),
        *_check_track_count_consistency(cuts, audio, metadata),
        *_check_speed_duration_consistency(cuts),
        *_check_speed_sync(cuts, audio),
    ]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _video_items(cuts: dict) -> Iterator[dict]:
    for track in cuts.get("video_tracks", []):
        yield from track.get("items", [])


def _video_item_ids(cuts: dict) -> Set[str]:
    return {item["id"] for item in _video_items(cuts) if item.get("id")}


def _by_media_ref(tracks: list) -> Dict[str, List[dict]]:
    groups: Dict[str, List[dict]] = {}
    for track in tracks:
        for item in track.get("items", []):
            if item.get("media_ref"):
                groups.setdefault(item["media_ref"], []).append(item)
    return groups


def _linked_pairs(cuts: dict, audio: dict) -> Iterator[Tuple[str, dict, dict]]:
    """(media_ref, video_item, audio_item) for linked clips.

    Several clips can share a media_ref (a clip split in two), so the n-th
    audio clip of a media is paired with the n-th video clip of that media.
    """
    video_by_ref = _by_media_ref(cuts.get("video_tracks", []))
    for ref, audio_items in _by_media_ref(audio.get("audio_tracks", [])).items():
        for video_item, audio_item in zip(video_by_ref.get(ref, []), audio_items):
            yield ref, video_item, audio_item


# ── Checks ──────────────────────────────────────────────────────────────────

def _check_orphaned_refs(entries: dict, video_ids: Set[str], label: str, domain: str) -> List[ValidationIssue]:
    """Per-clip entries (grades, effects) whose clip no longer exists."""
    return [
        ValidationIssue(
            severity="error",
            category="orphaned_ref",
            message=f"{label} references deleted clip '{item_id}'",
            details={"item_id": item_id, "domain": domain},
        )
        for item_id in entries
        if item_id not in video_ids
    ]


def _find_overlapping_pairs(track: dict) -> List[Tuple[dict, dict]]:
    """Adjacent-pair overlaps on one track, sorted by start frame.

    Shared by post-edit validation (`_check_overlapping_clips`) and the
    merge-preview overlap check in `vit/merge/service.py`, so there is one
    definition of "overlap" rather than two that could quietly drift apart.
    """
    items = sorted(track.get("items", []), key=lambda x: x.get("record_start_frame", 0))
    pairs = []
    for current, next_item in zip(items, items[1:]):
        if current.get("record_end_frame", 0) > next_item.get("record_start_frame", 0):
            pairs.append((current, next_item))
    return pairs


def _check_overlapping_clips(cuts: dict) -> List[ValidationIssue]:
    """Clips that overlap on the same track."""
    issues = []
    for track in cuts.get("video_tracks", []):
        track_idx = track.get("index", "?")
        for current, next_item in _find_overlapping_pairs(track):
            current_end = current.get("record_end_frame", 0)
            next_start = next_item.get("record_start_frame", 0)
            issues.append(ValidationIssue(
                severity="error",
                category="overlap",
                message=(
                    f"Clips overlap on V{track_idx}: "
                    f"'{current.get('name', '?')}' (ends frame {current_end}) "
                    f"overlaps '{next_item.get('name', '?')}' (starts frame {next_start})"
                ),
                details={"track": track_idx, "clip_a": current.get("id"), "clip_b": next_item.get("id")},
            ))
    return issues


def _check_audio_video_sync(cuts: dict, audio: dict) -> List[ValidationIssue]:
    """Linked audio and video clips should start and end on the same frames."""
    issues = []
    for ref, video_item, audio_item in _linked_pairs(cuts, audio):
        v_start = video_item.get("record_start_frame", 0)
        v_end = video_item.get("record_end_frame", 0)
        a_start = audio_item.get("start_frame", 0)
        a_end = audio_item.get("end_frame", 0)
        if v_start != a_start or v_end != a_end:
            issues.append(ValidationIssue(
                severity="warning",
                category="sync",
                message=(
                    f"Audio/video sync mismatch for media '{ref}': "
                    f"video [{v_start}-{v_end}] vs audio [{a_start}-{a_end}]"
                ),
                details={"media_ref": ref, "video_item": video_item.get("id"), "audio_item": audio_item.get("id")},
            ))
    return issues


def _check_track_count_consistency(cuts: dict, audio: dict, metadata: dict) -> List[ValidationIssue]:
    """Track counts in metadata.json should match the actual tracks."""
    issues = []
    track_count = metadata.get("track_count", {})
    for domain, actual, filename in (
        ("video", len(cuts.get("video_tracks", [])), "cuts.json"),
        ("audio", len(audio.get("audio_tracks", [])), "audio.json"),
    ):
        expected = track_count.get(domain, 0)
        if expected and actual != expected:
            issues.append(ValidationIssue(
                severity="warning",
                category="track_count",
                message=f"Metadata says {expected} {domain} tracks, but {filename} has {actual}",
                details={"expected": expected, "actual": actual, "domain": domain},
            ))
    return issues


def _check_speed_duration_consistency(cuts: dict) -> List[ValidationIssue]:
    """Retimed clips should have a record duration ≈ source duration / speed.

    Large mismatches suggest the speed metadata is stale after a merge.
    """
    issues = []
    for item in _video_items(cuts):
        pct = item.get("speed", {}).get("speed_percent", 100.0)
        if pct == 100.0 or pct <= 0:
            continue
        record_dur = item.get("record_end_frame", 0) - item.get("record_start_frame", 0)
        source_dur = item.get("source_end_frame", 0) - item.get("source_start_frame", 0)
        if source_dur <= 0 or record_dur <= 0:
            continue

        expected_record = source_dur / (pct / 100.0)
        # Allow 10% tolerance for rounding and frame-boundary effects
        if abs(record_dur - expected_record) > max(expected_record * 0.1, 2):
            issues.append(ValidationIssue(
                severity="warning",
                category="speed_duration",
                message=(
                    f"Clip '{item.get('name', '?')}' has {pct}% speed but "
                    f"record duration ({record_dur}f) doesn't match expected "
                    f"({expected_record:.0f}f) — may be stale after merge"
                ),
                details={
                    "item_id": item.get("id"),
                    "speed_percent": pct,
                    "record_duration": record_dur,
                    "expected_duration": round(expected_record),
                },
            ))
    return issues


def _check_speed_sync(cuts: dict, audio: dict) -> List[ValidationIssue]:
    """Linked video and audio clips should play at the same speed."""
    issues = []
    for ref, video_item, audio_item in _linked_pairs(cuts, audio):
        v_speed = video_item.get("speed", {}).get("speed_percent", 100.0)
        a_speed = audio_item.get("speed", {}).get("speed_percent", 100.0)
        if v_speed != a_speed:
            issues.append(ValidationIssue(
                severity="warning",
                category="speed_sync",
                message=f"Speed mismatch for linked media '{ref}': video={v_speed}% vs audio={a_speed}%",
                details={
                    "media_ref": ref,
                    "video_item": video_item.get("id"),
                    "audio_item": audio_item.get("id"),
                    "video_speed": v_speed,
                    "audio_speed": a_speed,
                },
            ))
    return issues
