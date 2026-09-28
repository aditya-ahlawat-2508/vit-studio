"use strict";

// ── Viewer ─────────────────────────────────────────────────────────────────

const canvas = $("viewerCanvas");
const ctx = canvas.getContext("2d");
const srcCanvas = Object.assign(document.createElement("canvas"), { width: VW, height: VH });
const srcCtx = srcCanvas.getContext("2d");
const gradeCanvas = Object.assign(document.createElement("canvas"), { width: VW, height: VH });
const gradeCtx = gradeCanvas.getContext("2d");
const videos = {};

function videoFor(src) {
  if (!videos[src.ref]) {
    const v = document.createElement("video");
    v.src = "/media/" + encodeURIComponent(src.file);
    v.preload = "auto"; v.muted = true; v.playsInline = true;
    v.addEventListener("seeked", requestRender);
    v.addEventListener("loadeddata", requestRender);
    videos[src.ref] = v;
  }
  return videos[src.ref];
}

function drawCover(c, media, mw, mh) {
  const scale = Math.max(VW / mw, VH / mh);
  const w = mw * scale, hh = mh * scale;
  c.drawImage(media, (VW - w) / 2, (VH - hh) / 2, w, hh);
}

function drawSource(src, frame, burnIn) {
  srcCtx.save();
  srcCtx.fillStyle = "#000"; srcCtx.fillRect(0, 0, VW, VH);
  if (!src || !src.available) {
    SOURCES.drawOffline(srcCtx, VW, VH, src ? src.name : "missing media");
  } else if (VIDEO_KINDS.has(src.kind)) {
    const v = videoFor(src);
    if (v.readyState >= 2) drawCover(srcCtx, v, v.videoWidth, v.videoHeight);
    else { srcCtx.fillStyle = "#888"; srcCtx.font = "20px system-ui"; srcCtx.fillText("Loading media…", 30, 50); }
  } else {
    SOURCES.draw(srcCtx, VW, VH, src.kind, frame);
  }
  if (burnIn && src) {
    const label = `${src.name}  ·  SRC ${frame}`;
    srcCtx.font = "600 17px ui-monospace, Consolas, monospace";
    const w = srcCtx.measureText(label).width + 20;
    srcCtx.fillStyle = "rgba(0,0,0,0.65)"; srcCtx.fillRect(14, VH - 44, w, 30);
    srcCtx.fillStyle = "#fff"; srcCtx.fillText(label, 24, VH - 23);
  }
  srcCtx.restore();
}

function coveringClip(track, frame) {
  return track.items.find((c) => c.clip_enabled !== false && c.record_start_frame <= frame && frame < c.record_end_frame);
}

// Draw a single frame from an arbitrary (possibly non-live) files snapshot —
// used by the merge conflict view to show "ours" vs "theirs" as an actual
// picture instead of two JSON blobs. Only the source frame, no grade/effects/
// transform: a fast, honest thumbnail, not a full re-render.
function renderFrameToCanvas(targetCtx, files, lib, frame) {
  targetCtx.fillStyle = "#000";
  targetCtx.fillRect(0, 0, VW, VH);
  const tracks = [...(files.cuts.video_tracks || [])].sort((a, b) => a.index - b.index);
  for (const track of tracks) {
    const item = coveringClip(track, frame);
    if (!item) continue;
    const src = lib[item.media_ref];
    drawSource(src, sourceFrameAt(item, frame), false);
    targetCtx.drawImage(srcCanvas, 0, 0);
    return; // topmost covering track wins, same as the live viewer
  }
  targetCtx.font = "16px system-ui";
  targetCtx.fillStyle = "#666";
  targetCtx.fillText("no clip at this frame", 12, VH / 2);
}

function sourceFrameAt(item, frame) {
  return item.source_start_frame + Math.floor((frame - item.record_start_frame) * speedOf(item));
}

