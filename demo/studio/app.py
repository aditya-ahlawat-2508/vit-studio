"""Composition root: wires config → media library → workspace → API → HTTP server."""

from dataclasses import dataclass
from http.server import ThreadingHTTPServer

from .api import StudioApi
from .config import DEFAULT_BIND, StudioConfig
from .handler import make_handler
from .media import MediaLibrary
from .workspace import Workspace


@dataclass
class Studio:
    config: StudioConfig
    library: MediaLibrary
    workspace: Workspace
    api: StudioApi

    def make_server(self, port: int, host: str = DEFAULT_BIND) -> ThreadingHTTPServer:
        return ThreadingHTTPServer((host, port), make_handler(self.config, self.api, self.library))


def build_studio(config: StudioConfig) -> Studio:
    library = MediaLibrary(config.media_dir)
    workspace = Workspace(config, library)
    return Studio(config=config, library=library, workspace=workspace, api=StudioApi(workspace))
