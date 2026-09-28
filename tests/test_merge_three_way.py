"""Clip-level three-way merge of domain files (pure, no git)."""

from vit.merge import three_way_merge_domains


def _clip(clip_id, start, end, track=1, **extra):
    item = {
        "id": clip_id,
        "name": f"{clip_id}.mov",
        "media_ref": f"sha256:{clip_id}",
        "record_start_frame": start,
        "record_end_frame": end,
        "source_start_frame": 0,
        "source_end_frame": end - start,
        "track_index": track,
        "transform": {"Opacity": 100.0, "ZoomX": 1.0},
    }
    item.update(extra)
    return item


def _cuts(*items, tracks=1):
    video_tracks = [{"index": i, "items": []} for i in range(1, tracks + 1)]
    for item in items:
        video_tracks[item["track_index"] - 1]["items"].append(item)
    return {"video_tracks": video_tracks}


def test_three_way_merge_combines_clips_added_on_both_branches():
    base = {"cuts": _cuts(_clip("a", 0, 100))}
    ours = {"cuts": _cuts(_clip("a", 0, 100), _clip("b", 100, 200))}
    theirs = {"cuts": _cuts(_clip("a", 0, 100), _clip("c", 200, 300))}

    merged, conflicts = three_way_merge_domains(base, ours, theirs)

    assert conflicts == []
    ids = [i["id"] for i in merged["cuts"]["video_tracks"][0]["items"]]
    assert ids == ["a", "b", "c"]


def test_three_way_merge_combines_different_fields_of_same_clip():
    base = {"cuts": _cuts(_clip("a", 0, 100))}
    ours = {"cuts": _cuts(_clip("a", 0, 80))}
    theirs_clip = _clip("a", 0, 100)
    theirs_clip["transform"]["ZoomX"] = 1.5
    theirs = {"cuts": _cuts(theirs_clip)}

    merged, conflicts = three_way_merge_domains(base, ours, theirs)

    assert conflicts == []
    item = merged["cuts"]["video_tracks"][0]["items"][0]
    assert item["record_end_frame"] == 80
    assert item["transform"]["ZoomX"] == 1.5


def test_three_way_merge_reports_and_resolves_same_field_conflict():
    base = {"color": {"grades": {"a": {"nodes": [{"saturation": 1.0}]}}}}
    ours = {"color": {"grades": {"a": {"nodes": [{"saturation": 1.4}]}}}}
    theirs = {"color": {"grades": {"a": {"nodes": [{"saturation": 0.2}]}}}}

    _, conflicts = three_way_merge_domains(base, ours, theirs)
    assert len(conflicts) == 1
    assert conflicts[0]["path"] == "color/grades/a/nodes"
    assert conflicts[0]["ours"] == [{"saturation": 1.4}]
    assert conflicts[0]["theirs"] == [{"saturation": 0.2}]

    merged, conflicts = three_way_merge_domains(
        base, ours, theirs, resolutions={"color/grades/a/nodes": "theirs"}
    )
    assert conflicts == []
    assert merged["color"]["grades"]["a"]["nodes"] == [{"saturation": 0.2}]


def test_three_way_merge_delete_vs_modify_is_conflict():
    base = {"cuts": _cuts(_clip("a", 0, 100))}
    ours = {"cuts": _cuts()}
    theirs = {"cuts": _cuts(_clip("a", 0, 50))}

    _, conflicts = three_way_merge_domains(base, ours, theirs)

    assert [c["path"] for c in conflicts] == ["cuts/video_tracks/a"]
    assert conflicts[0]["ours"] is None


def test_three_way_merge_deleted_track_is_not_resurrected_by_unrelated_edit():
    # base: 3 video tracks. ours deletes (empty) track 3. theirs, unrelated,
    # adds a clip to track 2 — track 3 must stay gone, not reappear because
    # theirs still has 3 tracks.
    base = {"cuts": _cuts(_clip("a", 0, 100, track=1), tracks=3)}
    ours = {"cuts": _cuts(_clip("a", 0, 100, track=1), tracks=2)}
    theirs = {"cuts": _cuts(_clip("a", 0, 100, track=1), _clip("b", 0, 50, track=2), tracks=3)}

    merged, conflicts = three_way_merge_domains(base, ours, theirs)

    assert conflicts == []
    indices = [t["index"] for t in merged["cuts"]["video_tracks"]]
    assert indices == [1, 2]
    track2_ids = [i["id"] for i in merged["cuts"]["video_tracks"][1]["items"]]
    assert track2_ids == ["b"]


def test_three_way_merge_empty_track_deleted_on_both_sides_stays_gone():
    base = {"cuts": _cuts(_clip("a", 0, 100, track=1), tracks=2)}
    ours = {"cuts": _cuts(_clip("a", 0, 100, track=1), tracks=1)}
    theirs = {"cuts": _cuts(_clip("a", 0, 100, track=1), tracks=1)}

    merged, conflicts = three_way_merge_domains(base, ours, theirs)

    assert conflicts == []
    assert [t["index"] for t in merged["cuts"]["video_tracks"]] == [1]


