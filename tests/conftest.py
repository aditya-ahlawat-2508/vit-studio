"""Shared fixtures."""

import os
import sys
import tempfile

import pytest

# Vit Studio's backend package (`studio`) lives in demo/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo"))

from tests.helpers import clip, commit_all, make_project, write_cuts  # noqa: E402


@pytest.fixture
def project():
    """A vit project on 'main' with one committed clip."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_project(os.path.join(tmp, "proj"))
        write_cuts(p, [clip("a", 0)])
        commit_all(p, "base")
        yield p
