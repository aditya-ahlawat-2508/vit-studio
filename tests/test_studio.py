"""Vit Studio backend: the editor's API workflow and the HTTP server's security rules."""

import copy
import http.client
import json
import threading

import pytest

from studio import StudioConfig, build_studio
from studio.serializer import normalize_numbers


@pytest.fixture
def studio(tmp_path):
    s = build_studio(StudioConfig(static_dir=str(tmp_path / "static"), workspace=str(tmp_path / "ws")))
    s.workspace.ensure()
    return s


def _add_clip(files, clip_id, start, ref="demo:city", name="City_Night.mov"):
    files = copy.deepcopy(files)
    files["cuts"]["video_tracks"][0]["items"].append({
        "id": clip_id, "name": name, "media_ref": ref,
        "record_start_frame": start, "record_end_frame": start + 48,
        "source_start_frame": 0, "source_end_frame": 48, "track_index": 1,
        "transform": {"Pan": 0, "Tilt": 0, "ZoomX": 1, "ZoomY": 1, "Opacity": 100},
    })
    return files


def _grade(files, clip_id, saturation):
    files = copy.deepcopy(files)
    files["color"]["grades"][clip_id] = {
        "num_nodes": 1, "version_name": "Version 1", "drx_file": None, "lut_file": None,
        "nodes": [{"index": 1, "label": "Primary", "lut": "", "saturation": saturation}],
    }
    return files


# ── API workflow ────────────────────────────────────────────────────────────

def test_fresh_project_state(studio):
    state = studio.api.state({}, None)
    assert state["branch"] == "main"
    assert state["dirty"] is False
    assert state["issues"] == []
    assert len(state["files"]["cuts"]["video_tracks"][0]["items"]) == 2
    assert any(s["ref"] == "demo:city" for s in state["library"])
    assert [c["message"] for c in studio.api.log({}, None)["commits"]] == ["vit: initial snapshot"]


def test_edit_save_and_commit(studio):
    files = _add_clip(studio.api.state({}, None)["files"], "v_city1", 384)

    saved = studio.api.save_working({}, {"files": files})
    assert saved["dirty"] is True
    assert "Added clip 'City_Night.mov'" in saved["diff"]

    result = studio.api.commit({}, {"message": "city b-roll", "author": "Aditi Rao"})
    assert result["hash"] and result["message"] == "vit: city b-roll"
    assert studio.api.state({}, None)["dirty"] is False
    head = studio.api.log({}, None)["commits"][0]
    assert head["author"] == "Aditi Rao"
    assert "demo:city" in studio.api.state({}, None)["files"]["manifest"]["assets"]

    assert studio.api.commit({}, {"message": "again"})["hash"] is None


def test_browser_round_trip_is_byte_stable(studio):
    """Ints the browser sends as 1 vs 1.0 must not create phantom changes."""
    files = json.loads(json.dumps(studio.api.state({}, None)["files"]).replace(".0,", ","))
    studio.api.save_working({}, {"files": files})
    assert studio.api.state({}, None)["dirty"] is False
    assert normalize_numbers({"frame": 3.0, "volume": 1}) == {"frame": 3, "volume": 1.0}


def test_branch_checkout_autosaves(studio):
    studio.api.create_branch({}, {"name": "aditi-edit"})
    studio.api.save_working({}, {"files": _add_clip(studio.api.state({}, None)["files"], "v_city1", 384)})

    r = studio.api.checkout({}, {"ref": "main", "author": "Aditi"})
    assert r["branch"] == "main" and r["autosaved"]
    assert len(studio.api.state({}, None)["files"]["cuts"]["video_tracks"][0]["items"]) == 2


def test_invalid_branch_name(studio):
    with pytest.raises(ValueError):
        studio.api.create_branch({}, {"name": "-bad name"})


def test_parallel_branches_merge_without_conflict(studio):
    base = studio.api.state({}, None)["files"]
    studio.api.create_branch({}, {"name": "aditi-edit"})
    studio.api.save_working({}, {"files": _add_clip(base, "v_city1", 384)})
    studio.api.checkout({}, {"ref": "main"})
    studio.api.create_branch({}, {"name": "kabir-edit"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 1.3)})
    studio.api.checkout({}, {"ref": "aditi-edit"})

    preview = studio.api.compare({"branch": "kabir-edit"}, None)
    assert preview["conflicts"] == [] and not preview["up_to_date"]

    r = studio.api.merge({}, {"branch": "kabir-edit", "author": "Aditi"})
    assert r["status"] == "merged"
    files = studio.api.state({}, None)["files"]
    assert "v_intro1" in files["color"]["grades"]
    assert "v_city1" in [c["id"] for c in files["cuts"]["video_tracks"][0]["items"]]
    assert len(studio.api.log({}, None)["commits"][0]["parents"]) == 2


def test_same_field_conflict_asks_then_resolves(studio):
    base = studio.api.state({}, None)["files"]
    studio.api.create_branch({}, {"name": "a"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 1.5)})
    studio.api.checkout({}, {"ref": "main"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 0.5)})

    r = studio.api.merge({}, {"branch": "a"})
    assert r["status"] == "conflicts"
    resolutions = {c["path"]: "theirs" for c in r["conflicts"]}
    r = studio.api.merge({}, {"branch": "a", "resolutions": resolutions})
    assert r["status"] == "merged"
    grade = studio.api.state({}, None)["files"]["color"]["grades"]["v_intro1"]
    assert grade["nodes"][0]["saturation"] == 1.5


def test_merge_into_itself_is_rejected(studio):
    with pytest.raises(ValueError):
        studio.api.merge({}, {"branch": "main"})


