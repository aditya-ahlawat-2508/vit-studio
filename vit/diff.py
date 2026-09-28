"""Human-readable diffs of timeline changes, e.g.

    CUTS:
      + Added clip 'City_Night.mov' on V1 at 00:00:16:00 (4.0s)
    COLOR:
      ~ clip 'v_intro1' node 1: Saturation 1.000 → 1.200

The formatting functions are pure (dicts in, lines out);
`diff_working_tree` is the one entry point that reads a project.
"""

from typing import Dict, List

from .project import VitProject
from .timeline.models import (
    COMPOSITE_MODE_NAMES,
    DYNAMIC_ZOOM_EASE_NAMES,
    MOTION_EST_NAMES,
    RETIME_PROCESS_NAMES,
)


def _frames_to_timecode(frames: int, fps: float = 24.0) -> str:
    """Convert frame number to HH:MM:SS:FF timecode."""
    total_frames = int(frames)
    ff = total_frames % int(fps)
    total_seconds = total_frames // int(fps)
    ss = total_seconds % 60
    total_minutes = total_seconds // 60
    mm = total_minutes % 60
    hh = total_minutes // 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _frames_to_duration(frames: int, fps: float = 24.0) -> str:
    """Convert frame count to human-readable duration."""
    seconds = frames / fps
    if seconds < 1:
        return f"{int(frames)}f"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m{secs:.0f}s"


def _items_by_id(domain: dict, tracks_key: str) -> Dict[str, dict]:
    """{item id: item} across every track of a cuts/audio document."""
    return {
        item["id"]: item
        for track in domain.get(tracks_key, [])
        for item in track.get("items", [])
    }


def _clip_identity(item: dict) -> tuple:
    """Same underlying footage, same trim — used to spot a clip re-linked under a new id."""
    return (item.get("media_ref"), item.get("source_start_frame"), item.get("source_end_frame"))


def _find_relinked_ids(old_items: Dict[str, dict], new_items: Dict[str, dict]) -> Dict[str, str]:
    """{new_id: old_id} for clips that vanished under one id and reappeared under another.

    Matched by identical (media_ref, source_start_frame, source_end_frame): same
    footage, same trim, just a new id — e.g. after a re-import. Without this,
    the diff reports an unrelated delete + add instead of one moved clip.
    """
    removed_ids = set(old_items) - set(new_items)
    added_ids = set(new_items) - set(old_items)
    old_by_identity = {_clip_identity(old_items[i]): i for i in removed_ids}
    relinked = {}
    for new_id in added_ids:
        old_id = old_by_identity.get(_clip_identity(new_items[new_id]))
        if old_id is not None:
            relinked[new_id] = old_id
            del old_by_identity[_clip_identity(new_items[new_id])]
    return relinked


