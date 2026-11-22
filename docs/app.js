"use strict";
/* BTC Paper Desk – a bot állapotfájljának (dashboard.json) megjelenítése. Csak olvas, semmit nem küld. */

const LIVE_URL = "https://raw.githubusercontent.com/petricorn/btc-paper-trading/bot-state/state/dashboard.json";
const DEMO_URL = "data/demo.json";
const ORDER = ["P1", "P2", "P3", "B1", "B2"];
const COLOR = { P1: "var(--s1)", P2: "var(--s2)", P3: "var(--s3)", B1: "var(--s4)", B2: "var(--s5)" };
const DASHED = { B1: true, B2: true };
const PAGE = 25;
const REFRESH_MS = 5 * 60 * 1000;

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const nf = (d) => new Intl.NumberFormat("hu-HU", { minimumFractionDigits: d, maximumFractionDigits: d });
const N0 = nf(0), N2 = nf(2), N1 = nf(1);
const usd = (v, d = 2) => (v == null ? "–" : `${nf(d).format(v)} $`);
const pct = (v, d = 1) => (v == null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${nf(d).format(Math.abs(v * 100))}%`);
const signed = (v, d = 2) => (v == null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${nf(d).format(Math.abs(v))} $`);
const tone = (v) => (v == null || v === 0 ? "" : v > 0 ? "pos" : "neg");
const btc = (v) => (v == null ? "–" : new Intl.NumberFormat("hu-HU", { minimumFractionDigits: 8, maximumFractionDigits: 8 }).format(v));

