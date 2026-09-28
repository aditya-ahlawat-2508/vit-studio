"use strict";

// ── Timeline ───────────────────────────────────────────────────────────────

const tlContent = $("tlContent");

function issueClipIds() {
  if (readonly()) return new Set();
  const ids = new Set();
  for (const i of S.issues) {
    const d = i.details || {};
    for (const k of ["clip_a", "clip_b", "video_item", "item_id"]) if (d[k]) ids.add(d[k]);
  }
  return ids;
}

function renderTimeline() {
  const files = view();
  const z = S.zoom;
  const len = timelineLength();
  const vTracks = [...files.cuts.video_tracks].sort((a, b) => b.index - a.index);
  const aTracks = [...files.audio.audio_tracks].sort((a, b) => a.index - b.index);
  const selId = S.selected && S.selected.type === "clip" ? S.selected.id : null;
  const flagged = issueClipIds();

  $("tlLabels").replaceChildren(
    h("div", { class: "m" }, "M"),
    ...vTracks.map((t) => h("div", {}, `V${t.index}`)),
    ...aTracks.map((t) => h("div", {}, `A${t.index}`)),
  );

  const pxPerSec = z * FPS;
  const step = [1, 2, 5, 10, 15, 30, 60].find((s) => s * pxPerSec >= 70) || 60;
  const ruler = h("div", { class: "ruler", dataset: { role: "ruler" } });
  for (let s = 0; s * FPS < len; s += step) {
    ruler.append(h("div", { class: "tick", style: `left:${s * pxPerSec}px` }, tc(s * FPS).slice(3, 8)));
  }

  const markerLane = h("div", { class: "lane m", dataset: { role: "lane" } },
    files.markers.markers.map((m) => h("div", {
      class: "marker" + (S.selected && S.selected.type === "marker" && S.selected.id === m.frame ? " selected" : ""),
      style: `left:${m.frame * z}px;background:${MARKER_COLORS[m.color] || MARKER_COLORS.Blue}`,
      title: `${tc(m.frame)} — ${m.name}${m.note ? ": " + m.note : ""}`,
      dataset: { marker: m.frame },
    })));

  const videoLanes = vTracks.map((t) => h("div", { class: "lane", dataset: { role: "lane", vtrack: t.index } },
    t.items.map((c) => {
      const src = S.lib[c.media_ref];
      const badges = [];
      if (files.color.grades[c.id]) badges.push(h("span", {}, "CC"));
      if (files.effects.clip_effects[c.id]) badges.push(h("span", {}, "FX"));
      if (c.speed) badges.push(h("span", {}, `${c.speed.speed_percent}%`));
      return h("div", {
        class: "clip video" + (c.id === selId ? " selected" : "") + (flagged.has(c.id) ? " issue" : "") +
          (c.clip_enabled === false ? " disabled" : "") + (readonly() ? " readonly" : ""),
        style: `left:${c.record_start_frame * z}px;width:${Math.max(4, (c.record_end_frame - c.record_start_frame) * z)}px;background:${src ? src.color : "#777"}`,
        title: `${c.name}\nid ${c.id}\ntimeline ${c.record_start_frame}–${c.record_end_frame}  ·  source ${c.source_start_frame}–${c.source_end_frame}`,
        dataset: { clip: c.id },
      },
      h("div", { class: "name" }, c.name),
      h("div", { class: "badges" }, badges),
      readonly() ? null : h("div", { class: "h l", dataset: { handle: "l" } }),
      readonly() ? null : h("div", { class: "h r", dataset: { handle: "r" } }));
    })));

  const audioLanes = aTracks.map((t) => h("div", { class: "lane", dataset: { role: "lane", atrack: t.index } },
    t.items.map((a) => {
      const vid = videoIdFor(a.id);
      const linked = findClip(vid, files);
      return h("div", {
        class: "clip audio" + (vid === selId ? " selected" : "") + (flagged.has(a.id) || flagged.has(vid) ? " issue" : ""),
        style: `left:${a.start_frame * z}px;width:${Math.max(4, (a.end_frame - a.start_frame) * z)}px`,
        title: `Audio ${a.id}\nvolume ${a.volume} dB  ·  pan ${a.pan}`,
        dataset: { audio: a.id },
      },
      h("div", { class: "wave" }),
      h("div", { class: "name" }, `${linked ? linked.name : a.media_ref}  ${a.volume ? (a.volume > 0 ? "+" : "") + a.volume + " dB" : ""}`));
    })));

  tlContent.style.width = `${len * z}px`;
  tlContent.replaceChildren(ruler, markerLane, ...videoLanes, ...audioLanes, h("div", { class: "playhead", id: "playhead" }));
  placePlayhead();
}

function placePlayhead() {
  const ph = $("playhead");
  if (ph) ph.style.left = `${Math.floor(S.playhead) * S.zoom}px`;
  $("timecode").textContent = tc(S.playhead);
}

function frameAtClientX(x) {
  return (x - tlContent.getBoundingClientRect().left) / S.zoom;
}

function snapFrames(frame, ignoreId) {
  const tol = 8 / S.zoom;
  let best = null;
  const edges = [0, Math.floor(S.playhead)];
  for (const c of allClips(S.files)) if (c.id !== ignoreId) edges.push(c.record_start_frame, c.record_end_frame);
  for (const e of edges) if (Math.abs(frame - e) <= tol && (best === null || Math.abs(frame - e) < Math.abs(frame - best))) best = e;
  return best;
}

