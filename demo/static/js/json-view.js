"use strict";

// ── JSON-on-disk view ──────────────────────────────────────────────────────

const JSON_FILES = ["timeline/cuts.json", "timeline/color.json", "timeline/audio.json", "timeline/effects.json",
  "timeline/markers.json", "timeline/metadata.json", "assets/manifest.json"];

async function loadJson() {
  $("jsonFiles").replaceChildren(...JSON_FILES.map((f) => h("button", {
    class: "small" + (f === S.jsonFile ? " active" : ""),
    onclick: () => { S.jsonFile = f; loadJson(); },
  }, f)));
  try {
    const r = await api(`/api/raw?path=${encodeURIComponent(S.jsonFile)}`);
    $("jsonContent").textContent = r.content;
    const lines = r.git_diff.split("\n").map((l) => h("div", {
      class: l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : "",
    }, l || " "));
    $("jsonDiff").replaceChildren(...(r.git_diff.trim() ? lines : [h("div", { class: "muted" }, "No unsaved changes in this file.")]));
  } catch (e) { toast(e.message, true); }
}
