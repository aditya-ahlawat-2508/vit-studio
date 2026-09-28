"use strict";

// ── Live co-editing (vit/live/) — real-time sync over a small custom CRDT ──
//
// This file is dual-mode on purpose: everything above the `module.exports`
// guard is pure data logic (no DOM, no `window`, no `S`) and mirrors
// vit/live/crdt.py field-for-field — same normalize/flatten shape, same
// Lamport-clock LWW-register rule, same delete-wins semantics. That means it
// can be `require()`'d from Node and convergence-tested exactly like the
// Python side, with no browser needed (see tests/live/test_live_crdt.node.js).
// Everything below the guard is the actual browser wiring: a WebSocket
// connection to demo/studio/live_server.py and the hook into model.js's
// `edit()`.

// ── Normalize / denormalize (mirrors vit/merge/three_way.py) ───────────────

function liveKeyedItems(tracks, idKey, trackField) {
  const items = {};
  for (const track of tracks || []) {
    for (const item of track.items || []) {
      const entry = Object.assign({}, item, { [trackField]: track.index });
      items[String(entry[idKey])] = entry;
    }
  }
  return items;
}

function liveTrackExistence(tracks) {
  const out = {};
  for (const t of tracks || []) out[String(t.index)] = true;
  return out;
}

function liveNormalizeDomain(domain, data) {
  data = JSON.parse(JSON.stringify(data || {}));
  if (domain === "cuts") {
    const raw = data.video_tracks || [];
    data.video_tracks = liveKeyedItems(raw, "id", "track_index");
    data._tracks = liveTrackExistence(raw);
  } else if (domain === "audio") {
    const raw = data.audio_tracks || [];
    data.audio_tracks = liveKeyedItems(raw, "id", "_track");
    data._tracks = liveTrackExistence(raw);
  } else if (domain === "markers") {
    const out = {};
    for (const m of data.markers || []) out[String(m.frame)] = m;
    data.markers = out;
  }
  return data;
}

function liveUnkeyedTracks(items, trackField, startKey, keepField, trackIndices) {
  const byTrack = {};
  for (const idx of Object.keys(trackIndices || {})) byTrack[Number(idx)] = [];
  for (const item of Object.values(items || {})) {
    const entry = Object.assign({}, item);
    const idx = Number(entry[trackField] != null ? entry[trackField] : 1);
    if (!keepField) delete entry[trackField];
    (byTrack[idx] = byTrack[idx] || []).push(entry);
  }
  return Object.keys(byTrack).map(Number).sort((a, b) => a - b).map((idx) => ({
    index: idx,
    items: byTrack[idx].slice().sort((x, y) =>
      (x[startKey] || 0) - (y[startKey] || 0) || String(x.id || "").localeCompare(String(y.id || ""))),
  }));
}

function liveDenormalizeDomain(domain, data) {
  data = Object.assign({}, data);
  if (domain === "cuts") {
    const trackIndices = data._tracks || {};
    delete data._tracks;
    data.video_tracks = liveUnkeyedTracks(data.video_tracks, "track_index", "record_start_frame", true, trackIndices);
  } else if (domain === "audio") {
    const trackIndices = data._tracks || {};
    delete data._tracks;
    data.audio_tracks = liveUnkeyedTracks(data.audio_tracks, "_track", "start_frame", false, trackIndices);
  } else if (domain === "markers") {
    data.markers = Object.values(data.markers || {}).sort((a, b) => a.frame - b.frame);
  }
  return data;
}

// ── Flatten / assign (mirrors vit/live/crdt.py's _flatten / _assign) ───────

function liveFlatten(prefix, node) {
  const isPlainObject = node && typeof node === "object" && !Array.isArray(node);
  if (isPlainObject && Object.keys(node).length > 0) {
    let pairs = [];
    for (const key of Object.keys(node)) {
      pairs = pairs.concat(liveFlatten(prefix.concat(String(key)), node[key]));
    }
    return pairs;
  }
  return [[prefix, node]]; // empty object, array, or scalar — all leaves
}

function liveAssign(root, path, value) {
  let node = root;
  for (let i = 0; i < path.length - 1; i++) {
    const key = path[i];
    if (!(key in node)) node[key] = {};
    node = node[key];
  }
  node[path[path.length - 1]] = value;
}

const LIVE_DOMAINS = ["cuts", "color", "audio", "effects", "markers", "metadata", "manifest"];
const LIVE_EXISTS = "__exists__";

function tsGte(a, b) {
  // a >= b, lexicographic on [counter, client_id] — mirrors Python tuple compare.
  if (a[0] !== b[0]) return a[0] > b[0];
  return a[1] >= b[1];
}

// ── The CRDT itself (mirrors vit/live/crdt.py::CRDTDoc) ────────────────────

class LiveCRDT {
  constructor(clientId) {
    this.clientId = clientId;
    this.counter = 0;
    this.cells = new Map(); // JSON.stringify(path) -> {path, value, timestamp:[counter, clientId]}
  }