tlContent.addEventListener("pointerdown", (ev) => {
  if (ev.button !== 0) return;
  const clipEl = ev.target.closest(".clip.video");
  const audioEl = ev.target.closest(".clip.audio");
  const markerEl = ev.target.closest(".marker");
  const rulerEl = ev.target.closest(".ruler");

  if (markerEl) {
    S.selected = { type: "marker", id: Number(markerEl.dataset.marker) };
    setPlayhead(S.selected.id);
    render();
    return;
  }
  if (audioEl) {
    S.selected = { type: "clip", id: videoIdFor(audioEl.dataset.audio) };
    render();
    return;
  }
  if (clipEl) {
    const id = clipEl.dataset.clip;
    S.selected = { type: "clip", id };
    renderInspector();
    renderTimeline();
    if (readonly()) return;
    const c = findClip(id, S.files);
    const mode = ev.target.dataset.handle === "l" ? "trimL" : ev.target.dataset.handle === "r" ? "trimR" : "move";
    S.drag = {
      id, mode, x0: ev.clientX, moved: false,
      orig: { rs: c.record_start_frame, re: c.record_end_frame, ss: c.source_start_frame, se: c.source_end_frame, track: c.track_index },
    };
    ev.preventDefault();
    return;
  }
  // ruler or empty lane: scrub
  if (rulerEl || ev.target.closest(".lane")) {
    if (!rulerEl) { S.selected = null; renderInspector(); renderTimeline(); }
    S.drag = { mode: "scrub" };
    setPlayhead(frameAtClientX(ev.clientX));
    ev.preventDefault();
  }
});

window.addEventListener("pointermove", (ev) => {
  const d = S.drag;
  if (!d) return;
  if (d.mode === "scrub") { setPlayhead(frameAtClientX(ev.clientX)); return; }
  const c = findClip(d.id, S.files);
  if (!c) return;
  const dx = Math.round((ev.clientX - d.x0) / S.zoom);
  if (dx !== 0) d.moved = true;
  const o = d.orig, sp = speedOf(c);
  const trackItems = allClips(S.files).filter((x) => x.track_index === o.track && x.id !== c.id);

  if (d.mode === "move") {
    const len = o.re - o.rs;
    let s = Math.max(0, o.rs + dx);
    const snapS = snapFrames(s, c.id), snapE = snapFrames(s + len, c.id);
    if (snapS !== null) s = snapS; else if (snapE !== null) s = snapE - len;
    c.record_start_frame = Math.max(0, s);
    c.record_end_frame = c.record_start_frame + len;
    const lane = document.elementsFromPoint(ev.clientX, ev.clientY).find((e) => e.dataset && e.dataset.vtrack);
    if (lane) { c.track_index = Number(lane.dataset.vtrack); d.moved = true; }
  } else if (d.mode === "trimL") {
    const src = S.lib[c.media_ref];
    const prevEnd = trackItems.filter((x) => x.record_end_frame <= o.rs).reduce((m, x) => Math.max(m, x.record_end_frame), 0);
    const minRs = Math.max(prevEnd, o.rs - Math.floor(o.ss / sp));
    let rs = clamp(o.rs + dx, minRs, o.re - 1);
    const snap = snapFrames(rs, c.id);
    if (snap !== null && snap >= minRs && snap < o.re) rs = snap;
    c.record_start_frame = rs;
    c.source_start_frame = clamp(o.ss + Math.round((rs - o.rs) * sp), 0, src ? src.duration_frames - 1 : Infinity);
  } else {
    const src = S.lib[c.media_ref];
    const nextStart = trackItems.filter((x) => x.record_start_frame >= o.re).reduce((m, x) => Math.min(m, x.record_start_frame), Infinity);
    const maxRe = Math.min(nextStart, o.re + Math.floor(((src ? src.duration_frames : o.se) - o.se) / sp));
    let re = clamp(o.re + dx, o.rs + 1, maxRe);
    const snap = snapFrames(re, c.id);
    if (snap !== null && snap > o.rs && snap <= maxRe) re = snap;
    c.record_end_frame = re;
    c.source_end_frame = o.se + Math.round((re - o.re) * sp);
  }
  renderTimeline();
  renderViewer();
});

window.addEventListener("pointerup", () => {
  const d = S.drag;
  S.drag = null;
  if (!d || d.mode === "scrub" || !d.moved) return;
  const c = findClip(d.id, S.files);
  if (!c) return;
  const o = d.orig;
  const unchanged = c.record_start_frame === o.rs && c.record_end_frame === o.re && c.track_index === o.track;
  if (unchanged) return;
  if (overlapsOn(c.track_index, c.record_start_frame, c.record_end_frame, c.id)) {
    Object.assign(c, { record_start_frame: o.rs, record_end_frame: o.re, source_start_frame: o.ss, source_end_frame: o.se, track_index: o.track });
    toast("Clips can't overlap on the same track — try another spot or V2.");
    render();
    return;
  }
  edit(() => syncAudio(c));
  renderInspector();
});

// Drag from the media bin
tlContent.addEventListener("dragover", (ev) => {
  const lane = ev.target.closest(".lane");
  if (!lane || readonly() || !(lane.dataset.vtrack || lane.dataset.atrack)) return;
  ev.preventDefault();
  document.querySelectorAll(".lane.drop").forEach((l) => l.classList.remove("drop"));
  lane.classList.add("drop");
});
tlContent.addEventListener("dragleave", (ev) => {
  const lane = ev.target.closest(".lane");
  if (lane) lane.classList.remove("drop");
});
tlContent.addEventListener("drop", (ev) => {
  const lane = ev.target.closest(".lane");
  document.querySelectorAll(".lane.drop").forEach((l) => l.classList.remove("drop"));
  const ref = ev.dataTransfer.getData("text/vit-ref");
  if (!lane || !ref) return;
  ev.preventDefault();
  addClip(ref, Number(lane.dataset.vtrack || lane.dataset.atrack), frameAtClientX(ev.clientX));
});
