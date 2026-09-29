"use strict";

// ── Modal helpers ──────────────────────────────────────────────────────────

function openModal(title, ...body) {
  $("modalTitle").textContent = title;
  $("modalBody").replaceChildren(...body);
  $("modal").hidden = false;
}
function closeModal() { $("modal").hidden = true; S.mergeFiles = null; }
$("modalClose").addEventListener("click", closeModal);
$("modal").addEventListener("click", (ev) => { if (ev.target === $("modal")) closeModal(); });

function diffBox(text) {
  const box = h("div", { class: "diff" });
  diffLines(text, box);
  return box;
}

async function openCommit(c) {
  try {
    const { diff } = await api(`/api/commit?ref=${c.hash}`);
    openModal(`${c.message.replace(/^vit:\s*/, "")}  ·  ${c.hash}`,
      h("div", { class: "muted" }, `${c.author} · ${c.date}${c.parents.length > 1 ? " · combined from two version lines" : ""}`),
      h("h3", {}, c.parents.length ? "What this version changed" : "Initial snapshot"),
      diffBox(diff),
      h("div", { class: "modal-actions" },
        h("button", { onclick: () => startPreview(c) }, "Preview in viewer"),
        h("button", { class: "accent", onclick: () => restoreVersion(c.hash) }, "Restore this version")));
  } catch (e) { toast(e.message, true); }
}

async function startPreview(c) {
  try {
    const { files } = await api(`/api/files?ref=${c.hash}`);
    S.preview = { ref: c.hash, files: ensureShape(files), label: c.message.replace(/^vit:\s*/, "") };
    S.selected = null;
    closeModal();
    render();
  } catch (e) { toast(e.message, true); }
}

async function restoreVersion(ref) {
  try {
    await flushSync();
    const r = await api("/api/restore", { ref, author: author() });
    S.preview = null;
    closeModal();
    await loadAll();
    toast(r.hash ? `Restored ${ref} as a new version (${r.hash}). Nothing in history was lost.` : "Working copy already matches that version.");
  } catch (e) { toast(e.message, true); }
}