def diff_cuts(old: dict, new: dict, fps: float = 24.0) -> List[str]:
    """Diff cuts.json and return human-readable lines."""
    lines = []

    old_items = _items_by_id(old, "video_tracks")
    new_items = _items_by_id(new, "video_tracks")
    relinked = _find_relinked_ids(old_items, new_items)

    # Re-linked clips (same footage/trim, new id) — reported once, not as add+remove
    for new_id, old_id in relinked.items():
        item = new_items[new_id]
        lines.append(
            f"  ~ '{item['name']}' re-linked on V{item['track_index']} (same source, new id '{new_id}')"
        )

    # Added clips
    for item_id, item in new_items.items():
        if item_id not in old_items and item_id not in relinked:
            tc = _frames_to_timecode(item["record_start_frame"], fps)
            dur = _frames_to_duration(
                item["record_end_frame"] - item["record_start_frame"], fps
            )
            lines.append(
                f"  + Added clip '{item['name']}' on V{item['track_index']} at {tc} ({dur})"
            )

    # Removed clips
    relinked_old_ids = set(relinked.values())
    for item_id, item in old_items.items():
        if item_id not in new_items and item_id not in relinked_old_ids:
            lines.append(
                f"  - Removed clip '{item['name']}' from V{item['track_index']}"
            )

    # Modified clips
    for item_id in new_items:
        if item_id not in old_items:
            continue
        old_item = old_items[item_id]
        new_item = new_items[item_id]

        # Check trim changes
        if old_item["record_start_frame"] != new_item["record_start_frame"]:
            old_tc = _frames_to_timecode(old_item["record_start_frame"], fps)
            new_tc = _frames_to_timecode(new_item["record_start_frame"], fps)
            lines.append(
                f"  ~ Trimmed '{new_item['name']}' start: {old_tc} → {new_tc}"
            )
        if old_item["record_end_frame"] != new_item["record_end_frame"]:
            old_tc = _frames_to_timecode(old_item["record_end_frame"], fps)
            new_tc = _frames_to_timecode(new_item["record_end_frame"], fps)
            lines.append(
                f"  ~ Trimmed '{new_item['name']}' end: {old_tc} → {new_tc}"
            )

        # Check track move
        if old_item["track_index"] != new_item["track_index"]:
            lines.append(
                f"  ~ Moved '{new_item['name']}' from V{old_item['track_index']} to V{new_item['track_index']}"
            )

        # Check transform changes
        old_t = old_item.get("transform", {})
        new_t = new_item.get("transform", {})
        transform_keys = [
            "Pan", "Tilt", "ZoomX", "ZoomY", "Opacity",
            "RotationAngle", "AnchorPointX", "AnchorPointY",
            "Pitch", "Yaw", "FlipX", "FlipY",
            "CropLeft", "CropRight", "CropTop", "CropBottom",
            "CropSoftness", "CropRetain", "Distortion",
        ]
        for key in transform_keys:
            default = False if key in ("FlipX", "FlipY", "CropRetain") else 0
            old_v = old_t.get(key, default)
            new_v = new_t.get(key, default)
            if old_v != new_v:
                lines.append(
                    f"  ~ clip '{new_item['name']}': {key} {old_v} → {new_v}"
                )

        # Composite mode
        old_cm = old_item.get("composite_mode", 0)
        new_cm = new_item.get("composite_mode", 0)
        if old_cm != new_cm:
            old_name = COMPOSITE_MODE_NAMES.get(old_cm, f"mode({old_cm})")
            new_name = COMPOSITE_MODE_NAMES.get(new_cm, f"mode({new_cm})")
            lines.append(f"  ~ clip '{new_item['name']}': Composite {old_name} → {new_name}")

        # Dynamic zoom ease
        old_dz = old_item.get("dynamic_zoom_ease", 0)
        new_dz = new_item.get("dynamic_zoom_ease", 0)
        if old_dz != new_dz:
            old_name = DYNAMIC_ZOOM_EASE_NAMES.get(old_dz, f"ease({old_dz})")
            new_name = DYNAMIC_ZOOM_EASE_NAMES.get(new_dz, f"ease({new_dz})")
            lines.append(f"  ~ clip '{new_item['name']}': Dynamic Zoom {old_name} → {new_name}")

        # Clip enabled
        old_en = old_item.get("clip_enabled", True)
        new_en = new_item.get("clip_enabled", True)
        if old_en != new_en:
            state = "enabled" if new_en else "disabled"
            lines.append(f"  ~ clip '{new_item['name']}': {state}")

        # Check speed changes
        lines.extend(_diff_speed(old_item, new_item, new_item["name"]))

    return lines


def _diff_speed(old_item: dict, new_item: dict, clip_name: str) -> List[str]:
    """Diff speed/retime properties between two clip versions."""
    lines = []
    old_speed = old_item.get("speed", {})
    new_speed = new_item.get("speed", {})

    old_pct = old_speed.get("speed_percent", 100.0)
    new_pct = new_speed.get("speed_percent", 100.0)

    if old_pct != new_pct:
        old_label = _format_speed(old_pct)
        new_label = _format_speed(new_pct)
        lines.append(f"  ~ clip '{clip_name}': Speed {old_label} → {new_label}")

    old_rt = old_speed.get("retime_process", 0)
    new_rt = new_speed.get("retime_process", 0)
    if old_rt != new_rt:
        old_name = RETIME_PROCESS_NAMES.get(old_rt, f"unknown({old_rt})")
        new_name = RETIME_PROCESS_NAMES.get(new_rt, f"unknown({new_rt})")
        lines.append(f"  ~ clip '{clip_name}': Retime method {old_name} → {new_name}")

    old_me = old_speed.get("motion_estimation", 0)
    new_me = new_speed.get("motion_estimation", 0)
    if old_me != new_me:
        old_name = MOTION_EST_NAMES.get(old_me, f"unknown({old_me})")
        new_name = MOTION_EST_NAMES.get(new_me, f"unknown({new_me})")
        lines.append(
            f"  ~ clip '{clip_name}': Motion estimation {old_name} → {new_name}"
        )

    return lines


