"""End-to-end proof for the live co-editing layer: a real asyncio WebSocket
server (the actual demo/studio/live_server.py code, not a mock) with two
real client connections, proving they converge over the wire — then that an
explicit save produces a normal, real git commit.

No browser is used or needed: convergence is a property of the message
protocol and the CRDT merge rule, both of which are exercised here exactly
as a real browser tab would exercise them (connect, receive a snapshot,
send/receive update messages over a real socket).
"""

import asyncio
import contextlib
import json
import os
import socket
import sys
import time

import pytest
import websockets

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo"))

from studio import live_server  # noqa: E402
from vit.live import registry  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_ws(project):
    registry.reset_all()
    port = _free_port()
    live_server.start_in_background(project.path, "127.0.0.1", port)
    # Give the background thread's event loop a moment to actually bind.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
    else:
        pytest.fail("live WS server never started listening")
    yield project, f"ws://127.0.0.1:{port}"
    registry.reset_all()


def test_two_clients_converge_on_a_concurrent_edit(live_ws):
    project, url = live_ws

    async def scenario():
        async with websockets.connect(url) as a, websockets.connect(url) as b:
            snap_a = json.loads(await a.recv())
            snap_b = json.loads(await b.recv())
            assert snap_a["type"] == "snapshot"
            assert snap_a["files"] == snap_b["files"]  # both start in sync

            # Two "browser tabs" each make a concurrent edit to the SAME field.
            await a.send(json.dumps({
                "type": "update",
                "update": {"path": ["metadata", "project_name"], "value": "from A", "timestamp": [1, "alice"]},
            }))
            await b.send(json.dumps({
                "type": "update",
                "update": {"path": ["metadata", "project_name"], "value": "from B", "timestamp": [1, "bob"]},
            }))

            # Each client receives the OTHER's update relayed back (never its own).
            relayed_to_a = json.loads(await asyncio.wait_for(a.recv(), timeout=2))
            relayed_to_b = json.loads(await asyncio.wait_for(b.recv(), timeout=2))
            assert relayed_to_a["update"]["value"] == "from B"
            assert relayed_to_b["update"]["value"] == "from A"

            # "bob" > "alice" lexicographically at the same Lamport counter,
            # so both sides deterministically converge on Bob's write.
            return relayed_to_a, relayed_to_b

    asyncio.run(scenario())

    server_state = registry.get_or_create(project).snapshot()
    assert server_state["metadata"]["project_name"] == "from B"


def test_stale_update_is_relayed_to_no_one(live_ws):
    """A client sending an update that's already superseded shouldn't cause
    a spurious broadcast — the relay only forwards state that actually
    changed, which is what keeps a large session from being flooded by
    no-op re-deliveries."""
    project, url = live_ws

    async def scenario():
        async with websockets.connect(url) as a, websockets.connect(url) as b:
            await a.recv()  # snapshot
            await b.recv()  # snapshot

            await a.send(json.dumps({
                "type": "update",
                "update": {"path": ["metadata", "project_name"], "value": "real edit", "timestamp": [5, "alice"]},
            }))
            await asyncio.wait_for(b.recv(), timeout=2)  # the real edit, relayed

            # Now a genuinely stale update (lower Lamport counter) — must not relay.
            await a.send(json.dumps({
                "type": "update",
                "update": {"path": ["metadata", "project_name"], "value": "stale", "timestamp": [0, ""]},
            }))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(b.recv(), timeout=0.5)

    asyncio.run(scenario())


def test_flush_to_disk_and_commit_produces_a_real_git_commit(live_ws):
    project, url = live_ws
    head_before = project.repo.rev_parse("HEAD")

    async def scenario():
        async with websockets.connect(url) as a:
            await a.recv()  # snapshot
            await a.send(json.dumps({
                "type": "update",
                "update": {"path": ["metadata", "project_name"], "value": "live edit", "timestamp": [1, "alice"]},
            }))
            await asyncio.sleep(0.1)  # let the server apply it before we flush

    asyncio.run(scenario())

    session = registry.get_or_create(project)
    commit_hash = session.flush_to_disk_and_commit("vit: live save")

    assert commit_hash is not None
    assert project.repo.rev_parse("HEAD") != head_before
    assert project.repo.is_clean()

    from vit.timeline import read_json
    metadata = read_json(project.store.path("metadata"))
    assert metadata["project_name"] == "live edit"
