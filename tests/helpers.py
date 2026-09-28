"""Small builders shared by the tests."""

from vit.project import VitProject
from vit.timeline import read_json, write_json


def make_project(path: str) -> VitProject:
    project = VitProject.create(path)
    project.repo.set_config("user.name", "Test")
    project.repo.set_config("user.email", "test@test")
    return project


def clip(clip_id: str, start: int, length: int = 10, **extra) -> dict:
    item = {
        "id": clip_id, "name": clip_id, "media_ref": "m",
        "record_start_frame": start, "record_end_frame": start + length,
        "source_start_frame": 0, "source_end_frame": length,
        "track_index": 1, "transform": {},
    }
    item.update(extra)
    return item


def write_cuts(project: VitProject, items, grades=None) -> None:
    """Write cuts.json (one video track) and color.json."""
    write_json(project.store.path("cuts"), {"video_tracks": [{"index": 1, "items": items}]})
    write_json(project.store.path("color"), {"grades": grades or {}})


def commit_all(project: VitProject, message: str) -> str:
    project.repo.add(["."])
    return project.repo.commit(message)


def clip_ids(project: VitProject):
    cuts = read_json(project.store.path("cuts"))
    return [i["id"] for t in cuts["video_tracks"] for i in t["items"]]
