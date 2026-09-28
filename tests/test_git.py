"""GitRepository and VitProject against a real git repo in a temp directory."""

import json
import os
import subprocess
import tempfile

from tests.helpers import commit_all, make_project, write_cuts
from vit.git import GitRepository
from vit.project import VitProject
from vit.timeline import write_json


def test_create_makes_project_structure(project):
    for sub in (".vit", "timeline", "assets"):
        assert os.path.isdir(os.path.join(project.path, sub))
    assert os.path.isfile(os.path.join(project.path, ".vit", "config.json"))
    assert project.exists()


def test_create_starts_on_main(project):
    assert project.repo.current_branch() == "main"


def test_create_keeps_existing_history():
    """Regression: re-pointing HEAD to 'main' orphaned work in existing repos."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init", "-q", "-b", "master", tmp], check=True)
        repo = GitRepository(tmp)
        repo.set_config("user.name", "Test")
        repo.set_config("user.email", "test@test")
        with open(os.path.join(tmp, "notes.txt"), "w") as f:
            f.write("old work")
        repo.add(["."])
        repo.commit("old work")
        before = repo.rev_parse("HEAD")

        VitProject.create(tmp)

        assert repo.current_branch() == "master"
        assert repo.rev_parse("HEAD") == before


def test_commit_and_log(project):
    write_cuts(project, [{"id": "item_001", "name": "Test Clip"}])
    short = commit_all(project, "add test clip")

    commits = project.repo.log_graph()
    assert commits[0]["message"] == "add test clip"
    assert commits[0]["hash"] == short
    assert commits[0]["is_head"] and "main" in commits[0]["refs"]


def test_commit_if_changed_skips_empty_commits(project):
    assert project.commit_if_changed("nothing new") is None
    write_cuts(project, [{"id": "item_001", "name": "Changed"}])
    assert project.commit_if_changed("changed")


def test_branch_and_checkout(project):
    project.repo.create_branch("color-grade")
    assert project.repo.current_branch() == "color-grade"

    project.repo.checkout("main")
    assert project.repo.current_branch() == "main"
    assert {"main", "color-grade"} <= set(project.repo.branches())


def test_merge_clean(project):
    """Branches that edit different files merge cleanly in plain git."""
    project.repo.create_branch("color-grade")
    write_json(project.store.path("color"), {"grades": {"item_001": {"num_nodes": 2}}})
    commit_all(project, "add color grade")

    project.repo.checkout("main")
    write_json(project.store.path("cuts"), {"video_tracks": [{"index": 1, "items": [{"id": "item_001", "name": "Updated"}]}]})
    commit_all(project, "update clip name")

    clean, _ = project.repo.merge_no_commit("color-grade")
    assert clean is True
    assert project.repo.rev_parse("MERGE_HEAD") is not None


def test_merge_conflict(project):
    """Branches that edit the same lines of one file conflict in plain git."""
    project.repo.create_branch("experiment")
    write_cuts(project, [{"id": "item_001", "name": "Experiment Clip"}])
    commit_all(project, "experiment edit")

    project.repo.checkout("main")
    write_cuts(project, [{"id": "item_001", "name": "Main Clip"}])
    commit_all(project, "main edit")

    clean, _ = project.repo.merge_no_commit("experiment")
    assert clean is False
    assert project.repo.conflicted_files() == ["timeline/cuts.json"]
    project.repo.merge_abort()
    assert project.repo.is_clean()


def test_show_file_at_ref(project):
    write_cuts(project, [{"id": "item_001", "name": "V1"}])
    commit_all(project, "version 1")
    write_cuts(project, [{"id": "item_001", "name": "V2"}])
    commit_all(project, "version 2")

    head = json.loads(project.repo.show_file("HEAD", "timeline/cuts.json"))
    prev = json.loads(project.repo.show_file("HEAD~1", "timeline/cuts.json"))
    assert head["video_tracks"][0]["items"][0]["name"] == "V2"
    assert prev["video_tracks"][0]["items"][0]["name"] == "V1"
    assert project.repo.show_file("HEAD", "timeline/missing.json") is None


def test_files_at_omits_missing_domains(project):
    files = project.files_at("HEAD")
    assert set(files) == {"cuts", "color"}
    assert project.files_at(None) == {}


def test_is_clean_and_diff(project):
    assert project.repo.is_clean()
    write_cuts(project, [{"id": "item_001", "name": "New"}])
    assert not project.repo.is_clean()
    assert "item_001" in project.repo.diff("HEAD", ["timeline/cuts.json"])


def test_rev_parse_unknown_ref(project):
    assert project.repo.rev_parse("no-such-branch") is None


def test_make_project_is_idempotent(project):
    head = project.repo.rev_parse("HEAD")
    make_project(project.path)
    assert project.repo.rev_parse("HEAD") == head