def test_conflicting_merge_response_carries_file_snapshots_for_frame_previews(studio):
    base = studio.api.state({}, None)["files"]
    studio.api.create_branch({}, {"name": "a"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 1.5)})
    studio.api.checkout({}, {"ref": "main"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 0.5)})

    r = studio.api.merge({}, {"branch": "a"})
    assert r["status"] == "conflicts"
    assert "ours_files" in r and "theirs_files" in r
    assert r["ours_files"]["color"]["grades"]["v_intro1"]["nodes"][0]["saturation"] == 0.5
    assert r["theirs_files"]["color"]["grades"]["v_intro1"]["nodes"][0]["saturation"] == 1.5


def test_compare_reports_auto_applied_and_exclude_auto_undoes_it(studio):
    base = studio.api.state({}, None)["files"]
    studio.api.create_branch({}, {"name": "feature"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 1.5)})
    studio.api.checkout({}, {"ref": "main"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 0.2)})
    studio.api.commit({}, {"message": "grade on main", "author": "tester"})

    r = studio.api.compare({"branch": "feature"}, None)
    # Below AUTO_APPLY_THRESHOLD by design (see vit/merge/suggest.py) — shows
    # up as a hinted conflict, not silently resolved.
    assert r["conflicts"]
    assert r["auto_applied"] == []
    path = r["conflicts"][0]["path"]
    assert path in r["suggestions"]
    assert r["suggestions"][path]["choice"] == "theirs"

    # exclude_auto is a no-op here (nothing was auto-applied to exclude) but
    # must not error, and should keep returning the same conflict.
    r2 = studio.api.compare({"branch": "feature", "exclude_auto": path}, None)
    assert r2["conflicts"]


def test_branches_status_reports_every_other_branch_up_front(studio):
    base = studio.api.state({}, None)["files"]
    studio.api.create_branch({}, {"name": "clean-branch"})
    studio.api.save_working({}, {"files": _add_clip(base, "v_city1", 384)})
    studio.api.checkout({}, {"ref": "main"})
    studio.api.create_branch({}, {"name": "conflicting-branch"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 1.5)})
    studio.api.checkout({}, {"ref": "main"})
    studio.api.save_working({}, {"files": _grade(base, "v_intro1", 0.5)})
    studio.api.commit({}, {"message": "grade on main", "author": "tester"})

    statuses = {s["branch"]: s for s in studio.api.branches_status({}, None)["branches"]}
    assert "main" not in statuses
    assert statuses["clean-branch"]["clean"] is True
    assert statuses["clean-branch"]["conflict_count"] == 0
    assert statuses["conflicting-branch"]["clean"] is False
    assert statuses["conflicting-branch"]["conflict_count"] == 1


def test_restore_adds_a_version(studio):
    first = studio.api.log({}, None)["commits"][0]["hash"]
    studio.api.save_working({}, {"files": _add_clip(studio.api.state({}, None)["files"], "v_city1", 384)})
    studio.api.commit({}, {"message": "add city"})

    assert studio.api.restore({}, {"ref": first})["hash"]
    assert len(studio.api.log({}, None)["commits"]) == 3
    assert len(studio.api.state({}, None)["files"]["cuts"]["video_tracks"][0]["items"]) == 2


def test_validation_flags_overlap(studio):
    files = _add_clip(studio.api.state({}, None)["files"], "v_city1", 100)
    issues = studio.api.save_working({}, {"files": files})["issues"]
    assert any(i["category"] == "overlap" for i in issues)


def test_raw_only_serves_domain_files(studio):
    assert '"video_tracks"' in studio.api.raw({"path": "timeline/cuts.json"}, None)["content"]
    with pytest.raises(ValueError):
        studio.api.raw({"path": "../../etc/passwd"}, None)


def test_reset(studio):
    studio.api.create_branch({}, {"name": "tmp"})
    studio.api.reset({}, {})
    assert studio.api.state({}, None)["branches"] == ["main"]


# ── HTTP transport ──────────────────────────────────────────────────────────

@pytest.fixture
def server(studio, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>vit</h1>")
    srv = studio.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(method, path, body=body, headers={"Host": f"localhost:{port}", **(headers or {})})
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return res.status, data


def test_http_serves_index_and_state(server):
    assert _request(server, "GET", "/") == (200, b"<h1>vit</h1>")
    status, data = _request(server, "GET", "/api/state")
    assert status == 200 and json.loads(data)["branch"] == "main"


def test_http_rejects_foreign_host(server):
    status, _ = _request(server, "GET", "/api/state", headers={"Host": "evil.example"})
    assert status == 403


def test_http_writes_need_csrf_header(server):
    assert _request(server, "POST", "/api/reset", b"{}")[0] == 403
    assert _request(server, "POST", "/api/reset", b"{}", {"X-Vit-Demo": "1"})[0] == 200


def test_http_errors_are_json_400(server):
    status, data = _request(server, "POST", "/api/branch", b'{"name": "-x"}', {"X-Vit-Demo": "1"})
    assert status == 400 and "Branch names" in json.loads(data)["error"]


def test_http_blocks_path_traversal(server):
    assert _request(server, "GET", "/../server.py")[0] == 404


def test_http_upload_goes_to_media_not_git(server, studio):
    status, data = _request(server, "POST", "/api/media?name=clip.mp4&duration_frames=48",
                            b"fake video bytes", {"X-Vit-Demo": "1"})
    entry = json.loads(data)
    assert status == 200 and entry["ref"].startswith("sha256:") and entry["available"]
    assert _request(server, "GET", f"/media/{entry['file']}")[1] == b"fake video bytes"
    assert studio.workspace.repo.is_clean()
