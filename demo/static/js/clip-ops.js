"use strict";

// ── Clip operations ────────────────────────────────────────────────────────

function addClip(ref, track, frame) {
  const src = S.lib[ref];
  if (!src) return;
  const len = Math.min(5 * FPS, src.duration_frames);
  const srcStart = Math.max(0, Math.min(Math.floor(src.duration_frames * 0.2), src.duration_frames - len));
  const v = {
    id: newId("v", src.name), name: src.name, media_ref: ref,
    record_start_frame: 0, record_end_frame: len,
    source_start_frame: srcStart, source_end_frame: srcStart + len,
    track_index: track,
    transform: { Pan: 0, Tilt: 0, ZoomX: 1, ZoomY: 1, Opacity: 100 },
  };
  const ok = edit(() => {
    v.record_start_frame = firstFreeStart(track, Math.max(0, Math.round(frame)), len, null);
    v.record_end_frame = v.record_start_frame + len;
    trackOf(S.files.cuts.video_tracks, track).items.push(v);
    syncAudio(v);
    S.selected = { type: "clip", id: v.id };
  });
  if (ok) renderInspector();
}

function deleteClip(id) {
  edit(() => {
    removeFrom(S.files.cuts.video_tracks, id);
    removeFrom(S.files.audio.audio_tracks, audioIdFor(id));
    delete S.files.color.grades[id];
    delete S.files.effects.clip_effects[id];
    S.selected = null;
  });
  renderInspector();
}

function splitClip(id, frame) {
  const v = findClip(id, S.files);
  frame = Math.floor(frame);
  if (!v || frame <= v.record_start_frame || frame >= v.record_end_frame) {
    toast("Put the playhead inside the selected clip to split it.");
    return;
  }
  edit(() => {
    const sp = speedOf(v);
    const right = clone(v);
    right.id = newId("v", v.name);
    right.record_start_frame = frame;
    right.source_start_frame = v.source_start_frame + Math.round((frame - v.record_start_frame) * sp);
    v.record_end_frame = frame;
    v.source_end_frame = right.source_start_frame;
    trackOf(S.files.cuts.video_tracks, v.track_index).items.push(right);
    const leftAudio = findAudio(audioIdFor(v.id), S.files);
    syncAudio(v);
    syncAudio(right);
    const rightAudio = findAudio(audioIdFor(right.id), S.files);
    if (leftAudio && rightAudio) { rightAudio.volume = leftAudio.volume; rightAudio.pan = leftAudio.pan; }
    if (S.files.color.grades[v.id]) S.files.color.grades[right.id] = clone(S.files.color.grades[v.id]);
    if (S.files.effects.clip_effects[v.id]) S.files.effects.clip_effects[right.id] = clone(S.files.effects.clip_effects[v.id]);
    S.selected = { type: "clip", id: right.id };
  });
  renderInspector();
}

function setSpeed(v, pct) {
  const src = S.lib[v.media_ref];
  const sp = pct / 100;
  const srcLen = v.source_end_frame - v.source_start_frame;
  let len = Math.max(1, Math.round(srcLen / sp));
  const next = allClips(S.files)
    .filter((c) => c.track_index === v.track_index && c.id !== v.id && c.record_start_frame >= v.record_start_frame)
    .reduce((m, c) => Math.min(m, c.record_start_frame), Infinity);
  len = Math.min(len, next - v.record_start_frame);
  v.record_end_frame = v.record_start_frame + len;
  v.source_end_frame = Math.min(src ? src.duration_frames : Infinity, v.source_start_frame + Math.round(len * sp));
  if (pct === 100) delete v.speed; else v.speed = { speed_percent: pct };
  syncAudio(v);
}

// Quick fixes for clips that ended up in the same slot after a merge.
function moveToFreeTrack(id) {
  const c = findClip(id, S.files);
  if (!c) return;
  const free = S.files.cuts.video_tracks.map((t) => t.index).sort((a, b) => a - b)
    .find((idx) => idx > c.track_index && !overlapsOn(idx, c.record_start_frame, c.record_end_frame, c.id));
  if (!free) { toast("No free track above — try “Place after”."); return; }
  edit(() => { c.track_index = free; syncAudio(c); S.selected = { type: "clip", id }; });
}

function placeAfter(id, anchorId) {
  const c = findClip(id, S.files), anchor = findClip(anchorId, S.files);
  if (!c || !anchor) return;
  const len = c.record_end_frame - c.record_start_frame;
  edit(() => {
    c.record_start_frame = firstFreeStart(c.track_index, anchor.record_end_frame, len, c.id);
    c.record_end_frame = c.record_start_frame + len;
    syncAudio(c);
    S.selected = { type: "clip", id };
  });
}

function addMarker() {
  const frame = Math.floor(S.playhead);
  const existing = view().markers.markers.find((m) => m.frame === frame);
  if (existing) { S.selected = { type: "marker", id: frame }; render(); return; }
  const n = view().markers.markers.length + 1;
  const ok = edit(() => {
    S.files.markers.markers.push({ frame, color: "Blue", name: `Note ${n}`, note: "", duration: 1 });
    S.selected = { type: "marker", id: frame };
  });
  if (ok) renderInspector();
}
