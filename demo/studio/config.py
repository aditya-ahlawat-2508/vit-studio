"""Paths and constants for Vit Studio."""

import os
from dataclasses import dataclass
from typing import Tuple

DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FPS = 24.0
DEFAULT_PORT = 8765
DEFAULT_BIND = "127.0.0.1"
LOCAL_HOSTS = ("127.0.0.1", "localhost")


@dataclass(frozen=True)
class StudioConfig:
    static_dir: str
    workspace: str
    # Host names the browser may use to reach the server. Anything else is
    # refused (DNS-rebinding protection); extend via VIT_ALLOWED_HOSTS.
    allowed_hosts: Tuple[str, ...] = LOCAL_HOSTS

    @property
    def project_dir(self) -> str:
        """The demo's git repo of timeline JSON."""
        return os.path.join(self.workspace, "project")

    @property
    def media_dir(self) -> str:
        """Imported videos. Outside the project, so media never enters git."""
        return os.path.join(self.workspace, "media")

    @classmethod
    def from_env(cls) -> "StudioConfig":
        extra = [h.strip() for h in os.environ.get("VIT_ALLOWED_HOSTS", "").split(",") if h.strip()]
        return cls(
            static_dir=os.path.join(DEMO_DIR, "static"),
            workspace=os.environ.get("VIT_DEMO_WORKSPACE", os.path.join(DEMO_DIR, "workspace")),
            allowed_hosts=LOCAL_HOSTS + tuple(extra),
        )
