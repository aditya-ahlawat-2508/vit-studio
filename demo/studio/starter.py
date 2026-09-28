"""The timeline a fresh demo project starts with: two clips on V1, each with linked audio."""

from vit.timeline import DomainFiles

from .config import FPS
from .media import synthetic_source


def _video(clip_id: str, src: dict, rec_start: int, rec_end: int, source_start: int, track: int = 1) -> dict:
    return {
        "id": clip_id, "name": src["name"], "media_ref": src["ref"],
        "record_start_frame": rec_start, "record_end_frame": rec_end,
        "source_start_frame": source_start, "source_end_frame": source_start + (rec_end - rec_start),
        "track_index": track,
        "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0, "ZoomY": 1.0, "Opacity": 100.0},
    }


def _linked_audio(video: dict) -> dict:
    # Linked audio shares the clip id with an "a" prefix instead of "v".
    return {
        "id": "a" + video["id"][1:], "media_ref": video["media_ref"],
        "start_frame": video["record_start_frame"], "end_frame": video["record_end_frame"],
        "volume": 0.0, "pan": 0.0,
    }


def starter_files() -> DomainFiles:
    v1 = _video("v_intro1", synthetic_source("interview"), 0, 192, 240)
    v2 = _video("v_beach1", synthetic_source("sunset"), 192, 384, 96)
    return {
        "metadata": {
            "project_name": "Vit Demo", "timeline_name": "Main Edit", "frame_rate": FPS,
            "resolution": {"width": 1920, "height": 1080}, "start_timecode": "01:00:00:00",
            "track_count": {"video": 2, "audio": 2},
        },
        "cuts": {"video_tracks": [{"index": 1, "items": [v1, v2]}, {"index": 2, "items": []}]},
        "audio": {"audio_tracks": [{"index": 1, "items": [_linked_audio(v1), _linked_audio(v2)]}, {"index": 2, "items": []}]},
        "color": {"grades": {}},
        "effects": {"clip_effects": {}},
        "markers": {"markers": []},
    }
