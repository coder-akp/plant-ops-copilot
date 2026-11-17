/* Plant Ops Copilot front end: plain JavaScript, no framework, no build step.
   Strings live in i18n.js (English and German). The 3D view (scene.js) loads after the page is usable. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const MACHINES = ["FILLER-01", "CAPPER-01", "LABELER-01", "PACKER-01"];
  const SIGNAL_KEYS = ["temp_c", "vibration_mm_s", "motor_current_a", "cycle_time_s", "rejects_per_min"];
  const AGENT_STEP = { detection_agent: 1, diagnosis_agent: 2, report_agent: 3 };
  const TOUR = ["bearing_wear", "overheating", "sensor_fault", "healthy"];

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  const lowPower = coarse || (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4;
  const params = new URLSearchParams(location.search);

  /* Preferences (language, theme) persist across visits; everything else is per session */
  const pref = {
    get(k) { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  };
  const store = {
    get(k) { try { return sessionStorage.getItem(k) || ""; } catch { return ""; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } },
  };

  /* Language */
  const I18N = window.POC_I18N;
  function pickLang() {
    const q = params.get("lang");
    if (q === "de" || q === "en") return q;
    const saved = pref.get("pocLang");
    if (saved === "de" || saved === "en") return saved;
    return (navigator.language || "en").toLowerCase().startsWith("de") ? "de" : "en";
  }
  let lang = pickLang();
  const t = (k, v) => {
    let s = I18N[lang][k];
    if (s === undefined) s = I18N.en[k] !== undefined ? I18N.en[k] : k;
    return v ? s.replace(/\{(\w+)\}/g, (m, n) => (v[n] !== undefined ? v[n] : m)) : s;
  };
  const nf = (x, d = 1) => Number(x).toLocaleString(lang === "de" ? "de-DE" : "en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const num = (x, d = 1) => (x === null || x === undefined ? "–" : nf(x, d));
  const roleOf = (id) => t("role_" + id.split("-")[0]);
  const sigName = (k) => t("sig_" + k);
  const issueName = (c) => { const v = I18N[lang]["issue_" + c]; return v !== undefined ? v : c.replace(/_/g, " "); };
  const scText = (sc, part) => { const v = I18N[lang][`sc_${sc.id}_${part}`]; return v !== undefined ? v : ({ t: sc.title, s: sc.story, g: sc.ground_truth })[part]; };

  const state = {
    status: null,
    scenarios: [],
    scenario: null,
    machine: "FILLER-01",
    signal: "vibration_mm_s",
    overview: null,
    series: null,
    running: false,
    queue: [],
    timers: [],
    events: [],
    approved: new Set(),
    runInfo: null,
    final: null,
    pipe: [null, { st: "idle" }, { st: "idle" }, { st: "idle" }, { st: "idle" }],
    now: null,
    notice: null,
    caption: null,
    scene: null,
    tools: 0,
    stepTools: [0, 0, 0, 0, 0],
    step: 0,
    clock: null,
    t0: 0,
    tour: null,
    replayDone: null,
  };

  /* Helpers */
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const kindOf = (sev) => (sev >= 60 ? "alert" : sev > 0 ? "watch" : "ok");

  /* Messages from the server are English; known ones are translated */
  const SERVER_MSG = [
    [/not configured on this deployment/, "s503a"], [/switched off by the owner/, "s503b"], [/access code is required/, "s403"],
    [/Another live run is in progress/, "s429busy"], [/Please wait (\d+)s/, "s429wait"], [/daily limit of live runs/, "s429day"],
    [/per-visitor limit/, "s429ip"], [/daily model budget/, "s429budget"],
  ];
  function serverMsg(detail) {
    for (const [re, k] of SERVER_MSG) {
      const m = String(detail).match(re);
      if (m) return t(k, { n: m[1] });
    }
    return detail;
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = null;
      try {
        const j = await res.json();
        if (typeof j.detail === "string") detail = j.detail;
      } catch { /* ignore */ }
      const err = new Error(detail || t("reqFailed", { s: res.status }));
      err.status = res.status;
      err.raw = detail;
      throw err;
    }
    return res.json();
  }

  /* Read-only data never changes within a session, so each GET is fetched once and prefetched ahead of the click. */
  const cache = new Map();
  function getJSON(path) {
    if (!cache.has(path)) cache.set(path, api(path).catch((e) => { cache.delete(path); throw e; }));
    return cache.get(path);
  }

  /* The notice and the "now" line are stored as functions so they can be re-rendered when the language changes */
  function setNotice(fn) { state.notice = fn; renderNotice(); }
  function renderNotice() {
    const box = $("#notice");
    const n = state.notice ? state.notice() : null;
    box.innerHTML = n ? `<div class="notice ${n.kind}" role="status">${esc(n.msg)}</div>` : "";
  }
  const notice = (msg, kind = "info") => setNotice(msg ? () => ({ msg: serverMsg(msg), kind }) : null);

  function setNow(fn, busy) { state.now = fn; $(".spin", $("#now")).hidden = !busy; renderNow(); }
  function renderNow() { $("#nowText").innerHTML = state.now ? state.now() : esc(t("nowIdle")); }

  /* Tooltips for any element with data-tip (hover, keyboard focus, or a tap on touch screens) */
  const gtip = $("#gtip");
  let tipTimer = 0;
  function showTip(el) {
    gtip.textContent = el.dataset.tip;
    gtip.hidden = false;
    const r = el.getBoundingClientRect();
    const w = gtip.offsetWidth, h = gtip.offsetHeight;
    const x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    const below = r.top < h + 16;
    gtip.style.left = `${x}px`;
    gtip.style.top = `${below ? r.bottom + 8 : r.top - h - 8}px`;
  }
  const hideTip = () => { gtip.hidden = true; clearTimeout(tipTimer); };
  document.addEventListener("pointerover", (e) => {
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (el && e.pointerType === "mouse") showTip(el);
  });
  document.addEventListener("pointerout", (e) => { if (e.target.closest && e.target.closest("[data-tip]")) hideTip(); });
  document.addEventListener("focusin", (e) => { const el = e.target.closest && e.target.closest("[data-tip]"); if (el) showTip(el); });
  document.addEventListener("focusout", hideTip);
  document.addEventListener("pointerdown", (e) => {
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (el && e.pointerType !== "mouse") { showTip(el); clearTimeout(tipTimer); tipTimer = setTimeout(hideTip, 2600); }
  });
  window.addEventListener("scroll", hideTip, { passive: true });

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
        svg += `<text class="win-label" x="${(a + 4).toFixed(1)}" y="${T + 11}">${esc(t("win_" + w.type))}</text>`;
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
      svg += `<line class="lim-${k}" x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="lim-label ${k}" x="${W - R - 4}" y="${(Y(v) - 4).toFixed(1)}" text-anchor="end">${t(k === "alert" ? "limAlert" : "limTrip")} ${nf(v, 1)}</text>`;
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
    el.style.touchAction = "pan-y";
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const gx = ((e.clientX - r.left) / r.width) * W;
      if (gx < L || gx > W - R) { tip.hidden = true; hl.setAttribute("visibility", "hidden"); return; }
      const t = x0 + ((gx - L) / (W - L - R)) * (x1 - x0);
      let best = pts[0];
      for (const q of pts) if (Math.abs(q.x - t) < Math.abs(best.x - t)) best = q;
      hl.setAttribute("x1", X(best.x)); hl.setAttribute("x2", X(best.x)); hl.setAttribute("visibility", "visible");
      tip.hidden = false;
      tip.textContent = `${hhmm(best.x)} · ${best.v === null ? t("noData") : nf(best.v, 2)} · ${best.s}`;
      tip.style.left = `${(X(best.x) / W) * r.width}px`;
      tip.style.top = `${best.pv === null ? 20 : (Y(best.pv) / H) * r.height}px`;
    });
    el.addEventListener("pointerleave", () => { tip.hidden = true; hl.setAttribute("visibility", "hidden"); });

    $("#legend").innerHTML =
      `<span><i style="background:var(--accent)"></i>${t("lgSignal")}</span>` +
      `<span><i style="background:var(--warn)"></i>${t("lgAlert")}</span><span><i style="background:var(--bad)"></i>${t("lgTrip")}</span>` +
      `<span><i style="background:var(--win)"></i>${t("lgAnomaly")}</span>` +
      `<span><i style="background:var(--band-fault)"></i>${t("lgFault")}</span><span><i style="background:var(--band-idle)"></i>${t("lgIdle")}</span><span><i style="background:var(--band-clean)"></i>${t("lgClean")}</span>`;
  }

  async function loadChart() {
    if (!state.scenario) return;
    try {
      state.series = await getJSON(`/api/scenarios/${state.scenario}/series?machine=${state.machine}&signal=${state.signal}`);
      drawChart(state.series);
    } catch (e) {
      $("#chart").textContent = serverMsg(e.message);
    }
  }

  /* Machine information shared by the 3D labels, the 2D tiles, the hover card and the side panel */
  function machineInfo(id) {
    const o = state.overview;
    if (!o) return null;
    const k = o.kpis.find((r) => r.machine_id === id) || {};
    const f = o.scan.findings.filter((x) => x.machine_id === id).sort((a, b) => b.severity - a.severity);
    const sev = f.length ? f[0].severity : 0;
    return { id, k, f, sev, kind: kindOf(sev) };
  }
  const issuesText = (f) => f.issues.map(issueName).join(", ");
  const kindLabel = (i) => `${t("kind_" + i.kind)}${i.sev ? " · " + i.sev : ""}`;

  function machineCard(id, hint) {
    const i = machineInfo(id);
    if (!i) return "";
    const top = i.f[0];
    const issue = top ? `${esc(sigName(top.signal))} · ${esc(issuesText(top))}` : esc(t("mNone"));
    return `<div class="mt-head"><b>${esc(id)}</b><span class="st ${i.kind}">${esc(kindLabel(i))}</span></div>` +
      `<div class="mt-role">${esc(roleOf(id))}</div><div class="mt-issue">${issue}</div>` +
      `<div class="mt-grid"><div><span>${t("mAvail")}</span><b>${num(i.k.availability_pct, 1)}%</b></div><div><span>${t("mFaults")}</span><b>${num(i.k.fault_events, 0)}</b></div>` +
      `<div><span>${t("mVib")}</span><b>${num(i.k.max_vibration_mm_s, 1)} mm/s</b></div><div><span>${t("mTemp")}</span><b>${num(i.k.max_temp_c, 1)} °C</b></div></div>` +
      (hint ? `<div class="mt-hint">${esc(hint)}</div>` : "");
  }

  function showMachineTip(h) {
    const tip = $("#mtip");
    if (!h) { tip.hidden = true; return; }
    tip.innerHTML = machineCard(h.id, t("mClick"));
    tip.hidden = false;
    const w = tip.offsetWidth, ht = tip.offsetHeight;
    tip.style.left = `${Math.min(Math.max(8, h.x + 14), h.w - w - 8)}px`;
    tip.style.top = `${Math.min(Math.max(8, h.y - ht - 10), h.h - ht - 8)}px`;
  }

  /* KPI ribbon with a short count-up */
  function countTo(el, to, fmt) {
    const from = parseFloat(el.dataset.v || "0") || 0;
    el.dataset.v = to;
    if (reduceMotion || from === to) { el.textContent = fmt(to); return; }
    const t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / 450);
      el.textContent = fmt(from + (to - from) * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function renderRibbon() {
    const o = state.overview;
    if (!o) return;
    const k = o.kpis;
    const avail = k.reduce((s, r) => s + (r.availability_pct || 0), 0) / (k.length || 1);
    const alerts = o.scan.findings.length;
    const top = o.scan.findings.reduce((m, f) => Math.max(m, f.severity), 0);
    const faults = k.reduce((s, r) => s + (r.fault_events || 0), 0);
    const tiles = [
      ["avail", "kpiAvail", avail, (v) => nf(v, 1) + "%", "ok", "kpiAvailTip"],
      ["alerts", "kpiFind", alerts, (v) => Math.round(v), alerts ? "watch" : "ok", "kpiFindTip"],
      ["sev", "kpiSev", top, (v) => Math.round(v), kindOf(top), "kpiSevTip"],
      ["faults", "kpiFault", faults, (v) => Math.round(v), faults ? "watch" : "ok", "kpiFaultTip"],
    ];
    const host = $("#kpiRibbon");
    if (host.dataset.lang !== lang) {
      const fresh = !host.children.length;
      host.dataset.lang = lang;
      host.innerHTML = tiles.map((x) => `<div class="kpi" id="k-${x[0]}" data-tip="${esc(t(x[5]))}"><span class="v" data-v="${fresh ? 0 : x[2]}">${fresh ? 0 : x[3](x[2])}</span><span class="l">${esc(t(x[1]))}</span></div>`).join("");
    }
    tiles.forEach((x) => {
      const el = $(`#k-${x[0]}`);
      el.className = "kpi " + x[4];
      countTo($(".v", el), x[2], x[3]);
    });
  }

  /* Line status: 2D tiles are always present as a fallback and for first paint */
  function renderFlat() {
    const host = $("#flat");
    if (!host.children.length) {
      MACHINES.forEach((id) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "tile ok";
        b.dataset.id = id;
        b.innerHTML = `<span class="t-id"><i></i>${id}</span><span class="t-role"></span><div class="t-sev"></div>`;
        b.addEventListener("click", () => selectMachine(id));
        b.addEventListener("pointerenter", (e) => {
          if (e.pointerType !== "mouse") return;
          const r = $("#scene").getBoundingClientRect();
          showMachineTip({ id, x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height });
        });
        b.addEventListener("pointerleave", () => showMachineTip(null));
        host.appendChild(b);
      });
    }
    if (!state.overview) return;
    $$(".tile", host).forEach((tl) => {
      const i = machineInfo(tl.dataset.id);
      tl.className = `tile ${i.kind}` + (tl.dataset.id === state.machine ? " sel" : "");
      $(".t-role", tl).textContent = roleOf(tl.dataset.id);
      $(".t-sev", tl).textContent = i.sev ? kindLabel(i) : t("kind_ok");
    });
  }

  function pushSceneData() {
    if (!state.scene || !state.overview) return;
    const map = {};
    MACHINES.forEach((id) => {
      const i = machineInfo(id);
      map[id] = { sev: i.sev, vibration: i.f.some((x) => x.signal === "vibration_mm_s" && x.severity > 0), text: i.sev ? kindLabel(i) : roleOf(id), role: roleOf(id) };
    });
    state.scene.setData(map);
  }

  function renderMachinePanel() {
    const host = $("#mpanel");
    const i = machineInfo(state.machine);
    if (!i) { host.hidden = true; return; }
    host.hidden = false;
    host.innerHTML = machineCard(state.machine, "") + `<a href="#data">${esc(t("openChart"))}</a>`;
  }

  function markSelected() { $$(".m3d-label").forEach((el) => el.classList.toggle("sel", el.dataset.id === state.machine)); }

  function selectMachine(id, opts = {}) {
    state.machine = id;
    const i = machineInfo(id);
    if (i && i.f[0] && !opts.keepSignal) state.signal = i.f[0].signal;
    syncSelects();
    loadChart();
    renderFlat();
    renderMachinePanel();
    if (state.scene) state.scene.select(id, opts.zoom !== false);
    markSelected();
  }

  /* 3D scene: loaded after first paint, skipped on data-saver or when WebGL is unavailable or software-rendered */
  async function initScene() {
    const saver = navigator.connection && navigator.connection.saveData;
    if (state.scene || params.get("scene") === "2d" || saver) return;
    try {
      const mod = await import("/static/scene.js");
      if (!mod.webglSupported(params.get("gl") === "force")) return;
      state.scene = mod.createScene($("#scene3d"), {
        lowPower, reduceMotion, touch: coarse,
        onSelect: (id) => selectMachine(id),
        onHover: showMachineTip,
        onLost: () => { document.body.classList.remove("has3d"); state.scene = null; $("#btnReset").hidden = true; $("#btnOrbit").hidden = true; },
      });
      document.body.classList.add("has3d");
      $("#btnReset").hidden = false;
      $("#btnOrbit").hidden = !coarse;
      pushSceneData();
      state.scene.select(state.machine, false);
      markSelected();
    } catch { /* the 2D view stays */ }
  }

  /* Render */
  function renderStatus() {
    const s = state.status, pill = $("#statusPill");
    if (!s) { pill.textContent = t("pillDown"); return; }
    if (s.github_url) { const gh = $("#gh"); gh.href = s.github_url; gh.hidden = false; }
    if (s.live_available) {
      pill.className = "pill";
      pill.textContent = t("pillLive", { model: s.model, runs: s.runs_left_today });
    } else {
      pill.className = "pill off";
      pill.textContent = t("pillOff");
    }
    $("#code").hidden = !(s.live_available && s.live_requires_code);
    if (!$("#code").value) $("#code").value = store.get("pocCode");
    updateButtons();
  }

  function updateButtons() {
    const sc = state.scenarios.find((x) => x.id === state.scenario);
    const s = state.status || {};
    const busy = state.running;
    $("#btnReplay").disabled = busy || !sc || !sc.has_replay;
    $("#btnLive").disabled = busy || !sc || !s.live_available || s.runs_left_today <= 0;
    $("#liveNote").textContent = !s.live_available ? t("liveOff") : s.runs_left_today <= 0 ? t("liveLimit") : t("liveSub") + (s.price_note ? " · " + s.price_note : "");
    $("#btnSkip").hidden = !(busy && state.queue.length);
    $("#btnTour").disabled = busy && !state.tour;
    $("#btnTour").textContent = state.tour ? t("tourStop") : t("tour");
    $$(".scn").forEach((b) => { b.disabled = !!state.tour; });
  }

  function renderScenarios() {
    const host = $("#scenarioCards");
    host.innerHTML = "";
    state.scenarios.forEach((sc) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "scn";
      b.dataset.id = sc.id;
      b.dataset.tip = scText(sc, "s");
      b.setAttribute("aria-pressed", sc.id === state.scenario ? "true" : "false");
      b.textContent = scText(sc, "t");
      b.addEventListener("click", () => selectScenario(sc.id));
      host.appendChild(b);
    });
  }

  function renderTruth() {
    const sc = state.scenarios.find((x) => x.id === state.scenario);
    $("#truthText").textContent = sc ? scText(sc, "g") : "";
  }

  function renderFindings() {
    const host = $("#findings");
    const f = state.overview.scan.findings;
    if (!f.length) {
      host.innerHTML = `<span class="chip ok">${esc(t("findNone"))}</span>`;
      return;
    }
    host.innerHTML = "";
    f.forEach((x) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip " + (x.severity >= 60 ? "high" : "mid");
      b.innerHTML = `<span class="sev">${x.severity}</span> ${esc(x.machine_id)} · ${esc(sigName(x.signal))} · ${esc(issuesText(x))}`;
      b.addEventListener("click", () => { state.signal = x.signal; selectMachine(x.machine_id, { keepSignal: true }); });
      host.appendChild(b);
    });
  }

  function renderKpis() {
    const rows = state.overview.kpis;
    const cols = ["machine_id", "availability_pct", "fault_events", "longest_fault_s", "max_temp_c", "max_vibration_mm_s", "max_motor_current_a", "total_rejects"];
    $("#kpiTable").innerHTML = "<thead><tr>" + cols.map((c) => `<th>${esc(t("th_" + c))}</th>`).join("") + "</tr></thead><tbody>" +
      rows.map((r) => "<tr>" + cols.map((k) => `<td>${k === "machine_id" ? esc(r[k]) : k === "longest_fault_s" ? num(r[k] / 60, 1) : num(r[k], k === "fault_events" ? 0 : 1)}</td>`).join("") + "</tr>").join("") + "</tbody>";
  }

  function fillSelects() {
    const ms = $("#machineSel"), ss = $("#signalSel");
    ms.innerHTML = ""; ss.innerHTML = "";
    MACHINES.forEach((m) => ms.add(new Option(`${m} · ${roleOf(m)}`, m)));
    SIGNAL_KEYS.forEach((k) => ss.add(new Option(sigName(k), k)));
    syncSelects();
  }
  function syncSelects() { $("#machineSel").value = state.machine; $("#signalSel").value = state.signal; }

  /* Agent pipeline and run meter */
  const toolNote = (n) => (n ? { k: n === 1 ? "toolOne" : "toolN", v: { n } } : null);
  function setStep(n, st, note) { state.pipe[n] = { st, note: note || null }; renderPipe(); }
  function renderPipe() {
    for (let n = 1; n <= 4; n++) {
      const li = $(`#pipe li[data-step="${n}"]`), p = state.pipe[n];
      li.dataset.state = p.st;
      $("em", li).textContent = p.note ? t(p.note.k, p.note.v) : "";
    }
  }
  function resetPipe() { for (let n = 1; n <= 4; n++) state.pipe[n] = { st: "idle", note: null }; renderPipe(); }

  const costText = () => {
    const u = (state.final && state.final.usage) || {};
    return state.status && state.status.provider === "gemini" ? t("free") : `≈ $${nf(u.est_cost_usd ?? 0, 4)}`;
  };
  function renderMeter() {
    const u = state.final ? state.final.usage || {} : null;
    $("#mTools").textContent = state.tools;
    $("#mCalls").textContent = u ? u.llm_calls || 0 : "–";
    $("#mTokens").textContent = u ? ((u.total_tokens || 0) >= 1000 ? nf((u.total_tokens || 0) / 1000, 1) + "k" : String(u.total_tokens || 0)) : "–";
    $("#mCost").textContent = u ? costText().replace("≈ ", "") : "–";
    if (state.final && state.final.duration_s) $("#mTime").textContent = nf(state.final.duration_s, 1);
  }
  function renderRunMeta() {
    const r = state.runInfo;
    let s = r ? `${t("run")} ${r.id} · ${t("model")}: ${r.model}` : "";
    if (r && state.final) {
      const u = state.final.usage || {};
      s += ` · ${t("modelCalls", { n: u.llm_calls || 0 })} · ${t("tokensN", { n: (u.total_tokens || 0).toLocaleString(lang === "de" ? "de-DE" : "en-US") })} · ${costText()} · ${t("sec", { n: nf(state.final.duration_s || 0, 1) })}`;
    }
    $("#runMeta").textContent = s;
  }
  function startClock() {
    stopClock();
    state.t0 = performance.now();
    state.clock = setInterval(() => { $("#mTime").textContent = nf((performance.now() - state.t0) / 1000, 1); }, 100);
  }
  function stopClock() { if (state.clock) { clearInterval(state.clock); state.clock = null; } }

  function resetRun() {
    state.timers.forEach(clearTimeout);
    state.timers = [];
    state.queue = [];
    state.events = [];
    state.approved = new Set();
    state.runId = null;
    state.runInfo = null;
    state.final = null;
    state.tools = 0;
    state.stepTools = [0, 0, 0, 0, 0];
    state.step = 0;
    stopClock();
    $("#timeline").innerHTML = "";
    $("#report").hidden = true;
    $("#report").innerHTML = "";
    $("#orders").innerHTML = "";
    $("#traceEmpty").hidden = false;
    $("#jumpReport").hidden = true;
    $("#mTime").textContent = nf(0, 1);
    resetPipe();
    renderMeter();
    renderRunMeta();
    setNow(null, false);
    if (state.scene) { state.scene.clearFlags(); state.scene.follow(null); }
    setNotice(null);
  }

  const replayUrl = (id) => `/api/replay/${id}?lang=${lang}`;

  async function selectScenario(id) {
    state.scenario = id;
    resetRun();
    renderScenarios();
    renderTruth();
    $("#truth").open = false;
    updateButtons();
    try {
      state.overview = await getJSON(`/api/scenarios/${id}/overview`);
    } catch (e) { notice(e.message, "bad"); return; }
    if (state.scenario !== id) return;
    const top = state.overview.scan.findings[0];
    state.machine = top ? top.machine_id : "FILLER-01";
    state.signal = top ? top.signal : "vibration_mm_s";
    syncSelects();
    renderFindings();
    renderKpis();
    renderRibbon();
    renderFlat();
    renderMachinePanel();
    pushSceneData();
    if (state.scene) state.scene.select(state.machine, false);
    markSelected();
    loadChart();
    const sc = state.scenarios.find((x) => x.id === id);
    if (sc.has_replay) getJSON(replayUrl(id)).catch(() => {});
  }

  /* Trace: timeline, report and work orders */
  function addTimeline(html, cls) {
    const d = document.createElement("div");
    d.className = "ev " + cls;
    d.innerHTML = html;
    const tl = $("#timeline");
    const stick = tl.scrollHeight - tl.scrollTop - tl.clientHeight < 80;
    tl.appendChild(d);
    if (stick) tl.scrollTop = tl.scrollHeight;
  }

  function addOrder(o) {
    const d = document.createElement("div");
    d.className = "order";
    d.id = `wo-${o.id}`;
    d.innerHTML = `<header><span class="prio ${esc(o.priority)}">${esc(o.priority)}</span><strong>${esc(o.title)}</strong><span class="meta">${esc(o.id)} · ${esc(o.machine_id)} · ${esc(t("proposed"))}</span></header>` +
      `<dl><dt>${t("evidence")}</dt><dd>${esc(o.evidence)}</dd><dt>${t("cause")}</dt><dd>${esc(o.suspected_cause)}</dd><dt>${t("action")}</dt><dd>${esc(o.recommended_action)}</dd></dl>` +
      `<p style="margin:10px 0 0"><button class="btn" type="button">${esc(t("approveBtn"))}</button></p>`;
    $("button", d).addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        await api("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: state.runId || "replay", order_id: o.id }) });
        e.target.closest("p").innerHTML = `<span class="status-ok">${esc(t("approvedMsg"))}</span>`;
        setStep(4, "done", { k: "approved" });
        setNow(() => esc(t("approvedNow")), false);
      } catch (err) { e.target.disabled = false; notice(err.message, "bad"); }
    });
    $("#orders").appendChild(d);
  }

  const argText = (args) => Object.entries(args || {}).map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v) : v}`).join(", ");
  const AGENT_NAME = { detection_agent: "hDet", diagnosis_agent: "hDiag", report_agent: "hRep" };
  const agentName = (ev) => (AGENT_NAME[ev.agent] ? t(AGENT_NAME[ev.agent]) : ev.label);

  function renderTrace(ev) {
    switch (ev.type) {
      case "run_start":
        $("#traceEmpty").hidden = true;
        break;
      case "agent_start":
        addTimeline(`<b>${esc(t("stepN", { n: AGENT_STEP[ev.agent] || "", label: agentName(ev) }))}</b>`, "agent");
        break;
      case "tool_call":
        addTimeline(`<span class="badge">${esc(t("toolBadge"))}</span><code>${esc(ev.name)}(${esc(argText(ev.args))})</code>`, "tool");
        break;
      case "tool_result":
        addTimeline(`<details><summary>${esc(t("resultOf"))} <code>${esc(ev.name)}</code> (${esc(t("chars", { n: ev.preview.length }))})</summary><pre>${esc(ev.preview)}</pre></details>`, "tool");
        break;
      case "agent_message":
        if (ev.agent === "report_agent") addTimeline(esc(t("reportDrafted")), "msg");
        else addTimeline(md(ev.text), "msg");
        break;
      case "work_order":
        addOrder(ev.order);
        break;
      case "final":
        if (ev.report) { const r = $("#report"); r.innerHTML = md(ev.report); r.hidden = false; }
        break;
      default: break;
    }
  }

  /* Progress: pipeline, run meter, 3D scene */
  function progress(ev) {
    switch (ev.type) {
      case "run_start":
        state.runId = ev.run_id;
        state.runInfo = { id: ev.run_id, model: ev.model };
        renderRunMeta();
        setNow(() => esc(t("runStarted")), true);
        if (ev.provider === "mock") setNotice(() => ({ msg: t("mockNote"), kind: "warn" }));
        break;
      case "agent_start": {
        const n = AGENT_STEP[ev.agent] || 0;
        for (let i = 1; i < n; i++) setStep(i, "done", toolNote(state.stepTools[i]));
        if (n) setStep(n, "active", { k: "working" });
        state.step = n;
        setNow(() => t("agentStarted", { label: esc(agentName(ev)) }), true);
        break;
      }
      case "tool_call": {
        state.tools += 1;
        state.stepTools[state.step] += 1;
        if (state.step) setStep(state.step, "active", toolNote(state.stepTools[state.step]));
        $("#mTools").textContent = state.tools;
        const m = ev.args && ev.args.machine_id;
        setNow(() => `<code>${esc(ev.name)}</code>${m ? esc(t("on", { m })) : ""}`, true);
        if (state.scene) { if (m) { state.scene.follow(m); state.scene.pulse(m); } else state.scene.pulse(null); }
        $$(".tile").forEach((tl) => { tl.classList.toggle("pulse", !m || tl.dataset.id === m); setTimeout(() => tl.classList.remove("pulse"), 900); });
        break;
      }
      case "work_order":
        if (state.scene) state.scene.flag(ev.order.machine_id, true);
        setStep(4, "wait", { k: "awaiting" });
        break;
      case "final":
        state.final = ev;
        renderMeter();
        renderRunMeta();
        for (let i = 1; i <= 3; i++) setStep(i, "done", toolNote(state.stepTools[i]));
        if (state.pipe[4].st === "idle") setStep(4, "skip", { k: "noOrder" });
        $("#jumpReport").hidden = false;
        setNow(() => esc(state.pipe[4].st === "wait" ? t("reportWait") : t("reportReady")), false);
        if (state.scene) state.scene.follow(null);
        break;
      case "error":
        notice(ev.message, "bad");
        for (let i = 1; i <= 4; i++) if (state.pipe[i].st === "active") state.pipe[i].st = "error";
        renderPipe();
        setNow(() => esc(serverMsg(ev.message)), false);
        break;
      default: break;
    }
  }

  function handleEvent(ev) {
    state.events.push(ev);
    renderTrace(ev);
    progress(ev);
  }

  /* Runs. The agents write in the interface language from the start: replays are recorded per language and live runs receive the language. */
  function setRunning(v) {
    state.running = v;
    if (!v) stopClock();
    updateButtons();
  }

  function finishReplay() {
    state.queue = [];
    state.timers = [];
    setRunning(false);
    if (state.replayDone) { const f = state.replayDone; state.replayDone = null; f(); }
  }

  async function startReplay() {
    resetRun();
    setRunning(true);
    try {
      const rec = await getJSON(replayUrl(state.scenario));
      const m = rec.meta || {};
      const fallback = (m.language || "en") !== lang;
      setNotice(() => ({
        msg: t("replayNote", { date: m.recorded_at ? t("replayFrom", { d: m.recorded_at }) : "", model: m.model ? t("replayWith", { m: m.model }) : "" }) + (fallback ? " " + t("replayFallback") : ""),
        kind: fallback ? "warn" : "info",
      }));
      const events = rec.events;
      /* Compress the recorded timing so a full run plays in at most about 8 seconds */
      const gaps = events.map((ev, i) => Math.min(Math.max((ev.t - (i ? events[i - 1].t : 0)) * 300, 40), 420));
      const total = gaps.reduce((a, b) => a + b, 0);
      const k = total > 8000 ? 8000 / total : 1;
      let at = 0;
      state.queue = events.slice();
      startClock();
      events.forEach((ev, idx) => {
        at += gaps[idx] * k;
        state.timers.push(setTimeout(() => {
          state.queue.shift();
          handleEvent(ev);
          if (idx === events.length - 1) finishReplay();
        }, at));
      });
      updateButtons();
      return new Promise((resolve) => { state.replayDone = resolve; });
    } catch (e) { notice(e.message, "bad"); setRunning(false); }
    return Promise.resolve();
  }

  function skipReplay() {
    const rest = state.queue.slice();
    state.timers.forEach(clearTimeout);
    state.timers = [];
    state.queue = [];
    rest.forEach(handleEvent);
    finishReplay();
  }

  async function startLive() {
    resetRun();
    setRunning(true);
    startClock();
    const code = $("#code").value.trim();
    if (code) store.set("pocCode", code);
    try {
      const res = await fetch("/api/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: state.scenario, code: code || null, lang }),
      });
      if (!res.ok) {
        let detail = null;
        try { const j = await res.json(); if (typeof j.detail === "string") detail = j.detail; } catch { /* ignore */ }
        setNotice(() => ({ msg: detail ? serverMsg(detail) : t("reqFailed", { s: res.status }), kind: "warn" }));
        setNow(() => esc(detail ? serverMsg(detail) : t("reqFailed", { s: res.status })), false);
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
      setNotice(() => ({ msg: t("connErr", { m: e.message }), kind: "bad" }));
    } finally {
      setRunning(false);
      try { state.status = await api("/api/status"); renderStatus(); } catch { /* ignore */ }
    }
  }

  /* Presentation mode and guided tour */
  function setPresent(on) {
    document.documentElement.classList.toggle("present", on);
    $("#btnExit").hidden = !on;
    if (state.scene) state.scene.invalidate();
    window.scrollTo({ top: 0 });
  }
  function togglePresent() {
    const on = !document.documentElement.classList.contains("present");
    setPresent(on);
    const el = document.documentElement;
    try {
      if (on && el.requestFullscreen) el.requestFullscreen().catch(() => {});
      else if (!on && document.fullscreenElement) document.exitFullscreen();
    } catch { /* fullscreen is optional */ }
  }
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement) setPresent(false); });

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function renderCaption() {
    const el = $("#caption");
    el.hidden = !state.caption;
    el.textContent = state.caption ? t("tour_" + state.caption) : "";
  }
  function stopTour() {
    if (!state.tour) return;
    state.tour.stop = true;
    state.tour = null;
    state.caption = null;
    renderCaption();
  }
  async function runTour() {
    if (state.tour) { stopTour(); skipReplay(); updateButtons(); return; }
    const tour = { stop: false };
    state.tour = tour;
    updateButtons();
    for (const id of TOUR) {
      if (tour.stop) break;
      await selectScenario(id);
      if (tour.stop) break;
      state.caption = id;
      renderCaption();
      await sleep(1600);
      if (tour.stop) break;
      await startReplay();
      if (tour.stop) break;
      await sleep(2600);
    }
    if (state.tour === tour) { state.tour = null; state.caption = null; renderCaption(); }
    updateButtons();
  }

  /* Language and theme */
  function applyStatic() {
    document.documentElement.lang = lang;
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    $$("[data-i18n-tip]").forEach((el) => { el.dataset.tip = t(el.dataset.i18nTip); });
    $$("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
    $$("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
    $("#btnLang").textContent = lang === "de" ? "EN" : "DE";
  }

  /* A recorded or live run holds text the agents wrote in one language, so changing the language ends the current run */
  function setLang(l) {
    if (l === lang) return;
    stopTour();
    state.timers.forEach(clearTimeout);
    state.timers = [];
    state.queue = [];
    if (state.replayDone) { const f = state.replayDone; state.replayDone = null; f(); }
    setRunning(false);
    lang = l;
    pref.set("pocLang", l);
    applyStatic();
    renderStatus();
    renderScenarios();
    renderTruth();
    fillSelects();
    resetRun();
    if (state.overview) {
      renderFindings(); renderKpis(); renderRibbon(); renderFlat(); renderMachinePanel(); pushSceneData(); markSelected();
    }
    if (state.series) drawChart(state.series);
    showMachineTip(null);
    updateButtons();
    const sc = state.scenarios.find((x) => x.id === state.scenario);
    if (sc && sc.has_replay) getJSON(replayUrl(sc.id)).catch(() => {});
  }
  function applyTheme(th) {
    document.documentElement.dataset.theme = th;
    $("#btnTheme").innerHTML = th === "dark" ? "&#9790;" : "&#9728;";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = th === "dark" ? "#0a0f16" : "#f3f5f9";
  }
  function initialTheme() {
    const q = params.get("theme");
    if (q === "light" || q === "dark") return q;
    const saved = pref.get("pocTheme");
    if (saved === "light" || saved === "dark") return saved;
    return "dark";
  }

  /* Boot */
  async function init() {
    applyTheme(initialTheme());
    applyStatic();
    fillSelects();
    renderFlat();
    renderPipe();
    renderNow();
    renderMeter();
    $("#machineSel").addEventListener("change", (e) => selectMachine(e.target.value, { keepSignal: true, zoom: false }));
    $("#signalSel").addEventListener("change", (e) => { state.signal = e.target.value; loadChart(); });
    $("#btnReplay").addEventListener("click", startReplay);
    $("#btnLive").addEventListener("click", startLive);
    $("#btnSkip").addEventListener("click", skipReplay);
    $("#btnTour").addEventListener("click", runTour);
    $("#btnPresent").addEventListener("click", togglePresent);
    $("#btnExit").addEventListener("click", togglePresent);
    $("#btnLang").addEventListener("click", () => setLang(lang === "de" ? "en" : "de"));
    $("#btnTheme").addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(next);
      pref.set("pocTheme", next);
    });
    $("#btnReset").addEventListener("click", () => state.scene && state.scene.resetView());
    $("#btnOrbit").addEventListener("click", (e) => {
      const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
      e.currentTarget.setAttribute("aria-pressed", String(on));
      if (state.scene) state.scene.setOrbit(on);
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.documentElement.classList.contains("present") && !document.fullscreenElement) setPresent(false); });
    try {
      [state.status, state.scenarios] = await Promise.all([api("/api/status"), api("/api/scenarios")]);
    } catch (e) {
      $("#statusPill").textContent = t("pillDown");
      notice(e.message || t("backendDown"), "bad");
      return;
    }
    renderStatus();
    const preferred = state.scenarios.find((s) => s.id === (params.get("scenario") || "bearing_wear")) || state.scenarios[0];
    if (preferred) await selectScenario(preferred.id);
    /* Warm the other scenarios and load the 3D view once the page is idle */
    const idle = window.requestIdleCallback || ((f) => setTimeout(f, 300));
    idle(() => {
      initScene();
      state.scenarios.filter((s) => s.id !== state.scenario).forEach((s, n) => setTimeout(() => {
        getJSON(`/api/scenarios/${s.id}/overview`).catch(() => {});
        if (s.has_replay) getJSON(replayUrl(s.id)).catch(() => {});
      }, 400 + n * 300));
    });
  }

  init();
})();
