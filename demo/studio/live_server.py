"""WebSocket relay for live (pre-commit) collaborative editing.

Purely a relay + connection registry — the actual CRDT logic lives in
`vit/live/`; this module only shuffles JSON messages between connected
clients of the same project and keeps their `LiveSession` in sync. Runs as
its own asyncio server in a background thread, separate from the main
`http.server`-based HTTP server (plain `http.server` doesn't speak
WebSocket).

Wire protocol (JSON text frames):
  server -> client, on connect:  {"type": "snapshot", "files": {...}}
  client -> server, on an edit:  {"type": "update", "update": {path, value, timestamp}}
  server -> client, relayed:     {"type": "update", "update": {...}}   (never echoed to the sender)
"""

import asyncio
import json
import threading
from typing import Dict, Set

import websockets

from vit.live import registry
from vit.project import VitProject

# Not type-hinted to a specific connection class: websockets' connection type
# changed between major versions (WebSocketServerProtocol -> ServerConnection
# in the newer asyncio-native implementation) and this module only ever calls
# .send()/iterates it, so duck typing avoids pinning to either.
_connections: Dict[str, Set[object]] = {}
_connections_guard = threading.Lock()


async def _handle_client(websocket, project_dir: str) -> None:
    project = VitProject(project_dir)
    session = registry.get_or_create(project)

    with _connections_guard:
        _connections.setdefault(project_dir, set()).add(websocket)

    try:
        await websocket.send(json.dumps({"type": "snapshot", "files": session.snapshot()}))
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "update" or "update" not in msg:
                continue
            changed = session.apply_remote_update(msg["update"])
            if not changed:
                continue  # stale or duplicate — nothing to tell anyone else
            with _connections_guard:
                peers = list(_connections.get(project_dir, ()))
            outgoing = json.dumps({"type": "update", "update": msg["update"]})
            for peer in peers:
                if peer is websocket:
                    continue
                try:
                    await peer.send(outgoing)
                except websockets.exceptions.ConnectionClosed:
                    pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        with _connections_guard:
            _connections.get(project_dir, set()).discard(websocket)


def _make_handler(project_dir: str):
    async def handler(websocket) -> None:
        await _handle_client(websocket, project_dir)

    return handler


def serve_forever(project_dir: str, host: str, port: int) -> None:
    """Blocking — call this from a dedicated thread, never the main one."""

    async def _main() -> None:
        async with websockets.serve(_make_handler(project_dir), host, port):
            await asyncio.Future()  # run until the process exits

    asyncio.run(_main())


def start_in_background(project_dir: str, host: str, port: int) -> threading.Thread:
    thread = threading.Thread(
        target=serve_forever, args=(project_dir, host, port), daemon=True, name="vit-live-ws",
    )
    thread.start()
    return thread