def _format_speed(pct: float) -> str:
    """Format speed percentage as a human-friendly string."""
    if pct == 100.0:
        return "100% (normal)"
    multiplier = pct / 100.0
    if pct > 100:
        return f"{pct}% ({multiplier:.2g}x fast)"
    return f"{pct}% ({multiplier:.2g}x slow)"


def _format_rgb(vals: list) -> str:
    """Format RGB list as readable string."""
    if not vals or len(vals) != 3:
        return str(vals)
    return f"R:{vals[0]:.3f} G:{vals[1]:.3f} B:{vals[2]:.3f}"


def _format_wheel(wheel: dict) -> str:
    """Format a color wheel dict as readable string."""
    if not wheel:
        return str(wheel)
    parts = []
    for ch in ["r", "g", "b", "y"]:
        if ch in wheel:
            label = {"r": "R", "g": "G", "b": "B", "y": "Y"}[ch]
            parts.append(f"{label}:{wheel[ch]:.3f}")
    return " ".join(parts)


def _diff_wheel_channels(
    old_node: dict, new_node: dict, prefix: str, wheel: str, label: str
) -> List[str]:
    """Diff per-channel values for a color wheel (e.g. lift R/G/B/M)."""
    channels = [("r", "R"), ("g", "G"), ("b", "B"), ("m", "M")]
    changed = []
    for ch_key, ch_label in channels:
        key = f"{wheel}_{ch_key}"
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v and (old_v is not None or new_v is not None):
            old_s = f"{old_v:+.4f}" if old_v is not None else "default"
            new_s = f"{new_v:+.4f}" if new_v is not None else "default"
            changed.append(f"{ch_label}: {old_s} → {new_s}")
    if changed:
        return [f"{prefix}: {label}  " + "  ".join(changed)]
    return []


def _diff_node_values(old_node: dict, new_node: dict, item_id: str, node_idx: int) -> List[str]:
    """Diff color values within a single node."""
    lines = []
    prefix = f"  ~ clip '{item_id}' node {node_idx}"

    # CDL values
    for key, label in [("slope", "Slope"), ("offset", "Offset"), ("power", "Power")]:
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v:
            old_s = _format_rgb(old_v) if old_v else "default"
            new_s = _format_rgb(new_v) if new_v else "default"
            lines.append(f"{prefix}: {label} {old_s} → {new_s}")

    # Scalar values
    for key, label in [("saturation", "Saturation"), ("contrast", "Contrast"),
                        ("pivot", "Pivot"), ("hue", "Hue"), ("color_boost", "Color Boost")]:
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v and (old_v is not None or new_v is not None):
            old_s = f"{old_v:.3f}" if old_v is not None else "default"
            new_s = f"{new_v:.3f}" if new_v is not None else "default"
            lines.append(f"{prefix}: {label} {old_s} → {new_s}")

    # Color wheels (legacy dict form)
    for key, label in [("lift", "Lift"), ("gamma", "Gamma"),
                        ("gain", "Gain"), ("color_offset", "Offset")]:
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v and (old_v is not None or new_v is not None):
            old_s = _format_wheel(old_v) if old_v else "default"
            new_s = _format_wheel(new_v) if new_v else "default"
            lines.append(f"{prefix}: {label} {old_s} → {new_s}")

    # Per-channel wheel values (richer format)
    for wheel_key, wheel_label in [
        ("lift", "Lift"), ("gamma", "Gamma"), ("gain", "Gain"), ("offset", "Offset")
    ]:
        lines.extend(_diff_wheel_channels(old_node, new_node, prefix, wheel_key, wheel_label))

    # White balance
    for key, label in [("temperature", "Temperature"), ("tint", "Tint")]:
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v and (old_v is not None or new_v is not None):
            old_s = f"{old_v:.0f}" if old_v is not None else "default"
            new_s = f"{new_v:.0f}" if new_v is not None else "default"
            suffix = "K" if key == "temperature" else ""
            lines.append(f"{prefix}: {label} {old_s}{suffix} → {new_s}{suffix}")

    # Sharpness and noise reduction
    for key, label in [("sharpness", "Sharpness"),
                        ("noise_reduction_luma", "NR Luma"),
                        ("noise_reduction_chroma", "NR Chroma")]:
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v and (old_v is not None or new_v is not None):
            old_s = f"{old_v:.3f}" if old_v is not None else "default"
            new_s = f"{new_v:.3f}" if new_v is not None else "default"
            lines.append(f"{prefix}: {label} {old_s} → {new_s}")

    # LUT changes
    old_lut = old_node.get("lut", "")
    new_lut = new_node.get("lut", "")
    if old_lut != new_lut:
        lines.append(f"{prefix}: LUT '{old_lut or 'none'}' → '{new_lut or 'none'}'")

    return lines