const TZ = "Europe/Budapest";
const fmtTime = new Intl.DateTimeFormat("hu-HU", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const fmtDay = new Intl.DateTimeFormat("hu-HU", { timeZone: TZ, month: "short", day: "numeric" });
const fmtHour = new Intl.DateTimeFormat("hu-HU", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const when = (t) => fmtTime.format(new Date(t * 1000));

const ICON = {
  check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17"/></svg>',
  alert: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4M12 17h.01M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  info: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  pulse: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg>',
  pause: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6v12M15 6v12"/></svg>',
  clock: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  sliders: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>',
};

const ui = { data: null, source: null, hidden: new Set(), range: 0, filter: "all", shown: PAGE, hoverIdx: null };

/* ------------------------------------------------------------------ betöltés */
async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function load() {
  const want = new URLSearchParams(location.search).get("src");
  const btn = $("#refresh");
  btn.classList.remove("is-spinning"); void btn.offsetWidth; btn.classList.add("is-spinning");
  let data = null, source = null, liveErr = null;
  if (want !== "demo") {
    try { data = await fetchJson(LIVE_URL); source = "live"; } catch (e) { liveErr = e; }
  }
  if (!data) {
    try { data = await fetchJson(DEMO_URL); source = "demo"; } catch (e) {
      showError(`Az adatfájl nem tölthető be (${e.message}).`);
      return;
    }
  }
  $("#load-error").hidden = true;
  ui.data = data; ui.source = source; ui.liveErr = liveErr;
  render();
}

function showError(msg) {
  const el = $("#load-error");
  el.innerHTML = `${ICON.alert}<span>${esc(msg)}</span>`;
  el.hidden = false;
  $("#last-run").textContent = "Nincs adat";
}

/* ------------------------------------------------------------------ fő megjelenítés */
function render() {
  const d = ui.data;
  const badge = $("#source-badge");
  const live = d.source === "live" && ui.source === "live";
  badge.textContent = live ? "ÉLŐ" : "DEMÓ";
  badge.className = `pill ${live ? "pill--live" : "pill--demo"}`;
  const ago = Math.max(0, Math.round(Date.now() / 1000 - d.generated));
  $("#last-run").textContent = live
    ? `Utolsó futás: ${when(d.generated)} (${ago < 3600 ? Math.round(ago / 60) + " perce" : Math.round(ago / 3600) + " órája"})`
    : `Állapot: ${when(d.generated)}`;

  const notice = $("#notice");
  if (!live) {
    notice.innerHTML = `${ICON.info}<span>${esc(d.note || "Demó adat.")} Az élő bot a 3. fázisban indul; addig ez az oldal a demót mutatja.</span>`;
    notice.hidden = false;
  } else {
    notice.hidden = true;
  }
  $("#config-hash").textContent = `Config verzió: ${d.config_hash}`;

  renderPrice(d);
  renderBalance(d);
  renderHealth(d);
  renderRank(d);
  renderLegend(d);
  drawEquity();
  renderStrategies(d);
  renderTradeFilter(d);
  renderTrades(d);
  renderRuns(d);
  renderAlerts(d);
}

function renderPrice(d) {
  const p = d.price || {};
  $("#price").textContent = p.last == null ? "–" : `${N2.format(p.last)} $`;
  for (const [id, v, lbl] of [["#chg24", p.change_24h, "24 óra"], ["#chg7", p.change_7d, "7 nap"]]) {
    const el = $(id);
    el.textContent = `${lbl} ${pct(v, 2)}`;
    el.className = `chip ${tone(v)}`;
  }
  drawSpark(p.series || []);
}

/* Egyenleg: tőke − kezdőtőke. A tőke a könyvelésből jön (díjak után, nyitott pozíció aktuális áron). */
function renderBalance(d) {
  const start = Number(d.initial_capital) || 200;
  const strat = d.portfolios.filter((p) => p.kind === "strategy");
  const eq = strat.reduce((s, p) => s + p.equity, 0);
  const base = start * strat.length;
  const pnl = eq - base;
  const r = base ? pnl / base : null;
  const big = $("#bal-total");
  big.textContent = signed(pnl);
  big.className = `balance__big num ${tone(pnl)}`;
  const open = strat.filter((p) => p.position).length;
  const trades = strat.reduce((s, p) => s + (p.trades || 0), 0);
  $("#bal-sub").innerHTML =
    `<span class="${tone(r)}">${pct(r, 2)}</span> · most ${usd(eq)} · induló ${usd(base)} · ` +
    `${N0.format(trades)} lezárt kötés · ${open ? open + " nyitott pozíció" : "nincs nyitott pozíció"}`;
  const v = $("#bal-verdict");
  v.textContent = pnl > 0 ? "▲ Pluszban" : pnl < 0 ? "▼ Mínuszban" : "Nullán";
  v.className = `balance__verdict ${tone(pnl)}`;

  $("#bal-cards").innerHTML = ORDER.map((n) => d.portfolios.find((p) => p.name === n)).filter(Boolean).map((p) => {
    const diff = p.equity - start;
    const bench = p.kind !== "strategy";
    return `<div class="bal-card${bench ? " bal-card--bench" : ""}">
      <div class="pf">${swatch(p.name)}<div><div class="pf__name">${p.name}</div><div class="pf__label">${esc(p.label)}</div></div></div>
      <p class="bal-card__val num ${tone(diff)}">${signed(diff)}</p>
      <p class="mono meta"><span class="${tone(p.return)}">${pct(p.return, 2)}</span> · ${usd(p.equity)}${p.position ? " · nyitott" : ""}</p>
    </div>`;
  }).join("");
}

function renderHealth(d) {
  const h = d.health || {};
  const pill = $("#status-pill");
  if (h.last_ok === true) {
    pill.className = "status status--ok"; pill.innerHTML = `${ICON.check}Rendben`;
  } else if (h.last_ok === false) {
    pill.className = "status status--bad"; pill.innerHTML = `${ICON.pause}Nincs döntés`;
  } else {
    pill.className = "status"; pill.textContent = "–";
  }
  $("#status-issue").textContent = h.last_ok === false
    ? `Utolsó futás: ${h.last_issues}`
    : "Az utolsó futásban az adatok frissek voltak, és a két forrás egyezett.";
  const failPct = h.runs ? h.runs_data_fail / h.runs : null;
  const items = [
    ["Futások összesen", N0.format(h.runs || 0)],
    ["Adat-hiba miatt döntés nélkül", `${N0.format(h.runs_data_fail || 0)} <span class="meta">(${pct(failPct, 1).replace("+", "")})</span>`],
    ["Egymást követő hibás futás", N0.format(h.consecutive_failures || 0)],
    ["Kereszt-ellenőrzés eltérés", N0.format(h.fail_crosscheck || 0)],
    ["Régi / hiányos adat", N0.format((h.fail_stale || 0) + (h.fail_gap || 0))],
    ["Késés miatt elmaradt belépés", N0.format(h.entries_skipped_late || 0)],
  ];
  $("#kpis").innerHTML = items.map(([k, v]) => `<div><dt>${k}</dt><dd class="num">${v}</dd></div>`).join("");
}

function swatch(name) {
  return DASHED[name]
    ? `<span class="pf__swatch pf__swatch--dash" style="border-color:${COLOR[name]}"></span>`
    : `<span class="pf__swatch" style="background:${COLOR[name]}"></span>`;
}

function stateTag(p) {
  if (p.halted) return `<span class="tag tag--halt">${ICON.pause}Leállítva (kill switch)</span>`;
  if (p.position) return `<span class="tag tag--open">${ICON.pulse}Nyitott pozíció</span>`;
  if (p.kind === "strategy") return `<span class="tag">${ICON.clock}Jelzésre vár</span>`;
  return `<span class="tag">${esc(p.waiting?.text || "")}</span>`;
}

function renderRank(d) {
  const rows = [...d.portfolios].sort((a, b) => b.equity - a.equity);
  $("#rank-table tbody").innerHTML = rows.map((p, i) => `
    <tr>
      <td class="rank">${i + 1}</td>
      <td><div class="pf">${swatch(p.name)}<div><div class="pf__name">${p.name}</div><div class="pf__label">${esc(p.label)}</div></div></div></td>
      <td class="r num">${usd(p.equity)}</td>
      <td class="r num ${tone(p.return)}">${pct(p.return, 2)}</td>
      <td class="r num">${p.max_drawdown ? "−" + N1.format(p.max_drawdown * 100) + "%" : "0%"}</td>
      <td class="r num">${p.kind === "strategy" ? N0.format(p.trades) : "–"}</td>
      <td class="r num">${p.win_rate == null ? "–" : N0.format(p.win_rate * 100) + "%"}</td>
      <td class="r num">${p.profit_factor == null ? "–" : N2.format(p.profit_factor)}</td>
      <td>${stateTag(p)}</td>
    </tr>`).join("");
}

/* ------------------------------------------------------------------ tőkegörbe */
function renderLegend(d) {
  const el = $("#legend");
  el.innerHTML = ORDER.map((n) => {
    const p = d.portfolios.find((x) => x.name === n);
    if (!p) return "";
    return `<button type="button" data-k="${n}" aria-pressed="${!ui.hidden.has(n)}">
      ${swatch(n)}<span>${n}</span><span class="val num ${tone(p.return)}">${pct(p.return, 1)}</span></button>`;
  }).join("");
  el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.k;
    if (ui.hidden.has(k)) ui.hidden.delete(k); else if (ui.hidden.size < ORDER.length - 1) ui.hidden.add(k);
    b.setAttribute("aria-pressed", String(!ui.hidden.has(k)));
    drawEquity();
  }));
}

