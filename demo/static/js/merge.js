"use strict";

// ── Merge ──────────────────────────────────────────────────────────────────

function findClipInFiles(files, id) {
  if (!files || !files.cuts) return null;
  for (const t of files.cuts.video_tracks || []) {
    const c = (t.items || []).find((i) => i.id === id);
    if (c) return c;
  }
  return null;
}

function conflictLabel(c) {
  const parts = c.path.split("/");
  const name = (id) => { const cl = findClip(id, S.files); return cl ? `"${cl.name}"` : "a clip"; };
  const field = () => { const f = describeField(parts[parts.length - 1]); return f ? ` — ${f}` : ""; };
  let base;
  if (parts[0] === "cuts" && parts[2]) base = `Clip ${name(parts[2])}${field()}`;
  else if (parts[0] === "color" && parts[2]) base = `Color grade on ${name(parts[2])}${field()}`;
  else if (parts[0] === "effects" && parts[2]) base = `Effects on ${name(parts[2])}${field()}`;
  else if (parts[0] === "audio" && parts[2]) base = `Audio on ${name(videoIdFor(parts[2]))}${field()}`;
  else if (parts[0] === "markers" && parts[2]) base = `Marker at ${tc(Number(parts[2]))}${field()}`;
  else base = `A property of this ${describeDomain(parts[0])}`;
  return c.time_range ? `${c.time_range.start_tc} → ${c.time_range.end_tc}  ·  ${base}` : base;
}

const showValue = (v, c) => formatConflictValue(v, c);

// ── Step 1: every branch at once ────────────────────────────────────────────

function openMerge() {
  if (S.detached) return toast("Switch to a version line before combining.", true);
  const result = h("div", { style: "display:flex;flex-direction:column;gap:14px" });
  openModal(`Combine into ${S.branch}`, result);
  loadBranchList(result);
}

async function loadBranchList(target) {
  target.replaceChildren(h("div", { class: "muted" }, "Checking every version line…"));
  try {
    await flushSync();
    const r = await api("/api/branches/status");
    if (!r.branches.length) {
      target.replaceChildren(h("div", { class: "callout good" }, h("b", {}, "Nothing to combine"),
        "Create another version line first, make some edits there, then combine it back."));
      return;
    }
    target.replaceChildren(
      h("div", { class: "muted" }, "Every other version line, checked up front — pick one to see what's different."),
      ...r.branches.map((s) => h("div", { class: "branch-list-row", onclick: () => compare(s.branch, target) },
        h("span", { class: "branch-name" }, s.branch),
        s.up_to_date
          ? h("span", { class: "status clean" }, "up to date")
          : s.clean
            ? h("span", { class: "status clean" }, "no decisions needed")
            : h("span", { class: "status conflicts" }, `${s.conflict_count} decision${s.conflict_count === 1 ? "" : "s"} needed`))),
    );
  } catch (e) {
    target.replaceChildren(h("div", { class: "callout bad" }, e.message));
  }
}

