"""Per-project locking in demo/studio/handler.py: _lock_for()."""

import sys
import threading
import time

sys.path.insert(0, "demo")  # conftest.py already does this for the suite; kept explicit here too

from studio.handler import _lock_for


def test_same_path_returns_the_same_lock_object():
    a = _lock_for("/tmp/project-a")
    b = _lock_for("/tmp/project-a")
    assert a is b


def test_different_paths_return_different_lock_objects():
    a = _lock_for("/tmp/project-a")
    b = _lock_for("/tmp/project-b")
    assert a is not b


def _timed_dispatch(project_path: str, sleep_for: float, results: list) -> None:
    start = time.monotonic()
    with _lock_for(project_path):
        time.sleep(sleep_for)
    results.append(time.monotonic() - start)


def test_different_projects_do_not_serialize_against_each_other():
    results: list = []
    sleep_for = 0.15
    t1 = threading.Thread(target=_timed_dispatch, args=("/tmp/proj-x", sleep_for, results))
    t2 = threading.Thread(target=_timed_dispatch, args=("/tmp/proj-y", sleep_for, results))

    overall_start = time.monotonic()
    t1.start(); t2.start()
    t1.join(); t2.join()
    overall = time.monotonic() - overall_start

    # Each thread's own dispatch took roughly one sleep, and running them
    # concurrently took roughly one sleep total — not two — proving the two
    # projects' locks didn't serialize against each other.
    assert all(sleep_for <= r < sleep_for * 1.8 for r in results)
    assert overall < sleep_for * 1.8


def test_same_project_still_fully_serializes():
    results: list = []
    sleep_for = 0.15
    t1 = threading.Thread(target=_timed_dispatch, args=("/tmp/proj-z", sleep_for, results))
    t2 = threading.Thread(target=_timed_dispatch, args=("/tmp/proj-z", sleep_for, results))

    overall_start = time.monotonic()
    t1.start(); t2.start()
    t1.join(); t2.join()
    overall = time.monotonic() - overall_start

    # This is the regression guard that actually matters: the point of the
    # lock is per-project mutual exclusion, not removing it. Same project ->
    # the two dispatches must still fully serialize (~2x the sleep, not ~1x).
    assert overall >= sleep_for * 1.8


def test_slow_branches_status_style_call_on_one_project_does_not_stall_another():
    """Regression guard specific to /api/branches/status: it runs preview_merge()
    once per branch inside the dispatch lock, so a project with many branches
    holds its own lock noticeably longer than any single prior endpoint did.
    That must never stall a concurrent request to a *different* project."""
    results: list = []
    slow_project_sleep = 0.3   # stands in for a multi-branch preview_merge() loop
    other_project_sleep = 0.05

    slow = threading.Thread(target=_timed_dispatch, args=("/tmp/proj-slow", slow_project_sleep, results))
    other = threading.Thread(target=_timed_dispatch, args=("/tmp/proj-other", other_project_sleep, results))

    slow.start()
    time.sleep(0.02)  # let the slow project's lock acquire first
    other_start = time.monotonic()
    other.start()
    other.join()
    other_elapsed = time.monotonic() - other_start
    slow.join()

    # The unrelated project's request must complete in roughly its own sleep
    # duration, not wait out the slow project's lock.
    assert other_elapsed < slow_project_sleep
