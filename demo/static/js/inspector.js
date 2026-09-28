"use strict";

// ── Inspector ──────────────────────────────────────────────────────────────

function slider(label, value, min, max, step, fmt, onInput) {
  const out = h("output", {}, fmt(value));
  const input = h("input", {
    type: "range", min, max, step, value,
    oninput: (ev) => { const v = Number(ev.target.value); out.textContent = fmt(v); onInput(v); },
  });
  return h("div", { class: "field" }, h("label", {}, label), input, out);
}

// Slider edits mutate in place and re-render the viewer + timeline without
// rebuilding the inspector (which would steal focus from the slider).
function liveEdit(fn) {
  if (readonly()) return;
  fn();
  sortAll();
  renderViewer();
  renderTimeline();
  scheduleSync();
}

function gradeNode(id, create) {
  const grades = S.files.color.grades;
  if (!grades[id] && create) {
    grades[id] = { num_nodes: 1, nodes: [{ index: 1, label: "Primary", lut: "" }], version_name: "Version 1", drx_file: null, lut_file: null };
  }
  return grades[id] ? grades[id].nodes[0] : null;
}

function setGrade(id, key, value) {
  const isDefault = Math.abs(value - GRADE_DEFAULTS[key]) < 1e-9;
  const node = gradeNode(id, !isDefault);
  if (!node) return;
  if (isDefault) delete node[key]; else node[key] = round3(value);
  if (!Object.keys(GRADE_DEFAULTS).some((k) => k in node)) delete S.files.color.grades[id];
}

function setEffect(id, key, value, isDefault) {
  const all = S.files.effects.clip_effects;
  const fx = all[id] || {};
  if (isDefault) delete fx[key]; else fx[key] = value;
  if (Object.keys(fx).length) all[id] = fx; else delete all[id];
}

const GRADE_PRESETS = {
  "Warm film": { saturation: 0.9, contrast: 1.15, temperature: 900, gain_m: 1.05, hue: 0 },
  "Cool night": { saturation: 0.85, contrast: 1.2, temperature: -1200, gain_m: 0.9, hue: 0 },
  "Punchy": { saturation: 1.45, contrast: 1.25, temperature: 0, gain_m: 1, hue: 0 },
  "B&W": { saturation: 0, contrast: 1.3, temperature: 0, gain_m: 1, hue: 0 },
  "Reset": { ...GRADE_DEFAULTS },
};