function niceStep(span, target) {
  const raw = span / target, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
}

function nearest(points, t) {
  let lo = 0, hi = points.length - 1;
  if (hi < 0) return -1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (points[mid][0] < t) lo = mid + 1; else hi = mid; }
  if (lo > 0 && Math.abs(points[lo - 1][0] - t) <= Math.abs(points[lo][0] - t)) lo--;
  return lo;
}

function equitySeries() {
  const d = ui.data, cap = d.initial_capital;
  const all = d.portfolios.filter((p) => ORDER.includes(p.name));
  const tmax = Math.max(...all.map((p) => (p.equity_series.at(-1) || [0])[0]));
  const tmin = ui.range ? tmax - ui.range * 86400 : -Infinity;
  return ORDER.filter((n) => !ui.hidden.has(n)).map((n) => {
    const p = all.find((x) => x.name === n);
    return { key: n, points: (p ? p.equity_series : []).filter(([t]) => t >= tmin).map(([t, e]) => [t, e / cap - 1]) };
  }).filter((s) => s.points.length);
}

function drawEquity() {
  const el = $("#equity-chart");
  const series = equitySeries();
  const W = el.clientWidth, H = el.clientHeight;
  if (!series.length || W < 50) { el.innerHTML = '<p class="empty">Nincs adat ehhez az időtávhoz.</p>'; return; }
  const m = { l: 52, r: 12, t: 10, b: 28 };
  const ts = series.flatMap((s) => s.points.map((p) => p[0]));
  const vs = series.flatMap((s) => s.points.map((p) => p[1]));
  const x0 = Math.min(...ts), x1 = Math.max(...ts);
  let y0 = Math.min(0, ...vs), y1 = Math.max(0, ...vs);
  const padY = (y1 - y0 || 0.02) * 0.12; y0 -= padY; y1 += padY;
  const step = niceStep(y1 - y0, H < 300 ? 4 : 5);
  y0 = Math.floor(y0 / step) * step; y1 = Math.ceil(y1 / step) * step;
  const X = (t) => m.l + ((t - x0) / Math.max(1, x1 - x0)) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);

  let g = "";
  for (let v = y0; v <= y1 + 1e-9; v += step) {
    g += `<line class="gridline" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>`;
    g += `<text x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${pct(Math.abs(v) < 1e-12 ? 0 : v, step < 0.01 ? 1 : 0)}</text>`;
  }
  const xt = Math.max(2, Math.min(6, Math.floor((W - m.l) / 110)));
  for (let i = 0; i <= xt; i++) {
    const t = x0 + ((x1 - x0) * i) / xt;
    const lbl = x1 - x0 < 2 * 86400 ? fmtHour.format(new Date(t * 1000)) : fmtDay.format(new Date(t * 1000));
    g += `<text x="${X(t)}" y="${H - 8}" text-anchor="${i === 0 ? "start" : i === xt ? "end" : "middle"}">${lbl}</text>`;
  }
  const lines = series.map((s) => {
    const d = s.points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    return `<path class="series ${DASHED[s.key] ? "series--dash" : ""}" stroke="${COLOR[s.key]}" d="${d}"/>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">
      <g class="axis">${g}</g>
      <line class="zero" x1="${m.l}" x2="${W - m.r}" y1="${Y(0)}" y2="${Y(0)}"/>
      ${lines}
      <g id="xh" visibility="hidden"><line class="crosshair" y1="${m.t}" y2="${H - m.b}"/>${series.map((s) =>
        `<circle r="4.5" fill="${COLOR[s.key]}" stroke="var(--bg)" stroke-width="2" data-k="${s.key}"/>`).join("")}</g>
      <rect class="hit" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}"/>
    </svg>`;
  const base = series.reduce((a, b) => (b.points.length > a.points.length ? b : a)).points;
  const svg = el.querySelector("svg"), xh = svg.querySelector("#xh"), tip = $("#tooltip");

  const show = (idx, clientX, clientY) => {
    idx = Math.max(0, Math.min(base.length - 1, idx));
    ui.hoverIdx = idx;
    const t = base[idx][0];
    xh.setAttribute("visibility", "visible");
    xh.querySelector("line").setAttribute("x1", X(t)); xh.querySelector("line").setAttribute("x2", X(t));
    const rows = series.map((s) => {
      const p = s.points[nearest(s.points, t)];
      const c = xh.querySelector(`circle[data-k="${s.key}"]`);
      c.setAttribute("cx", X(p[0])); c.setAttribute("cy", Y(p[1]));
      return { k: s.key, v: p[1] };
    }).sort((a, b) => b.v - a.v);
    tip.innerHTML = `<div class="tooltip__time">${when(t)}</div>` + rows.map((r) =>
      `<div class="tooltip__row"><span>${swatch(r.k)}${r.k}</span><span class="num ${tone(r.v)}">${pct(r.v, 2)}</span></div>`).join("");
    tip.hidden = false;
    const box = el.getBoundingClientRect();
    const px = clientX ?? box.left + X(t), py = clientY ?? box.top + m.t + 20;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = px + 16; if (left + tw > window.innerWidth - 8) left = px - tw - 16;
    let top = py - th / 2; top = Math.max(8, Math.min(window.innerHeight - th - 8, top));
    tip.style.left = `${Math.max(8, left)}px`; tip.style.top = `${top}px`;
  };
  const hide = () => { xh.setAttribute("visibility", "hidden"); tip.hidden = true; };
  const hit = svg.querySelector(".hit");
  hit.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const t = x0 + ((e.clientX - r.left - m.l) / (W - m.l - m.r)) * (x1 - x0);
    show(nearest(base, t), e.clientX, e.clientY);
  });
  hit.addEventListener("pointerleave", hide);
  el.onkeydown = (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const stepN = Math.max(1, Math.round(base.length / 60));
      const cur = ui.hoverIdx ?? base.length - 1;
      show(cur + (e.key === "ArrowRight" ? stepN : -stepN));
    } else if (e.key === "Escape") { hide(); }
  };
  el.onblur = hide;
}

