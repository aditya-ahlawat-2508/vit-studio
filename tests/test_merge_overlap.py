"""Overlap between DIFFERENT clip ids, added independently on two branches.

Id-keyed field merging never sees this on its own — two freshly-added ids
just both get added. Regression coverage for the reported bug: `adi_codes`
adds Sunset_Beach to V1 @ 16:00 (5s); `anu_codes` independently adds
Forest_Drone to the same track at the same time. The branch-status list must
report a conflict, not "no conflicts", and the merge must not go through
silently with two clips physically occupying the same seconds of track.
"""

import pytest

from tests.helpers import clip, clip_ids, commit_all, write_cuts
from vit.merge import CONFLICTS, MERGED, perform_merge, preview_merge
from vit.merge.service import TIMELINE_OVERLAP
from vit.timeline import read_json, write_json


def _diverge(project, ours_items, theirs_items):
    project.repo.create_branch("anu_codes")
    write_cuts(project, theirs_items)
    commit_all(project, "anu edit")
    project.repo.checkout("main")
    write_cuts(project, ours_items)
    commit_all(project, "adi edit")


def test_independent_clips_added_to_same_range_are_reported_as_conflict(project):
    sunset = clip("sunset_beach", 384, length=120)   # V1 @ 16:00-21:00 (24fps)
    forest = clip("forest_drone", 384, length=120)    # same track, same range
    _diverge(project, [clip("a", 0), sunset], [clip("a", 0), forest])

    preview = preview_merge(project, "anu_codes")

    overlap = [c for c in preview.conflicts if c["category"] == TIMELINE_OVERLAP]
    assert len(overlap) == 1
    assert overlap[0]["time_range"]["start_tc"] == "00:00:16:00"
    assert {overlap[0]["clip_a"]["id"], overlap[0]["clip_b"]["id"]} == {"sunset_beach", "forest_drone"}


def test_merge_blocks_on_unresolved_overlap_instead_of_silently_combining(project):
    sunset = clip("sunset_beach", 384, length=120)
    forest = clip("forest_drone", 384, length=120)
    _diverge(project, [clip("a", 0), sunset], [clip("a", 0), forest])

    outcome = perform_merge(project, "anu_codes")

    assert outcome.status == CONFLICTS
    assert outcome.conflicts[0]["category"] == TIMELINE_OVERLAP
    # Nothing committed — both clips do NOT silently end up overlapping on disk.
    assert clip_ids(project) == ["a", "sunset_beach"]


def test_keep_a_resolution_drops_the_other_clip(project):
    sunset = clip("sunset_beach", 384, length=120)
    forest = clip("forest_drone", 384, length=120)
    _diverge(project, [clip("a", 0), sunset], [clip("a", 0), forest])

    outcome = perform_merge(project, "anu_codes")
    conflict = outcome.conflicts[0]
    kept_id = conflict["clip_a"]["id"]

    outcome = perform_merge(project, "anu_codes", {conflict["path"]: {"op": "keep_a"}})
    assert outcome.status == MERGED
    assert set(clip_ids(project)) == {"a", kept_id}


def test_keep_both_back_to_back_resolution_ripples_the_track(project):
    sunset = clip("sunset_beach", 384, length=120)     # 384-504
    forest = clip("forest_drone", 384, length=120)      # 384-504, same range
    later = clip("later", 504, length=48)                # right after, on the same track
    _diverge(project, [clip("a", 0), sunset, later], [clip("a", 0), forest])

    outcome = perform_merge(project, "anu_codes")
    conflict = outcome.conflicts[0]
    path = conflict["path"]
    a_id, b_id = conflict["clip_a"]["id"], conflict["clip_b"]["id"]
    order = "a_first" if a_id == "sunset_beach" else "b_first"

    outcome = perform_merge(project, "anu_codes", {path: {"op": "keep_both", "order": order}})
    assert outcome.status == MERGED

    cuts = read_json(project.store.path("cuts"))
    items = {i["id"]: i for t in cuts["video_tracks"] for i in t["items"]}
    assert items["sunset_beach"]["record_start_frame"] == 384
    assert items["sunset_beach"]["record_end_frame"] == 504
    assert items["forest_drone"]["record_start_frame"] == 504
    assert items["forest_drone"]["record_end_frame"] == 624
    # "later" started at 504 (>= the insertion point) -> rippled forward by 120 frames.
    assert items["later"]["record_start_frame"] == 624
    assert items["later"]["record_end_frame"] == 672


def _audio_clip(clip_id, media_ref, start, length=120):
    return {"id": clip_id, "media_ref": media_ref, "start_frame": start, "end_frame": start + length,
            "volume": 0.0, "pan": 0.0}


