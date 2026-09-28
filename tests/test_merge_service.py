"""End-to-end merges against a real git repo (perform_merge / preview_merge)."""

import pytest

from tests.helpers import clip, clip_ids, commit_all, write_cuts
from vit.git import GitError, GitRepository
from vit.merge import CONFLICTS, MERGED, UP_TO_DATE, perform_merge, preview_merge
from vit.timeline import read_json


def _diverge(project, ours_items, theirs_items, ours_grades=None, theirs_grades=None):
    project.repo.create_branch("feature")
    write_cuts(project, theirs_items, theirs_grades)
    commit_all(project, "feature edit")
    project.repo.checkout("main")
    write_cuts(project, ours_items, ours_grades)
    commit_all(project, "main edit")


def _grade(sat):
    return {"a": {"nodes": [{"saturation": sat}]}}


def test_merge_keeps_clips_added_on_both_branches(project):
    _diverge(project, [clip("a", 0), clip("ours", 10)], [clip("a", 0), clip("theirs", 20)])

    outcome = perform_merge(project, "feature")

    assert outcome.status == MERGED
    assert clip_ids(project) == ["a", "ours", "theirs"]
    assert "timeline/cuts.json" in outcome.git_text_conflicts
    assert project.repo.rev_parse("HEAD^2") == project.repo.rev_parse("feature")
    assert project.repo.is_clean()


def test_merge_works_when_git_lacks_merge_tree(project, monkeypatch):
    """git < 2.38 has no `merge-tree --write-tree`; merging must not depend on it."""
    monkeypatch.setattr(GitRepository, "merge_tree_conflicts", lambda *a: None)
    _diverge(project, [clip("a", 0), clip("ours", 10)], [clip("a", 0), clip("theirs", 20)])

    outcome = perform_merge(project, "feature")

    assert outcome.status == MERGED
    assert outcome.git_text_conflicts == []
    assert clip_ids(project) == ["a", "ours", "theirs"]


def test_conflict_leaves_repo_untouched_until_resolved(project):
    _diverge(project, [clip("a", 0)], [clip("a", 0)], _grade(1.5), _grade(0.2))
    head = project.repo.rev_parse("HEAD")

    outcome = perform_merge(project, "feature")
    assert outcome.status == CONFLICTS
    assert project.repo.rev_parse("HEAD") == head
    assert project.repo.rev_parse("MERGE_HEAD") is None

    outcome = perform_merge(project, "feature", {c["path"]: "theirs" for c in outcome.conflicts})
    assert outcome.status == MERGED
    color = read_json(project.store.path("color"))
    assert color["grades"]["a"]["nodes"][0]["saturation"] == 0.2


def test_merge_up_to_date(project):
    project.repo.create_branch("feature")
    project.repo.checkout("main")
    assert perform_merge(project, "feature").status == UP_TO_DATE


def test_merge_unknown_branch(project):
    with pytest.raises(GitError):
        perform_merge(project, "nope")


def test_preview_reports_without_touching_repo(project):
    _diverge(project, [clip("a", 0)], [clip("a", 0)], _grade(1.5), _grade(0.2))
    head = project.repo.rev_parse("HEAD")

    preview = preview_merge(project, "feature")

    assert [c["domain"] for c in preview.conflicts] == ["color"]
    assert not preview.up_to_date
    assert project.repo.rev_parse("HEAD") == head
    assert project.repo.is_clean()


def test_preview_unknown_branch(project):
    with pytest.raises(ValueError):
        preview_merge(project, "nope")
