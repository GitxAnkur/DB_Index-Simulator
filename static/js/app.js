/* Indexed Product Search & Benchmarking System — frontend logic */
(() => {
  "use strict";

  const state = {
    health: null,
    methods: [],
    chart: null,
    lastBenchmark: null,
    lastBenchmarkPayload: null,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const COLOR_HEX = {
    Black: "#111827", Blue: "#2563eb", Green: "#16a34a", Grey: "#6b7280",
    Red: "#dc2626", Silver: "#9ca3af", White: "#f8fafc",
  };

  const SHORT_LABELS = {
    full_scan: "Full scan",
    btree: "B-tree",
    hash: "Hash",
    composite_btree: "Composite",
    hnsw: "HNSW",
    hybrid: "Hybrid",
    cached: "Cached",
  };

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

  function fmtNum(value) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString();
  }

  function fmtINR(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return new Intl.NumberFormat("en-IN", {
      style: "currency", currency: "INR", maximumFractionDigits: 0,
    }).format(n);
  }

  function fmtPct(value) {
    if (value === null || value === undefined) return "—";
    return `${(Number(value) * 100).toFixed(1)}%`;
  }

  function toast(message, isError = false) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.toggle("error", isError);
    node.hidden = false;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { node.hidden = true; }, 4200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      if (contentType.includes("application/json")) {
        const data = await response.json();
        message = data.error || message;
        if (data.details && data.details.message) message += `: ${data.details.message}`;
      }
      throw new Error(message);
    }
    if (contentType.includes("application/json")) return response.json();
    return response;
  }

  function setLoading(button, loading, label) {
    if (!button) return;
    const spinner = $(".spinner", button);
    const text = $(".btn-label", button);
    button.disabled = loading;
    if (spinner) spinner.hidden = !loading;
    if (text) {
      if (!text.dataset.original) text.dataset.original = text.textContent;
      text.textContent = loading && label ? label : text.dataset.original;
    }
  }

  function shortLabel(method) {
    return SHORT_LABELS[method] || method;
  }

  function cachePill(status) {
    if (status === "hit") return '<span class="pill pill-green">Cache hit</span>';
    if (status === "miss") return '<span class="pill pill-amber">Cache miss</span>';
    return '<span class="pill pill-soft">No cache</span>';
  }

  /* ------------------------------------------------------------------ init */
  async function loadHealth() {
    try {
      const data = await api("/api/health");
      state.health = data;
      state.methods = data.methods || [];
      const pill = $("#dbStatus");
      pill.className = "status-pill status-ok";
      pill.innerHTML = '<span class="dot"></span> PostgreSQL online';
      $("#statProducts").textContent = fmtNum(data.database.product_count);
      $("#statEmbedded").textContent = fmtNum(data.database.embedded_count);
      populateMethods();
      if (data.dataset_validation && !data.dataset_validation.all_checks_passed) {
        toast("Dataset validation reported a problem. See docs/validation_report.md.", true);
      }
    } catch (error) {
      const pill = $("#dbStatus");
      pill.className = "status-pill status-error";
      pill.innerHTML = '<span class="dot"></span> Database unavailable';
      toast(`Health check failed: ${error.message}`, true);
    }
  }

  async function loadSuite() {
    try {
      const data = await api("/api/benchmark/suite");
      const select = $("#suiteSelect");
      data.queries.forEach((query) => {
        const option = document.createElement("option");
        option.value = query;
        option.textContent = query;
        select.appendChild(option);
      });
    } catch (error) {
      // The fixed suite is optional for the UI; the free-form query still works.
      console.warn(error);
    }
  }

  function populateMethods() {
    const select = $("#methodSelect");
    const current = select.value;
    select.innerHTML = '<option value="">Select a method…</option>';
    state.methods.forEach((method) => {
      const option = document.createElement("option");
      option.value = method.id;
      option.textContent = method.label;
      select.appendChild(option);
    });
    if (current) select.value = current;

    const list = $("#benchmarkMethodList");
    list.innerHTML = "";
    state.methods.forEach((method) => {
      const label = document.createElement("label");
      label.className = "method-checkbox";
      label.innerHTML = `
        <input type="checkbox" value="${escapeHtml(method.id)}" checked />
        <span>${escapeHtml(method.label)}<small>${escapeHtml(method.expected_index || "—")}</small></span>`;
      list.appendChild(label);
    });
    updateMethodHint();
  }

  function updateMethodHint() {
    const id = $("#methodSelect").value;
    const hint = $("#methodHint");
    if (!id) { hint.hidden = true; return; }
    const method = state.methods.find((m) => m.id === id);
    if (!method) { hint.hidden = true; return; }
    $("#methodHintName").textContent = method.label;
    $("#methodHintIndex").textContent = method.expected_index || "no index";
    $("#methodHintText").textContent = method.description;
    hint.hidden = false;
  }

  /* ---------------------------------------------------------------- search */
  async function runSearch(event) {
    event.preventDefault();
    const query = $("#queryInput").value.trim();
    const method = $("#methodSelect").value;
    const limit = Number($('input[name="limit"]:checked').value);
    const errorBox = $("#searchError");
    errorBox.hidden = true;

    if (!query) { showSearchError("Enter a natural-language query first."); $("#queryInput").focus(); return; }
    if (!method) { showSearchError("Choose one of the seven search methods. The application does not auto-select a method."); $("#methodSelect").focus(); return; }

    const button = $("#searchBtn");
    setLoading(button, true, "Searching…");
    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({ query, method, limit, include_plan: true }),
      });
      const renderStart = performance.now();
      renderSearch(data);
      const clientRenderMs = performance.now() - renderStart;
      state.lastSearch = data;
      renderClientTiming(clientRenderMs);
      $("#performanceSection").hidden = false;
      $("#resultsSection").hidden = false;
      $("#technicalSection").hidden = false;
      $("#performanceSection").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      showSearchError(error.message);
      toast(error.message, true);
    } finally {
      setLoading(button, false);
    }
  }

  function showSearchError(message) {
    const box = $("#searchError");
    box.textContent = message;
    box.hidden = false;
  }

  function renderClientTiming(ms) {
    const grid = $("#metricGrid");
    const card = document.createElement("div");
    card.className = "metric-card";
    const value = ms > 0 && ms < 0.001 ? "<0.001" : fmtMs(ms);
    card.innerHTML = `
      <div class="metric-label">Client render</div>
      <div class="metric-value">${value}<small>ms</small></div>
      <div class="metric-sub">browser-side render only</div>`;
    grid.appendChild(card);
  }

  function renderSearch(data) {
    const technical = data.technical || {};
    const plan = technical.explain || {};
    const cacheStatus = (data.cache || {}).status;
    const cacheBadge = $("#cacheBadge");
    if (cacheStatus) {
      cacheBadge.innerHTML = cachePill(cacheStatus);
      cacheBadge.hidden = false;
    } else {
      cacheBadge.hidden = true;
    }

    const grid = $("#metricGrid");
    grid.innerHTML = "";
    const metrics = [
      { label: "Selected method", value: data.method_label, sub: data.method, accent: true, small: false },
      { label: "DB execution", value: fmtMs(data.db_execution_ms), unit: "ms", sub: "actual PostgreSQL query" },
      { label: "Total execution", value: fmtMs(data.execution_ms), unit: "ms", sub: "parse + embedding + DB + cache lookup" },
      { label: "Embedding", value: fmtMs(data.embedding_ms), unit: "ms", sub: "query embedding time" },
      { label: "Results", value: fmtNum(data.result_count), sub: `limit ${data.limit}` },
      { label: "Rows processed", value: fmtNum(technical.rows_processed), sub: "root plan node actual rows" },
      { label: "Indexes used", value: (technical.indexes_used || []).length ? technical.indexes_used.join(", ") : "None (seq scan)", sub: "from EXPLAIN ANALYZE", small: true },
    ];
    if (cacheStatus) {
      metrics.push({ label: "Cache", value: cacheStatus.toUpperCase(), sub: data.cache?.lookup_ms != null ? `${fmtMs(data.cache.lookup_ms)} ms lookup` : "application cache" });
    }
    metrics.forEach((m) => {
      const card = document.createElement("div");
      card.className = `metric-card${m.accent ? " accent" : ""}`;
      const valueClass = m.small ? "metric-value" : "metric-value";
      const valueStyle = m.small ? ' style="font-size:0.82rem;line-height:1.25;font-family:var(--mono);word-break:break-all"' : "";
      card.innerHTML = `
        <div class="metric-label">${escapeHtml(m.label)}</div>
        <div class="${valueClass}"${valueStyle}>${escapeHtml(m.value)}${m.unit ? `<small>${escapeHtml(m.unit)}</small>` : ""}</div>
        <div class="metric-sub">${escapeHtml(m.sub || "")}</div>`;
      grid.appendChild(card);
    });

    renderParsedFilters(data.parsed_filters || {});
    renderWarnings(data.warnings || []);
    renderProducts(data.results || []);
    renderTechnical(data);
  }

  function renderParsedFilters(filters) {
    const box = $("#parsedFilters");
    const parts = [];
    if (filters.category) parts.push(["Category", filters.category]);
    if (filters.brand) parts.push(["Brand", filters.brand]);
    if (filters.color) parts.push(["Colour", filters.color]);
    if (filters.min_price != null) parts.push(["Min price", fmtINR(filters.min_price)]);
    if (filters.max_price != null) parts.push(["Max price", fmtINR(filters.max_price)]);
    if (filters.use_case) parts.push(["Use case", filters.use_case]);
    if ((filters.keywords || []).length) parts.push(["Keywords", filters.keywords.join(", ")]);
    box.innerHTML = parts.length
      ? parts.map(([k, v]) => `<span class="filter-chip"><strong>${escapeHtml(k)}:</strong> ${escapeHtml(v)}</span>`).join("")
      : '<span class="filter-chip">No structured filters parsed; semantic search uses the original query.</span>';
  }

  function renderWarnings(warnings) {
    const box = $("#searchWarnings");
    if (!warnings.length) { box.hidden = true; box.innerHTML = ""; return; }
    box.innerHTML = warnings.map((w) => `<div class="warning-item">${escapeHtml(w)}</div>`).join("");
    box.hidden = false;
  }

  function renderProducts(products) {
    const grid = $("#productGrid");
    $("#resultCount").textContent = `${products.length} product${products.length === 1 ? "" : "s"}`;
    if (!products.length) {
      grid.innerHTML = '<div class="empty-state">No products matched this query and method. Try a broader query or another method.</div>';
      return;
    }
    grid.innerHTML = products.map((p) => {
      let specs = [];
      try {
        const parsed = JSON.parse(p.specifications || "[]");
        if (Array.isArray(parsed)) specs = parsed.slice(0, 3);
      } catch (_) { specs = []; }
      const tags = String(p.tags || "").split(",").map((t) => t.trim()).filter(Boolean).slice(0, 4);
      const colorHex = COLOR_HEX[p.color] || "#94a3b8";
      const similarity = p.similarity != null
        ? `<span class="similarity-badge">similarity ${(Number(p.similarity) * 100).toFixed(1)}%</span>` : "";
      return `
        <article class="product-card">
          <div class="product-top">
            <span class="product-cat">${escapeHtml(p.category)}</span>
            <span class="product-id">${escapeHtml(p.product_id)}</span>
          </div>
          <h3 class="product-name">${escapeHtml(p.name)}</h3>
          <div class="product-brand">${escapeHtml(p.brand)}${p.use_case ? ` · ${escapeHtml(p.use_case)}` : ""}</div>
          <div class="product-price-row">
            <span class="product-price">${fmtINR(p.price_inr)} <small>INR</small></span>
            <span class="rating">★ ${Number(p.rating).toFixed(1)}</span>
          </div>
          <div class="product-meta">
            <span class="meta-pill"><span class="color-dot" style="background:${colorHex}"></span>${escapeHtml(p.color || "—")}</span>
            <span class="meta-pill">Stock ${fmtNum(p.stock_quantity)}</span>
            ${specs.map((s) => `<span class="meta-pill">${escapeHtml(s)}</span>`).join("")}
            ${similarity}
          </div>
          <p class="product-desc">${escapeHtml(p.description || "")}</p>
          <div class="tag-row">${tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("")}</div>
        </article>`;
    }).join("");
  }

  function renderTechnical(data) {
    const t = data.technical || {};
    const plan = t.explain || {};
    const buffers = t.buffers || {};
    const vector = t.vector_info;
    const indexes = t.indexes_used || [];
    const details = t.method_details || {};
    const cache = t.cache || data.cache;

    const nodeRows = (plan.nodes || []).map((node) => {
      const indent = "&nbsp;".repeat((node.depth || 0) * 3);
      const extra = [
        node.index ? `index: ${node.index}` : "",
        node.relation ? `relation: ${node.relation}` : "",
        node.actual_total_ms != null ? `${node.actual_total_ms} ms` : "",
        node.actual_rows != null ? `${fmtNum(node.actual_rows)} rows` : "",
        node.filter ? `filter: ${node.filter}` : "",
        node.index_condition ? `cond: ${node.index_condition}` : "",
      ].filter(Boolean).join(" · ");
      return `<tr>
        <td class="plan-node-name">${indent}${escapeHtml(node.node_type || "")}</td>
        <td>${escapeHtml(extra)}</td>
        <td class="num">${node.actual_total_ms != null ? fmtMs(node.actual_total_ms) : "—"}</td>
      </tr>`;
    }).join("");

    const vectorHtml = vector ? `
      <div class="tech-block">
        <h4>Vector similarity</h4>
        <div class="big">${escapeHtml(vector.index_type)} · ${escapeHtml(vector.metric)}</div>
        <div class="metric-sub">operator ${escapeHtml(vector.operator)} · dimension ${vector.dimension} · ef_search ${vector.ef_search}</div>
        <div class="metric-sub">model ${escapeHtml(vector.model)}</div>
      </div>` : "";

    const cacheHtml = cache ? `
      <div class="tech-block">
        <h4>Cache status</h4>
        <div class="big">${escapeHtml((cache.status || "n/a").toUpperCase())}</div>
        <div class="metric-sub">key ${escapeHtml(cache.key || "—")}</div>
        <div class="metric-sub">lookup ${fmtMs(cache.lookup_ms)} ms · TTL ${escapeHtml(cache.ttl_seconds ?? "—")}s · entries ${escapeHtml(cache.stats?.entries ?? "—")}</div>
      </div>` : "";

    $("#technicalBody").innerHTML = `
      <div class="tech-grid">
        <div class="tech-block">
          <h4>Executed SQL</h4>
          <div class="big">${escapeHtml(data.method)}</div>
          <div class="metric-sub">${escapeHtml(t.expected_index || "no expected index")}</div>
        </div>
        <div class="tech-block">
          <h4>EXPLAIN ANALYZE</h4>
          <div class="big">${fmtMs(plan.execution_time_ms)} ms</div>
          <div class="metric-sub">planning ${fmtMs(plan.planning_time_ms)} ms · capture ${fmtMs(t.plan_capture_ms)} ms</div>
        </div>
        <div class="tech-block">
          <h4>Indexes used</h4>
          <div class="index-badges">${indexes.length ? indexes.map((i) => `<span class="index-badge">${escapeHtml(i)}</span>`).join("") : '<span class="index-badge">none</span>'}</div>
          <div class="metric-sub">top node: ${escapeHtml(plan.top_node || "—")}</div>
        </div>
        <div class="tech-block">
          <h4>Rows &amp; buffers</h4>
          <div class="big">${fmtNum(plan.rows_returned_by_root)} rows</div>
          <div class="metric-sub">shared hit ${fmtNum(buffers.shared_hit_blocks)} · read ${fmtNum(buffers.shared_read_blocks)} · temp read ${fmtNum(buffers.temp_read_blocks)}</div>
        </div>
        ${vectorHtml}
        ${cacheHtml}
      </div>

      <div class="tech-section">
        <h3>Executed SQL (parameterised)</h3>
        <pre class="code-block">${escapeHtml(t.sql || "")}</pre>
        <div class="tech-section" style="margin-top:8px">
          <h3>Parameters</h3>
          <pre class="params-block">${escapeHtml(JSON.stringify(t.params || [], null, 2))}</pre>
        </div>
        ${t.planner_settings && t.planner_settings.length ? `<div class="tech-section"><h3>Planner settings</h3><div class="index-badges">${t.planner_settings.map((s) => `<span class="index-badge">${escapeHtml(s)}</span>`).join("")}</div></div>` : ""}
      </div>

      <div class="tech-section">
        <h3>Query plan (EXPLAIN ANALYZE, BUFFERS)</h3>
        <div class="table-scroll">
          <table class="plan-table">
            <thead><tr><th>Node</th><th>Details</th><th class="num">Actual time</th></tr></thead>
            <tbody>${nodeRows || '<tr><td colspan="3">No plan captured.</td></tr>'}</tbody>
          </table>
        </div>
        <details style="margin-top:10px">
          <summary>Raw EXPLAIN JSON</summary>
          <pre class="code-block">${escapeHtml(JSON.stringify(plan.plan_json || {}, null, 2))}</pre>
        </details>
      </div>

      <div class="tech-section">
        <h3>Method notes</h3>
        <pre class="params-block">${escapeHtml(JSON.stringify(details, null, 2))}</pre>
      </div>`;
  }

  /* ------------------------------------------------------------- benchmark */
  function benchmarkPayload() {
    const methods = $$("#benchmarkMethodList input:checked").map((input) => input.value);
    return {
      query: $("#benchmarkQuery").value.trim(),
      methods,
      limit: Number($("#benchmarkLimit").value),
      repetitions: Number($("#repetitions").value),
      clear_cache: true,
      warmup_runs: 1,
      capture_representative_plan: true,
    };
  }

  async function runBenchmark(event) {
    event.preventDefault();
    const payload = benchmarkPayload();
    const errorBox = $("#benchmarkError");
    errorBox.hidden = true;
    if (!payload.query) { showBenchmarkError("Enter a benchmark query."); return; }
    if (!payload.methods.length) { showBenchmarkError("Select at least one method to compare."); return; }

    const button = $("#runBenchmarkBtn");
    setLoading(button, true, "Running…");
    $("#benchmarkStatus").textContent = `Running ${payload.repetitions} repetitions per method…`;
    try {
      const data = await api("/api/benchmark", { method: "POST", body: JSON.stringify(payload) });
      state.lastBenchmark = data;
      state.lastBenchmarkPayload = payload;
      $("#benchmarkResults").hidden = false;
      renderBenchmark(data);
      $("#benchmarkStatus").textContent = `Completed in ${data.duration_seconds}s`;
      const failed = data.methods.filter((m) => m.failed_runs > 0);
      if (failed.length) {
        toast(`${failed.length} method(s) had failed runs. See the comparison table and raw samples.`, true);
      }
    } catch (error) {
      showBenchmarkError(error.message);
      $("#benchmarkStatus").textContent = "";
      toast(error.message, true);
    } finally {
      setLoading(button, false);
    }
  }

  function showBenchmarkError(message) {
    const box = $("#benchmarkError");
    box.textContent = message;
    box.hidden = false;
  }

  function renderBenchmark(data) {
    renderChart(data);
    renderComparisonTable(data);
    renderBenchmarkConditions(data);
    renderComparability(data);
  }

  function renderChart(data) {
    const canvas = $("#benchmarkChart");
    const rows = data.comparison_table;
    const labels = rows.map((r) => shortLabel(r.method));
    const median = rows.map((r) => Math.max(Number(r.median_ms || 0), 0));
    const min = rows.map((r) => Math.max(Number(r.min_ms || 0), 0));
    const max = rows.map((r) => Math.max(Number(r.max_ms || 0), 0));
    const logScale = $("#logScale").checked;

    const values = (arr) => arr.map((v) => (logScale ? Math.max(v, 0.01) : v));
    if (state.chart) state.chart.destroy();
    state.chart = new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "Median", data: values(median), backgroundColor: "rgba(79,70,229,0.88)", borderRadius: 5, borderSkipped: false },
          { label: "Minimum", data: values(min), backgroundColor: "rgba(6,182,212,0.75)", borderRadius: 5, borderSkipped: false },
          { label: "Maximum", data: values(max), backgroundColor: "rgba(245,158,11,0.72)", borderRadius: 5, borderSkipped: false },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 350 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "top", labels: { usePointStyle: true, boxWidth: 9, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmtMs(ctx.parsed.y)} ms`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 11 } } },
          y: {
            type: logScale ? "logarithmic" : "linear",
            beginAtZero: !logScale,
            title: { display: true, text: "Execution time (ms)" },
            grid: { color: "rgba(148,163,184,0.18)" },
            ticks: { font: { size: 10 } },
          },
        },
      },
    });
    $("#chartCaption").textContent =
      `“${data.query}” · limit ${data.limit} · ${data.repetitions} repetitions · ${data.methods.length} methods · database execution time`;
  }

  function renderComparisonTable(data) {
    const tbody = $("#comparisonTable tbody");
    tbody.innerHTML = data.comparison_table.map((row) => {
      const method = data.methods.find((m) => m.method === row.method);
      const cacheState = method
        ? (method.cache_conditions.hit_runs && method.cache_conditions.miss_runs
            ? "miss → hit"
            : method.cache_conditions.hit_runs ? "hit" : method.cache_conditions.miss_runs ? "miss" : "n/a")
        : "n/a";
      const cacheClass = cacheState === "hit" ? "pill-green" : cacheState.includes("hit") ? "pill-blue" : cacheState === "miss" ? "pill-amber" : "pill-soft";
      const comparable = row.comparable ? '<span class="pill pill-green">Yes</span>' : '<span class="pill pill-amber">No</span>';
      const overlap = row.overlap_with_full_scan != null ? `${row.overlap_with_full_scan}` : "—";
      return `<tr>
        <td class="method-cell">${escapeHtml(row.label)}<div class="metric-sub">${escapeHtml(row.method)}</div></td>
        <td class="num">${fmtMs(row.median_ms)}</td>
        <td class="num">${fmtMs(row.mean_ms)}</td>
        <td class="num">${fmtMs(row.min_ms)}</td>
        <td class="num">${fmtMs(row.max_ms)}</td>
        <td class="num">${row.successful_runs}/${method ? method.repetitions : "—"}</td>
        <td><span class="pill ${cacheClass}">${escapeHtml(cacheState)}</span></td>
        <td>${comparable}</td>
        <td class="num">${overlap}</td>
      </tr>`;
    }).join("");
  }

  function renderBenchmarkConditions(data) {
    const appCache = data.conditions.application_cache;
    const chips = [
      `Query: ${data.query}`,
      `Limit: ${data.limit}`,
      `Repetitions: ${data.repetitions}`,
      `Warm-up runs: ${data.warmup_runs}`,
      `PostgreSQL cache: ${data.conditions.postgres_cache}`,
      `App cache before: ${appCache.before.entries} entries`,
      `App cache after: ${appCache.after.entries} entries`,
      `Duration: ${data.duration_seconds}s`,
    ];
    $("#benchmarkConditions").innerHTML = `
      <h4>Experimental conditions</h4>
      <p>${escapeHtml(data.conditions.note)}</p>
      <div class="condition-chips">${chips.map((c) => `<span class="condition-chip">${escapeHtml(c)}</span>`).join("")}</div>`;
  }

  function renderComparability(data) {
    const items = data.methods.map((m) => `
      <div class="comparability-item">
        <strong>${escapeHtml(m.label)}</strong> — ${escapeHtml(m.comparability.note)}
        ${m.representative_plan ? `<span class="metric-sub">Representative plan: ${escapeHtml(m.representative_plan.top_node || "—")} · indexes: ${escapeHtml((m.representative_plan.indexes_used || []).join(", ") || "none")} · ${fmtMs(m.representative_plan.execution_time_ms)} ms</span>` : ""}
      </div>`).join("");
    $("#comparabilityNotes").innerHTML = `<h4 class="field-label" style="margin-bottom:2px">Comparability notes</h4>${items}`;
  }

  async function exportCsv() {
    const payload = benchmarkPayload();
    if (!payload.query) { showBenchmarkError("Enter a benchmark query first."); return; }
    if (!payload.methods.length) { showBenchmarkError("Select at least one method first."); return; }
    const button = $("#exportCsvBtn");
    button.disabled = true;
    $("#benchmarkStatus").textContent = "Running benchmark and generating CSV…";
    try {
      const response = await fetch("/api/benchmark/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, capture_representative_plan: false }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Export failed (${response.status})`);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename = match ? match[1] : "benchmark_results.csv";
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      $("#benchmarkStatus").textContent = `CSV exported: ${filename}`;
      toast("Benchmark CSV exported.");
    } catch (error) {
      showBenchmarkError(error.message);
      $("#benchmarkStatus").textContent = "";
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function clearCache() {
    try {
      const data = await api("/api/cache/clear", { method: "POST", body: "{}" });
      toast(`Cache cleared (${data.cleared_entries} entries removed).`);
    } catch (error) {
      toast(error.message, true);
    }
  }

  /* --------------------------------------------------------------- events */
  function bindEvents() {
    $("#searchForm").addEventListener("submit", runSearch);
    $("#methodSelect").addEventListener("change", updateMethodHint);
    $$(".example").forEach((button) => button.addEventListener("click", () => {
      $("#queryInput").value = button.textContent.trim();
      $("#queryInput").focus();
    }));
    $("#benchmarkForm").addEventListener("submit", runBenchmark);
    $("#suiteSelect").addEventListener("change", (event) => {
      if (event.target.value) $("#benchmarkQuery").value = event.target.value;
    });
    $("#selectAllMethods").addEventListener("click", () => {
      $$("#benchmarkMethodList input").forEach((input) => { input.checked = true; });
    });
    $("#clearAllMethods").addEventListener("click", () => {
      $$("#benchmarkMethodList input").forEach((input) => { input.checked = false; });
    });
    $("#logScale").addEventListener("change", () => {
      if (state.lastBenchmark) renderChart(state.lastBenchmark);
    });
    $("#exportCsvBtn").addEventListener("click", exportCsv);
    $("#clearCacheBtn").addEventListener("click", clearCache);
  }

  async function applyUrlState() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("query")) {
      $("#queryInput").value = params.get("query");
      $("#benchmarkQuery").value = params.get("query");
    }
    if (params.get("method")) {
      const select = $("#methodSelect");
      if (state.methods.some((m) => m.id === params.get("method"))) {
        select.value = params.get("method");
        updateMethodHint();
      }
    }
    if (params.get("limit") === "10") {
      const radio = $('input[name="limit"][value="10"]');
      if (radio) radio.checked = true;
    }
    if (params.get("autosearch") === "1" && $("#queryInput").value && $("#methodSelect").value) {
      await runSearch({ preventDefault: () => {} });
    }
    if (params.get("autobenchmark") === "1" && $("#benchmarkQuery").value) {
      await runBenchmark({ preventDefault: () => {} });
    }
    if (params.get("open_technical") === "1") {
      const details = $("#technicalSection details");
      if (details) {
        details.open = true;
        details.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bindEvents();
    await Promise.all([loadHealth(), loadSuite()]);
    await applyUrlState();
  });
})();