def diff_color(old: dict, new: dict) -> List[str]:
    """Diff color.json and return human-readable lines."""
    lines = []
    old_grades = old.get("grades", {})
    new_grades = new.get("grades", {})

    for item_id in sorted(new_grades):
        if item_id not in old_grades:
            lines.append(f"  + Added color grade for clip '{item_id}'")
            # Show what was added
            new_g = new_grades[item_id]
            for node in new_g.get("nodes", []):
                for key, label in [("slope", "Slope"), ("saturation", "Saturation"),
                                    ("contrast", "Contrast"), ("hue", "Hue")]:
                    val = node.get(key)
                    if val is not None:
                        if isinstance(val, list):
                            lines.append(f"    {label}: {_format_rgb(val)}")
                        else:
                            lines.append(f"    {label}: {val:.3f}")
            continue

        old_g = old_grades[item_id]
        new_g = new_grades[item_id]

        for key in ["num_nodes", "version_name", "drx_file"]:
            old_v = old_g.get(key)
            new_v = new_g.get(key)
            if old_v != new_v:
                lines.append(f"  ~ clip '{item_id}': {key} {old_v} → {new_v}")

        old_nodes = old_g.get("nodes", [])
        new_nodes = new_g.get("nodes", [])

        # Diff nodes pairwise
        max_nodes = max(len(old_nodes), len(new_nodes))
        for idx in range(max_nodes):
            if idx >= len(old_nodes):
                lines.append(f"  + clip '{item_id}': added node {idx + 1}")
                continue
            if idx >= len(new_nodes):
                lines.append(f"  - clip '{item_id}': removed node {idx + 1}")
                continue
            node_lines = _diff_node_values(old_nodes[idx], new_nodes[idx], item_id, idx + 1)
            lines.extend(node_lines)

    for item_id in sorted(old_grades):
        if item_id not in new_grades:
            lines.append(f"  - Removed color grade for clip '{item_id}'")

    return lines


def diff_audio(old: dict, new: dict, fps: float = 24.0) -> List[str]:
    """Diff audio.json and return human-readable lines."""
    lines = []

    old_items = _items_by_id(old, "audio_tracks")
    new_items = _items_by_id(new, "audio_tracks")

    for item_id, item in new_items.items():
        if item_id not in old_items:
            lines.append(f"  + Added audio clip '{item_id}'")
        else:
            old_item = old_items[item_id]
            for key in ["volume", "pan"]:
                if old_item.get(key) != item.get(key):
                    lines.append(
                        f"  ~ audio '{item_id}': {key} {old_item.get(key)} → {item.get(key)}"
                    )
            lines.extend(_diff_speed(old_item, item, item_id))

    for item_id in old_items:
        if item_id not in new_items:
            lines.append(f"  - Removed audio clip '{item_id}'")

    return lines