function drawSpark(points) {
  const el = $("#spark");
  const W = el.clientWidth, H = el.clientHeight;
  if (points.length < 2 || W < 50) { el.innerHTML = ""; return; }
  const ts = points.map((p) => p[0]), vs = points.map((p) => p[1]);
  const x0 = ts[0], x1 = ts.at(-1), lo = Math.min(...vs), hi = Math.max(...vs);
  const pad = (hi - lo || 1) * 0.08;
  const X = (t) => ((t - x0) / Math.max(1, x1 - x0)) * W;
  const Y = (v) => 4 + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - 8);
  const line = points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">
    <defs><linearGradient id="sg" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="var(--accent)" stop-opacity=".28"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>
    <path d="${line}L${W},${H}L0,${H}Z" fill="url(#sg)"/>
    <path d="${line}" fill="none" stroke="var(--text)" stroke-width="1.6" stroke-linejoin="round"/>
    <g id="sx" visibility="hidden"><line class="crosshair" y1="0" y2="${H}"/><circle r="4.5" fill="var(--accent)" stroke="var(--bg)" stroke-width="2"/></g>
    <rect class="hit" x="0" y="0" width="${W}" height="${H}"/></svg>`;
  const svg = el.querySelector("svg"), sx = svg.querySelector("#sx"), tip = $("#tooltip");
  svg.querySelector(".hit").addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const t = x0 + ((e.clientX - r.left) / W) * (x1 - x0);
    const p = points[nearest(points, t)];
    sx.setAttribute("visibility", "visible");
    sx.querySelector("line").setAttribute("x1", X(p[0])); sx.querySelector("line").setAttribute("x2", X(p[0]));
    sx.querySelector("circle").setAttribute("cx", X(p[0])); sx.querySelector("circle").setAttribute("cy", Y(p[1]));
    tip.innerHTML = `<div class="tooltip__time">${when(p[0])}</div><div class="tooltip__row"><span>BTC ár</span><span class="num">${N2.format(p[1])} $</span></div>`;
    tip.hidden = false;
    let left = e.clientX + 16; if (left + tip.offsetWidth > window.innerWidth - 8) left = e.clientX - tip.offsetWidth - 16;
    tip.style.left = `${Math.max(8, left)}px`; tip.style.top = `${Math.max(8, e.clientY - tip.offsetHeight - 12)}px`;
  });
  svg.querySelector(".hit").addEventListener("pointerleave", () => { sx.setAttribute("visibility", "hidden"); tip.hidden = true; });
}

/* ------------------------------------------------------------------ stratégiák */
function renderStrategies(d) {
  const lastPrice = d.price?.last;
  $("#strategies").innerHTML = ["P1", "P2", "P3"].map((n) => {
    const p = d.portfolios.find((x) => x.name === n);
    if (!p) return "";
    let body = "";
    if (p.halted) {
      body = `<p class="verdict">${esc(p.halt_reason)}</p>`;
    } else if (p.position) {
      const q = p.position;
      const right = q.target ?? q.entry_price + 2 * (q.entry_price - q.initial_stop);
      const left = Math.min(q.stop, q.initial_stop);
      const span = right - left || 1;
      const at = (v) => Math.max(0, Math.min(100, ((v - left) / span) * 100));
      body = `
        <dl class="pos-grid">
          <div><dt>Belépő ár</dt><dd class="num">${usd(q.entry_price)}</dd></div>
          <div><dt>Mennyiség</dt><dd class="num">${btc(q.qty)} BTC</dd></div>
          <div><dt>Stop${q.trailing ? " (trailing)" : ""}</dt><dd class="num">${usd(q.stop)}</dd></div>
          <div><dt>Részleges cél</dt><dd class="num">${q.target ? usd(q.target) : "teljesült"}</dd></div>
          <div><dt>Nem realizált</dt><dd class="num ${tone(q.unrealized)}">${signed(q.unrealized)}</dd></div>
          <div><dt>Jelenleg</dt><dd class="num ${tone(q.r)}">${q.r >= 0 ? "+" : "−"}${N2.format(Math.abs(q.r))} R</dd></div>
        </dl>
        <div class="rbar" role="img" aria-label="Az ár helyzete a stop és a cél között">
          <span class="rbar__mark" style="left:${at(lastPrice)}%"></span>
          <span class="rbar__lbl rbar__lbl--now" style="left:${at(lastPrice)}%">most</span>
          <span class="rbar__lbl" style="left:0%;transform:none">stop</span>
          <span class="rbar__lbl" style="left:${at(q.entry_price)}%">belépő</span>
          <span class="rbar__lbl" style="left:100%;transform:translateX(-100%)">cél</span>
        </div>
        <p class="verdict">Belépés: ${when(Date.parse(q.entry_time) / 1000)}</p>`;
    } else {
      const w = p.waiting || {};
      const conds = w.conditions || [];
      const okN = conds.filter((c) => c.ok).length;
      body = `<ul class="conds">${conds.map((c) => `
          <li><span class="ic ${c.ok ? "ok" : "no"}" aria-label="${c.ok ? "teljesül" : "nem teljesül"}">${c.ok ? ICON.check : ICON.x}</span>
            <div><div class="lbl">${esc(c.label)}</div><div class="det num">${esc(c.detail)}</div></div></li>`).join("")}
        </ul>
        <p class="verdict">${w.action === "skip" ? `Kihagyott belépés: ${esc(w.reason)}`
          : okN === conds.length && conds.length ? "Minden feltétel teljesült a legutóbbi gyertyán."
          : `Vár: ${okN}/${conds.length} feltétel teljesül.`}
          ${w.bar_close ? `<br><span class="meta">Utolsó lezárt gyertya: ${when(Date.parse(w.bar_close) / 1000)}</span>` : ""}</p>`;
    }
    return `<article class="card strat">
        <div class="strat__head">
          <div class="strat__title">${swatch(n)}<div><h3>${n}</h3><div class="strat__sub">${esc(p.label)}</div></div></div>
          ${stateTag(p)}
        </div>${body}</article>`;
  }).join("");
}

/* ------------------------------------------------------------------ kötések */
function renderTradeFilter(d) {
  const el = $("#trade-filter");
  const opts = [["all", "Mind"], ...ORDER.map((n) => [n, n])];
  el.innerHTML = opts.map(([k, l]) => `<button type="button" data-f="${k}" aria-pressed="${ui.filter === k}">${l}</button>`).join("");
  el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    ui.filter = b.dataset.f; ui.shown = PAGE;
    el.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderTrades(ui.data);
  }));
}

function renderTrades(d) {
  const all = [...d.trades].reverse().filter((t) => ui.filter === "all" || t.portfolio === ui.filter);
  const rows = all.slice(0, ui.shown);
  $("#trade-table tbody").innerHTML = rows.length ? rows.map((t) => `
    <tr>
      <td class="num">${when(t.time)}</td>
      <td><div class="pf">${swatch(t.portfolio)}<span class="pf__name">${t.portfolio}</span></div></td>
      <td><span class="side ${t.side === "BUY" ? "side--buy" : "side--sell"}">${t.side === "BUY" ? "Vétel" : "Eladás"}</span></td>
      <td>${esc(t.reason)}</td>
      <td class="r num">${btc(t.qty)}</td>
      <td class="r num">${usd(t.price)}</td>
      <td class="r num">${usd(t.value)}</td>
      <td class="r num">${usd(t.fee, 2)}</td>
      <td class="r num ${tone(t.pnl)}">${t.pnl == null ? "–" : signed(t.pnl)}</td>
    </tr>`).join("") : `<tr><td colspan="9" class="empty">Még nincs kötés.</td></tr>`;
  $("#trade-count").textContent = `${Math.min(ui.shown, all.length)} / ${all.length} kötés`;
  $("#trade-more").hidden = ui.shown >= all.length;
}

/* ------------------------------------------------------------------ futások, riasztások */
function renderRuns(d) {
  const runs = d.runs || [];
  const bad = runs.filter((r) => !r.ok).length;
  $("#runs-meta").textContent = `utolsó ${runs.length} futás · ${bad} döntés nélküli`;
  const el = $("#runs");
  el.innerHTML = runs.map((r, i) => `<span role="listitem" data-i="${i}" class="${r.ok ? "" : "bad"}"
     aria-label="${when(r.time)}: ${r.ok ? "rendben" : "nincs döntés"}"></span>`).join("");
  const detail = $("#run-detail");
  el.querySelectorAll("span").forEach((s) => s.addEventListener("pointerenter", () => {
    const r = runs[+s.dataset.i];
    detail.innerHTML = `<strong>${when(r.time)}</strong> · ${r.ok ? "rendben" : esc(r.issues)}${r.diff != null ? ` · Coinbase–Kraken eltérés ${N2.format(r.diff * 100)}%` : ""}`;
  }));
}

const ALERT_TEXT = {
  ALERT_DATA: ["bad", "Adat-hiba több futáson át", (p) => `${p.failed_runs} egymást követő futásban nem volt döntés`],
  DATA_RECOVERED: ["ok", "Az adatok ismét rendben", (p) => `${p.failed_runs || ""} hibás futás után`],
  ALERT_KILL: ["bad", "Kill switch: a portfólió leállt", (p) => p.reason || ""],
  ALERT_PARAM: ["warn", "Paraméterváltozás (új config-verzió)", (p) => `${p.old} → ${p.new}`],
};

function renderAlerts(d) {
  const list = [...(d.alerts || [])].reverse();
  $("#alerts").innerHTML = list.length ? list.map((a) => {
    const [kind, title, fn] = ALERT_TEXT[a.kind] || ["warn", a.kind, () => ""];
    const icon = kind === "ok" ? ICON.check : kind === "warn" ? ICON.sliders : ICON.alert;
    return `<li><span class="ic ic--${kind}">${icon}</span><div>
      <div class="t">${a.portfolio ? esc(a.portfolio) + " · " : ""}${esc(title)}</div>
      <div class="d">${when(a.time)} · ${esc(fn(a.payload || {}))}</div></div></li>`;
  }).join("") : `<li class="empty">Nincs riasztás.</li>`;
}

/* ------------------------------------------------------------------ vezérlők */
function setTheme(next) {
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch (e) {}
  if (ui.data) { drawEquity(); drawSpark(ui.data.price?.series || []); }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#refresh").addEventListener("click", load);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    setTheme(cur === "light" ? "dark" : "light");
  });
  $("#range").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    ui.range = +b.dataset.range;
    $("#range").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    drawEquity();
  }));
  $("#trade-more").addEventListener("click", () => { ui.shown += PAGE; renderTrades(ui.data); });
  let rt;
  window.addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(() => { if (ui.data) { drawEquity(); drawSpark(ui.data.price?.series || []); } }, 120);
  });
  // finom megjelenés görgetéskor (csökkentett mozgás esetén nincs)
  const secs = document.querySelectorAll(".section");
  if ("IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }),
      { rootMargin: "0px 0px -8% 0px" });
    secs.forEach((s) => { s.classList.add("reveal"); io.observe(s); });
  }
  // a 3D érme enyhén követi az egeret
  const stage = $("#coin-stage");
  if (stage && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    window.addEventListener("pointermove", (e) => {
      const x = e.clientX / window.innerWidth - 0.5, y = e.clientY / window.innerHeight - 0.5;
      stage.style.transform = `perspective(900px) rotateY(${(x * 10).toFixed(2)}deg) rotateX(${(-y * 8).toFixed(2)}deg)`;
    }, { passive: true });
  }
  load();
  // a betűtípusok betöltése után a méretek változhatnak → grafikonok újrarajzolása
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => { if (ui.data) { drawEquity(); drawSpark(ui.data.price?.series || []); } });
  }
  setInterval(() => { if (ui.source === "live") load(); }, REFRESH_MS);
});
