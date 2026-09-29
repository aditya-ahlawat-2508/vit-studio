"use strict";

// ── Plain-language labels ────────────────────────────────────────────────
//
// One place for the terminology this app uses instead of git jargon, and
// the two helpers (describeDomain / formatConflictValue) that keep merge.js
// and inspector.js from ever showing a raw internal field name or a JSON
// blob to someone who isn't a programmer. Loaded before every other script.

const LABELS = {
  branch: "version line",
  branchPlural: "version lines",
  commit: "save a version",
  merge: "combine",
  conflict: "decision needed",
  detached: "Viewing an old version",
  diff: "what changed",
};

// Friendly name for a domain (one of the JSON files vit tracks), used
// wherever a conflict or an advanced view needs to say what kind of thing
// changed without saying "cuts.json".
const DOMAIN_LABELS = {
  cuts: "clip",
  color: "color grade",
  audio: "audio",
  effects: "effects",
  markers: "marker",
  metadata: "project settings",
  manifest: "media",
};

function describeDomain(domain) {
  return DOMAIN_LABELS[domain] || "item";
}

// Friendly name for a specific field, used by conflictLabel() (merge.js)
// and the plain field list that replaces a raw JSON dump.
const FIELD_LABELS = {
  record_start_frame: "start point",
  record_end_frame: "end point",
  source_start_frame: "source start",
  source_end_frame: "source end",
  start_frame: "start point",
  end_frame: "end point",
  name: "name",
  note: "note",
  color: "color",
  frame: "position",
  track_index: "track",
  clip_enabled: "enabled",
  volume: "volume",
  pan: "pan",
  saturation: "saturation",
  contrast: "contrast",
  hue: "hue",
  temperature: "temperature",
  gain_m: "exposure",
  transform: "position/zoom/rotation",
  speed: "speed",
  speed_percent: "speed",
  Pan: "pan",
  Tilt: "tilt",
  ZoomX: "zoom",
  ZoomY: "zoom",
  Opacity: "opacity",
  RotationAngle: "rotation",
  FlipX: "flip (horizontal)",
  FlipY: "flip (vertical)",
  blur: "blur",
  vignette: "vignette",
  fade_in: "fade in",
  fade_out: "fade out",
};

function describeField(key) {
  return FIELD_LABELS[key] || null;
}

const FRAME_FIELD = /(^|_)(frame)$/; // record_start_frame, end_frame, frame, etc.

// Renders a conflicting value the way a video editor would read it — reusing
// tc() (already in core.js, mirrors vit/diff.py's _frames_to_timecode) for
// anything frame-valued, and the same units/conventions inspector.js's own
// sliders already use, instead of raw JSON.
function formatConflictValue(value, conflict) {
  if (value === null || value === undefined) return "(removed on this version line)";
  const key = conflict && conflict.path ? conflict.path.split("/").pop() : null;

  if (typeof value === "number") {
    if (key && FRAME_FIELD.test(key)) return tc(value);
    if (key === "speed_percent") return `${value}% speed`;
    if (key === "volume") return `${value > 0 ? "+" : ""}${value} dB`;
    if (key === "hue" || key === "RotationAngle") return `${value}°`;
    if (key === "Opacity") return `${value}%`;
    if (key === "saturation" || key === "contrast" || key === "gain_m") return value.toFixed(2);
    return String(value);
  }
  if (typeof value === "boolean") return value ? "On" : "Off";
  if (typeof value === "string") return `"${value}"`;
  if (Array.isArray(value)) return value.length ? `${value.length} item${value.length === 1 ? "" : "s"}` : "(empty)";
  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return "(no changes)";
    return entries.map(([k, v]) => `${describeField(k) || k}: ${formatConflictValue(v, null)}`).join(", ");
  }
  return String(value);
}
