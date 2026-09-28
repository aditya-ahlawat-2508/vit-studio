"use strict";

// ── Timeline model helpers ─────────────────────────────────────────────────

const view = () => (S.preview ? S.preview.files : S.files);
const readonly = () => Boolean(S.preview);
const speedOf = (item) => ((item.speed && item.speed.speed_percent) || 100) / 100;
const audioIdFor = (vid) => "a" + vid.slice(1);
const videoIdFor = (aid) => "v" + aid.slice(1);

function ensureShape(files) {
  files.cuts = files.cuts || {};
  files.audio = files.audio || {};
  files.cuts.video_tracks = files.cuts.video_tracks || [];
  files.audio.audio_tracks = files.audio.audio_tracks || [];
  for (const [list, n] of [[files.cuts.video_tracks, 2], [files.audio.audio_tracks, 2]]) {
    for (let i = 1; i <= n; i++) if (!list.find((t) => t.index === i)) list.push({ index: i, items: [] });
    list.sort((a, b) => a.index - b.index);
  }
  files.color = files.color || {};
  files.color.grades = files.color.grades || {};
  files.effects = files.effects || {};
  files.effects.clip_effects = files.effects.clip_effects || {};
  files.markers = files.markers || {};
  files.markers.markers = files.markers.markers || [];
  files.metadata = files.metadata || {};
  const tcount = files.metadata.track_count || {};
  files.metadata.track_count = {
    video: Math.max(tcount.video || 0, files.cuts.video_tracks.length),
    audio: Math.max(tcount.audio || 0, files.audio.audio_tracks.length),
  };
  return files;
}

function trackOf(tracks, index) {
  let t = tracks.find((x) => x.index === index);
  if (!t) { t = { index, items: [] }; tracks.push(t); tracks.sort((a, b) => a.index - b.index); }
  return t;
}

function allClips(files = view()) {
  return files.cuts.video_tracks.flatMap((t) => t.items);
}

function findClip(id, files = view()) {
  return allClips(files).find((c) => c.id === id) || null;
}

function findAudio(aid, files = view()) {
  for (const t of files.audio.audio_tracks) {
    const a = t.items.find((x) => x.id === aid);
    if (a) return a;
  }
  return null;
}

function removeFrom(tracks, id) {
  for (const t of tracks) {
    const i = t.items.findIndex((x) => x.id === id);
    if (i >= 0) return t.items.splice(i, 1)[0];
  }
  return null;
}

function sortAll(files = S.files) {
  const by = (k) => (a, b) => (a[k] - b[k]) || String(a.id).localeCompare(String(b.id));
  files.cuts.video_tracks.forEach((t) => t.items.sort(by("record_start_frame")));
  files.audio.audio_tracks.forEach((t) => t.items.sort(by("start_frame")));
  files.markers.markers.sort((a, b) => a.frame - b.frame);
}

// Every video clip has a linked audio clip (same media, same frames), the way
// an NLE links picture and sound. Sound designers edit its volume/pan.
function syncAudio(v) {
  const aid = audioIdFor(v.id);
  const a = removeFrom(S.files.audio.audio_tracks, aid) || { id: aid, volume: 0.0, pan: 0.0 };
  a.media_ref = v.media_ref;
  a.start_frame = v.record_start_frame;
  a.end_frame = v.record_end_frame;
  if (v.speed) a.speed = { ...v.speed }; else delete a.speed;
  trackOf(S.files.audio.audio_tracks, v.track_index).items.push(a);
}

function overlapsOn(track, start, end, ignoreId, files = S.files) {
  const t = files.cuts.video_tracks.find((x) => x.index === track);
  return (t ? t.items : []).find((c) => c.id !== ignoreId && start < c.record_end_frame && c.record_start_frame < end) || null;
}

function firstFreeStart(track, start, len, ignoreId) {
  let s = start, hit;
  while ((hit = overlapsOn(track, s, s + len, ignoreId))) s = hit.record_end_frame;
  return s;
}

function contentEnd(files = view()) {
  return allClips(files).reduce((m, c) => Math.max(m, c.record_end_frame), 0);
}

function timelineLength() {
  return Math.max(contentEnd() + 10 * FPS, 40 * FPS);
}

function newId(prefix, name) {
  const slug = name.toLowerCase().replace(/\.[^.]+$/, "").replace(/[^a-z0-9]+/g, "").slice(0, 10);
  return `${prefix}_${slug}${Math.random().toString(16).slice(2, 6)}`;
}

function edit(fn) {
  if (readonly()) { toast("You're previewing an old version — go back to the working copy to edit."); return false; }
  fn();
  sortAll();
  render();
  scheduleSync();
  return true;
}
