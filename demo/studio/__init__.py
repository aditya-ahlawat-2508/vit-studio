"""Vit Studio backend — a local HTTP server around vit's core library.

    config.py      paths and constants
    media.py       MediaLibrary: procedural sources + imported videos (outside git)
    starter.py     the starter timeline for a fresh project
    serializer.py  browser JSON → vit Timeline
    workspace.py   Workspace: save / commit / auto-save / reset the demo project
    api.py         StudioApi: one method per JSON endpoint
    handler.py     HTTP transport: routing, local-only security, static + media files
    app.py         composition root (build_studio)
"""

from .app import Studio, build_studio
from .config import StudioConfig

__all__ = ["Studio", "StudioConfig", "build_studio"]
