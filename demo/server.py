"""Vit Studio — a browser timeline editor backed by vit's core library and real git.

Run:  python demo/server.py        then open http://127.0.0.1:8765

The browser plays the NLE; this server writes the timeline as domain-split
JSON with vit's models, and every version-control action runs through vit
(the system git binary). The backend lives in demo/studio/.
"""

import argparse
import os
import sys
import threading
import webbrowser

# Make the `vit` package (repo root) importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from studio import StudioConfig, build_studio  # noqa: E402
from studio.config import DEFAULT_BIND, DEFAULT_PORT  # noqa: E402
from studio import live_server  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Vit Studio")
    # Most PaaS platforms (Render, Railway, Heroku, ...) inject $PORT and route
    # to whatever port the container actually listens on — respecting it here
    # means the same image deploys correctly without per-platform config.
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    parser.add_argument("--host", default=DEFAULT_BIND,
                        help="address to bind (0.0.0.0 inside Docker; the default keeps it local)")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--reset", action="store_true", help="start from a fresh demo project")
    parser.add_argument("--no-live", action="store_true",
                        help="skip the live co-editing WebSocket server")
    args = parser.parse_args()

    studio = build_studio(StudioConfig.from_env())
    if args.reset and studio.workspace.project.exists():
        studio.workspace.reset()
    studio.workspace.ensure()

    url = f"http://localhost:{args.port}"
    server = studio.make_server(args.port, args.host)
    print(f"\n  Vit Studio running at {url}")
    print(f"  Project repo (plain git + JSON): {studio.config.project_dir}")

    if not args.no_live:
        # Separate port: plain http.server (the main server above) can't speak
        # WebSocket. On a PaaS that only forwards one public port (Render's
        # free tier, for one) this port won't be externally reachable — live
        # co-editing then only works locally / in Docker with both ports
        # exposed. See docs/ARCHITECTURE.md.
        live_port = int(os.environ.get("VIT_LIVE_PORT", args.port + 1))
        live_server.start_in_background(studio.config.project_dir, args.host, live_port)
        print(f"  Live co-editing (WebSocket): ws://localhost:{live_port}")

    print("  Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
