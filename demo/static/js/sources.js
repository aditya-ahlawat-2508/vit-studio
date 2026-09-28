// Procedural "footage". Each source is a pure function of (kind, sourceFrame),
// so a timeline that says "use frames 240–432 of Interview_A" renders the same
// pixels on every machine — the demo equivalent of shared media on disk.

const SOURCES = (() => {
  function rng(seed) {
    let s = seed >>> 0;
    return () => {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };
  }

  function bars(ctx, W, H, f) {
    const cols = ["#c0c0c0", "#c0c000", "#00c0c0", "#00c000", "#c000c0", "#c00000", "#0000c0"];
    const bw = W / cols.length;
    cols.forEach((c, i) => { ctx.fillStyle = c; ctx.fillRect(i * bw, 0, bw + 1, H * 0.67); });
    const g = ctx.createLinearGradient(0, 0, W, 0);
    g.addColorStop(0, "#000"); g.addColorStop(1, "#fff");
    ctx.fillStyle = g; ctx.fillRect(0, H * 0.67, W, H * 0.13);
    ctx.fillStyle = "#101010"; ctx.fillRect(0, H * 0.8, W, H * 0.2);
    ctx.fillStyle = "#fff";
    ctx.font = `bold ${H * 0.12}px ui-monospace, Menlo, Consolas, monospace`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(String(f).padStart(4, "0"), W / 2, H * 0.9);
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
  }

  function sunset(ctx, W, H, f) {
    const sky = ctx.createLinearGradient(0, 0, 0, H * 0.62);
    sky.addColorStop(0, "#2b1d4e"); sky.addColorStop(0.55, "#c2536b"); sky.addColorStop(1, "#f7a54a");
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H * 0.62);
    const sunY = H * 0.3 + (f / 720) * H * 0.3;
    ctx.fillStyle = "#ffd27a";
    ctx.beginPath(); ctx.arc(W * 0.62, sunY, H * 0.09, 0, Math.PI * 2); ctx.fill();
    const sea = ctx.createLinearGradient(0, H * 0.62, 0, H);
    sea.addColorStop(0, "#7a3b5c"); sea.addColorStop(1, "#1a1633");
    ctx.fillStyle = sea; ctx.fillRect(0, H * 0.62, W, H * 0.38);
    ctx.strokeStyle = "rgba(255,210,140,0.35)"; ctx.lineWidth = 2;
    for (let i = 0; i < 9; i++) {
      const y = H * 0.65 + i * H * 0.04;
      ctx.beginPath();
      for (let x = 0; x <= W; x += 16) {
        const yy = y + Math.sin(x / 40 + f / 6 + i) * (2 + i * 0.6);
        x === 0 ? ctx.moveTo(x, yy) : ctx.lineTo(x, yy);
      }
      ctx.stroke();
    }
    ctx.fillStyle = "rgba(255,210,122,0.5)";
    ctx.fillRect(W * 0.62 - 30 - Math.sin(f / 8) * 8, H * 0.64, 60 + Math.sin(f / 8) * 16, 4);
  }

  function city(ctx, W, H, f) {
    const sky = ctx.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, "#070b1f"); sky.addColorStop(1, "#1d2356");
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
    const r = rng(7);
    let x = 0;
    while (x < W) {
      const bw = 40 + r() * 70, bh = H * (0.25 + r() * 0.5);
      ctx.fillStyle = `hsl(230, 25%, ${10 + r() * 8}%)`;
      ctx.fillRect(x, H * 0.85 - bh, bw, bh);
      for (let wy = H * 0.85 - bh + 10; wy < H * 0.82; wy += 16) {
        for (let wx = x + 6; wx < x + bw - 8; wx += 12) {
          const lit = r() > 0.55 !== (Math.floor(f / 24 + wx * 0.01) % 7 === 0);
          if (lit) { ctx.fillStyle = "#ffd98a"; ctx.fillRect(wx, wy, 5, 7); }
        }
      }
      x += bw + 4;
    }
    ctx.fillStyle = "#11142a"; ctx.fillRect(0, H * 0.85, W, H * 0.15);
    for (let k = 0; k < 6; k++) {
      const cx = (f * (5 + k) + k * 190) % (W + 80) - 40;
      ctx.fillStyle = k % 2 ? "#ff4d4d" : "#fff6c8";
      ctx.beginPath(); ctx.arc(k % 2 ? W - cx : cx, H * 0.9 + (k % 2) * 14, 4, 0, Math.PI * 2); ctx.fill();
    }
  }

  function interview(ctx, W, H, f) {
    const bg = ctx.createRadialGradient(W * 0.35, H * 0.4, 20, W * 0.5, H * 0.5, W * 0.7);
    bg.addColorStop(0, "#6d5a48"); bg.addColorStop(1, "#231c17");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
    const r = rng(3);
    for (let i = 0; i < 14; i++) {
      ctx.fillStyle = `rgba(255, 200, 140, ${0.05 + r() * 0.08})`;
      ctx.beginPath(); ctx.arc(W * 0.65 + r() * W * 0.35, r() * H * 0.7, 10 + r() * 30, 0, Math.PI * 2); ctx.fill();
    }
    const sway = Math.sin(f / 22) * 6, nod = Math.sin(f / 9) * 2;
    ctx.fillStyle = "#3a4a63";
    ctx.beginPath(); ctx.ellipse(W * 0.42 + sway, H * 1.02, W * 0.2, H * 0.36, 0, Math.PI, 0); ctx.fill();
    ctx.fillStyle = "#c99a7a";
    ctx.fillRect(W * 0.42 + sway - 22, H * 0.52, 44, 50);
    ctx.beginPath(); ctx.ellipse(W * 0.42 + sway, H * 0.42 + nod, 62, 78, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#2a1c14";
    ctx.beginPath(); ctx.ellipse(W * 0.42 + sway, H * 0.34 + nod, 66, 44, 0, Math.PI, 0); ctx.fill();
    if (f % 90 > 30) {
      ctx.fillStyle = "rgba(10,14,24,0.8)"; ctx.fillRect(W * 0.06, H * 0.76, W * 0.4, H * 0.1);
      ctx.fillStyle = "#f5a524"; ctx.fillRect(W * 0.06, H * 0.76, 6, H * 0.1);
      ctx.fillStyle = "#fff"; ctx.font = `600 ${H * 0.04}px system-ui, sans-serif`;
      ctx.fillText("Dr. Meera Rao", W * 0.08, H * 0.815);
      ctx.fillStyle = "#b8c0cc"; ctx.font = `${H * 0.028}px system-ui, sans-serif`;
      ctx.fillText("Marine biologist", W * 0.08, H * 0.85);
    }
  }

  function forest(ctx, W, H, f) {
    const sky = ctx.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, "#9fd3e6"); sky.addColorStop(1, "#e9f1d8");
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
    const layers = [["#7fa88a", 0.45, 0.6], ["#4b7d5c", 0.6, 1.2], ["#23513a", 0.78, 2.2]];
    layers.forEach(([col, base, speed], li) => {
      const r = rng(11 + li);
      ctx.fillStyle = col;
      const spacing = 50 - li * 8;
      const offset = (f * speed) % spacing;
      for (let x = -spacing; x < W + spacing; x += spacing) {
        const h = H * (0.18 + r() * 0.16) * (1 + li * 0.3);
        const tx = x - offset;
        ctx.beginPath();
        ctx.moveTo(tx - spacing * 0.6, H * base + h * 0.3);
        ctx.lineTo(tx, H * base - h);
        ctx.lineTo(tx + spacing * 0.6, H * base + h * 0.3);
        ctx.fill();
      }
      ctx.fillRect(0, H * base + 10, W, H);
    });
  }

  function ocean(ctx, W, H, f) {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, "#0d4f73"); g.addColorStop(1, "#04182b");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    for (let i = 0; i < 14; i++) {
      ctx.fillStyle = `rgba(120, 210, 235, ${0.05 + i * 0.012})`;
      ctx.beginPath();
      ctx.moveTo(0, H);
      for (let x = 0; x <= W; x += 12) {
        ctx.lineTo(x, H * 0.18 + i * H * 0.06 + Math.sin(x / (60 + i * 5) + f / (10 - i * 0.4) + i) * (6 + i));
      }
      ctx.lineTo(W, H); ctx.fill();
    }
    ctx.fillStyle = "rgba(255,255,255,0.7)";
    const r = rng(5);
    for (let i = 0; i < 40; i++) {
      const x = (r() * W + f * (1 + r() * 2)) % W, y = H * 0.2 + r() * H * 0.8;
      ctx.fillRect(x, y, 2, 2);
    }
  }

  const drawers = { bars, sunset, city, interview, forest, ocean };

  function drawOffline(ctx, W, H, name) {
    ctx.fillStyle = "#3a0d0d"; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "#ff6b6b";
    ctx.font = `bold ${H * 0.07}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.fillText("MEDIA OFFLINE", W / 2, H / 2);
    ctx.font = `${H * 0.035}px system-ui, sans-serif`;
    ctx.fillStyle = "#ffb3b3";
    ctx.fillText(name || "unknown media", W / 2, H / 2 + H * 0.07);
    ctx.textAlign = "left";
  }

  return {
    draw(ctx, W, H, kind, frame) {
      const fn = drawers[kind];
      if (fn) fn(ctx, W, H, frame);
      return Boolean(fn);
    },
    drawOffline,
  };
})();
