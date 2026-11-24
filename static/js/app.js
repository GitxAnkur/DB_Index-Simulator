/* Indexed Product Search — frontend logic */
(() => {
  "use strict";

  const ANALYSIS_KEY = "dbms2.analysis.queries.v1";
  const LAST_SEARCH_KEY = "dbms2.lastSearch.v1";

  const state = {
    health: null,
    methods: [],
    lastSearch: null,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const COLOR_HEX = {
    Black: "#111827", Blue: "#2563eb", Green: "#16a34a", Grey: "#6b7280",
    Red: "#dc2626", Silver: "#9ca3af", White: "#f8fafc",
  };

  const SHORT_LABELS = {
    full_scan: "Full Table Scan",
    btree: "B+ Tree",
    hash: "Hash Index",
    composite_btree: "Composite Index",
    hnsw: "HNSW Vector Search",
    hybrid: "Hybrid (Filters + Vector)",
    cached: "Cached Search",
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
    } catch (error) {
      const pill = $("#dbStatus");
      pill.className = "status-pill status-error";
      pill.innerHTML = '<span class="dot"></span> Database unavailable';
      toast(`Health check failed: ${error.message}`, true);
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
    hideError();

    if (!query) {
      showError("Enter a natural-language query first.");
      $("#queryInput").focus();
      return;
    }
    if (!method) {
      showError("Choose a search method. The application does not auto-select one.");
      $("#methodSelect").focus();
      return;
    }

    const button = $("#searchBtn");
    setLoading(button, true, "Searching…");
    try {
      const data = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({ query, method, limit, include_plan: false }),
      });
      const analysisId = recordAnalysis(data);
      saveLastSearch({ query, method, limit });
      renderSearch(data, analysisId);
    } catch (error) {
      showError(error.message);
      toast(error.message, true);
    } finally {
      setLoading(button, false);
    }
  }

  function showError(message) {
    const box = $("#searchError");
    box.textContent = message;
    box.hidden = false;
  }

  function hideError() {
    $("#searchError").hidden = true;
  }

  function hashString(value) {
    // FNV-1a, converted to a short stable base-36 identifier.
    let hash = 2166136261;
    for (let i = 0; i < value.length; i += 1) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36).toUpperCase().padStart(6, "0").slice(-6);
  }

  function queryIdFor(normalizedQuery, limit) {
    return `Q-${hashString(`${normalizedQuery}|${limit}`)}`;
  }

  function readAnalysisStore() {
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
      /* fall through to an empty store */
    }
    return { version: 1, queries: {} };
  }

  function writeAnalysisStore(store) {
    try {
      localStorage.setItem(ANALYSIS_KEY, JSON.stringify(store));
    } catch (_) {
      /* localStorage may be unavailable in private mode; search still works. */
    }
  }

  function recordAnalysis(data) {
    if (!data || data.out_of_scope) return null;
    const normalized = data.normalized_query || String(data.query || "").trim().toLowerCase();
    const queryId = queryIdFor(normalized, data.limit);
    const now = new Date().toISOString();
    const store = readAnalysisStore();
    const entry = store.queries[queryId] || {
      id: queryId,
      query: data.query,
      normalized,
      limit: data.limit,
      created_at: now,
      updated_at: now,
      methods: {},
    };
    entry.query = data.query;
    entry.normalized = normalized;
    entry.limit = data.limit;
    entry.updated_at = now;
    entry.methods[data.method] = {
      method: data.method,
      label: data.method_label,
      db_execution_ms: Number(data.db_execution_ms) || 0,
      result_count: data.result_count,
      limit: data.limit,
      cache_status: (data.cache || {}).status || null,
      timestamp: now,
    };
    store.queries[queryId] = entry;
    writeAnalysisStore(store);
    return queryId;
  }

  function saveLastSearch(value) {
    try {
      localStorage.setItem(LAST_SEARCH_KEY, JSON.stringify(value));
    } catch (_) {
      /* localStorage may be unavailable; search still works. */
    }
  }

  function readLastSearch() {
    try {
      const stored = JSON.parse(localStorage.getItem(LAST_SEARCH_KEY) || "null");
      if (stored && typeof stored === "object" && stored.query) return stored;
    } catch (_) {
      /* ignore malformed state */
    }
    return null;
  }

  function renderSearch(data, analysisId) {
    state.lastSearch = data;
    const noticeBox = $("#searchNotice");
    const analysisLink = $("#queryAnalysisLink");

    if (data.out_of_scope) {
      noticeBox.textContent = data.notice || "No products match this query.";
      noticeBox.hidden = false;
      analysisLink.hidden = true;
      $("#performanceSection").hidden = true;
      $("#resultsSection").hidden = false;
      renderResults(data, "This query is outside the product catalogue, so no products are shown.");
      $("#resultsSection").scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }

    noticeBox.hidden = true;
    if (analysisId) {
      analysisLink.href = `/analysis?q=${encodeURIComponent(analysisId)}`;
      analysisLink.textContent = `View ${analysisId} analysis`;
      analysisLink.hidden = false;
    } else {
      analysisLink.hidden = true;
    }
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
      {
        label: "DB execution",
        value: fmtMs(data.db_execution_ms),
        unit: "ms",
        sub: "actual PostgreSQL search query",
        accent: true,
      },
      { label: "Results", value: fmtNum(data.result_count), sub: `limit ${data.limit}` },
      { label: "Method", value: data.method_label, sub: data.method },
    ];
    if (analysisId) {
      metrics.push({
        label: "Query ID",
        value: analysisId,
        sub: "open it in Analysis",
      });
    }
    if (cacheStatus) {
      metrics.push({
        label: "Cache",
        value: cacheStatus.toUpperCase(),
        sub: data.cache?.lookup_ms != null ? `${fmtMs(data.cache.lookup_ms)} ms lookup` : "application cache",
      });
    }
    metrics.forEach((m) => {
      const card = document.createElement("div");
      card.className = `metric-card${m.accent ? " accent" : ""}`;
      card.innerHTML = `
        <div class="metric-label">${escapeHtml(m.label)}</div>
        <div class="metric-value">${escapeHtml(m.value)}${m.unit ? `<small>${escapeHtml(m.unit)}</small>` : ""}</div>
        <div class="metric-sub">${escapeHtml(m.sub || "")}</div>`;
      grid.appendChild(card);
    });

    renderParsedFilters(data.parsed_filters || {});
    renderWarnings(data.warnings || []);
    renderResults(data, "No products matched this query and method. Try a broader query or another method.");

    $("#performanceSection").hidden = false;
    $("#resultsSection").hidden = false;
    $("#performanceSection").scrollIntoView({ behavior: "smooth", block: "start" });
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

  function renderResults(data, emptyMessage) {
    const products = data.results || [];
    const grid = $("#productGrid");
    $("#resultCount").textContent = `${products.length} product${products.length === 1 ? "" : "s"}`;
    if (!products.length) {
      grid.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
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

  /* --------------------------------------------------------------- events */
  function bindEvents() {
    $("#searchForm").addEventListener("submit", runSearch);
    $("#methodSelect").addEventListener("change", updateMethodHint);
    $$(".example").forEach((button) => button.addEventListener("click", () => {
      $("#queryInput").value = button.textContent.trim();
      $("#queryInput").focus();
    }));
  }

  async function applyUrlState() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("query")) $("#queryInput").value = params.get("query");
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

    // Returning from Analysis without URL parameters should keep the previous
    // query so the user can change only the method and compare the same query.
    if (!params.get("query") && !params.get("method")) {
      const last = readLastSearch();
      if (last) {
        $("#queryInput").value = last.query || "";
        if (last.method && state.methods.some((m) => m.id === last.method)) {
          $("#methodSelect").value = last.method;
          updateMethodHint();
        }
        if (Number(last.limit) === 10) {
          const radio = $('input[name="limit"][value="10"]');
          if (radio) radio.checked = true;
        }
      }
    }

    if (params.get("autosearch") === "1" && $("#queryInput").value && $("#methodSelect").value) {
      await runSearch({ preventDefault: () => {} });
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bindEvents();
    await loadHealth();
    await applyUrlState();
  });
})();
