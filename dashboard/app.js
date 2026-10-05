/* Local dashboard for output/metrics.json and the per-site CSVs (README: Metrics; dashboard/README.md for how
   to preview). No build step: plain fetch() + Chart.js from a CDN. Must be served over http:// (python -m
   http.server from the repo root) — browsers refuse fetch() of local files under file://. */
"use strict";

// Fixed site order and color, used consistently across every chart (dataviz skill: categorical hues, fixed
// order, never cycled). Mirrors extractor/config.py's SITES order (the water's own path: Upstream -> the two
// discharge points -> Downstream).
const SITES = [
  { key: "Upstream", file: "upstream.csv", color: "--site-upstream", flow: false },
  { key: "LDP7 Water Treatment Plant", file: "ldp7-water-treatment-plant.csv", color: "--site-ldp7", flow: true },
  { key: "LDP8 Turkeys Nest", file: "ldp8-turkeys-nest.csv", color: "--site-ldp8", flow: true },
  { key: "Downstream", file: "downstream.csv", color: "--site-downstream", flow: false },
];

// Mirrors extractor/config.py's SANE_BOUNDS (README: Metrics) — kept in sync by hand, since this is a plain
// static page with no access to the Python config.
const SANE_BOUNDS = { ph: [0, 14], sc: [10, 10000], temp: [-5, 45], turb: [0, 20000] };
const STALE_HOURS = 12; // mirrors config.STALE_HOURS
const GAP_HOURS = 4; // mirrors config.GAP_HOURS

const csvCache = new Map();
let metricsData = null;
let currentWindowDays = 90;
let flaggedPage = 0;
const FLAGGED_PAGE_SIZE = 20;
const charts = {};

// Australian date formats throughout (DD/MM/YYYY), not whatever the browser's own locale happens to be.
const DATE_FMT = new Intl.DateTimeFormat("en-AU", { day: "2-digit", month: "2-digit", year: "numeric" });
const DATETIME_FMT = new Intl.DateTimeFormat("en-AU", {
  day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const TICK_DATE_FMT = new Intl.DateTimeFormat("en-AU", { day: "2-digit", month: "2-digit" });
const TICK_TIME_FMT = new Intl.DateTimeFormat("en-AU", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function num(s) {
  return s === undefined || s === "" ? null : parseFloat(s);
}

function sane(key, v) {
  if (v === null || Number.isNaN(v)) return null;
  const [lo, hi] = SANE_BOUNDS[key];
  return v >= lo && v <= hi ? v : null;
}

async function fetchCSV(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  const text = await res.text();
  const lines = text.split("\n");
  const header = lines[0].split(",").map((h) => h.trim());
  const idx = Object.fromEntries(header.map((h, i) => [h, i]));
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line) continue;
    const cols = line.split(",");
    const ts = Date.parse(cols[idx.timestamp_utc]);
    if (Number.isNaN(ts)) continue;
    rows.push({
      ts,
      ph: sane("ph", num(cols[idx.ph])),
      sc: sane("sc", num(cols[idx.specific_conductivity])),
      turb: sane("turb", num(cols[idx.turbidity])),
      flow: idx.flow_volume !== undefined ? num(cols[idx.flow_volume]) : null,
    });
  }
  return rows; // already ascending by ts, like the CSV itself
}

function loadSite(site) {
  if (!csvCache.has(site.file)) csvCache.set(site.file, fetchCSV(`../output/${site.file}`));
  return csvCache.get(site.file);
}

// Binary search: first row at or after the cutoff. Rows are ascending, so this avoids scanning the whole
// (potentially 100k+ row) array on every window change.
function sliceWindow(rows, days) {
  const cutoff = Date.now() - days * 86400000;
  let lo = 0, hi = rows.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].ts < cutoff) lo = mid + 1; else hi = mid;
  }
  return rows.slice(lo);
}

function tickFormat(days) {
  const fmt = days <= 1 ? TICK_TIME_FMT : TICK_DATE_FMT;
  return (value) => fmt.format(new Date(value));
}

