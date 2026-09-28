"""Pre-triage for merge conflicts: vit.merge.suggest."""

import json
from unittest.mock import patch

from tests.helpers import clip, commit_all, write_cuts
from vit.merge import preview_merge
from vit.merge.service import TIMELINE_OVERLAP
from vit.merge.suggest import (
    AUTO_APPLY_THRESHOLD,
    GEMINI_API_KEY_ENV,
    Suggestion,
    gemini_batch_source,
    heuristic_source,
    suggest_resolutions,
)


def _field_conflict(domain="color", base=None):
    return {"path": f"{domain}/grades/a/nodes", "domain": domain, "category": "field",
            "base": base, "ours": {"saturation": 1.4}, "theirs": {"saturation": 0.2}}


def _overlap_conflict(ref_a="sha256:a", ref_b="sha256:b"):
    return {
        "path": "cuts/video_tracks/1/overlap/x~y", "domain": "cuts", "category": TIMELINE_OVERLAP,
        "track": 1,
        "clip_a": {"id": "x", "media_ref": ref_a}, "clip_b": {"id": "y", "media_ref": ref_b},
        "time_range": {"start_frame": 0, "end_frame": 100, "start_tc": "00:00:00:00", "end_tc": "00:00:04:04"},
    }


def test_heuristic_source_does_not_over_trigger_on_a_real_base_value():
    c = _field_conflict(domain="color", base={"saturation": 1.0})
    assert heuristic_source(c) is None


def test_heuristic_source_suggests_theirs_for_independently_added_grade():
    c = _field_conflict(domain="color", base=None)
    s = heuristic_source(c)
    assert s is not None
    assert s.choice == "theirs"
    assert s.confidence < AUTO_APPLY_THRESHOLD  # deliberately conservative — see the preview-integration test below
    assert s.confidence >= 0.5


def test_heuristic_source_never_reaches_auto_apply_threshold_for_timeline_overlap():
    c = _overlap_conflict(ref_a="sha256:different", ref_b="sha256:other")
    s = heuristic_source(c)
    assert s is not None
    assert s.choice == "keep_both"
    assert s.confidence < AUTO_APPLY_THRESHOLD

    suggestions = suggest_resolutions([c])
    auto_applied = {p: s for p, s in suggestions.items() if s.confidence >= AUTO_APPLY_THRESHOLD}
    assert auto_applied == {}


def test_heuristic_source_no_suggestion_when_same_source_clip():
    # Same media_ref overlapping (e.g. a duplicated import) isn't the
    # "two people independently added different footage" case the heuristic
    # is narrowly targeting.
    c = _overlap_conflict(ref_a="sha256:same", ref_b="sha256:same")
    assert heuristic_source(c) is None


def test_suggest_resolutions_respects_source_order():
    calls = []

    def first_source(conflict):
        calls.append("first")
        return Suggestion(path=conflict["path"], choice="ours", confidence=1.0, reason="stub")

    def second_source(conflict):
        calls.append("second")
        return Suggestion(path=conflict["path"], choice="theirs", confidence=1.0, reason="should not run")

    result = suggest_resolutions([_field_conflict()], sources=[first_source, second_source])
    assert calls == ["first"]
    assert list(result.values())[0].choice == "ours"


def _grade(sat):
    return {"a": {"nodes": [{"saturation": sat}]}}


def test_preview_merge_integration_overlap_case(project):
    sunset = clip("sunset_beach", 384, length=120, media_ref="sha256:sunset")
    forest = clip("forest_drone", 384, length=120, media_ref="sha256:forest")
    project.repo.create_branch("anu_codes")
    write_cuts(project, [clip("a", 0), forest])
    commit_all(project, "anu edit")
    project.repo.checkout("main")
    write_cuts(project, [clip("a", 0), sunset])
    commit_all(project, "adi edit")

    preview = preview_merge(project, "anu_codes")

    overlap_paths = [c["path"] for c in preview.conflicts if c["category"] == TIMELINE_OVERLAP]
    assert len(overlap_paths) == 1
    assert overlap_paths[0] not in preview.auto_applied
    assert overlap_paths[0] in preview.suggestions
    assert preview.suggestions[overlap_paths[0]].choice == "keep_both"


def test_preview_merge_integration_field_case_stays_a_hint_below_threshold(project):
    # heuristic_source's field-conflict confidence (0.55) is deliberately below
    # AUTO_APPLY_THRESHOLD (0.85) — same conservative stance as timeline_overlap,
    # just not called out by name in the module since 0.55 already sits under
    # the cutoff. It shows up as a hint alongside the conflict, not auto-applied.
    project.repo.create_branch("feature")
    write_cuts(project, [clip("a", 0)], grades=_grade(1.5))
    commit_all(project, "feature grade")
    project.repo.checkout("main")
    write_cuts(project, [clip("a", 0)], grades=_grade(0.2))
    commit_all(project, "main grade")

    preview = preview_merge(project, "feature")

    assert len(preview.conflicts) == 1
    path = preview.conflicts[0]["path"]
    assert path not in preview.auto_applied
    assert path in preview.suggestions
    assert preview.suggestions[path].choice == "theirs"


