(() => {
  const $ = (id) => document.getElementById(id);

  const state = {
    data: null,
    sweep: 0,
    locked: null,
    audioEnabled: true,
    audioCtx: null,
    lastClick: 0,
    waterfall: [],
  };

  const radar = $("radar");
  const rctx = radar.getContext("2d");
  const waterfall = $("waterfall");
  const wctx = waterfall.getContext("2d");

  function categoryColor(cat) {
    switch (cat) {
      case "DRONE":
        return "#ff4d6d";
      case "HIDDEN_CAM":
      case "IP_CAMERA":
        return "#ffbf47";
      case "IOT_CAMERA":
        return "#60a5fa";
      default:
        return "#64748b";
    }
  }

  function ensureAudio() {
    if (!state.audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      state.audioCtx = new AC();
    }
    if (state.audioCtx.state === "suspended") state.audioCtx.resume();
    return state.audioCtx;
  }

  function geigerClick(intensity) {
    if (!state.audioEnabled) return;
    const ctx = ensureAudio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const filter = ctx.createBiquadFilter();
    osc.type = "square";
    // Closer (higher intensity) → higher pitch + louder
    osc.frequency.value = 900 + intensity * 2200;
    filter.type = "highpass";
    filter.frequency.value = 600;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.05 + intensity * 0.12, t + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.04 + intensity * 0.03);
    osc.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.08);
  }

  function rssiToIntensity(rssi) {
    // -30 dBm ≈ 1.0, -90 dBm ≈ 0.0
    return Math.max(0, Math.min(1, (rssi + 90) / 60));
  }

  function updateGeiger(device) {
    const bar = $("geigerBar");
    const readout = $("geigerReadout");
    if (!device) {
      bar.style.width = "0%";
      readout.textContent = "— dBm";
      return;
    }
    const rssi = device.rssi_smooth ?? device.rssi;
    const intensity = rssiToIntensity(rssi);
    bar.style.width = `${Math.round(intensity * 100)}%`;
    readout.textContent = `${rssi.toFixed(1)} dBm · ~${device.distance_m} m`;

    const now = performance.now();
    // Click interval: far ~900ms, near ~60ms
    const interval = 900 - intensity * 840;
    if (now - state.lastClick >= interval) {
      state.lastClick = now;
      geigerClick(intensity);
    }
  }

  function drawRadar(devices, lockedBssid) {
    const w = radar.width;
    const h = radar.height;
    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(cx, cy) - 18;

    rctx.clearRect(0, 0, w, h);

    // Rings
    rctx.strokeStyle = "rgba(61,255,196,0.18)";
    rctx.lineWidth = 1;
    for (let i = 1; i <= 4; i++) {
      rctx.beginPath();
      rctx.arc(cx, cy, (radius * i) / 4, 0, Math.PI * 2);
      rctx.stroke();
    }
    // Cross
    rctx.beginPath();
    rctx.moveTo(cx - radius, cy);
    rctx.lineTo(cx + radius, cy);
    rctx.moveTo(cx, cy - radius);
    rctx.lineTo(cx, cy + radius);
    rctx.stroke();

    // Range labels
    rctx.fillStyle = "rgba(127,163,154,0.8)";
    rctx.font = "12px Cascadia Mono, Consolas, monospace";
    ["20m", "40m", "60m", "80m"].forEach((label, i) => {
      rctx.fillText(label, cx + 6, cy - ((radius * (i + 1)) / 4) + 4);
    });

    // Sweep wedge
    state.sweep = (state.sweep + 0.018) % (Math.PI * 2);
    const grad = rctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
    grad.addColorStop(0, "rgba(61,255,196,0.20)");
    grad.addColorStop(1, "rgba(61,255,196,0.0)");
    rctx.fillStyle = grad;
    rctx.beginPath();
    rctx.moveTo(cx, cy);
    rctx.arc(cx, cy, radius, state.sweep - 0.45, state.sweep);
    rctx.closePath();
    rctx.fill();

    // Sweep line
    rctx.strokeStyle = "rgba(61,255,196,0.85)";
    rctx.beginPath();
    rctx.moveTo(cx, cy);
    rctx.lineTo(cx + Math.cos(state.sweep) * radius, cy + Math.sin(state.sweep) * radius);
    rctx.stroke();

    const maxM = 80;
    for (const d of devices) {
      const ang = ((d.angle_deg || 0) * Math.PI) / 180;
      const dist = Math.min(maxM, d.distance_m || 10);
      const r = (dist / maxM) * radius;
      const x = cx + Math.cos(ang) * r;
      const y = cy + Math.sin(ang) * r;
      const color = categoryColor(d.category);
      const isLocked = lockedBssid && d.bssid === lockedBssid;
      const isThreat = d.score >= 60;

      if (isLocked || isThreat) {
        rctx.beginPath();
        rctx.strokeStyle = isLocked ? "rgba(255,191,71,0.7)" : "rgba(255,77,109,0.35)";
        rctx.lineWidth = isLocked ? 2 : 1;
        rctx.arc(x, y, isLocked ? 14 : 10, 0, Math.PI * 2);
        rctx.stroke();
      }

      rctx.beginPath();
      rctx.fillStyle = color;
      rctx.arc(x, y, isThreat ? 5.5 : 3.5, 0, Math.PI * 2);
      rctx.fill();

      if (d.score >= 50) {
        rctx.fillStyle = "rgba(215,246,238,0.85)";
        rctx.font = "11px Segoe UI, sans-serif";
        const label = (d.ssid || d.bssid).slice(0, 16);
        rctx.fillText(label, x + 8, y - 6);
      }
    }

    // Center pip
    rctx.beginPath();
    rctx.fillStyle = "#3dffc4";
    rctx.arc(cx, cy, 3, 0, Math.PI * 2);
    rctx.fill();
  }

  function drawWaterfall(history) {
    const w = waterfall.width;
    const h = waterfall.height;
    wctx.fillStyle = "#050d12";
    wctx.fillRect(0, 0, w, h);

    // Grid
    wctx.strokeStyle = "rgba(61,255,196,0.12)";
    wctx.beginPath();
    for (let y = 0; y < h; y += 20) {
      wctx.moveTo(0, y);
      wctx.lineTo(w, y);
    }
    wctx.stroke();

    if (!history || history.length < 2) return;

    // Map RSSI -100..-20 to canvas y
    const toY = (rssi) => {
      const clamped = Math.max(-100, Math.min(-20, rssi));
      return ((-20 - clamped) / 80) * (h - 8) + 4;
    };

    wctx.beginPath();
    wctx.strokeStyle = "#3dffc4";
    wctx.lineWidth = 2;
    history.forEach((v, i) => {
      const x = (i / Math.max(1, history.length - 1)) * (w - 4) + 2;
      const y = toY(v);
      if (i === 0) wctx.moveTo(x, y);
      else wctx.lineTo(x, y);
    });
    wctx.stroke();

    // Fill under curve
    const lastX = w - 2;
    wctx.lineTo(lastX, h);
    wctx.lineTo(2, h);
    wctx.closePath();
    wctx.fillStyle = "rgba(61,255,196,0.12)";
    wctx.fill();
  }

  function renderDevices(devices, lockedBssid) {
    const list = $("deviceList");
    list.innerHTML = "";
    if (!devices.length) {
      list.innerHTML = `<div class="meta">No transmitters yet. Start scan or enable Simulation.</div>`;
      return;
    }
    for (const d of devices) {
      const el = document.createElement("div");
      el.className = "device" + (d.score >= 60 ? " threat" : "") + (d.bssid === lockedBssid ? " locked" : "");
      el.innerHTML = `
        <div class="row">
          <div class="ssid">${escapeHtml(d.ssid || "(hidden)")}</div>
          <div class="score" style="color:${d.score >= 60 ? "#ff4d6d" : "#3dffc4"}">${d.score}</div>
        </div>
        <div class="meta">${escapeHtml(d.category_label)} · ${escapeHtml(d.vendor)} · ${d.band} GHz ch${d.channel} · ${d.rssi_smooth} dBm · ~${d.distance_m}m</div>
        <div class="meta">${escapeHtml(d.bssid)}${d.lan_ip ? " · " + d.lan_ip : ""}${d.open_ports?.length ? " · ports " + d.open_ports.join(",") : ""}</div>
        <div class="reasons">${(d.reasons || []).slice(0, 3).map(escapeHtml).join(" · ")}</div>
      `;
      el.addEventListener("click", () => lockTarget(d.bssid));
      list.appendChild(el);
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function applySnapshot(data) {
    state.data = data;
    const lockedBssid = data.locked?.bssid || null;
    state.locked = lockedBssid;

    $("statDevices").textContent = data.stats?.device_count ?? 0;
    $("statThreats").textContent = data.stats?.threat_count ?? 0;
    $("statDrones").textContent = data.stats?.drone_count ?? 0;
    $("statCameras").textContent = data.stats?.camera_count ?? 0;

    $("statusScan").textContent = data.scanning
      ? data.simulation
        ? "SCANNING (simulation)"
        : "SCANNING"
      : "Idle";
    const adapter = data.selected_adapter;
    $("statusAdapter").textContent = adapter
      ? adapter.description
      : "No adapter selected";
    $("statusScanCount").textContent = `Scans: ${data.scan_count || 0}`;
    $("statusError").textContent = data.last_error || "";
    const locLink = $("locationLink");
    const needsLoc = !!(data.last_error && /location/i.test(data.last_error));
    locLink.style.display = needsLoc ? "inline" : "none";

    $("simToggle").checked = !!data.simulation;
    if (data.scan_interval) {
      const intervalSel = $("intervalSelect");
      intervalSel.value = String(Math.round(data.scan_interval));
    }

    // Adapter select
    const sel = $("adapterSelect");
    const current = sel.value;
    sel.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = data.simulation ? "(simulation)" : "Auto / preferred";
    sel.appendChild(opt0);
    for (const a of data.adapters || []) {
      const o = document.createElement("option");
      o.value = a.guid;
      o.textContent = `${a.preferred ? "★ " : ""}${a.description}`;
      sel.appendChild(o);
    }
    if (adapter?.guid && adapter.guid !== "{SIMULATION}") {
      sel.value = adapter.guid;
    } else if (current) {
      sel.value = current;
    }

    const devices = data.devices || [];
    drawRadar(devices, lockedBssid);
    renderDevices(devices, lockedBssid);

    const lockedDev =
      devices.find((d) => d.bssid === lockedBssid) ||
      data.threats?.[0] ||
      devices.find((d) => d.score >= 60) ||
      null;

    if (lockedBssid && data.locked) {
      $("lockInfo").textContent = `LOCKED ${data.locked.ssid || lockedBssid} · ${data.locked.category_label || ""} · walk closer to raise click rate`;
    } else if (lockedDev) {
      $("lockInfo").textContent = `Tracking strongest threat: ${lockedDev.ssid} (${lockedDev.score}) — click to lock`;
    }

    updateGeiger(data.locked || lockedDev);

    const hist =
      (data.locked && data.locked.rssi_history) ||
      lockedDev?.rssi_history ||
      [];
    drawWaterfall(hist);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) throw new Error(`${path} → ${res.status}`);
    return res.json();
  }

  async function lockTarget(bssid) {
    ensureAudio();
    const data = await api("/api/lock", {
      method: "POST",
      body: JSON.stringify({ bssid }),
    });
    applySnapshot(data);
  }

  // Radar click → nearest blip
  radar.addEventListener("click", (ev) => {
    const data = state.data;
    if (!data?.devices?.length) return;
    const rect = radar.getBoundingClientRect();
    const scaleX = radar.width / rect.width;
    const scaleY = radar.height / rect.height;
    const mx = (ev.clientX - rect.left) * scaleX;
    const my = (ev.clientY - rect.top) * scaleY;
    const cx = radar.width / 2;
    const cy = radar.height / 2;
    const radius = Math.min(cx, cy) - 18;
    const maxM = 80;

    let best = null;
    let bestDist = 28;
    for (const d of data.devices) {
      const ang = ((d.angle_deg || 0) * Math.PI) / 180;
      const dist = Math.min(maxM, d.distance_m || 10);
      const r = (dist / maxM) * radius;
      const x = cx + Math.cos(ang) * r;
      const y = cy + Math.sin(ang) * r;
      const dd = Math.hypot(x - mx, y - my);
      if (dd < bestDist) {
        bestDist = dd;
        best = d;
      }
    }
    if (best) lockTarget(best.bssid);
  });

  $("btnStart").addEventListener("click", async () => {
    ensureAudio();
    applySnapshot(await api("/api/scan/start", { method: "POST" }));
  });
  $("btnStop").addEventListener("click", async () => {
    applySnapshot(await api("/api/scan/stop", { method: "POST" }));
  });
  $("btnOnce").addEventListener("click", async () => {
    ensureAudio();
    applySnapshot(await api("/api/scan/once", { method: "POST" }));
  });
  $("btnUnlock").addEventListener("click", async () => {
    applySnapshot(await api("/api/lock", { method: "POST", body: JSON.stringify({ bssid: null }) }));
  });
  $("simToggle").addEventListener("change", async (e) => {
    applySnapshot(
      await api("/api/simulation", {
        method: "POST",
        body: JSON.stringify({ enabled: e.target.checked }),
      })
    );
  });
  $("intervalSelect").addEventListener("change", async (e) => {
    const seconds = Number(e.target.value);
    await api("/api/interval", {
      method: "POST",
      body: JSON.stringify({ seconds }),
    });
  });
  $("adapterSelect").addEventListener("change", async (e) => {
    applySnapshot(
      await api("/api/adapters/select", {
        method: "POST",
        body: JSON.stringify({ guid: e.target.value || null }),
      })
    );
  });
  $("audioToggle").addEventListener("change", (e) => {
    state.audioEnabled = e.target.checked;
    if (state.audioEnabled) ensureAudio();
  });

  const helpBtn = $("btnHelp");
  const helpPanel = $("helpPanel");
  helpBtn.addEventListener("click", () => {
    const opening = !helpPanel.classList.contains("open");
    helpPanel.classList.toggle("open", opening);
    helpPanel.setAttribute("aria-hidden", opening ? "false" : "true");
  });
  document.addEventListener("click", (ev) => {
    if (!helpPanel.classList.contains("open")) return;
    if (helpPanel.contains(ev.target) || helpBtn.contains(ev.target)) return;
    helpPanel.classList.remove("open");
    helpPanel.setAttribute("aria-hidden", "true");
  });

  // WebSocket live feed
  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "telemetry" || msg.type === "error") {
          applySnapshot(msg.data);
        }
      } catch (_) {}
    };
    ws.onclose = () => setTimeout(connectWs, 1500);
  }

  // Animation loop for sweep + geiger when locked
  function tick() {
    if (state.data) {
      drawRadar(state.data.devices || [], state.locked);
      const lockedDev =
        state.data.locked ||
        (state.data.devices || []).find((d) => d.bssid === state.locked) ||
        state.data.threats?.[0] ||
        null;
      if (state.data.scanning || state.data.simulation) {
        updateGeiger(lockedDev);
      }
    }
    requestAnimationFrame(tick);
  }

  // Boot
  api("/api/snapshot")
    .then(applySnapshot)
    .catch((err) => {
      $("statusError").textContent = String(err);
    });
  connectWs();
  requestAnimationFrame(tick);
})();