function baseLineDataset(label, colorVar, points) {
  return {
    label,
    data: points,
    borderColor: cssVar(colorVar),
    backgroundColor: cssVar(colorVar),
    borderWidth: 2,
    pointRadius: 0,
    spanGaps: false,
    tension: 0,
  };
}

function baseChartOptions(days, yLabel) {
  return {
    responsive: true,
    maintainAspectRatio: false, // size to the .chart-wrap container's explicit height, not the canvas's own
    animation: false,
    // "nearest" finds, per dataset, the point whose x-value is actually closest to the cursor. "index" instead
    // matches by array position across datasets, which silently breaks here: each site's points have nulls and
    // out-of-bounds readings dropped independently (sanitize()), so the four datasets aren't the same length and
    // the same array index doesn't mean the same timestamp — that's what was making the hover points drift away
    // from the cursor for every site except the one with no gaps up to that point.
    interaction: { mode: "nearest", axis: "x", intersect: false },
    scales: {
      x: {
        type: "linear",
        ticks: { color: cssVar("--text-muted"), callback: tickFormat(days), maxRotation: 0 },
        grid: { color: cssVar("--gridline") },
      },
      y: {
        title: { display: !!yLabel, text: yLabel, color: cssVar("--text-secondary") },
        ticks: { color: cssVar("--text-muted") },
        grid: { color: cssVar("--gridline") },
      },
    },
    plugins: {
      legend: { labels: { color: cssVar("--text-secondary"), boxWidth: 12, boxHeight: 12 } },
      tooltip: {
        callbacks: {
          title: (items) => DATETIME_FMT.format(new Date(items[0].parsed.x)),
        },
      },
    },
  };
}

function renderChart(canvasId, datasets, days, yLabel, extraPlugins) {
  const ctx = document.getElementById(canvasId);
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(ctx, {
    type: "line",
    data: { datasets },
    options: baseChartOptions(days, yLabel),
    plugins: extraPlugins || [],
  });
}

// Draws the 6.5-8.5 EPA licence band behind the pH lines (README: Metrics).
const phBandPlugin = {
  id: "phBand",
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea, scales } = chart;
    if (!chartArea) return;
    const yTop = scales.y.getPixelForValue(8.5);
    const yBottom = scales.y.getPixelForValue(6.5);
    ctx.save();
    ctx.fillStyle = cssVar("--gridline");
    ctx.globalAlpha = 0.6;
    ctx.fillRect(chartArea.left, yTop, chartArea.right - chartArea.left, yBottom - yTop);
    ctx.restore();
  },
};

async function renderTimeSeriesCharts(days) {
  currentWindowDays = days;
  const perSite = await Promise.all(SITES.map((site) => loadSite(site).then((rows) => sliceWindow(rows, days))));

  const conductivity = SITES.map((site, i) =>
    baseLineDataset(site.key, site.color, perSite[i].map((r) => ({ x: r.ts, y: r.sc })).filter((p) => p.y !== null)));
  renderChart("chart-conductivity", conductivity, days, "µS/cm");

  const turbidity = SITES.map((site, i) =>
    baseLineDataset(site.key, site.color, perSite[i].map((r) => ({ x: r.ts, y: r.turb })).filter((p) => p.y !== null)));
  renderChart("chart-turbidity", turbidity, days, "NTU");

  const ph = SITES.map((site, i) =>
    baseLineDataset(site.key, site.color, perSite[i].map((r) => ({ x: r.ts, y: r.ph })).filter((p) => p.y !== null)));
  renderChart("chart-ph", ph, days, "pH", [phBandPlugin]);

  const flowSites = SITES.filter((s) => s.flow);
  const flowDatasets = flowSites.map((site) => {
    const rows = perSite[SITES.indexOf(site)];
    return baseLineDataset(site.key, site.color,
      rows.map((r) => ({ x: r.ts, y: r.flow })).filter((p) => p.y !== null && p.y > 0));
  });
  const hasFlow = flowDatasets.some((d) => d.data.length > 0);
  document.getElementById("chart-flow-wrap").classList.toggle("hidden", !hasFlow);
  document.getElementById("flow-empty-note").classList.toggle("hidden", hasFlow);
  if (hasFlow) renderChart("chart-flow", flowDatasets, days, "litres / 15 min");
}

