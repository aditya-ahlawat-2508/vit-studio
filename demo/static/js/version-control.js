"use strict";

// ── Version control panel ──────────────────────────────────────────────────

function diffLines(text, target) {
  const rows = [];
  for (const raw of (text || "").split("\n")) {
    if (!raw.trim() || raw.trim().startsWith("Timeline:") || raw.trim().startsWith("Branch:")) continue;
    const line = raw.replace(/^ {2}/, "");
    let cls = "meta";
    if (/^[A-Z]+:$/.test(line)) cls = "sec";
    else if (line.startsWith("+ ")) cls = "add";
    else if (line.startsWith("- ")) cls = "del";
    else if (line.startsWith("~ ")) cls = "mod";
    else if (line === "No changes.") cls = "none";
    rows.push(h("div", { class: cls }, line));
  }
  if (!rows.length) rows.push(h("div", { class: "none" }, "No changes."));
  target.replaceChildren(...rows);
  return rows.filter((r) => ["add", "del", "mod"].includes(r.className)).length;
}

function renderVC() {
  $("branchPill").textContent = S.detached ? "detached HEAD" : S.branch;
  $("dirtyPill").hidden = !S.dirty;
  $("branchSelect").replaceChildren(...S.branches.map((b) => h("option", { value: b, selected: b === S.branch }, b)));

  const n = diffLines(S.dirty ? S.diff : "", $("diffView"));
  $("changesCount").textContent = S.dirty ? `${n} change${n === 1 ? "" : "s"} since last version` : "working copy matches last version";
  $("commitBtn").disabled = !S.dirty || readonly();

  $("issuesView").replaceChildren(...S.issues.map((i) => {
    const d = i.details || {};
    let fix = null;
    if (i.category === "orphaned_ref") {
      fix = h("button", { class: "small", onclick: () => edit(() => {
        if (d.domain === "color") delete S.files.color.grades[d.item_id];
        else delete S.files.effects.clip_effects[d.item_id];
      }) }, "Drop it");
    } else if (i.category === "sync" || i.category === "speed_sync") {
      fix = h("button", { class: "small", onclick: () => edit(() => { const v = findClip(d.video_item, S.files); if (v) syncAudio(v); }) }, "Re-link audio");
    } else if (i.category === "overlap") {
      fix = [
        h("button", { class: "small", onclick: () => moveToFreeTrack(d.clip_b) }, "Move up a track"),
        h("button", { class: "small", onclick: () => placeAfter(d.clip_b, d.clip_a) }, "Place after"),
      ];
    }
    return h("div", { class: "issue-row " + i.severity }, h("span", {}, i.message), fix);
  }));
}

function laneLayout(commits) {
  const lanes = [];
  const pos = {};
  commits.forEach((c, row) => {
    let col = lanes.indexOf(c.hash);
    if (col === -1) { col = lanes.indexOf(null); if (col === -1) { col = lanes.length; lanes.push(null); } }
    for (let j = 0; j < lanes.length; j++) if (j !== col && lanes[j] === c.hash) lanes[j] = null;
    pos[c.hash] = { row, col };
    lanes[col] = c.parents[0] || null;
    for (const p of c.parents.slice(1)) {
      if (lanes.includes(p)) continue;
      const free = lanes.indexOf(null);
      if (free === -1) lanes.push(p); else lanes[free] = p;
    }
  });
  return pos;
}

function renderGraph() {
  const commits = S.commits;
  const pos = laneLayout(commits);
  const rowH = 46, laneW = 16, pad = 12;
  const maxCol = Math.max(0, ...Object.values(pos).map((p) => p.col));
  const width = pad * 2 + maxCol * laneW;
  const height = commits.length * rowH;
  const X = (col) => pad + col * laneW, Y = (row) => row * rowH + rowH / 2;
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", width); svg.setAttribute("height", height);

  commits.forEach((c) => {
    const a = pos[c.hash];
    c.parents.forEach((p, i) => {
      const b = pos[p];
      if (!b) return;
      const path = document.createElementNS(NS, "path");
      let d;
      if (a.col === b.col) d = `M${X(a.col)},${Y(a.row)} L${X(b.col)},${Y(b.row)}`;
      else if (i === 0) d = `M${X(a.col)},${Y(a.row)} L${X(a.col)},${Y(b.row) - rowH} C${X(a.col)},${Y(b.row) - rowH / 3} ${X(b.col)},${Y(b.row) - rowH / 2} ${X(b.col)},${Y(b.row)}`;
      else d = `M${X(a.col)},${Y(a.row)} C${X(a.col)},${Y(a.row) + rowH / 2} ${X(b.col)},${Y(a.row) + rowH / 3} ${X(b.col)},${Y(a.row) + rowH} L${X(b.col)},${Y(b.row)}`;
      path.setAttribute("d", d);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", LANE_COLORS[(i === 0 ? a.col : b.col) % LANE_COLORS.length]);
      path.setAttribute("stroke-width", "2");
      svg.append(path);
    });
  });
  commits.forEach((c) => {
    const a = pos[c.hash];
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", X(a.col)); dot.setAttribute("cy", Y(a.row));
    dot.setAttribute("r", c.is_head ? 6 : 4.5);
    dot.setAttribute("fill", c.is_head ? "#fff" : LANE_COLORS[a.col % LANE_COLORS.length]);
    dot.setAttribute("stroke", LANE_COLORS[a.col % LANE_COLORS.length]);
    dot.setAttribute("stroke-width", c.is_head ? 3 : 0);
    svg.append(dot);
  });

  const rows = commits.map((c) => h("div", {
    class: "commit-row" + (c.is_head ? " head" : ""), style: `padding-left:${width + 4}px`,
    onclick: () => openCommit(c),
  },
  h("div", { class: "msg" }, c.message.replace(/^vit:\s*/, "")),
  h("div", { class: "sub" },
    c.refs.map((r) => h("span", { class: "ref" + (r === S.branch ? " current" : "") }, r)),
    `${c.author} · ${c.date} · ${c.hash}`)));
  $("graph").replaceChildren(svg, ...rows);
}