  loadFromFiles(files) {
    this.cells = new Map();
    for (const domain of LIVE_DOMAINS) {
      const normalized = liveNormalizeDomain(domain, (files && files[domain]) || {});
      if (Object.keys(normalized).length === 0) continue;
      for (const [path, value] of liveFlatten([domain], normalized)) {
        this.cells.set(JSON.stringify(path), { path, value, timestamp: [0, ""] });
      }
    }
  }

  applyLocal(path, value) {
    this.counter += 1;
    const timestamp = [this.counter, this.clientId];
    this.cells.set(JSON.stringify(path), { path, value, timestamp });
    return { path, value, timestamp };
  }

  deleteItem(itemPath) {
    return this.applyLocal(itemPath.concat(LIVE_EXISTS), false);
  }

  applyRemote(update) {
    const key = JSON.stringify(update.path);
    const current = this.cells.get(key);
    if (current && tsGte(current.timestamp, update.timestamp)) {
      return false; // already at this state or ahead of it — safe no-op either way
    }
    this.cells.set(key, { path: update.path, value: update.value, timestamp: update.timestamp });
    this.counter = Math.max(this.counter, update.timestamp[0]);
    return true;
  }

  snapshot() {
    const deletedItems = [];
    for (const cell of this.cells.values()) {
      if (cell.path[cell.path.length - 1] === LIVE_EXISTS && cell.value === false) {
        deletedItems.push(cell.path.slice(0, -1));
      }
    }
    const isUnderDeleted = (path) => deletedItems.some(
      (itemPath) => itemPath.length <= path.length && itemPath.every((k, i) => k === path[i]));

    const byDomain = {};
    for (const cell of this.cells.values()) {
      const path = cell.path;
      if (path[path.length - 1] === LIVE_EXISTS) continue;
      if (isUnderDeleted(path)) continue;
      const domain = path[0];
      liveAssign(byDomain[domain] || (byDomain[domain] = {}), path.slice(1), cell.value);
    }
    const out = {};
    for (const domain of LIVE_DOMAINS) out[domain] = liveDenormalizeDomain(domain, byDomain[domain] || {});
    return out;
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    liveNormalizeDomain, liveDenormalizeDomain, liveFlatten, liveAssign, LiveCRDT, LIVE_DOMAINS,
  };
}

// ── Browser wiring: WebSocket transport + the edit() hook ──────────────────

if (typeof window !== "undefined") {
  (function () {
    let ws = null;
    let doc = null;
    let applyingRemote = false; // true while a remote snapshot/update is being
                                 // applied to S.files, so the edit() hook that
                                 // fires from render()-adjacent code doesn't
                                 // re-diff and re-broadcast our own echo back.
    const clientId = Math.random().toString(36).slice(2, 10);

    function connectLive(port) {
      doc = new LiveCRDT(clientId);
      ws = new WebSocket(`ws://${location.hostname}:${port}`);
      ws.addEventListener("message", (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "snapshot") {
          doc.loadFromFiles(msg.files);
          applyRemoteSnapshot();
        } else if (msg.type === "update" && doc.applyRemote(msg.update)) {
          applyRemoteSnapshot();
        }
      });
      ws.addEventListener("close", () => { ws = null; });
    }

    function applyRemoteSnapshot() {
      applyingRemote = true;
      try {
        S.files = ensureShape(doc.snapshot());
        if (S.selected && S.selected.type === "clip" && !findClip(S.selected.id)) S.selected = null;
        render();
      } finally {
        applyingRemote = false;
      }
    }

    function diffAndBroadcast(prevFiles, newFiles) {
      if (applyingRemote || !doc || !ws || ws.readyState !== WebSocket.OPEN) return;
      for (const domain of LIVE_DOMAINS) {
        const before = liveNormalizeDomain(domain, prevFiles[domain] || {});
        const after = liveNormalizeDomain(domain, newFiles[domain] || {});

        // Deletions first: an item (clip/track entry) present before and gone
        // after doesn't show up as a field diff — its fields just vanish.
        for (const listKey of ["video_tracks", "audio_tracks"]) {
          if (!before[listKey] && !after[listKey]) continue;
          const beforeIds = new Set(Object.keys(before[listKey] || {}));
          const afterIds = new Set(Object.keys(after[listKey] || {}));
          for (const id of beforeIds) {
            if (!afterIds.has(id)) send(doc.deleteItem([domain, listKey, id]));
          }
        }

        const beforeLeaves = new Map(liveFlatten([domain], before).map(([p, v]) => [JSON.stringify(p), v]));
        const afterLeaves = liveFlatten([domain], after);
        for (const [path, value] of afterLeaves) {
          const key = JSON.stringify(path);
          if (!beforeLeaves.has(key) || JSON.stringify(beforeLeaves.get(key)) !== JSON.stringify(value)) {
            send(doc.applyLocal(path, value));
          }
        }
      }
    }

    function send(update) {
      ws.send(JSON.stringify({ type: "update", update }));
    }

    window.connectLive = connectLive;
    window.onLiveEdit = diffAndBroadcast; // called by model.js's edit(), if defined
  })();
}
