/* Query-scoped analysis: one graph per query, comparing the methods you ran. */
(() => {
  "use strict";

  const ANALYSIS_KEY = "dbms2.analysis.queries.v1";
  const METHOD_ORDER = [
    "full_scan", "btree", "hash", "composite_btree", "hnsw", "hybrid", "cached",
  ];
  const LABELS = {
    full_scan: "Full Table Scan",
    btree: "B+ Tree",
    hash: "Hash Index",
    composite_btree: "Composite Index",
    hnsw: "HNSW Vector Search",
    hybrid: "Hybrid (Filters + Vector)",
    cached: "Cached Search",
  };
  const SHORT_LABELS = {
    full_scan: "Full scan",
    btree: "B+ Tree",
    hash: "Hash",
    composite_btree: "Composite",
    hnsw: "HNSW",
    hybrid: "Hybrid",
    cached: "Cached",
  };
  const COLORS = {
    full_scan: "rgba(220, 38, 38, 0.82)",
    btree: "rgba(37, 99, 235, 0.82)",
    hash: "rgba(217, 119, 6, 0.82)",
    composite_btree: "rgba(79, 70, 229, 0.86)",
    hnsw: "rgba(6, 182, 212, 0.82)",
    hybrid: "rgba(5, 150, 105, 0.82)",
    cached: "rgba(100, 116, 139, 0.78)",
  };

  const $ = (selector) => document.querySelector(selector);
  let chart = null;
  const state = { selectedId: null };

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

  function readStore() {
    try {
      const stored = JSON.parse(localStorage.getItem(ANALYSIS_KEY) || "null");
      if (
        stored &&
        typeof stored === "object" &&
        stored.queries &&
        typeof stored.queries === "object" &&
        !Array.isArray(stored.queries)
      ) {
        return stored;
      }
    } catch (_) {
      /* fall through */
    }
    return { version: 1, queries: {} };
  }

  function sortedQueries(store) {
    return Object.values(store.queries).sort(
      (a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0)
    );
  }

  function methodsFor(entry) {
    const methods = entry.methods && typeof entry.methods === "object" ? entry.methods : {};
    const known = METHOD_ORDER.filter((id) => methods[id]);
    const extra = Object.keys(methods).filter((id) => !METHOD_ORDER.includes(id));
    return [...known, ...extra].map((id) => ({ id, ...methods[id] }));
  }

  function renderSummary(entry, methods) {
    const times = methods.map((m) => Number(m.db_execution_ms) || 0);
    const fastestIndex = times.indexOf(Math.min(...times));
    const slowestIndex = times.indexOf(Math.max(...times));
    const fastest = methods[fastestIndex];
    const slowest = methods[slowestIndex];
    const cards = [
      {
        label: "Query ID",
        value: entry.id,
        sub: "tap it below to reopen",
        small: true,
      },
      {
        label: "Methods tested",
        value: String(methods.length),
        sub: `limit ${entry.limit}`,
      },
      {
        label: "Fastest",
        value: escapeHtml(LABELS[fastest.id] || fastest.label || fastest.id),
        sub: `${fmtMs(fastest.db_execution_ms)} ms`,
        small: true,
      },
      {
        label: "Slowest",
        value: escapeHtml(LABELS[slowest.id] || slowest.label || slowest.id),
        sub: `${fmtMs(slowest.db_execution_ms)} ms`,
        small: true,
      },
    ];
    $("#analysisSummary").innerHTML = cards.map((c) => `
      <div class="metric-card">
        <div class="metric-label">${c.label}</div>
        <div class="metric-value"${c.small ? ' style="font-size:0.92rem;line-height:1.3"' : ""}>${escapeHtml(c.value)}</div>
        <div class="metric-sub">${escapeHtml(c.sub)}</div>
      </div>`).join("");
  }

  function renderChart(entry, methods) {
    const canvas = $("#analysisChart");
    const labels = methods.map((m) => SHORT_LABELS[m.id] || m.label || m.id);
    const values = methods.map((m) => Math.max(Number(m.db_execution_ms) || 0, 0));
    const colors = methods.map((m) => COLORS[m.id] || "rgba(79, 70, 229, 0.8)");

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
        animation: { duration: 300 },
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: `${entry.id} · ${entry.query}`,
            color: "#1e293b",
            font: { size: 12, weight: "600" },
            padding: { bottom: 12 },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => `${fmtMs(ctx.parsed.y)} ms`,
              afterLabel: (ctx) => {
                const method = methods[ctx.dataIndex];
                return method ? `Results: ${method.result_count ?? "—"}` : "";
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { font: { size: 11 }, maxRotation: 20, minRotation: 0 },
          },
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

  function renderTable(methods) {
    $("#analysisTable tbody").innerHTML = methods.map((m) => `
      <tr>
        <td class="method-cell">${escapeHtml(LABELS[m.id] || m.label || m.id)}</td>
        <td class="num">${fmtMs(m.db_execution_ms)} ms</td>
        <td class="num">${escapeHtml(m.result_count ?? "—")}</td>
        <td>${escapeHtml(m.cache_status || "—")}</td>
        <td>${escapeHtml(fmtWhen(m.timestamp))}</td>
      </tr>`).join("");
  }

  function renderDetail(entry) {
    const methods = methodsFor(entry);
    $("#detailQueryId").textContent = entry.id;
    $("#detailQueryText").textContent = entry.query;
    $("#detailMeta").textContent =
      `limit ${entry.limit} · ${methods.length} method${methods.length === 1 ? "" : "s"} tested · updated ${fmtWhen(entry.updated_at)}`;
    renderSummary(entry, methods);
    renderChart(entry, methods);
    renderTable(methods);
  }

  function renderList(queries, selectedId) {
    $("#queryCount").textContent = `${queries.length} quer${queries.length === 1 ? "y" : "ies"}`;
    $("#queryList").innerHTML = queries.map((entry) => {
      const methods = methodsFor(entry);
      const active = entry.id === selectedId;
      return `
        <button type="button" class="query-card${active ? " active" : ""}" data-query-id="${escapeHtml(entry.id)}">
          <span class="query-id-badge">${escapeHtml(entry.id)}</span>
          <span class="query-card-body">
            <span class="query-card-text">${escapeHtml(entry.query)}</span>
            <span class="query-card-meta">
              ${methods.length} method${methods.length === 1 ? "" : "s"} · limit ${escapeHtml(entry.limit)} · updated ${escapeHtml(fmtWhen(entry.updated_at))}
            </span>
          </span>
          <span class="query-card-chevron" aria-hidden="true">›</span>
        </button>`;
    }).join("");
  }

  function render() {
    const store = readStore();
    const queries = sortedQueries(store);
    const empty = $("#analysisEmpty");
    const detail = $("#analysisDetail");
    const listPanel = $("#queryListPanel");

    if (!queries.length) {
      empty.hidden = false;
      detail.hidden = true;
      listPanel.hidden = true;
      if (chart) { chart.destroy(); chart = null; }
      return;
    }

    const requested = new URLSearchParams(window.location.search).get("q");
    let selectedId = state.selectedId;
    if (!selectedId || !store.queries[selectedId]) {
      selectedId = requested && store.queries[requested] ? requested : queries[0].id;
    }
    state.selectedId = selectedId;

    empty.hidden = true;
    detail.hidden = false;
    listPanel.hidden = false;
    renderDetail(store.queries[selectedId]);
    renderList(queries, selectedId);
  }

  document.addEventListener("DOMContentLoaded", () => {
    render();

    $("#queryList").addEventListener("click", (event) => {
      const card = event.target.closest("[data-query-id]");
      if (!card) return;
      state.selectedId = card.dataset.queryId;
      const url = new URL(window.location.href);
      url.searchParams.set("q", state.selectedId);
      window.history.replaceState(null, "", url);
      render();
      $("#analysisTitle").scrollIntoView({ behavior: "smooth", block: "start" });
    });

    $("#clearHistoryBtn").addEventListener("click", () => {
      if (!window.confirm("Clear every saved query analysis in this browser?")) return;
      try { localStorage.removeItem(ANALYSIS_KEY); } catch (_) { /* ignore */ }
      state.selectedId = null;
      window.history.replaceState(null, "", window.location.pathname);
      render();
    });
  });
})();
