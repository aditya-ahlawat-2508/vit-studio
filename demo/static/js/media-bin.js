"use strict";

// ── Media bin ──────────────────────────────────────────────────────────────

function renderBin() {
  const items = S.library.map((src) => {
    const thumb = h("canvas", { width: 192, height: 108 });
    const tctx = thumb.getContext("2d");
    const paint = (media) => {
      const tmp = Object.assign(document.createElement("canvas"), { width: VW, height: VH });
      const c = tmp.getContext("2d");
      if (!src.available) SOURCES.drawOffline(c, VW, VH, src.name);
      else if (media) drawCoverOn(c, media);
      else SOURCES.draw(c, VW, VH, src.kind, Math.floor(src.duration_frames / 2));
      tctx.drawImage(tmp, 0, 0, 192, 108);
    };
    if (VIDEO_KINDS.has(src.kind) && src.available) {
      const v = h("video", { src: "/media/" + encodeURIComponent(src.file), preload: "auto", muted: true });
      v.addEventListener("loadeddata", () => { v.currentTime = Math.min(1, v.duration / 2); });
      v.addEventListener("seeked", () => paint(v), { once: true });
    } else {
      paint(null);
    }
    return h("div", {
      class: "bin-item", draggable: "true", title: `${src.name}\n${src.ref}\nDouble-click to add at playhead`,
      ondragstart: (ev) => { ev.dataTransfer.setData("text/vit-ref", src.ref); ev.dataTransfer.effectAllowed = "copy"; },
      ondblclick: () => addClip(src.ref, 1, S.playhead),
    }, thumb, h("div", { class: "meta" },
      h("b", {}, src.name),
      h("span", {}, src.available ? `${(src.duration_frames / FPS).toFixed(1)}s · ${src.duration_frames}f` : "offline")));
  });
  $("binList").replaceChildren(...items);
}

function drawCoverOn(c, media) {
  const scale = Math.max(VW / media.videoWidth, VH / media.videoHeight);
  const w = media.videoWidth * scale, hh = media.videoHeight * scale;
  c.drawImage(media, (VW - w) / 2, (VH - hh) / 2, w, hh);
}

$("importInput").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  const url = URL.createObjectURL(file);
  const probe = h("video", { preload: "metadata", src: url });
  try {
    await new Promise((res, rej) => { probe.onloadedmetadata = res; probe.onerror = () => rej(new Error("This browser can't play that file. Try an .mp4 (H.264) or .webm.")); });
    toast(`Importing ${file.name}…`);
    const q = new URLSearchParams({
      name: file.name, duration_frames: Math.round(probe.duration * FPS),
      width: probe.videoWidth, height: probe.videoHeight,
    });
    const res = await fetch(`/api/media?${q}`, { method: "POST", body: file, headers: { "X-Vit-Demo": "1" } });
    const entry = await res.json();
    if (!res.ok) throw new Error(entry.error || "Upload failed");
    S.library = S.library.filter((s) => s.ref !== entry.ref).concat(entry);
    S.lib[entry.ref] = entry;
    renderBin();
    toast(`${file.name} is in the media bin. Only its checksum will go into git.`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    URL.revokeObjectURL(url);
  }
});
