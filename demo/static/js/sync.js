"use strict";

// ── Sync working copy → server (writes JSON to disk) ────────────────────────

let syncTimer = null, pendingSync = false, syncChain = Promise.resolve();

function scheduleSync() {
  pendingSync = true;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(flushSync, 250);
}

function flushSync() {
  clearTimeout(syncTimer);
  if (!pendingSync) return syncChain;
  pendingSync = false;
  const payload = clone(S.files);
  syncChain = syncChain
    .then(() => api("/api/working", { files: payload }))
    .then((r) => {
      S.dirty = r.dirty; S.diff = r.diff; S.issues = r.issues;
      renderVC(); renderTimeline();
      if (S.view === "json") loadJson();
    })
    .catch((e) => toast(e.message, true));
  return syncChain;
}