function statusClass(tier) {
  return { normal: "good", elevated: "warning", alert: "critical", unknown: "unknown" }[tier] || "unknown";
}

function renderHeadline(data) {
  const ratio = data.conductivity_ratio;
  const ratioTile = document.getElementById("tile-ratio");
  ratioTile.querySelector(".tile-value").textContent = ratio.current != null ? `${ratio.current.toFixed(2)}x` : "—";
  ratioTile.querySelector(".tile-sub").innerHTML =
    `<span class="status-dot status-${statusClass(ratio.tier)}"></span>` +
    `<span class="status-label status-text-${statusClass(ratio.tier)}">${ratio.tier}</span>` +
    ` (elevated ≥ ${ratio.elevated_threshold}x, alert ≥ ${ratio.alert_threshold}x)`;

  const sites = Object.entries(data.sites);
  const outOfBand = sites.filter(([, s]) => s.ph_in_band === false);
  const phTile = document.getElementById("tile-ph");
  phTile.querySelector(".tile-value").textContent = `${sites.length - outOfBand.length}/${sites.length} in band`;
  phTile.querySelector(".tile-sub").innerHTML = outOfBand.length
    ? `<span class="status-dot status-critical"></span>outside band: ${outOfBand.map(([k]) => k).join(", ")}`
    : `<span class="status-dot status-good"></span>all sites within range`;

  const highConfidence = data.flagged_periods.filter((p) => p.confidence === "high");
  const flaggedTile = document.getElementById("tile-flagged");
  flaggedTile.querySelector(".tile-value").textContent = highConfidence.length;
  const mostRecent = data.flagged_periods.length
    ? data.flagged_periods.reduce((a, b) => (a.start > b.start ? a : b))
    : null;
  flaggedTile.querySelector(".tile-sub").textContent = mostRecent
    ? `most recent: ${DATE_FMT.format(new Date(mostRecent.start * 1000))}`
    : "none recorded";

  const latestTimes = Object.values(data.sites).map((s) => s.latest_reading_at).filter(Boolean);
  const newest = latestTimes.length ? Math.max(...latestTimes) : null;
  const freshnessTile = document.getElementById("tile-freshness");
  const freshnessHeader = document.getElementById("freshness");
  if (newest) {
    const ageHours = (Date.now() / 1000 - newest) / 3600;
    freshnessTile.querySelector(".tile-value").textContent = `${ageHours.toFixed(1)}h ago`;
    freshnessTile.querySelector(".tile-sub").textContent = DATETIME_FMT.format(new Date(newest * 1000));
    const stale = ageHours > STALE_HOURS;
    freshnessTile.querySelector(".tile-sub").classList.toggle("status-text-critical", stale);
    freshnessHeader.textContent = `Generated ${DATETIME_FMT.format(new Date(data.generated_at * 1000))} · ` +
      `newest reading ${ageHours.toFixed(1)}h ago`;
    freshnessHeader.classList.toggle("stale", stale);
  }
}