function renderInspector() {
  const box = $("inspector");
  const sel = S.selected;
  const files = view();
  if (!sel) {
    box.replaceChildren(h("p", { class: "empty" }, "Select a clip or marker on the timeline. Every control here edits one of the JSON files vit tracks — the small label on each group shows which."));
    return;
  }
  if (sel.type === "marker") {
    const m = files.markers.markers.find((x) => x.frame === sel.id);
    if (!m) { S.selected = null; return renderInspector(); }
    const ro = readonly();
    box.replaceChildren(
      h("div", { class: "insp-title" }, `Marker at ${tc(m.frame)}`),
      h("div", { class: "insp-sub" }, "markers.json"),
      h("div", { class: "field text" }, h("label", {}, "Name"),
        h("input", { value: m.name, disabled: ro, oninput: (ev) => liveEdit(() => { m.name = ev.target.value; }) })),
      h("div", { class: "field text" }, h("label", {}, "Note"),
        h("input", { value: m.note, disabled: ro, oninput: (ev) => liveEdit(() => { m.note = ev.target.value; }) })),
      h("div", { class: "field text" }, h("label", {}, "Color"),
        h("select", { disabled: ro, onchange: (ev) => liveEdit(() => { m.color = ev.target.value; }) },
          Object.keys(MARKER_COLORS).map((c) => h("option", { value: c, selected: c === m.color }, c)))),
      ro ? null : h("div", { class: "insp-actions" }, h("button", {
        class: "small danger",
        onclick: () => { edit(() => { S.files.markers.markers = S.files.markers.markers.filter((x) => x !== m); S.selected = null; }); renderInspector(); },
      }, "Delete marker")),
    );
    return;
  }

  const c = findClip(sel.id, files);
  if (!c) { S.selected = null; return renderInspector(); }
  if (readonly()) {
    box.replaceChildren(
      h("div", { class: "insp-title" }, c.name),
      h("div", { class: "insp-sub" }, c.id),
      h("p", { class: "empty" }, "Read-only preview of an older version."),
      h("pre", { class: "diff" }, JSON.stringify(c, null, 2)));
    return;
  }
  const t = c.transform || (c.transform = { Pan: 0, Tilt: 0, ZoomX: 1, ZoomY: 1, Opacity: 100 });
  const node = gradeNode(c.id, false) || {};
  const g = { ...GRADE_DEFAULTS, ...node };
  const fx = S.files.effects.clip_effects[c.id] || {};
  const a = findAudio(audioIdFor(c.id), S.files);
  const src = S.lib[c.media_ref];

  const gradeSliders = h("div", {},
    slider("Exposure", g.gain_m, 0.3, 2, 0.01, (v) => v.toFixed(2), (v) => liveEdit(() => setGrade(c.id, "gain_m", v))),
    slider("Contrast", g.contrast, 0.3, 2, 0.01, (v) => v.toFixed(2), (v) => liveEdit(() => setGrade(c.id, "contrast", v))),
    slider("Saturation", g.saturation, 0, 2, 0.01, (v) => v.toFixed(2), (v) => liveEdit(() => setGrade(c.id, "saturation", v))),
    slider("Temp", g.temperature, -2000, 2000, 50, (v) => `${v > 0 ? "+" : ""}${v}`, (v) => liveEdit(() => setGrade(c.id, "temperature", v))),
    slider("Hue", g.hue, -180, 180, 1, (v) => `${v}°`, (v) => liveEdit(() => setGrade(c.id, "hue", v))),
  );

  box.replaceChildren(
    h("div", { class: "insp-title" }, c.name),
    h("div", { class: "insp-sub" }, `${c.id}  ·  source ${c.source_start_frame}–${c.source_end_frame} of ${src ? src.duration_frames : "?"}`),

    h("div", { class: "insp-group" },
      h("h3", {}, "Edit", h("span", { class: "domain-tag" }, "cuts.json")),
      slider("Zoom", t.ZoomX ?? 1, 0.5, 3, 0.01, (v) => v.toFixed(2), (v) => liveEdit(() => { t.ZoomX = round3(v); t.ZoomY = round3(v); })),
      slider("Pan", t.Pan || 0, -960, 960, 1, String, (v) => liveEdit(() => { t.Pan = v; })),
      slider("Tilt", t.Tilt || 0, -540, 540, 1, String, (v) => liveEdit(() => { t.Tilt = v; })),
      slider("Rotate", t.RotationAngle || 0, -180, 180, 1, (v) => `${v}°`, (v) => liveEdit(() => { if (v) t.RotationAngle = v; else delete t.RotationAngle; })),
      slider("Opacity", t.Opacity ?? 100, 0, 100, 1, (v) => `${v}%`, (v) => liveEdit(() => { t.Opacity = v; })),
      h("div", { class: "field text" }, h("label", {}, "Speed"),
        h("select", { onchange: (ev) => edit(() => setSpeed(c, Number(ev.target.value))) },
          [25, 50, 75, 100, 150, 200, 400].map((p) => h("option", { value: p, selected: p === Math.round(speedOf(c) * 100) }, `${p}%`)))),
      h("div", { class: "field text" }, h("label", {}, "Enabled"),
        h("input", { type: "checkbox", checked: c.clip_enabled !== false, style: "justify-self:start",
          onchange: (ev) => edit(() => { if (ev.target.checked) delete c.clip_enabled; else c.clip_enabled = false; }) })),
    ),

    h("div", { class: "insp-group" },
      h("h3", {}, "Color", h("span", { class: "domain-tag" }, "color.json")),
      h("div", { class: "presets" }, Object.entries(GRADE_PRESETS).map(([name, vals]) => h("button", {
        class: "small ghost",
        onclick: () => { edit(() => Object.entries(vals).forEach(([k, v]) => setGrade(c.id, k, v))); renderInspector(); },
      }, name))),
      gradeSliders,
    ),

    h("div", { class: "insp-group" },
      h("h3", {}, "Effects", h("span", { class: "domain-tag" }, "effects.json")),
      slider("Blur", fx.blur || 0, 0, 20, 0.5, (v) => `${v}px`, (v) => liveEdit(() => setEffect(c.id, "blur", v, v === 0))),
      slider("Vignette", fx.vignette || 0, 0, 1, 0.05, (v) => v.toFixed(2), (v) => liveEdit(() => setEffect(c.id, "vignette", round3(v), v === 0))),
      slider("Fade in", fx.fade_in || 0, 0, 48, 1, (v) => `${v}f`, (v) => liveEdit(() => setEffect(c.id, "fade_in", v, v === 0))),
      slider("Fade out", fx.fade_out || 0, 0, 48, 1, (v) => `${v}f`, (v) => liveEdit(() => setEffect(c.id, "fade_out", v, v === 0))),
    ),

    a ? h("div", { class: "insp-group" },
      h("h3", {}, "Audio", h("span", { class: "domain-tag" }, "audio.json")),
      slider("Volume", a.volume, -40, 12, 0.5, (v) => `${v > 0 ? "+" : ""}${v} dB`, (v) => liveEdit(() => { a.volume = v; })),
      slider("Pan", a.pan, -100, 100, 1, String, (v) => liveEdit(() => { a.pan = v; })),
    ) : null,

    h("div", { class: "insp-actions" },
      h("button", { class: "small", onclick: () => splitClip(c.id, S.playhead) }, "Split at playhead"),
      h("button", { class: "small danger", onclick: () => deleteClip(c.id) }, "Delete clip")),
  );
}