def test_three_way_merge_item_added_to_a_deleted_track_keeps_the_item():
    # ours deletes track 2 (empty); theirs, on that same now-deleted track,
    # adds a clip. The item merge sees a clean "added on theirs" (ours never
    # touched item "b"), so it's kept — the track marker is revived rather
    # than the clip being silently dropped.
    base = {"cuts": _cuts(_clip("a", 0, 100, track=1), tracks=2)}
    ours = {"cuts": _cuts(_clip("a", 0, 100, track=1), tracks=1)}
    theirs = {"cuts": _cuts(_clip("a", 0, 100, track=1), _clip("b", 0, 50, track=2), tracks=2)}

    merged, conflicts = three_way_merge_domains(base, ours, theirs)

    assert conflicts == []
    track2_ids = [i["id"] for i in merged["cuts"]["video_tracks"][1]["items"]]
    assert track2_ids == ["b"]


def test_three_way_merge_manual_override_resolution():
    base = {"color": {"grades": {"a": {"nodes": [{"saturation": 1.0}]}}}}
    ours = {"color": {"grades": {"a": {"nodes": [{"saturation": 1.4}]}}}}
    theirs = {"color": {"grades": {"a": {"nodes": [{"saturation": 0.2}]}}}}

    merged, conflicts = three_way_merge_domains(
        base, ours, theirs,
        resolutions={"color/grades/a/nodes": {"value": [{"saturation": 0.9}]}},
    )

    assert conflicts == []
    assert merged["color"]["grades"]["a"]["nodes"] == [{"saturation": 0.9}]


def test_three_way_merge_conflict_carries_time_range():
    base = {
        "metadata": {"frame_rate": 24.0},
        "cuts": _cuts(_clip("a", 240, 480, source_end_frame=999)),
    }
    ours_clip = _clip("a", 240, 500, source_end_frame=999)
    theirs_clip = _clip("a", 240, 460, source_end_frame=999)
    ours = {"metadata": {"frame_rate": 24.0}, "cuts": _cuts(ours_clip)}
    theirs = {"metadata": {"frame_rate": 24.0}, "cuts": _cuts(theirs_clip)}

    _, conflicts = three_way_merge_domains(base, ours, theirs)

    cuts_conflicts = [c for c in conflicts if c["domain"] == "cuts"]
    assert len(cuts_conflicts) == 1
    tr = cuts_conflicts[0]["time_range"]
    assert tr["start_frame"] == 240
    assert tr["start_tc"] == "00:00:10:00"
    # end_frame comes from whichever side (ours here) the clip lookup hits first.
    assert tr["end_frame"] in (500, 460)


def test_three_way_merge_keep_both_places_clips_back_to_back_and_ripples_track():
    # base: one 100-frame clip. ours trims its end to 80; theirs independently
    # extends it to 130 -> both changed record_end_frame differently -> conflict.
    base_clip = _clip("a", 0, 100, source_end_frame=999)
    ours_clip = _clip("a", 0, 80, source_end_frame=999)
    theirs_clip = _clip("a", 0, 130, source_end_frame=999)
    later_clip = _clip("later", 100, 150)  # sits right after "a" on the same track

    base = {"cuts": _cuts(base_clip, later_clip)}
    ours = {"cuts": _cuts(ours_clip, later_clip)}
    theirs = {"cuts": _cuts(theirs_clip, later_clip)}

    _, conflicts = three_way_merge_domains(base, ours, theirs)
    cuts_conflicts = [c for c in conflicts if c["domain"] == "cuts"]
    assert len(cuts_conflicts) == 1
    path = cuts_conflicts[0]["path"]
    # Resolve at the clip level (not the leaf field) so keep_both sees whole clips.
    clip_path = "/".join(path.split("/")[:3])

    merged, conflicts = three_way_merge_domains(
        base, ours, theirs, resolutions={clip_path: {"op": "keep_both", "order": "ours_first"}}
    )

    assert conflicts == []
    items = {i["id"]: i for i in merged["cuts"]["video_tracks"][0]["items"]}
    assert items["a"]["record_start_frame"] == 0
    assert items["a"]["record_end_frame"] == 80         # ours, unchanged
    assert items["a__b"]["record_start_frame"] == 80     # placed right after "a"
    assert items["a__b"]["record_end_frame"] == 210      # theirs' own 130-frame duration
    # "later" started at 100, which is >= the insertion point (80) -> rippled forward
    # by the inserted clip's duration (130 frames).
    assert items["later"]["record_start_frame"] == 230
    assert items["later"]["record_end_frame"] == 280


def test_three_way_merge_keeps_audio_tracks_and_markers_shape():
    base = {
        "audio": {"audio_tracks": [{"index": 1, "items": []}, {"index": 2, "items": []}]},
        "markers": {"markers": [{"frame": 10, "name": "x"}]},
    }
    ours = {
        "audio": {"audio_tracks": [
            {"index": 1, "items": [{"id": "a1", "media_ref": "m", "start_frame": 0,
                                    "end_frame": 10, "volume": 0.0, "pan": 0.0}]},
            {"index": 2, "items": []},
        ]},
        "markers": {"markers": [{"frame": 10, "name": "x"}, {"frame": 5, "name": "y"}]},
    }
    theirs = base

    merged, conflicts = three_way_merge_domains(base, ours, theirs)

    assert conflicts == []
    assert merged["audio"] == ours["audio"]
    assert [m["frame"] for m in merged["markers"]["markers"]] == [5, 10]