function renderViewer() {
  const files = view();
  const frame = Math.floor(S.playhead);
  const burnIn = $("burnIn").checked;
  ctx.fillStyle = "#000"; ctx.fillRect(0, 0, VW, VH);
  const lines = [];

  for (const track of [...files.cuts.video_tracks].sort((a, b) => a.index - b.index)) {
    const item = coveringClip(track, frame);
    if (!item) { lines.unshift(h("div", {}, `V${track.index}  ·  —`)); continue; }
    const src = S.lib[item.media_ref];
    const sf = sourceFrameAt(item, frame);
    drawSource(src, sf, burnIn);

    const node = ((files.color.grades[item.id] || {}).nodes || [])[0] || {};
    const g = { ...GRADE_DEFAULTS, ...node };
    const fx = files.effects.clip_effects[item.id] || {};
    gradeCtx.save();
    gradeCtx.clearRect(0, 0, VW, VH);
    gradeCtx.filter = `brightness(${g.gain_m}) contrast(${g.contrast}) saturate(${g.saturation}) hue-rotate(${g.hue}deg)` +
      (fx.blur ? ` blur(${fx.blur}px)` : "");
    gradeCtx.drawImage(srcCanvas, 0, 0);
    gradeCtx.filter = "none";
    if (g.temperature) {
      gradeCtx.globalCompositeOperation = "soft-light";
      gradeCtx.fillStyle = g.temperature > 0 ? "#ff8a1f" : "#1f7bff";
      gradeCtx.globalAlpha = Math.min(1, Math.abs(g.temperature) / 2000) * 0.8;
      gradeCtx.fillRect(0, 0, VW, VH);
      gradeCtx.globalAlpha = 1;
      gradeCtx.globalCompositeOperation = "source-over";
    }
    if (fx.vignette) {
      const vg = gradeCtx.createRadialGradient(VW / 2, VH / 2, VH * 0.3, VW / 2, VH / 2, VW * 0.62);
      vg.addColorStop(0, "rgba(0,0,0,0)");
      vg.addColorStop(1, `rgba(0,0,0,${fx.vignette})`);
      gradeCtx.fillStyle = vg; gradeCtx.fillRect(0, 0, VW, VH);
    }
    gradeCtx.restore();

    const t = item.transform || {};
    let alpha = (t.Opacity ?? 100) / 100;
    const into = frame - item.record_start_frame, left = item.record_end_frame - 1 - frame;
    if (fx.fade_in && into < fx.fade_in) alpha *= into / fx.fade_in;
    if (fx.fade_out && left < fx.fade_out) alpha *= left / fx.fade_out;
    ctx.save();
    ctx.globalAlpha = clamp(alpha, 0, 1);
    ctx.translate(VW / 2 + (t.Pan || 0) / 2, VH / 2 - (t.Tilt || 0) / 2);
    ctx.rotate(((t.RotationAngle || 0) * Math.PI) / 180);
    ctx.scale((t.ZoomX ?? 1) * (t.FlipX ? -1 : 1), (t.ZoomY ?? 1) * (t.FlipY ? -1 : 1));
    ctx.drawImage(gradeCanvas, -VW / 2, -VH / 2);
    ctx.restore();

    lines.unshift(h("div", {},
      `V${track.index}  ·  timeline frame ${frame} → `, h("b", {}, src ? src.name : item.media_ref),
      ` source frame `, h("b", {}, sf),
      speedOf(item) !== 1 ? `  (${Math.round(speedOf(item) * 100)}% speed)` : "",
      files.color.grades[item.id] ? "  ·  graded" : ""));
  }
  $("frameMap").replaceChildren(...lines);
  $("timecode").textContent = tc(frame);
  $("frameNo").textContent = `frame ${frame}`;
  syncVideos(frame);
}

let renderQueued = false;
function requestRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderViewer(); });
}

function syncVideos(frame) {
  const files = view();
  const active = {};
  for (const track of files.cuts.video_tracks) {
    const item = coveringClip(track, frame);
    const src = item && S.lib[item.media_ref];
    if (src && src.available && VIDEO_KINDS.has(src.kind)) active[src.ref] = item;
  }
  for (const [ref, v] of Object.entries(videos)) {
    const item = active[ref];
    if (!item) { if (!v.paused) v.pause(); v.muted = true; continue; }
    const t = sourceFrameAt(item, frame) / FPS;
    if (S.playing) {
      const a = findAudio(audioIdFor(item.id), files);
      v.playbackRate = clamp(speedOf(item), 0.25, 4);
      v.volume = clamp(Math.pow(10, ((a && a.volume) || 0) / 20), 0, 1);
      v.muted = false;
      if (v.paused) { v.currentTime = t; v.play().catch(() => {}); }
      else if (Math.abs(v.currentTime - t) > 0.3) v.currentTime = t;
    } else {
      if (!v.paused) v.pause();
      if (Math.abs(v.currentTime - t) > 0.5 / FPS) v.currentTime = t;
    }
  }
}

let lastTs = null;
function togglePlay() {
  S.playing = !S.playing;
  if (S.playing) {
    if (S.playhead >= contentEnd() - 1) S.playhead = 0;
    lastTs = null;
    requestAnimationFrame(tick);
  } else {
    renderViewer();
  }
  $("playBtn").textContent = S.playing ? "❚❚" : "▶";
}

function tick(ts) {
  if (!S.playing) return;
  if (lastTs !== null) S.playhead += ((ts - lastTs) / 1000) * FPS;
  lastTs = ts;
  const end = contentEnd();
  if (S.playhead >= end) { S.playhead = Math.max(0, end - 1); S.playing = false; $("playBtn").textContent = "▶"; }
  renderViewer();
  placePlayhead();
  if (S.playing) requestAnimationFrame(tick);
}

function setPlayhead(frame) {
  S.playhead = clamp(Math.round(frame), 0, timelineLength());
  renderViewer();
  placePlayhead();
}