async function compare(branch, target, excluded = new Set()) {
  target.replaceChildren(h("div", { class: "muted" }, "Comparing…"));
  try {
    await flushSync();
    const q = `branch=${encodeURIComponent(branch)}` + (excluded.size ? `&exclude_auto=${encodeURIComponent([...excluded].join(","))}` : "");
    const r = await api(`/api/compare?${q}`);
    if (r.up_to_date) {
      target.replaceChildren(
        h("button", { class: "back-link", onclick: () => loadBranchList(target) }, "‹ All version lines"),
        h("div", { class: "callout good" }, h("b", {}, "Nothing to combine"), `${S.branch} already contains everything from ${branch}.`));
      return;
    }
    if (r.git_text_conflicts.length) console.debug("vit: git text conflicts in", r.git_text_conflicts);
    // Every auto-applied resolution stays fully visible here, with a one-click
    // undo that re-runs the comparison excluding it — it reappears as a normal
    // conflict below, never just silently vanishes.
    const autoSection = r.auto_applied.length
      ? h("div", { class: "callout warn" },
          h("b", {}, `${r.auto_applied.length} thing${r.auto_applied.length === 1 ? "" : "s"} combined automatically`),
          r.auto_applied.map((s) => h("div", { class: "auto-applied-row" },
            h("span", {}, `${s.reason} — ${Math.round(s.confidence * 100)}% sure`),
            h("button", { class: "small", onclick: () => compare(branch, target, new Set([...excluded, s.path])) }, "Undo, let me choose"))))
      : null;
    target.replaceChildren(
      h("button", { class: "back-link", onclick: () => loadBranchList(target) }, "‹ All version lines"),
      autoSection,
      h("div", { class: "cols2" },
        h("div", {}, h("h3", {}, `Changed on ${S.branch} since the split`), diffBox(r.ours_diff)),
        h("div", {}, h("h3", {}, `Changed on ${branch} since the split`), diffBox(r.theirs_diff))),
      r.conflicts.length
        ? h("div", { class: "callout bad" }, h("b", {}, `${r.conflicts.length} thing${r.conflicts.length === 1 ? "" : "s"} need your decision`),
          "Both version lines changed the same thing on the same clip. You'll pick which one to keep.")
        : h("div", { class: "callout good" }, h("b", {}, "Nothing needs a decision"),
          "Every clip, grade, effect and marker from both version lines combines cleanly."),
      r.dirty ? h("div", { class: "muted" }, "Your unsaved changes will be saved as a version first.") : null,
      h("div", { class: "modal-actions" },
        h("button", { class: "ghost", onclick: closeModal }, "Cancel"),
        h("button", { class: "accent", onclick: () => doMerge(branch, target, r.auto_resolutions) }, `Combine ${branch} → ${S.branch}`)),
    );
  } catch (e) {
    target.replaceChildren(h("div", { class: "callout bad" }, e.message));
  }
}