def test_keep_both_back_to_back_ripples_linked_audio_to_stay_in_sync(project):
    """Regression test for the reported bug: choosing "keep both" for an
    overlap conflict rippled the VIDEO track correctly but left each clip's
    own linked audio behind at its old position — video and audio fell out
    of sync exactly where the app's own validation would then complain about
    it. Audio must follow its video clip to the new position, and any other
    audio clip already past the insertion point must ripple too, same as
    the video track does."""
    sunset = clip("sunset_beach", 384, length=120, media_ref="sha256:sunset")
    forest = clip("forest_drone", 384, length=120, media_ref="sha256:forest")
    later = clip("later", 504, length=48, media_ref="sha256:later")
    _diverge(project, [clip("a", 0), sunset, later], [clip("a", 0), forest])

    # Linked audio for every clip, at exactly its video's original position —
    # written on top of whichever branch ends up "ours" after checkout below.
    write_json(project.store.path("audio"), {"audio_tracks": [{"index": 1, "items": [
        _audio_clip("a_sunset", "sha256:sunset", 384, 120),
        _audio_clip("a_later", "sha256:later", 504, 48),
    ]}]})
    commit_all(project, "audio for adi's clips")

    outcome = perform_merge(project, "anu_codes")
    conflict = outcome.conflicts[0]
    path = conflict["path"]
    a_id, b_id = conflict["clip_a"]["id"], conflict["clip_b"]["id"]
    order = "a_first" if a_id == "sunset_beach" else "b_first"

    outcome = perform_merge(project, "anu_codes", {path: {"op": "keep_both", "order": order}})
    assert outcome.status == MERGED

    cuts = read_json(project.store.path("cuts"))
    video = {i["id"]: i for t in cuts["video_tracks"] for i in t["items"]}
    audio = read_json(project.store.path("audio"))
    sound = {i["id"]: i for t in audio["audio_tracks"] for i in t["items"]}

    # sunset stayed put (first); forest followed it to 504-624 (second);
    # "later" (unrelated video, further down the track) rippled to 624-672.
    assert (video["sunset_beach"]["record_start_frame"], video["sunset_beach"]["record_end_frame"]) == (384, 504)
    assert (video["forest_drone"]["record_start_frame"], video["forest_drone"]["record_end_frame"]) == (504, 624)
    assert (video["later"]["record_start_frame"], video["later"]["record_end_frame"]) == (624, 672)

    # Audio follows its own video exactly — sync preserved, not just flagged.
    assert (sound["a_sunset"]["start_frame"], sound["a_sunset"]["end_frame"]) == (384, 504)
    assert (sound["a_later"]["start_frame"], sound["a_later"]["end_frame"]) == (624, 672)


def test_keep_both_new_track_resolution_moves_the_second_clip(project):
    sunset = clip("sunset_beach", 384, length=120)
    forest = clip("forest_drone", 384, length=120)
    _diverge(project, [clip("a", 0), sunset], [clip("a", 0), forest])

    outcome = perform_merge(project, "anu_codes")
    conflict = outcome.conflicts[0]
    path = conflict["path"]
    a_id, b_id = conflict["clip_a"]["id"], conflict["clip_b"]["id"]
    order = "a_first" if a_id == "sunset_beach" else "b_first"
    moved_id = b_id if order == "a_first" else a_id

    outcome = perform_merge(project, "anu_codes", {path: {"op": "keep_both_new_track", "order": order}})
    assert outcome.status == MERGED

    cuts = read_json(project.store.path("cuts"))
    by_track = {t["index"]: [i["id"] for i in t["items"]] for t in cuts["video_tracks"]}
    assert moved_id not in by_track[1]
    assert moved_id in by_track[2]


def test_validation_and_merge_share_one_overlap_definition():
    from vit.validation import _find_overlapping_pairs as validation_pairs
    from vit.merge.service import _overlap_conflicts

    track = {"index": 1, "items": [
        {"id": "x", "name": "X", "record_start_frame": 0, "record_end_frame": 100},
        {"id": "y", "name": "Y", "record_start_frame": 50, "record_end_frame": 150},
    ]}
    pairs = validation_pairs(track)
    assert len(pairs) == 1

    conflicts = _overlap_conflicts({"video_tracks": [track]}, fps=24.0)
    assert len(conflicts) == 1
    assert conflicts[0]["clip_a"]["id"] == pairs[0][0]["id"]
    assert conflicts[0]["clip_b"]["id"] == pairs[0][1]["id"]