def diff_markers(old: dict, new: dict, fps: float = 24.0) -> List[str]:
    """Diff markers.json and return human-readable lines."""
    lines = []
    old_markers = {m["frame"]: m for m in old.get("markers", [])}
    new_markers = {m["frame"]: m for m in new.get("markers", [])}

    for frame, marker in new_markers.items():
        if frame not in old_markers:
            tc = _frames_to_timecode(frame, fps)
            lines.append(f'  + Added marker at {tc}: "{marker.get("name", "")}"')
        else:
            old_m = old_markers[frame]
            if old_m != marker:
                tc = _frames_to_timecode(frame, fps)
                lines.append(f'  ~ Modified marker at {tc}: "{marker.get("name", "")}"')

    for frame in old_markers:
        if frame not in new_markers:
            tc = _frames_to_timecode(frame, fps)
            lines.append(f"  - Removed marker at {tc}")

    return lines


def diff_effects(old: dict, new: dict) -> List[str]:
    """Diff effects.json clip_effects and return human-readable lines."""
    lines = []
    old_fx = old.get("clip_effects", {})
    new_fx = new.get("clip_effects", {})

    for item_id in sorted(new_fx):
        if item_id not in old_fx:
            lines.append(f"  + Added effects for clip '{item_id}'")
            continue
        for key in sorted(set(old_fx[item_id]) | set(new_fx[item_id])):
            old_v = old_fx[item_id].get(key)
            new_v = new_fx[item_id].get(key)
            if old_v != new_v:
                lines.append(f"  ~ clip '{item_id}': {key} {old_v} → {new_v}")

    for item_id in sorted(old_fx):
        if item_id not in new_fx:
            lines.append(f"  - Removed effects for clip '{item_id}'")

    return lines


def diff_metadata(old: dict, new: dict) -> List[str]:
    """Diff metadata.json and return human-readable lines."""
    lines = []
    for key in ["project_name", "timeline_name", "frame_rate", "start_timecode"]:
        old_v = old.get(key)
        new_v = new.get(key)
        if old_v != new_v:
            lines.append(f"  ~ {key}: {old_v} → {new_v}")

    old_res = old.get("resolution", {})
    new_res = new.get("resolution", {})
    if old_res != new_res:
        lines.append(
            f"  ~ resolution: {old_res.get('width')}x{old_res.get('height')} → "
            f"{new_res.get('width')}x{new_res.get('height')}"
        )

    return lines


def format_diff(
    old_files: Dict[str, dict],
    new_files: Dict[str, dict],
    timeline_name: str = "",
    branch_info: str = "",
) -> str:
    """Format a complete human-readable diff across all domain files.

    Args:
        old_files: Dict of domain name → old JSON data
        new_files: Dict of domain name → new JSON data
        timeline_name: Optional timeline name for header
        branch_info: Optional branch context (e.g. "color-grade → main")

    Returns:
        Formatted diff string
    """
    fps = new_files.get("metadata", {}).get("frame_rate", 24.0)
    output_lines = []

    if timeline_name:
        output_lines.append(f"  Timeline: {timeline_name}")
    if branch_info:
        output_lines.append(f"  Branch: {branch_info}")
    if output_lines:
        output_lines.append("")

    sections = [
        ("CUTS", "cuts", lambda old, new: diff_cuts(old, new, fps)),
        ("COLOR", "color", diff_color),
        ("AUDIO", "audio", lambda old, new: diff_audio(old, new, fps)),
        ("EFFECTS", "effects", diff_effects),
        ("MARKERS", "markers", lambda old, new: diff_markers(old, new, fps)),
        ("METADATA", "metadata", diff_metadata),
    ]

    has_changes = False
    for section_name, key, diff_fn in sections:
        old_data = old_files.get(key, {})
        new_data = new_files.get(key, {})
        if old_data == new_data:
            continue

        diff_lines = diff_fn(old_data, new_data)
        if diff_lines:
            has_changes = True
            output_lines.append(f"  {section_name}:")
            output_lines.extend(diff_lines)
            output_lines.append("")

    if not has_changes:
        output_lines.append("  No changes.")

    return "\n".join(output_lines)


def diff_working_tree(project: VitProject, ref: str = "HEAD") -> str:
    """Human-readable diff of the project's unsaved edits against `ref`."""
    new_files = project.working_files()
    return format_diff(
        project.files_at(ref),
        new_files,
        timeline_name=new_files.get("metadata", {}).get("timeline_name", ""),
    )