async function doMerge(branch, target, resolutions) {
  try {
    await flushSync();
    const r = await api("/api/merge", { branch, author: author(), resolutions });
    if (r.status === "up_to_date") { toast("Already up to date."); closeModal(); return; }
    if (r.status === "conflicts") return showConflicts(branch, r, target);
    if (r.git_text_conflicts.length) console.debug("vit: git text conflicts handled in", r.git_text_conflicts);
    await loadAll();
    target.replaceChildren(
      h("div", { class: "callout good" }, h("b", {}, `Combined ${branch} into ${S.branch}  ·  ${r.hash}`),
        `Both version lines are now combined into ${S.branch}.`),
      h("h3", {}, `What came in from ${branch}`), diffBox(r.diff),
      r.issues.length
        ? h("div", { class: "callout warn" }, h("b", {}, "A few things to check"), r.issues.map((i) => h("div", {}, `• ${i.message}`)),
          h("div", { class: "muted", style: "margin-top:6px" }, "These are also listed under Unsaved changes, with quick fixes."))
        : h("div", { class: "callout good" }, h("b", {}, "Everything checks out"), "No orphaned grades, overlaps or sync problems."),
      h("div", { class: "modal-actions" }, h("button", { class: "accent", onclick: closeModal }, "Done")),
    );
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Step 2/3: time-ranged, frame-previewed conflicts with a real third option

function conflictThumbnails(c, r) {
  // Only "cuts" conflicts carry a frame to look at; color/audio/marker
  // conflicts fall back to the JSON view alone.
  if (c.domain !== "cuts" || !S.mergeFiles) return null;
  const clipId = c.path.split("/")[2];
  const midFrame = c.time_range
    ? Math.floor((c.time_range.start_frame + c.time_range.end_frame) / 2)
    : ((c.ours || c.theirs || {}).record_start_frame ?? 0);
  const thumb = (files, branchLabel) => {
    const clip = findClipInFiles(files, clipId);
    const cv = h("canvas", { width: VW, height: VH, class: "conflict-thumb" });
    if (files) renderFrameToCanvas(cv.getContext("2d"), files, S.lib, midFrame);
    return h("div", {},
      h("div", { class: "muted", style: "font-size:11px;margin-bottom:4px" }, `${branchLabel} · ${clip ? clip.name : clipId}`),
      cv);
  };
  return h("div", { class: "cols2" }, thumb(S.mergeFiles.ours, r.ours), thumb(S.mergeFiles.theirs, r.theirs));
}

// A timeline-overlap conflict isn't a field pick — both clips are already
// fully present in the tentative merge, and the choice is how to arrange
// them: keep one, or keep both (back-to-back, or moved to a new track).
function renderOverlapConflict(c, r, choices) {
  const nameAttr = "c_" + c.path.replace(/[^a-z0-9]/gi, "_");

  const filesFor = (clipObj) => {
    if (!S.mergeFiles) return null;
    if (findClipInFiles(S.mergeFiles.ours, clipObj.id)) return S.mergeFiles.ours;
    if (findClipInFiles(S.mergeFiles.theirs, clipObj.id)) return S.mergeFiles.theirs;
    return null;
  };
  const thumb = (clipObj, label) => {
    const files = filesFor(clipObj);
    const cv = h("canvas", { width: VW, height: VH, class: "conflict-thumb" });
    if (files) {
      const mid = Math.floor((clipObj.record_start_frame + clipObj.record_end_frame) / 2);
      renderFrameToCanvas(cv.getContext("2d"), files, S.lib, mid);
    }
    return h("div", {}, h("div", { class: "muted", style: "font-size:11px;margin-bottom:4px" }, `${label} · ${clipObj.name}`), cv);
  };

  const orderSelect = h("select", {},
    h("option", { value: "a_first" }, `${c.clip_a.name} first`),
    h("option", { value: "b_first" }, `${c.clip_b.name} first`));
  const pick = (op) => { choices[c.path] = { op, order: orderSelect.value }; };
  orderSelect.addEventListener("change", () => {
    if (choices[c.path] && String(choices[c.path].op || "").startsWith("keep_both")) pick(choices[c.path].op);
  });

  choices[c.path] = { op: "keep_a" }; // default: don't silently keep both overlapping

  const suggestion = r.suggestions && r.suggestions[c.path];
  const hint = suggestion
    ? h("div", { class: "muted hint" }, `Suggestion: ${suggestion.reason} (this kind of change always asks first, even when we're fairly sure)`)
    : null;

  return h("div", { class: "conflict overlap" },
    h("div", { class: "path" }, `${c.time_range.start_tc} → ${c.time_range.end_tc}  ·  Timeline overlap on V${c.track}`),
    h("div", { class: "muted" }, `'${c.clip_a.name}' and '${c.clip_b.name}' both land on this range — pick one, or keep both.`),
    hint,
    h("div", { class: "cols2" }, thumb(c.clip_a, "Option A"), thumb(c.clip_b, "Option B")),
    h("label", { class: "choice" },
      h("input", { type: "radio", name: nameAttr, checked: true, onchange: () => { choices[c.path] = { op: "keep_a" }; } }),
      `Keep '${c.clip_a.name}' only`),
    h("label", { class: "choice" },
      h("input", { type: "radio", name: nameAttr, onchange: () => { choices[c.path] = { op: "keep_b" }; } }),
      `Keep '${c.clip_b.name}' only`),
    h("label", { class: "choice" },
      h("input", { type: "radio", name: nameAttr, onchange: () => pick("keep_both") }),
      "Keep both — back to back, ripple whatever comes after"),
    h("label", { class: "choice" },
      h("input", { type: "radio", name: nameAttr, onchange: () => pick("keep_both_new_track") }),
      "Keep both — move one to a new track", orderSelect),
  );
}

function showConflicts(branch, r, target) {
  const choices = {};
  S.mergeFiles = r.ours_files && r.theirs_files ? { ours: r.ours_files, theirs: r.theirs_files } : null;

  // Chronological: conflicts with a time range first (earliest first), then
  // everything without one (color/audio/effects/markers), in whatever order
  // the server reported them.
  const sorted = [...r.conflicts].sort((a, b) => {
    const at = a.time_range ? a.time_range.start_frame : Infinity;
    const bt = b.time_range ? b.time_range.start_frame : Infinity;
    return at - bt;
  });

  const rows = sorted.map((c) => {
    if (c.category === "timeline_overlap") return renderOverlapConflict(c, r, choices);

    const nameAttr = "c_" + c.path.replace(/[^a-z0-9]/gi, "_");
    choices[c.path] = "ours";
    const opt = (side, label, value) => h("label", { class: "choice" },
      h("span", {}, h("input", { type: "radio", name: nameAttr, checked: side === "ours", onchange: () => { choices[c.path] = side; } }), label),
      h("pre", {}, showValue(value, c)));

    const customInput = h("input", { type: "text", class: "custom-value", placeholder: "Type your own value…", disabled: true });
    const applyCustom = () => {
      let parsed;
      try { parsed = JSON.parse(customInput.value); } catch { parsed = customInput.value; }
      choices[c.path] = { value: parsed };
    };
    customInput.addEventListener("input", applyCustom);
    const customOpt = h("label", { class: "choice" },
      h("span", {},
        h("input", { type: "radio", name: nameAttr, onchange: () => { customInput.disabled = false; customInput.focus(); applyCustom(); } }),
        "Neither — I'll type my own"),
      customInput);

    const oursInput = opt("ours", `Keep ${r.ours}`, c.ours);
    const theirsInput = opt("theirs", `Use ${r.theirs}`, c.theirs);
    const disableOthers = (except) => {
      customInput.disabled = except !== "custom";
    };
    for (const row of [oursInput, theirsInput]) {
      row.querySelector("input[type=radio]").addEventListener("change", () => disableOthers("side"));
    }

    // "Keep both" only makes sense for a cuts-domain conflict where both
    // branches still have the whole clip (not one side having deleted it) —
    // it's a structural placement, not a value pick, so it's resolved at the
    // clip's own path rather than the (possibly deeper) field path in c.path.
    let keepBothOpt = null;
    if (c.domain === "cuts" && S.mergeFiles) {
      const clipId = c.path.split("/")[2];
      const clipPath = `cuts/video_tracks/${clipId}`;
      const oursClip = findClipInFiles(S.mergeFiles.ours, clipId);
      const theirsClip = findClipInFiles(S.mergeFiles.theirs, clipId);
      if (oursClip && theirsClip) {
        const orderSelect = h("select", { disabled: true },
          h("option", { value: "ours_first" }, `${r.ours} first, then ${r.theirs}`),
          h("option", { value: "theirs_first" }, `${r.theirs} first, then ${r.ours}`));
        const applyKeepBoth = () => { choices[clipPath] = { op: "keep_both", order: orderSelect.value }; };
        orderSelect.addEventListener("change", applyKeepBoth);
        keepBothOpt = h("label", { class: "choice" },
          h("span", {},
            h("input", {
              type: "radio", name: nameAttr + "_kb",
              onchange: () => { orderSelect.disabled = false; applyKeepBoth(); },
            }),
            "Keep both — back to back"),
          orderSelect);
        // Any other choice on this row cancels the keep-both resolution too.
        for (const row of [oursInput, theirsInput, customOpt]) {
          row.querySelector("input[type=radio]").addEventListener("change", () => {
            orderSelect.disabled = true;
            delete choices[clipPath];
          });
        }
        keepBothOpt.querySelector("input[type=radio]").addEventListener("change", () => { customInput.disabled = true; });
      }
    }

    const fieldSuggestion = r.suggestions && r.suggestions[c.path];
    const fieldHint = fieldSuggestion
      ? h("div", { class: "muted hint" }, `Suggestion: ${fieldSuggestion.reason} (${Math.round(fieldSuggestion.confidence * 100)}% sure — not confident enough to decide on its own)`)
      : null;

    return h("div", { class: "conflict" },
      h("div", { class: "path" }, conflictLabel(c)),
      fieldHint,
      conflictThumbnails(c, r),
      h("div", { class: "cols2" }, oursInput, theirsInput),
      customOpt,
      keepBothOpt);
  });

  target.replaceChildren(
    h("div", { class: "callout bad" }, h("b", {}, "A few things were edited differently on each version line"),
      "Everything else combined automatically. For each item below, choose which version to keep."),
    ...rows,
    h("div", { class: "modal-actions" },
      h("button", { class: "ghost", onclick: closeModal }, "Cancel"),
      h("button", { class: "accent", onclick: () => doMerge(branch, target, choices) }, "Combine now")),
  );
}