function renderFlaggedTable(periods) {
  const el = document.getElementById("flagged-table");
  if (!periods.length) {
    el.innerHTML = '<p class="empty-note">No flagged periods.</p>';
    return;
  }
  const sorted = [...periods].sort((a, b) => b.start - a.start);
  const pageCount = Math.ceil(sorted.length / FLAGGED_PAGE_SIZE);
  flaggedPage = Math.min(flaggedPage, pageCount - 1);
  const start = flaggedPage * FLAGGED_PAGE_SIZE;
  const shown = sorted.slice(start, start + FLAGGED_PAGE_SIZE);
  const fmt = (ts) => DATETIME_FMT.format(new Date(ts * 1000));
  const rows = shown.map((p) => `
    <tr>
      <td>${fmt(p.start)}</td>
      <td>${fmt(p.end)}</td>
      <td>${p.peak_ratio.toFixed(1)}x</td>
      <td><span class="pill pill-${p.confidence}">${p.confidence}</span></td>
      <td>${p.corroborated_by.length ? p.corroborated_by.join(", ") : "—"}</td>
    </tr>`).join("");
  el.innerHTML = `<table><thead><tr><th>Start</th><th>End</th><th>Peak ratio</th><th>Confidence</th>
    <th>Corroborated by</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="pagination">
      <button id="flagged-prev" ${flaggedPage === 0 ? "disabled" : ""}>&larr; Newer</button>
      <span class="page-label">Showing ${start + 1}–${start + shown.length} of ${sorted.length}
        (page ${flaggedPage + 1} of ${pageCount})</span>
      <button id="flagged-next" ${flaggedPage >= pageCount - 1 ? "disabled" : ""}>Older &rarr;</button>
    </div>`;
  document.getElementById("flagged-prev").addEventListener("click", () => {
    flaggedPage--; renderFlaggedTable(periods);
  });
  document.getElementById("flagged-next").addEventListener("click", () => {
    flaggedPage++; renderFlaggedTable(periods);
  });
}

// Sites whose low completeness is expected by design (not a data-quality problem) — explained in the paragraph
// above the table (index.html) rather than repeated per row, since currently only one site needs it.
const HEALTH_EXPECTATIONS = new Set(["LDP7 Water Treatment Plant"]);

function healthStatus(site, completeness) {
  // A site with a documented reason for low completeness (see HEALTH_EXPECTATIONS) isn't unhealthy — it's working
  // as designed — so it's never shown in a warning/serious colour just for having a low number.
  if (HEALTH_EXPECTATIONS.has(site)) return "good";
  if (completeness >= 0.95) return "good";
  if (completeness >= 0.80) return "warning";
  return "serious";
}

function renderHealthTable(health) {
  const el = document.getElementById("health-table");
  const rows = Object.entries(health).map(([site, h]) => {
    const pct = (h.completeness * 100).toFixed(1);
    const status = healthStatus(site, h.completeness);
    return `
    <tr>
      <td>${site}</td>
      <td>
        <span class="bar-track"><span class="bar-fill status-${status}" style="width:${pct}%"></span></span>
        ${pct}%
      </td>
      <td>${h.valid.toLocaleString()} / ${h.total.toLocaleString()}</td>
      <td>${h.gaps.length}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `<table><thead><tr><th>Site</th><th>Completeness</th><th>Valid / total</th>
    <th>Gaps ≥ ${GAP_HOURS}h</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderChronicTrend(trend) {
  const daily = trend.map((d) => ({ x: Date.parse(d.date), y: d.daily_median_ratio }));
  const rolling = trend.map((d) => ({ x: Date.parse(d.date), y: d.rolling_90d_median_ratio }));
  renderChart("chart-trend", [
    { label: "Daily median", data: daily, borderColor: cssVar("--text-muted"), borderWidth: 1,
      pointRadius: 0, tension: 0 },
    { label: "Rolling 90-day median", data: rolling, borderColor: cssVar("--site-upstream"), borderWidth: 2,
      pointRadius: 0, tension: 0 },
  ], 9999, "ratio");
}

function wireWindowToggle() {
  const container = document.getElementById("window-toggle");
  container.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-days]");
    if (!btn) return;
    container.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderTimeSeriesCharts(Number(btn.dataset.days));
  });
}

async function init() {
  wireWindowToggle();
  document.getElementById("gap-hours-note").textContent = GAP_HOURS;
  const res = await fetch("../output/metrics.json");
  metricsData = await res.json();
  renderHeadline(metricsData);
  renderFlaggedTable(metricsData.flagged_periods);
  renderHealthTable(metricsData.data_health);
  renderChronicTrend(metricsData.chronic_trend);
  await renderTimeSeriesCharts(currentWindowDays);
}

init().catch((err) => {
  document.getElementById("freshness").textContent = `Failed to load: ${err.message}`;
  console.error(err);
});