def test_high_confidence_field_suggestion_auto_applies(project):
    # Distinct from the heuristic's own (conservative) confidence — this
    # proves the auto-apply *mechanism* itself works end to end when a
    # source does clear the threshold, using a stand-in high-confidence source.
    from vit.merge import service as merge_service

    def confident_source(conflict):
        if conflict.get("category", "field") != "field":
            return None
        return Suggestion(path=conflict["path"], choice="theirs", confidence=0.95, reason="stub: always theirs")

    project.repo.create_branch("feature")
    write_cuts(project, [clip("a", 0)], grades=_grade(1.5))
    commit_all(project, "feature grade")
    project.repo.checkout("main")
    write_cuts(project, [clip("a", 0)], grades=_grade(0.2))
    commit_all(project, "main grade")

    real_suggest = merge_service.suggest_resolutions
    merge_service.suggest_resolutions = lambda conflicts, sources=None: (
        {c["path"]: confident_source(c) for c in conflicts if confident_source(c)}
    )
    try:
        preview = preview_merge(project, "feature")
    finally:
        merge_service.suggest_resolutions = real_suggest

    assert preview.conflicts == []
    assert len(preview.auto_applied) == 1
    path, suggestion = next(iter(preview.auto_applied.items()))
    assert suggestion.choice == "theirs"
    assert path.startswith("color/grades/a")


# ── gemini_batch_source: fails soft, never blocks a merge ───────────────────

def _fake_gemini_response(rows):
    text = json.dumps(rows)
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_gemini_batch_source_returns_nothing_without_an_api_key(monkeypatch):
    monkeypatch.delenv(GEMINI_API_KEY_ENV, raising=False)
    c = _field_conflict(domain="cuts")  # heuristic has no opinion on this one
    assert gemini_batch_source([c]) == {}


def test_gemini_batch_source_parses_a_well_formed_response(monkeypatch):
    monkeypatch.setenv(GEMINI_API_KEY_ENV, "test-key-not-real")
    c = _field_conflict(domain="cuts")
    fake_resp = _fake_gemini_response([
        {"path": c["path"], "choice": "ours", "confidence": 0.7, "reason": "ours looks intentional"},
    ])

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(fake_resp).encode()

    with patch("vit.merge.suggest.urllib.request.urlopen", return_value=_Resp()):
        result = gemini_batch_source([c])

    assert result[c["path"]].choice == "ours"
    assert result[c["path"]].confidence == 0.7


def test_gemini_batch_source_fails_soft_on_network_error(monkeypatch):
    import urllib.error
    monkeypatch.setenv(GEMINI_API_KEY_ENV, "test-key-not-real")
    c = _field_conflict(domain="cuts")

    def _raise(*a, **kw):
        raise urllib.error.URLError("no network")

    with patch("vit.merge.suggest.urllib.request.urlopen", side_effect=_raise):
        assert gemini_batch_source([c]) == {}


def test_gemini_batch_source_fails_soft_on_malformed_json(monkeypatch):
    monkeypatch.setenv(GEMINI_API_KEY_ENV, "test-key-not-real")
    c = _field_conflict(domain="cuts")
    bad_resp = {"candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(bad_resp).encode()

    with patch("vit.merge.suggest.urllib.request.urlopen", return_value=_Resp()):
        assert gemini_batch_source([c]) == {}


def test_gemini_batch_source_ignores_unknown_paths_and_invalid_choices(monkeypatch):
    monkeypatch.setenv(GEMINI_API_KEY_ENV, "test-key-not-real")
    c = _field_conflict(domain="cuts")
    fake_resp = _fake_gemini_response([
        {"path": "not/a/real/path", "choice": "ours", "confidence": 0.9},
        {"path": c["path"], "choice": "definitely not a side", "confidence": 0.9},
    ])

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(fake_resp).encode()

    with patch("vit.merge.suggest.urllib.request.urlopen", return_value=_Resp()):
        assert gemini_batch_source([c]) == {}


def test_gemini_batch_source_never_sees_timeline_overlap_conflicts(monkeypatch):
    monkeypatch.setenv(GEMINI_API_KEY_ENV, "test-key-not-real")
    overlap = _overlap_conflict()
    with patch("vit.merge.suggest.urllib.request.urlopen") as mock_urlopen:
        result = gemini_batch_source([overlap])
    mock_urlopen.assert_not_called()
    assert result == {}


def test_high_confidence_overlap_suggestion_never_auto_applies_even_via_batch_source():
    """Structural guard in preview_merge(), not just self-restraint by a
    source: even if some future/misbehaving batch source returned a
    high-confidence suggestion for a timeline_overlap conflict, it must never
    reach auto_applied — that resolution ripples the whole track."""
    from vit.merge import service as merge_service

    def reckless_batch_source(conflicts):
        return {c["path"]: Suggestion(path=c["path"], choice="keep_both", order="ours_first", confidence=0.99, reason="stub")
                for c in conflicts if c.get("category") == TIMELINE_OVERLAP}

    real_suggest = merge_service.suggest_resolutions
    merge_service.suggest_resolutions = lambda conflicts, sources=None, batch_sources=None: (
        suggest_resolutions(conflicts, batch_sources=[reckless_batch_source])
    )
    try:
        sunset = clip("sunset_beach", 384, length=120, media_ref="sha256:sunset")
        forest = clip("forest_drone", 384, length=120, media_ref="sha256:forest")
        import tempfile, os as _os
        from tests.helpers import make_project
        with tempfile.TemporaryDirectory() as tmp:
            p = make_project(_os.path.join(tmp, "proj"))
            write_cuts(p, [clip("a", 0)])
            commit_all(p, "base")
            p.repo.create_branch("anu_codes")
            write_cuts(p, [clip("a", 0), forest])
            commit_all(p, "anu edit")
            p.repo.checkout("main")
            write_cuts(p, [clip("a", 0), sunset])
            commit_all(p, "adi edit")

            preview = preview_merge(p, "anu_codes")
    finally:
        merge_service.suggest_resolutions = real_suggest

    overlap_paths = [c["path"] for c in preview.conflicts if c["category"] == TIMELINE_OVERLAP]
    assert len(overlap_paths) == 1
    assert overlap_paths[0] not in preview.auto_applied
