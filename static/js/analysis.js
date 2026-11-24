/* Analysis dashboard: latest database execution time per tested method. */
(() => {
  "use strict";

  const ANALYSIS_KEY = "dbms2.analysis.history.v1";
  const METHOD_ORDER = [
    "full_scan", "hash", "composite_btree", "hnsw", "hybrid", "cached",
  ];
  const LABELS = {
    full_scan: "Full Table Scan",
    hash: "Hash Index",
    composite_btree: "Composite Index",
    hnsw: "HNSW Vector Search",
    hybrid: "Hybrid (Filters + Vector)",
    cached: "Cached Search",
  };
  const COLORS = {
    full_scan: "rgba(220, 38, 38, 0.82)",
    hash: "rgba(217, 119, 6, 0.82)",
    composite_btree: "rgba(79, 70, 229, 0.86)",
    hnsw: "rgba(6, 182, 212, 0.82)",
    hybrid: "rgba(5, 150, 105, 0.82)",
    cached: "rgba(100, 116, 139, 0.78)",
  };

  const $ = (selector) => document.querySelector(selector);
  let chart = null;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  function fmtMs(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    if (n === 0) return "0.000";
    if (n < 0.01) return n.toFixed(4);
    if (n < 10) return n.toFixed(3);
    if (n < 1000) return n.toFixed(2);
    return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }

  function fmtWhen(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleString();
  }

  function readHistory() {
    try {
      const stored = JSON.parse(localStorage.getItem(ANALYSIS_KEY) || "{}");
      if (!stored || typeof stored !== "object" || Array.isArray(stored)) return {};
      return stored;
    } catch (_) {
      return {};
    }
  }

  function orderedEntries(history) {
    const known = METHOD_ORDER
      .filter((id) => history[id])
      .map((id) => ({ id, ...history[id] }));
    const extra = Object.keys(history)
      .filter((id) => !METHOD_ORDER.includes(id))
      .map((id) => ({ id, ...history[id] }));
    return [...known, ...extra];
  }

  function renderSummary(entries) {
    const times = entries.map((e) => Number(e.db_execution_ms) || 0);
    const fastest = entries[times.indexOf(Math.min(...times))];
    const slowest = entries[times.indexOf(Math.max(...times))];
    const cards = [
      { label: "Methods tested", value: String(entries.length), sub: "in this browser" },
      { label: "Fastest", value: escapeHtml(LABELS[fastest.id] || fastest.id), sub: `${fmtMs(fastest.db_execution_ms)} ms`, small: true },
      { label: "Slowest", value: escapeHtml(LABELS[slowest.id] || slowest.id), sub: `${fmtMs(slowest.db_execution_ms)} ms`, small: true },
    ];
    $("#analysisSummary").innerHTML = cards.map((c) => `
      <div class="metric-card">
        <div class="metric-label">${c.label}</div>
        <div class="metric-value"${c.small ? ' style="font-size:0.92rem;line-height:1.3"' : ""}>${c.value}</div>
        <div class="metric-sub">${c.sub}</div>
      </div>`).join("");
  }

  function renderChart(entries) {
    const canvas = $("#analysisChart");
    const labels = entries.map((e) => LABELS[e.id] || e.label || e.id);
    const values = entries.map((e) => Math.max(Number(e.db_execution_ms) || 0, 0));
    const colors = entries.map((e) => COLORS[e.id] || "rgba(79, 70, 229, 0.8)");

    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: "DB execution time",
          data: values,
          backgroundColor: colors,
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: 70,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 350 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `${fmtMs(ctx.parsed.y)} ms`,
              afterLabel: (ctx) => {
                const entry = entries[ctx.dataIndex];
                return entry && entry.query ? `Query: ${entry.query}` : "";
              },
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 11 }, maxRotation: 20, minRotation: 0 } },
          y: {
            beginAtZero: true,
            title: { display: true, text: "Database execution time (ms)" },
            grid: { color: "rgba(148,163,184,0.18)" },
            ticks: { font: { size: 10 } },
          },
        },
      },
    });
  }

  function renderTable(entries) {
    $("#analysisTable tbody").innerHTML = entries.map((e) => `
      <tr>
        <td class="method-cell">${escapeHtml(LABELS[e.id] || e.label || e.id)}</td>
        <td>${escapeHtml(e.query || "—")}</td>
        <td class="num">${fmtMs(e.db_execution_ms)} ms</td>
        <td class="num">${escapeHtml(e.result_count ?? "—")}</td>
        <td>${escapeHtml(fmtWhen(e.timestamp))}</td>
      </tr>`).join("");
  }

  function render() {
    const entries = orderedEntries(readHistory());
    const empty = $("#analysisEmpty");
    const content = $("#analysisContent");
    if (!entries.length) {
      empty.hidden = false;
      content.hidden = true;
      if (chart) { chart.destroy(); chart = null; }
      return;
    }
    empty.hidden = true;
    content.hidden = false;
    renderSummary(entries);
    renderChart(entries);
    renderTable(entries);
  }

  document.addEventListener("DOMContentLoaded", () => {
    render();
    $("#clearHistoryBtn").addEventListener("click", () => {
      try { localStorage.removeItem(ANALYSIS_KEY); } catch (_) { /* ignore */ }
      render();
    });
  });
})();
