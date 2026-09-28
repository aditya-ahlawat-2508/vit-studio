"use strict";

// ── Loading + top-level render ─────────────────────────────────────────────

async function loadAll() {
  const st = await api("/api/state");
  Object.assign(S, {
    files: ensureShape(st.files), library: st.library, branch: st.branch, branches: st.branches,
    detached: st.detached, dirty: st.dirty, diff: st.diff, issues: st.issues, head: st.head,
  });
  S.lib = Object.fromEntries(S.library.map((s) => [s.ref, s]));
  if (S.selected && S.selected.type === "clip" && !findClip(S.selected.id)) S.selected = null;
  renderBin();
  render();
  await loadLog();
  if (S.view === "json") loadJson();
}

async function loadLog() {
  const r = await api("/api/log");
  S.commits = r.commits;
  renderGraph();
}

function render() {
  const pv = S.preview;
  $("previewBanner").hidden = !pv;
  if (pv) $("previewLabel").textContent = `Previewing ${pv.ref} — “${pv.label}” (read-only)`;
  renderTimeline();
  renderViewer();
  renderInspector();
  renderVC();
}

// ── Wiring ─────────────────────────────────────────────────────────────────

$("playBtn").addEventListener("click", togglePlay);
$("splitBtn").addEventListener("click", () => {
  if (S.selected && S.selected.type === "clip") splitClip(S.selected.id, S.playhead);
  else toast("Select a clip first.");
});
$("markerBtn").addEventListener("click", addMarker);
$("burnIn").addEventListener("change", renderViewer);
$("zoomRange").addEventListener("input", (ev) => { S.zoom = Number(ev.target.value); renderTimeline(); });

document.querySelectorAll(".center-tabs .tab").forEach((tab) => tab.addEventListener("click", () => {
  S.view = tab.dataset.view;
  document.querySelectorAll(".center-tabs .tab").forEach((t) => t.classList.toggle("active", t === tab));
  $("viewerWrap").hidden = S.view !== "viewer";
  $("jsonWrap").hidden = S.view !== "json";
  if (S.view === "json") flushSync().then(loadJson);
}));

$("previewExit").addEventListener("click", () => { S.preview = null; S.selected = null; render(); });
$("previewRestore").addEventListener("click", () => restoreVersion(S.preview.ref));

$("commitForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await flushSync();
    const msg = $("commitMsg").value.trim();
    if (!msg) { $("commitMsg").focus(); toast("Give this version a short description."); return; }
    const r = await api("/api/commit", { message: msg, author: author() });
    $("commitMsg").value = "";
    toast(r.hash ? `Saved version ${r.hash} on ${S.branch}` : "Nothing changed since the last version.");
    await loadAll();
  } catch (e) { toast(e.message, true); }
});

$("branchSelect").addEventListener("change", async (ev) => {
  const ref = ev.target.value;
  try {
    await flushSync();
    const r = await api("/api/checkout", { ref, author: author() });
    S.preview = null;
    await loadAll();
    toast(r.autosaved ? `Auto-saved your changes (${r.autosaved}), then switched to ${ref}.` : `Switched to ${ref}. The timeline was rebuilt from its JSON.`);
  } catch (e) { toast(e.message, true); renderVC(); }
});

$("newBranchBtn").addEventListener("click", () => { $("newBranchForm").hidden = false; $("newBranchName").focus(); });
$("newBranchCancel").addEventListener("click", () => { $("newBranchForm").hidden = true; });
$("newBranchForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const name = $("newBranchName").value.trim();
  if (!name) return;
  try {
    await flushSync();
    const from = S.branch;
    await api("/api/branch", { name });
    $("newBranchName").value = "";
    $("newBranchForm").hidden = true;
    await loadAll();
    toast(`Created ${name} from ${from} — edits here won't touch ${from}.`);
  } catch (e) { toast(e.message, true); }
});

$("mergeBtn").addEventListener("click", async () => { await flushSync(); openMerge(); });

$("resetBtn").addEventListener("click", () => {
  openModal("Reset the demo?",
    h("p", {}, "This deletes the demo git repository (all branches and versions) and starts again from the starter timeline. Imported media stays in the media bin."),
    h("div", { class: "modal-actions" },
      h("button", { class: "ghost", onclick: closeModal }, "Cancel"),
      h("button", { class: "accent", onclick: async () => {
        try {
          clearTimeout(syncTimer); pendingSync = false;
          await api("/api/reset", {});
          S.preview = null; S.selected = null; S.playhead = 0;
          closeModal();
          await loadAll();
          toast("Fresh project on main.");
        } catch (e) { toast(e.message, true); }
      } }, "Reset")));
});

try { $("authorInput").value = localStorage.getItem("vit-demo-author") || ""; } catch (_) { /* storage unavailable */ }
$("authorInput").addEventListener("input", (ev) => {
  try { localStorage.setItem("vit-demo-author", ev.target.value); } catch (_) { /* ignore */ }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") { if (!$("modal").hidden) closeModal(); return; }
  if (ev.target.closest("input, textarea, select") || !$("modal").hidden) return;
  const sel = S.selected;
  if (ev.key === " ") { ev.preventDefault(); togglePlay(); }
  else if (ev.key === "ArrowLeft") { ev.preventDefault(); setPlayhead(S.playhead - (ev.shiftKey ? FPS : 1)); }
  else if (ev.key === "ArrowRight") { ev.preventDefault(); setPlayhead(S.playhead + (ev.shiftKey ? FPS : 1)); }
  else if ((ev.key === "Delete" || ev.key === "Backspace") && sel) {
    ev.preventDefault();
    if (sel.type === "clip") deleteClip(sel.id);
    else { edit(() => { S.files.markers.markers = S.files.markers.markers.filter((m) => m.frame !== sel.id); S.selected = null; }); renderInspector(); }
  }
  else if (ev.key === "s" && sel && sel.type === "clip") splitClip(sel.id, S.playhead);
  else if (ev.key === "m") addMarker();
});

loadAll().catch((e) => toast(`Could not reach the vit demo server: ${e.message}`, true));
