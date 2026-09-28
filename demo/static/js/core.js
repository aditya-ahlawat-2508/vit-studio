"use strict";

// Constants, shared editor state, DOM/format helpers and the API client.

// Vit Studio — a tiny NLE whose whole timeline is the domain-split JSON that
// vit versions. Edits mutate that JSON in memory; the server writes it to
// disk with vit's own models, and git does everything else.

const FPS = 24;
const VW = 960, VH = 540;
const VIDEO_KINDS = new Set(["video"]);
const MARKER_COLORS = { Blue: "#5b8cff", Red: "#ff5b5b", Green: "#4ade80", Yellow: "#facc15", Purple: "#b57bff", Cyan: "#22d3ee" };
const GRADE_DEFAULTS = { saturation: 1, contrast: 1, gain_m: 1, hue: 0, temperature: 0 };
const LANE_COLORS = ["#f5a524", "#6ea8fe", "#4ade80", "#f472b6", "#a78bfa", "#22d3ee", "#fb923c"];

const S = {
  files: null, library: [], lib: {},
  branch: "main", branches: [], detached: false, dirty: false, diff: "", issues: [], head: "",
  commits: [],
  selected: null,           // {type: "clip"|"marker", id}
  playhead: 0, playing: false, zoom: 2,
  preview: null,            // {ref, files, label} — read-only view of an older version
  mergeFiles: null,         // {ours, theirs} full snapshots while a conflict modal is open
  view: "viewer", jsonFile: "timeline/cuts.json",
  drag: null,
};

const $ = (id) => document.getElementById(id);

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const clone = (x) => JSON.parse(JSON.stringify(x));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const round3 = (v) => Math.round(v * 1000) / 1000;

function tc(frames) {
  const f = Math.max(0, Math.floor(frames));
  const ff = f % FPS, s = Math.floor(f / FPS);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor(s / 60) % 60)}:${p(s % 60)}:${p(ff)}`;
}

function toast(msg, isError = false) {
  const t = h("div", { class: "toast" + (isError ? " error" : "") }, msg);
  $("toasts").append(t);
  setTimeout(() => t.remove(), isError ? 6000 : 3500);
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-Vit-Demo": "1" }, body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function author() {
  return $("authorInput").value.trim() || "Vit Demo";
}
