"""Browser timeline → vit Timeline.

The browser plays the NLE: it edits the domain-split JSON in memory and posts
it here. This module is the "serializer" — it round-trips that JSON through
vit's models, so whatever lands on disk is valid, canonical timeline JSON.
"""

from vit.timeline import (
    Asset,
    AudioTrack,
    ColorGrade,
    DomainFiles,
    Marker,
    Timeline,
    TimelineMetadata,
    VideoTrack,
)

from .media import IMPORTED_KIND, MediaLibrary

# Integer-valued fields in the domain JSON. Every other number is written as a
# float, so a value that round-trips through the browser (where 1.0 becomes 1)
# produces byte-identical JSON and git doesn't see a phantom change.
INT_KEYS = {
    "record_start_frame", "record_end_frame", "source_start_frame", "source_end_frame",
    "start_frame", "end_frame", "track_index", "index", "num_nodes", "frame", "duration",
    "duration_frames", "width", "height", "video", "audio", "composite_mode",
    "dynamic_zoom_ease", "retime_process", "motion_estimation", "fade_in", "fade_out",
}


def normalize_numbers(value, key=None):
    """Coerce JSON numbers to int or float by field name (see INT_KEYS)."""
    if isinstance(value, dict):
        return {k: normalize_numbers(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_numbers(v, key) for v in value]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return int(round(value)) if key in INT_KEYS else float(value)


def used_media_refs(files: DomainFiles) -> set:
    refs = set()
    for domain, tracks_key in (("cuts", "video_tracks"), ("audio", "audio_tracks")):
        for track in files.get(domain, {}).get(tracks_key, []):
            refs.update(item["media_ref"] for item in track.get("items", []))
    return refs


def build_assets(files: DomainFiles, library: MediaLibrary) -> dict:
    """Manifest = every media ref the timeline uses (paths and metadata, never bytes).

    A ref missing from the library (e.g. an imported file that was deleted)
    keeps its previous manifest entry.
    """
    sources = library.by_ref()
    previous = (files.get("manifest") or {}).get("assets", {})
    assets = {}
    for ref in sorted(used_media_refs(files)):
        src = sources.get(ref)
        if src is None:
            if ref in previous:
                assets[ref] = Asset.from_dict(previous[ref])
            continue
        procedural = src["kind"] != IMPORTED_KIND
        assets[ref] = Asset(
            filename=src["name"],
            original_path="(procedural demo source)" if procedural else library.file_path(src),
            duration_frames=int(src["duration_frames"]),
            codec="procedural" if procedural else "browser-decoded",
            resolution=f"{src.get('width', 1920)}x{src.get('height', 1080)}",
        )
    return assets


def timeline_from_browser(files: DomainFiles, library: MediaLibrary) -> Timeline:
    files = normalize_numbers(files)
    return Timeline(
        metadata=TimelineMetadata.from_dict(files.get("metadata", {})),
        video_tracks=[VideoTrack.from_dict(t) for t in files.get("cuts", {}).get("video_tracks", [])],
        audio_tracks=[AudioTrack.from_dict(t) for t in files.get("audio", {}).get("audio_tracks", [])],
        color_grades={k: ColorGrade.from_dict(v) for k, v in files.get("color", {}).get("grades", {}).items()},
        effects={"clip_effects": files.get("effects", {}).get("clip_effects", {})},
        markers=[Marker.from_dict(m) for m in files.get("markers", {}).get("markers", [])],
        assets=build_assets(files, library),
    )

