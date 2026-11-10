/* Plant Ops Copilot front end: plain JavaScript, no dependencies, no build step. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const MACHINES = ["FILLER-01", "CAPPER-01", "LABELER-01", "PACKER-01"];
  const SIGNALS = {
    temp_c: "Temperature (°C)",
    vibration_mm_s: "Vibration (mm/s)",
    motor_current_a: "Motor current (A)",
    cycle_time_s: "Cycle time (s)",
    rejects_per_min: "Rejects (per min)",
  };
  const AGENT_STEP = { detection_agent: 1, diagnosis_agent: 2, report_agent: 3 };

  const state = {
    status: null,
    scenarios: [],
    scenario: null,
    machine: "FILLER-01",
    signal: "vibration_mm_s",
    overview: null,
    running: false,
    timers: [],
    runId: null,
    provider: null,
  };

  /* Helpers */
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (x, d = 1) => (x === null || x === undefined ? "–" : Number(x).toFixed(d));
  const store = {
    get(k) { try { return sessionStorage.getItem(k) || ""; } catch { return ""; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } },
  };

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const j = await res.json();
        if (typeof j.detail === "string") detail = j.detail;
      } catch { /* ignore */ }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  function notice(msg, kind = "info") {
    const box = $("#notice");
    box.innerHTML = msg ? `<div class="notice ${kind}" role="status">${esc(msg)}</div>` : "";
  }

  /* Markdown */
  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[([A-Z]+-\d+ §\d+)\]/g, '<span class="cite">$1</span>');
  }

  function md(src) {
    const lines = String(src).replace(/\r/g, "").split("\n");
    const out = [];
    let i = 0;
    const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
    const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
    while (i < lines.length) {
      const ln = lines[i];
      if (isRow(ln) && i + 1 < lines.length && /^\s*\|[\s:\-|]+\|\s*$/.test(lines[i + 1])) {
        const head = cells(ln);
        i += 2;
        const rows = [];
        while (i < lines.length && isRow(lines[i])) rows.push(cells(lines[i++]));
        out.push("<div class='table-wrap'><table><thead><tr>" + head.map((h) => `<th>${inline(h)}</th>`).join("") + "</tr></thead><tbody>" +
          rows.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table></div>");
      } else if (/^#{1,4}\s/.test(ln)) {
        out.push(`<h3>${inline(ln.replace(/^#{1,4}\s+/, ""))}</h3>`);
        i++;
      } else if (/^\s*\d+\.\s/.test(ln)) {
        const items = [];
        while (i < lines.length && /^\s*\d+\.\s/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+\.\s+/, ""));
        out.push("<ol>" + items.map((t) => `<li>${inline(t)}</li>`).join("") + "</ol>");
      } else if (/^\s*[-*]\s/.test(ln)) {
        const items = [];
        while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
        out.push("<ul>" + items.map((t) => `<li>${inline(t)}</li>`).join("") + "</ul>");
      } else if (!ln.trim()) {
        i++;
      } else {
        const para = [];
        while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*\d+\.\s|\s*[-*]\s)/.test(lines[i]) && !isRow(lines[i])) para.push(lines[i++]);
        out.push(`<p>${inline(para.join(" "))}</p>`);
      }
    }
    return out.join("");
  }

  /* Chart */
  const tms = (iso) => Date.parse(iso + "Z");
  const hhmm = (ms) => { const d = new Date(ms); return String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0"); };

  function niceTicks(min, max, n = 5) {
    if (!isFinite(min) || !isFinite(max) || min === max) { min = (min || 0) - 1; max = (max || 0) + 1; }
    const span = max - min;
    const raw = span / n;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(6));
    return ticks;
  }

  function drawChart(p) {
    const W = 860, H = 300, L = 50, R = 18, T = 16, B = 30;
    // Stops are shown as shaded bands, so the line plots RUN minutes only
    const pts = p.points.map((q) => ({ x: tms(q.t), v: q.v, s: q.s, pv: q.s === "RUN" ? q.v : null }));
    const xs = pts.map((q) => q.x);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const vals = pts.map((q) => q.pv).filter((v) => v !== null);
    let dmin = Math.min(...vals), dmax = Math.max(...vals);
    const lim = p.limits || {};
    const inDomain = (l) => l !== undefined && l <= dmax + Math.max(dmax - dmin, Math.abs(dmax) * 0.25) * 1.0;
    const shown = {};
    ["alert", "trip"].forEach((k) => { if (inDomain(lim[k])) { shown[k] = lim[k]; dmax = Math.max(dmax, lim[k]); } });
    const pad = (dmax - dmin) * 0.08 || 1;
    const ticks = niceTicks(dmin - pad, dmax + pad, 5);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const X = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R);
    const Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);

    let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">`;
    // State bands
    (p.stops || []).forEach((s) => {
      const a = Math.max(X(tms(s.start)), L), b = Math.min(X(tms(s.end)), W - R);
      if (b > a) svg += `<rect class="band-${esc(s.state)}" x="${a.toFixed(1)}" y="${T}" width="${(b - a).toFixed(1)}" height="${H - T - B}"><title>${esc(s.state)} ${hhmm(tms(s.start))}–${hhmm(tms(s.end))}</title></rect>`;
    });
    // Anomaly windows
    (p.windows || []).forEach((w) => {
      const a = Math.max(X(tms(w.start)), L), b = Math.min(X(tms(w.end)), W - R);
      if (b > a) {
        svg += `<rect class="win" x="${a.toFixed(1)}" y="${T}" width="${(b - a).toFixed(1)}" height="${H - T - B}"/>`;
        svg += `<text class="win-label" x="${(a + 4).toFixed(1)}" y="${T + 11}">${esc(w.type)}</text>`;
      }
    });
    // Grid and y axis
    svg += '<g class="grid ax">';
    ticks.forEach((v) => { svg += `<line x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text x="${L - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${+v.toFixed(2)}</text>`; });
    // X axis (hourly)
    const first = Math.ceil(x0 / 3600000) * 3600000;
    for (let t = first; t <= x1; t += 3600000) svg += `<line x1="${X(t).toFixed(1)}" x2="${X(t).toFixed(1)}" y1="${T}" y2="${H - B}"/><text x="${X(t).toFixed(1)}" y="${H - 10}" text-anchor="middle">${hhmm(t)}</text>`;
    svg += "</g>";
    // Alarm limits
    Object.entries(shown).forEach(([k, v]) => {
      svg += `<line class="lim-${k}" x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="lim-label ${k}" x="${W - R - 4}" y="${(Y(v) - 4).toFixed(1)}" text-anchor="end">${k} ${v}</text>`;
    });
    // Series (the line breaks at gaps)
    let d = "", pen = false;
    pts.forEach((q) => {
      if (q.pv === null) { pen = false; return; }
      d += (pen ? "L" : "M") + X(q.x).toFixed(1) + " " + Y(q.pv).toFixed(1);
      pen = true;
    });
    svg += `<path class="series" d="${d}"/>`;
    svg += `<line class="hover-line" id="hl" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/>`;
    svg += "</svg>";

    const host = $("#chart");
    host.style.position = "relative";
    host.innerHTML = svg + '<div class="tip" id="tip" hidden></div>';
    const el = $("svg", host), tip = $("#tip"), hl = $("#hl");
    el.addEventListener("mousemove", (e) => {
      const r = el.getBoundingClientRect();
      const gx = ((e.clientX - r.left) / r.width) * W;
      if (gx < L || gx > W - R) { tip.hidden = true; hl.setAttribute("visibility", "hidden"); return; }
      const t = x0 + ((gx - L) / (W - L - R)) * (x1 - x0);
      let best = pts[0];
      for (const q of pts) if (Math.abs(q.x - t) < Math.abs(best.x - t)) best = q;
      hl.setAttribute("x1", X(best.x)); hl.setAttribute("x2", X(best.x)); hl.setAttribute("visibility", "visible");
      tip.hidden = false;
      tip.textContent = `${hhmm(best.x)} · ${best.v === null ? "no data" : best.v} · ${best.s}`;
      tip.style.left = `${(X(best.x) / W) * r.width}px`;
      tip.style.top = `${best.pv === null ? 20 : (Y(best.pv) / H) * r.height}px`;
    });
    el.addEventListener("mouseleave", () => { tip.hidden = true; hl.setAttribute("visibility", "hidden"); });

    $("#legend").innerHTML =
      '<span><i style="background:var(--accent)"></i>signal (1 min mean)</span>' +
      '<span><i style="background:var(--warn)"></i>alert limit</span><span><i style="background:var(--bad)"></i>trip limit</span>' +
      '<span><i style="background:var(--win)"></i>detected anomaly</span>' +
      '<span><i style="background:var(--band-fault)"></i>FAULT</span><span><i style="background:var(--band-idle)"></i>IDLE</span><span><i style="background:var(--band-clean)"></i>CLEAN</span>';
  }

  async function loadChart() {
    if (!state.scenario) return;
    try {
      const p = await api(`/api/scenarios/${state.scenario}/series?machine=${state.machine}&signal=${state.signal}`);
      drawChart(p);
    } catch (e) {
      $("#chart").textContent = e.message;
    }
  }

  /* Render */
  function renderStatus() {
    const s = state.status, pill = $("#statusPill");
    if (s.github_url) { const gh = $("#gh"); gh.href = s.github_url; gh.hidden = false; }
    if (s.live_available) {
      pill.className = "pill";
      pill.textContent = `Live agents · ${s.model} · ${s.runs_left_today} runs left today`;
    } else {
      pill.className = "pill off";
      pill.textContent = "Replay mode · live agents off";
    }
    $("#code").hidden = !(s.live_available && s.live_requires_code);
    $("#code").value = store.get("pocCode");
    updateButtons();
  }

  function updateButtons() {
    const sc = state.scenarios.find((x) => x.id === state.scenario);
    const s = state.status || {};
    $("#btnReplay").disabled = state.running || !sc || !sc.has_replay;
    $("#btnReplay").title = sc && !sc.has_replay ? "No recording has been added for this scenario yet." : "";
    $("#btnLive").disabled = state.running || !sc || !s.live_available || s.runs_left_today <= 0;
    $("#liveNote").textContent = !s.live_available ? "not configured" : s.runs_left_today <= 0 ? "daily limit reached" : "real model call" + (s.price_note ? " · " + s.price_note : "");
  }

  function renderScenarios() {
    const host = $("#scenarioCards");
    host.innerHTML = "";
    state.scenarios.forEach((sc) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "scn";
      b.setAttribute("aria-pressed", sc.id === state.scenario ? "true" : "false");
      b.innerHTML = `<strong>${esc(sc.title)}</strong><span>${esc(sc.story)}</span>`;
      b.addEventListener("click", () => selectScenario(sc.id));
      host.appendChild(b);
    });
  }

  function renderFindings() {
    const host = $("#findings");
    const f = state.overview.scan.findings;
    if (!f.length) {
      host.innerHTML = '<span class="chip ok">Detector: no anomalies, the line looks healthy</span>';
      return;
    }
    host.innerHTML = '<span class="meta">Detector findings (click to inspect):</span>';
    f.forEach((x) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip " + (x.severity >= 60 ? "high" : "mid");
      b.innerHTML = `<span class="sev">${x.severity}</span> ${esc(x.machine_id)} · ${esc(SIGNALS[x.signal] || x.signal)} · ${esc(x.issues.join(", "))}`;
      b.addEventListener("click", () => { state.machine = x.machine_id; state.signal = x.signal; syncSelects(); loadChart(); });
      host.appendChild(b);
    });
  }

  function renderKpis() {
    const rows = state.overview.kpis;
    const cols = [["machine_id", "Machine"], ["availability_pct", "Availability %"], ["fault_events", "Fault events"], ["longest_fault_s", "Longest fault (min)"],
      ["max_temp_c", "Max temp °C"], ["max_vibration_mm_s", "Max vib mm/s"], ["max_motor_current_a", "Max current A"], ["total_rejects", "Rejects"]];
    $("#kpiTable").innerHTML = "<thead><tr>" + cols.map((c) => `<th>${c[1]}</th>`).join("") + "</tr></thead><tbody>" +
      rows.map((r) => "<tr>" + cols.map(([k]) => `<td>${k === "machine_id" ? esc(r[k]) : k === "longest_fault_s" ? num(r[k] / 60, 1) : num(r[k], k === "fault_events" ? 0 : 1)}</td>`).join("") + "</tr>").join("") + "</tbody>";
  }

  function syncSelects() { $("#machineSel").value = state.machine; $("#signalSel").value = state.signal; }

  function resetRun() {
    state.timers.forEach(clearTimeout);
    state.timers = [];
    state.runId = null;
    $("#timeline").innerHTML = "";
    $("#report").hidden = true;
    $("#report").innerHTML = "";
    $("#orders").innerHTML = "";
    $("#runMeta").textContent = "";
    notice("");
  }

  async function selectScenario(id) {
    state.scenario = id;
    resetRun();
    renderScenarios();
    const sc = state.scenarios.find((x) => x.id === id);
    $("#truthText").textContent = sc.ground_truth;
    $("#truth").open = false;
    updateButtons();
    try {
      state.overview = await api(`/api/scenarios/${id}/overview`);
    } catch (e) { notice(e.message, "bad"); return; }
    const top = state.overview.scan.findings[0];
    if (top) { state.machine = top.machine_id; state.signal = top.signal; }
    else { state.machine = "FILLER-01"; state.signal = "vibration_mm_s"; }
    syncSelects();
    renderFindings();
    renderKpis();
    loadChart();
  }

  /* Timeline */
  function addTimeline(html, cls) {
    const d = document.createElement("div");
    d.className = "ev " + cls;
    d.innerHTML = html;
    $("#timeline").appendChild(d);
    d.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function addOrder(o) {
    const id = `wo-${esc(o.id)}`;
    const d = document.createElement("div");
    d.className = "order";
    d.id = id;
    d.innerHTML = `<header><span class="prio ${esc(o.priority)}">${esc(o.priority)}</span><strong>${esc(o.title)}</strong><span class="meta">${esc(o.id)} · ${esc(o.machine_id)} · proposed, not executed</span></header>` +
      `<dl><dt>Evidence</dt><dd>${esc(o.evidence)}</dd><dt>Suspected cause</dt><dd>${esc(o.suspected_cause)}</dd><dt>Action</dt><dd>${esc(o.recommended_action)}</dd></dl>` +
      `<p style="margin:10px 0 0"><button class="btn" type="button">Approve work order</button></p>`;
    $("button", d).addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        await api("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: state.runId || "replay", order_id: o.id }) });
        e.target.closest("p").innerHTML = '<span class="status-ok">Approved. In this demo nothing is sent to a real maintenance system.</span>';
      } catch (err) { e.target.disabled = false; notice(err.message, "bad"); }
    });
    $("#orders").appendChild(d);
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case "run_start":
        state.runId = ev.run_id;
        state.provider = ev.provider;
        $("#runMeta").textContent = `Run ${ev.run_id} · model: ${ev.model}`;
        if (ev.provider === "mock") notice("Scripted demo: no language model is involved in this run. It only exercises the pipeline.", "warn");
        break;
      case "agent_start":
        addTimeline(`<b>Step ${AGENT_STEP[ev.agent] || ""} · ${esc(ev.label)}</b>`, "agent");
        break;
      case "tool_call":
        addTimeline(`<span class="badge">TOOL</span><code>${esc(ev.name)}(${esc(Object.entries(ev.args || {}).map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v) : v}`).join(", "))})</code>`, "tool");
        break;
      case "tool_result":
        addTimeline(`<details><summary>result of <code>${esc(ev.name)}</code> (${ev.preview.length} chars)</summary><pre>${esc(ev.preview)}</pre></details>`, "tool");
        break;
      case "agent_message":
        if (ev.agent === "report_agent") addTimeline("Report drafted (shown below).", "msg");
        else addTimeline(md(ev.text), "msg");
        break;
      case "work_order":
        addOrder(ev.order);
        break;
      case "final": {
        const u = ev.usage || {};
        const cost = state.status && state.status.provider === "gemini" ? "free tier" : `≈ $${(u.est_cost_usd ?? 0).toFixed(4)}`;
        $("#runMeta").textContent += ` · ${u.llm_calls || 0} model calls · ${(u.total_tokens || 0).toLocaleString()} tokens · ${cost} · ${(ev.duration_s || 0).toFixed(1)} s`;
        if (ev.report) { const r = $("#report"); r.innerHTML = md(ev.report); r.hidden = false; }
        break;
      }
      case "error":
        notice(ev.message, "bad");
        break;
      default: break;
    }
  }

  /* Runs */
  function setRunning(v) { state.running = v; updateButtons(); }

  async function startReplay() {
    resetRun();
    setRunning(true);
    try {
      const rec = await api(`/api/replay/${state.scenario}`);
      const m = rec.meta || {};
      notice(`Recorded run${m.recorded_at ? " from " + m.recorded_at : ""}${m.model ? " with " + m.model : ""}. Played back at accelerated speed, no model call is made now.`, "info");
      let prev = 0, at = 0;
      rec.events.forEach((ev, idx) => {
        at += Math.min(Math.max((ev.t - prev) * 300, 120), 900);
        prev = ev.t;
        state.timers.push(setTimeout(() => {
          handleEvent(ev);
          if (idx === rec.events.length - 1) setRunning(false);
        }, at));
      });
    } catch (e) { notice(e.message, "bad"); setRunning(false); }
  }

  async function startLive() {
    resetRun();
    setRunning(true);
    const code = $("#code").value.trim();
    if (code) store.set("pocCode", code);
    try {
      const res = await fetch("/api/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: state.scenario, code: code || null }),
      });
      if (!res.ok) {
        let detail = `Request failed (${res.status})`;
        try { const j = await res.json(); if (typeof j.detail === "string") detail = j.detail; } catch { /* ignore */ }
        notice(detail, "warn");
        return;
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, i);
          buf = buf.slice(i + 2);
          if (chunk.startsWith("data: ")) { try { handleEvent(JSON.parse(chunk.slice(6))); } catch { /* ignore malformed */ } }
        }
      }
    } catch (e) {
      notice("Connection problem: " + e.message, "bad");
    } finally {
      setRunning(false);
      try { state.status = await api("/api/status"); renderStatus(); } catch { /* ignore */ }
    }
  }

  /* Boot */
  async function init() {
    const ms = $("#machineSel"), ss = $("#signalSel");
    MACHINES.forEach((m) => ms.add(new Option(m, m)));
    Object.entries(SIGNALS).forEach(([k, v]) => ss.add(new Option(v, k)));
    ms.addEventListener("change", () => { state.machine = ms.value; loadChart(); });
    ss.addEventListener("change", () => { state.signal = ss.value; loadChart(); });
    $("#btnReplay").addEventListener("click", startReplay);
    $("#btnLive").addEventListener("click", startLive);
    try {
      [state.status, state.scenarios] = await Promise.all([api("/api/status"), api("/api/scenarios")]);
    } catch (e) {
      $("#statusPill").textContent = "backend unavailable";
      notice(e.message, "bad");
      return;
    }
    renderStatus();
    const preferred = state.scenarios.find((s) => s.id === "bearing_wear") || state.scenarios[0];
    if (preferred) await selectScenario(preferred.id);
  }

  init();
})();
