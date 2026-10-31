(() => {
  const STORAGE_KEY = "svrmon24.basicAuth";
  const ACCENT_KEY = "svrmon24.accent";
  const authConfig = {
    loaded: false,
    basic_auth_enabled: false,
    oidc_enabled: false,
    login_path: "/auth/login",
    logout_path: "/auth/logout",
    expected_origin: "",
    host_matches_redirect: true,
    host_hint: "",
    redirect_uri: "",
  };

  const AUTH_ERROR_MESSAGES = {
    oidc_state:
      "OIDC login state was missing or expired. Most often this means the browser host does not match OIDC_REDIRECT_URI (localhost vs 127.0.0.1 are different cookie jars). Open the expected origin, sign in again, and avoid mixing hosts.",
    oidc_provider:
      "The identity provider rejected or failed the login. Check Keycloak/Entra client settings and try again.",
    oidc_config:
      "OIDC is not configured correctly. Check OIDC_ENABLED, OIDC_ISSUER, and OIDC_CLIENT_ID.",
  };
  const ACCENT_PRESETS = {
    /* sidebar* stays navy/indigo family — Teal accents buttons/nav only, never page/sidebar shell */
    "#4F46E5": {
      hover: "#4338CA",
      soft: "rgba(79, 70, 229, 0.12)",
      ring: "rgba(79, 70, 229, 0.28)",
      accent2: "#6366F1",
      sidebarBg: "#0F172A",
      sidebarBg2: "#1E1B4B",
      sidebarBorder: "rgba(148, 163, 184, 0.16)",
    },
    "#2563EB": {
      hover: "#1D4ED8",
      soft: "rgba(37, 99, 235, 0.12)",
      ring: "rgba(37, 99, 235, 0.28)",
      accent2: "#3B82F6",
      sidebarBg: "#0B1224",
      sidebarBg2: "#172554",
      sidebarBorder: "rgba(147, 197, 253, 0.14)",
    },
    "#0D9488": {
      hover: "#0F766E",
      soft: "rgba(13, 148, 136, 0.12)",
      ring: "rgba(13, 148, 136, 0.28)",
      accent2: "#14B8A6",
      /* Keep navy/indigo shell — do not paint sidebar teal/green */
      sidebarBg: "#0F172A",
      sidebarBg2: "#1E1B4B",
      sidebarBorder: "rgba(148, 163, 184, 0.16)",
    },
    "#475569": {
      hover: "#334155",
      soft: "rgba(71, 85, 105, 0.12)",
      ring: "rgba(71, 85, 105, 0.28)",
      accent2: "#64748B",
      sidebarBg: "#0F172A",
      sidebarBg2: "#1E293B",
      sidebarBorder: "rgba(148, 163, 184, 0.16)",
    },
    "#7C3AED": {
      hover: "#6D28D9",
      soft: "rgba(124, 58, 237, 0.12)",
      ring: "rgba(124, 58, 237, 0.28)",
      accent2: "#8B5CF6",
      sidebarBg: "#0F0A1F",
      sidebarBg2: "#2E1065",
      sidebarBorder: "rgba(196, 181, 253, 0.14)",
    },
  };
  const DEFAULT_ACCENT = "#4F46E5";
  const state = {
    page: 1,
    pageSize: 25,
    totalPages: 1,
    editingId: null,
    customFields: [],
    deleteTarget: null,
    relPage: 1,
    relTotalPages: 1,
    editingRelId: null,
    relTypes: [],
    componentIds: [],
    currentDiagnosticId: null,
    inventoryType: null,
    activeNav: "dashboard",
    authenticated: false,
    authMethod: "",
  };

  const INVENTORY_TABS = {
    servers: "Server",
    network: "Network",
    applications: "Application",
    middleware: "Middleware",
    databases: "Database",
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function toast(message, isError = false) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("show"), 4200);
  }

  function normalizeAccent(value) {
    const raw = String(value || "").trim().toUpperCase();
    if (!/^#[0-9A-F]{6}$/.test(raw)) return DEFAULT_ACCENT;
    return ACCENT_PRESETS[raw] ? raw : DEFAULT_ACCENT;
  }

  function applyAccent(hex, { persist = true } = {}) {
    const accent = normalizeAccent(hex);
    const preset = ACCENT_PRESETS[accent];
    const root = document.documentElement;
    root.style.setProperty("--accent", accent);
    root.style.setProperty("--accent-hover", preset.hover);
    root.style.setProperty("--accent-dim", preset.hover);
    root.style.setProperty("--accent-2", preset.accent2);
    root.style.setProperty("--accent-soft", preset.soft);
    root.style.setProperty("--accent-ring", preset.ring);
    root.style.setProperty("--sidebar-bg", preset.sidebarBg);
    root.style.setProperty("--sidebar-bg-2", preset.sidebarBg2);
    root.style.setProperty("--sidebar-border", preset.sidebarBorder);

    const select = $("#accentSelect");
    if (select) select.value = accent;
    $$(".accent-swatch").forEach((btn) => {
      const active = normalizeAccent(btn.getAttribute("data-accent")) === accent;
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });

    if (persist) {
      try {
        localStorage.setItem(ACCENT_KEY, accent);
      } catch (_) {
        /* ignore quota / private mode */
      }
    }
  }

  function restoreAccent() {
    let saved = DEFAULT_ACCENT;
    try {
      saved = localStorage.getItem(ACCENT_KEY) || DEFAULT_ACCENT;
    } catch (_) {
      saved = DEFAULT_ACCENT;
    }
    applyAccent(saved, { persist: false });
  }

  const PAGE_META = {
    dashboard: { title: "Dashboard", subtitle: "Live CMDB and diagnostic overview" },
    servers: { title: "Servers", subtitle: "Server inventory filtered by component_type=Server" },
    network: { title: "Network", subtitle: "Network devices filtered by component_type=Network" },
    applications: { title: "Applications", subtitle: "Applications filtered by component_type=Application" },
    middleware: { title: "Middleware", subtitle: "Middleware filtered by component_type=Middleware" },
    databases: { title: "Databases", subtitle: "Databases filtered by component_type=Database" },
    inventory: { title: "Inventory", subtitle: "CMDB components with separate OS and product columns" },
    relationships: { title: "Relationships", subtitle: "Manual links with separate protocol and ports" },
    dependencies: { title: "Dependencies", subtitle: "Traversal, cycles, and potentially affected apps" },
    diagnostics: { title: "Diagnostics", subtitle: "DEMO / SIMULATED evidence only — no live probes" },
    custom: { title: "Custom Fields", subtitle: "Extend inventory forms with typed definitions" },
    columns: { title: "Column Settings", subtitle: "Coming soon — grid column configs not implemented" },
    users: { title: "Users", subtitle: "Placeholder — memberships / RBAC come later" },
    roles: { title: "Roles and Permissions", subtitle: "Coming soon — RBAC not implemented" },
    organizations: { title: "Organizations", subtitle: "Coming soon — no tenant isolation yet" },
    plans: { title: "Subscription Plans", subtitle: "Coming soon — entitlements not implemented" },
    settings: { title: "Settings", subtitle: "Organization placeholder and accent colour" },
    audit: { title: "Audit Logs", subtitle: "Coming soon — audit collection not implemented" },
  };

  function setSessionChip(connected, username = "", authMethod = "") {
    state.authenticated = !!connected;
    state.authMethod = connected ? (authMethod || state.authMethod || "") : "";
    const methodLabel =
      state.authMethod === "oidc" ? "OIDC" : state.authMethod === "basic" ? "Basic" : "Auth";
    const chip = $("#sessionChip");
    if (chip) {
      chip.classList.toggle("on", !!connected);
      chip.textContent = connected
        ? `${methodLabel} session · ${username || "user"}`
        : "Session: disconnected";
    }
    const authChip = $("#authStatusChip");
    const authText = $("#authStatusText");
    if (authChip) authChip.classList.toggle("on", !!connected);
    if (authText) authText.textContent = connected ? "Authenticated" : "Disconnected";
    const nameEl = $("#userDisplayName");
    const avatar = $("#userAvatar");
    if (nameEl) nameEl.textContent = connected ? (username || "user") : "Not signed in";
    if (avatar) avatar.textContent = connected
      ? String(username || "U").trim().charAt(0).toUpperCase()
      : "?";
    const pill = $("#kpiConnPill");
    const sub = $("#kpiConnSub");
    if (pill) {
      pill.className = `status-pill ${connected ? "healthy" : "disconnected"}`;
      pill.textContent = connected ? "healthy" : "disconnected";
    }
    if (sub) {
      sub.textContent = connected
        ? `Authenticated via ${methodLabel} (single logical tenant — no org isolation yet)`
        : "Sign in with OIDC (or Basic if enabled) to load APIs";
    }
  }

  function applyInventoryTypeLock(componentType) {
    state.inventoryType = componentType || null;
    const filter = $("#filterType");
    const wrap = $("#filterTypeWrap");
    const hint = $("#inventoryTypeHint");
    const heading = $("#inventoryHeading");
    if (filter) {
      if (componentType) {
        filter.value = componentType;
        filter.disabled = true;
      } else {
        filter.disabled = false;
      }
    }
    if (wrap) wrap.classList.toggle("hidden", !!componentType);
    if (hint) {
      hint.classList.toggle("show", !!componentType);
      hint.textContent = componentType
        ? `Filtered inventory via /api/components?component_type=${componentType}. Separate OS Family / OS Version / Product Type / Product Version columns are preserved.`
        : "";
    }
    if (heading) {
      heading.textContent = componentType ? `${componentType} inventory` : "Inventory";
    }
  }

  function showLoginShell() {
    document.body.classList.add("is-login");
    document.body.classList.remove("is-app");
    $("#loginGate")?.classList.remove("hidden");
    $("#appShell")?.classList.add("hidden");
  }

  function showAppShell() {
    document.body.classList.remove("is-login");
    document.body.classList.add("is-app");
    $("#loginGate")?.classList.add("hidden");
    $("#appShell")?.classList.remove("hidden");
  }

  function logout() {
    sessionStorage.removeItem(STORAGE_KEY);
    setSessionChip(false);
    state.authenticated = false;
    $("#dashContent")?.classList.add("hidden");
    const loading = $("#dashLoading");
    if (loading) {
      loading.classList.remove("hidden");
      loading.innerHTML =
        "<strong>API disconnected</strong> Sign in to load live CMDB KPIs, relationships, and SIMULATED diagnostic widgets.";
    }
    if ($("#kpiComponents")) $("#kpiComponents").textContent = "—";
    if ($("#kpiRels")) $("#kpiRels").textContent = "—";
    showLoginShell();
    const logoutPath = authConfig.logout_path || "/auth/logout";
    // Clear server OIDC session cookie (and optional IdP end-session redirect).
    window.location.href = logoutPath;
  }

  function setGlobalLoading(show, text = "Working…") {
    const el = $("#globalLoading");
    if (!el) return;
    $("#globalLoadingText").textContent = text;
    el.classList.toggle("show", !!show);
  }

  function setOverlayLoading(sel, show) {
    const el = $(sel);
    if (!el) return;
    el.classList.toggle("show", !!show);
  }

  function emptyStateHtml(title, detail) {
    return `<tr><td colspan="99"><div class="empty-state"><strong>${escapeHtml(title)}</strong>${escapeHtml(detail)}</div></td></tr>`;
  }

  function renderCountList(sel, mapping) {
    const el = $(sel);
    el.innerHTML = "";
    const entries = Object.entries(mapping || {});
    if (!entries.length) {
      el.innerHTML = `<li><span>None yet</span><span class="count">0</span></li>`;
      return;
    }
    for (const [label, count] of entries) {
      const li = document.createElement("li");
      li.innerHTML = `<span>${escapeHtml(label)}</span><span class="count">${escapeHtml(count)}</span>`;
      el.appendChild(li);
    }
  }

  function renderDashTable(containerSel, rows, columns, emptyTitle) {
    const wrap = $(containerSel);
    if (!rows || !rows.length) {
      wrap.innerHTML = `<div class="empty-state"><strong>${escapeHtml(emptyTitle)}</strong>No records from the live API.</div>`;
      return;
    }
    const head = columns.map((c) => `<th>${escapeHtml(c.label)}</th>`).join("");
    const body = rows.map((row) => {
      const cells = columns.map((c) => {
        const val = typeof c.value === "function" ? c.value(row) : row[c.key];
        return `<td class="${c.mono ? "mono" : ""}">${escapeHtml(dash(val))}</td>`;
      }).join("");
      return `<tr>${cells}</tr>`;
    }).join("");
    wrap.innerHTML = `<div class="table-wrap" style="min-height:auto"><table class="dash-table-compact"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  async function loadDashboard() {
    const data = await api("/api/dashboard/summary?recent_limit=8");
    $("#dashLoading").classList.add("hidden");
    $("#dashContent").classList.remove("hidden");
    $("#dashTotalComponents").textContent = String(data.total_components ?? 0);
    $("#dashTotalRels").textContent = String(data.total_relationships ?? 0);
    if ($("#kpiComponents")) $("#kpiComponents").textContent = String(data.total_components ?? 0);
    if ($("#kpiRels")) $("#kpiRels").textContent = String(data.total_relationships ?? 0);
    renderCountList("#dashByType", data.components_by_type);
    renderCountList("#dashByEnv", data.components_by_environment);
    $("#dashDemoBanner").textContent =
      data.labels?.findings_banner ||
      "Diagnostic widgets reflect SIMULATED / SYNTHETIC_DEMO evidence only.";
    $("#dashHint").textContent = `Live aggregates · diagnostics mode ${data.labels?.diagnostics_mode || "SIMULATED"}`;

    renderDashTable(
      "#dashRecentDiags",
      data.recent_diagnostics || [],
      [
        { label: "ID", key: "diagnostic_id", mono: true },
        { label: "Component", value: (r) => r.component?.component_id },
        { label: "Profile", key: "profile_name" },
        { label: "Mode", key: "execution_mode" },
        { label: "Overall", value: (r) => r.summary?.overall_status },
        { label: "When", key: "timestamp" },
      ],
      "No recent diagnostics"
    );

    renderDashTable(
      "#dashRecentFindings",
      data.recent_findings || [],
      [
        { label: "Diagnostic", key: "diagnostic_id", mono: true },
        { label: "Component", key: "component_id", mono: true },
        { label: "Overall", key: "overall_status" },
        {
          label: "Non-ok checks",
          value: (r) => (r.non_ok_checks || []).map((c) => c.check_id).join(", ") || "—",
        },
        { label: "Mode", key: "execution_mode" },
      ],
      "No recent findings"
    );

    renderDashTable(
      "#dashCritical",
      data.critical_components_requiring_review || [],
      [
        { label: "Component", key: "component_id", mono: true },
        { label: "Name", key: "name" },
        { label: "Type", key: "component_type" },
        { label: "Env", key: "environment" },
        { label: "Status", key: "status" },
        {
          label: "Reasons",
          value: (r) => (r.reasons || []).join("; "),
        },
      ],
      "No components flagged for review"
    );
  }

  function authHeader() {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
      const { username, password } = JSON.parse(raw);
      if (!username || !password) return null;
      return "Basic " + btoa(`${username}:${password}`);
    } catch {
      return null;
    }
  }

  async function api(path, options = {}) {
    const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    const auth = authHeader();
    if (auth) headers.Authorization = auth;
    if (options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, { ...options, headers, credentials: "include" });
    let data = null;
    const text = await res.text();
    if (text) {
      try { data = JSON.parse(text); } catch { data = { detail: text }; }
    }
    if (!res.ok) {
      const detail = data?.error?.message || data?.detail || res.statusText;
      const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
      const err = new Error(msg);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function dash(value) {
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  }

  function statusClass(status) {
    if (status === "active") return "healthy";
    if (status === "inactive") return "warning";
    if (status === "decommissioned") return "critical";
    if (status === "unknown") return "disconnected";
    return "disconnected";
  }

  function saveAuthFromForm() {
    const username = $("#authUser").value.trim();
    const password = $("#authPass").value;
    if (!username || !password) {
      toast("Enter username and password", true);
      return false;
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ username, password }));
    return true;
  }

  function loadAuthIntoForm() {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const { username, password } = JSON.parse(raw);
      $("#authUser").value = username || "";
      $("#authPass").value = password || "";
    } catch { /* ignore */ }
  }

  async function afterAuthenticated(me, { toastMessage = "Connected" } = {}) {
    setSessionChip(true, me.username, me.auth_method || "");
    showAppShell();
    if (toastMessage) toast(toastMessage);
    await Promise.all([
      loadDashboard(),
      loadTypes(),
      loadCustomFields(),
      loadInventory(),
      loadRelationshipTypes(),
      loadRelationships(),
      refreshComponentIdList(),
      loadDiagnosticProfiles(),
      loadDiagnosticHistory(),
    ]);
    if ($("#depComponentId") && !$("#depComponentId").value && state.componentIds[0]) {
      $("#depComponentId").value = state.componentIds[0];
    }
    if ($("#diagComponentId") && !$("#diagComponentId").value && state.componentIds[0]) {
      $("#diagComponentId").value = state.componentIds[0];
    }
    showTab("dashboard");
  }

  async function connect() {
    if (!authConfig.basic_auth_enabled) {
      toast("HTTP Basic is disabled (BASIC_AUTH_ENABLED=false)", true);
      return;
    }
    if (!saveAuthFromForm()) return;
    setGlobalLoading(true, "Connecting…");
    try {
      const me = await api("/api/me");
      await afterAuthenticated(me);
    } catch (err) {
      setSessionChip(false);
      toast(err.message || "Auth failed", true);
    } finally {
      setGlobalLoading(false);
    }
  }

  async function tryResumeSession() {
    setGlobalLoading(true, "Checking session…");
    try {
      const me = await api("/api/me");
      await afterAuthenticated(me, { toastMessage: "Session restored" });
      return true;
    } catch (_) {
      setSessionChip(false);
      return false;
    } finally {
      setGlobalLoading(false);
    }
  }

  function applyAuthConfig(cfg) {
    authConfig.loaded = true;
    authConfig.basic_auth_enabled = !!cfg.basic_auth_enabled;
    authConfig.oidc_enabled = !!cfg.oidc_enabled;
    authConfig.login_path = cfg.login_path || "/auth/login";
    authConfig.logout_path = cfg.logout_path || "/auth/logout";
    authConfig.expected_origin = cfg.expected_origin || "";
    authConfig.host_matches_redirect = cfg.host_matches_redirect !== false;
    authConfig.host_hint = cfg.host_hint || "";
    authConfig.redirect_uri = cfg.redirect_uri || "";

    const hint = $("#authHint");
    const oidcRow = $("#oidcAuthRow");
    const basicRow = $("#basicAuthRow");
    const misconfigured = $("#authMisconfigured");
    const hostBanner = $("#hostMismatchBanner");

    if (hint) {
      if (cfg.oidc_enabled && cfg.basic_auth_enabled) {
        hint.textContent =
          "Sign in with SSO (OIDC) or use feature-flagged HTTP Basic for migration/testing.";
      } else if (cfg.oidc_enabled) {
        hint.textContent =
          "Sign in with your identity provider (OIDC). HTTP Basic is disabled.";
      } else if (cfg.basic_auth_enabled) {
        hint.textContent =
          "OIDC is disabled. Using feature-flagged HTTP Basic (migration/testing). Production-oriented default is BASIC_AUTH_ENABLED=false.";
      } else {
        hint.textContent = "No authentication method is currently enabled.";
      }
    }
    oidcRow?.classList.toggle("hidden", !cfg.oidc_enabled);
    basicRow?.classList.toggle("hidden", !cfg.basic_auth_enabled);
    misconfigured?.classList.toggle("hidden", !!(cfg.oidc_enabled || cfg.basic_auth_enabled));

    if (hostBanner) {
      if (cfg.oidc_enabled && cfg.host_matches_redirect === false && cfg.expected_origin) {
        hostBanner.classList.remove("hidden");
        hostBanner.innerHTML =
          `This page is opened as <code>${escapeHtml(window.location.host)}</code>, but ` +
          `<code>OIDC_REDIRECT_URI</code> expects <code>${escapeHtml(cfg.expected_origin)}</code>. ` +
          `${escapeHtml(cfg.host_hint || "")} ` +
          `<a href="${escapeHtml(cfg.expected_origin)}/">Continue on ${escapeHtml(cfg.expected_origin)}</a>`;
      } else {
        hostBanner.classList.add("hidden");
        hostBanner.innerHTML = "";
      }
    }
  }

  function showAuthErrorFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("auth_error");
    const banner = $("#authErrorBanner");
    if (!banner) return;
    if (!code) {
      banner.classList.add("hidden");
      banner.textContent = "";
      return;
    }
    banner.classList.remove("hidden");
    banner.textContent = AUTH_ERROR_MESSAGES[code] || `Sign-in failed (${code}).`;
    // Clean the query so refresh does not keep flashing the error.
    params.delete("auth_error");
    const next = `${window.location.pathname}${params.toString() ? `?${params}` : ""}${window.location.hash || ""}`;
    window.history.replaceState({}, "", next);
  }

  async function loadAuthConfig() {
    try {
      const cfg = await fetch("/api/auth/config", { credentials: "include", headers: { Accept: "application/json" } })
        .then((r) => r.json());
      applyAuthConfig(cfg);
    } catch (_) {
      applyAuthConfig({ basic_auth_enabled: false, oidc_enabled: false });
      toast("Could not load auth configuration", true);
    }
  }

  async function loadTypes() {
    const data = await api("/api/components/types");
    const selects = ["#filterType", "#fieldType", "#cfApplies"];
    for (const sel of selects) {
      const el = $(sel);
      if (!el) continue;
      const keepFirst = el.getAttribute("data-keep-first") === "1";
      const first = keepFirst ? el.options[0] : null;
      el.innerHTML = "";
      if (first) el.appendChild(first);
      for (const t of data.types) {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t;
        el.appendChild(opt);
      }
      if (sel === "#cfApplies") {
        const all = document.createElement("option");
        all.value = "*";
        all.textContent = "All types";
        el.insertBefore(all, el.firstChild);
        el.value = "*";
      }
    }
  }

  function queryParams() {
    const params = new URLSearchParams();
    const q = $("#searchQ").value.trim();
    const component_type = state.inventoryType || $("#filterType").value;
    const environment = $("#filterEnv").value.trim();
    const status = $("#filterStatus").value;
    if (q) params.set("q", q);
    if (component_type) params.set("component_type", component_type);
    if (environment) params.set("environment", environment);
    if (status) params.set("status", status);
    params.set("page", String(state.page));
    params.set("page_size", String(state.pageSize));
    params.set("sort_by", "updated_at");
    params.set("sort_dir", "desc");
    return params;
  }

  async function loadInventory() {
    setOverlayLoading("#inventoryLoading", true);
    try {
      const data = await api(`/api/components?${queryParams().toString()}`);
      state.totalPages = data.total_pages || 1;
      $("#pageInfo").textContent = `Page ${data.page} / ${state.totalPages || 1} · ${data.total} components`;
      $("#btnPrev").disabled = data.page <= 1;
      $("#btnNext").disabled = data.page >= (data.total_pages || 1);

      const tbody = $("#inventoryBody");
      tbody.innerHTML = "";
      const rows = data.inventory || [];
      if (!rows.length) {
        tbody.innerHTML = emptyStateHtml(
          "No components found",
          "Adjust filters or add a component to the CMDB inventory."
        );
        return;
      }
      for (const row of rows) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="mono">${escapeHtml(row.component_id)}</td>
          <td>${escapeHtml(row.hostname_or_name)}</td>
          <td>${escapeHtml(row.component_type)}</td>
          <td class="${row.os_family === "—" ? "dash" : ""}">${escapeHtml(row.os_family)}</td>
          <td class="${row.os_version === "—" ? "dash" : ""}">${escapeHtml(row.os_version)}</td>
          <td class="${row.product_type === "—" ? "dash" : ""}">${escapeHtml(row.product_type)}</td>
          <td class="${row.product_version === "—" ? "dash" : ""}">${escapeHtml(row.product_version)}</td>
          <td>${escapeHtml(row.environment)}</td>
          <td><span class="status-pill ${statusClass(row.status)}">${escapeHtml(row.status)}</span></td>
          <td class="actions">
            <button type="button" class="ghost" data-view="${escapeAttr(row.component_id)}">View</button>
            <button type="button" class="secondary" data-edit="${escapeAttr(row.component_id)}">Edit</button>
            <button type="button" class="danger" data-del="${escapeAttr(row.component_id)}">Delete</button>
          </td>`;
        tbody.appendChild(tr);
      }
    } finally {
      setOverlayLoading("#inventoryLoading", false);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll("'", "&#39;");
  }

  const TYPE_FIELDS = {
    Server: ["hostname", "ip_address", "os_family", "os_version"],
    Middleware: [
      "product_type", "product_version", "instance_name", "domain_name",
      "host_server_id", "listen_address", "listen_port", "installation_path",
      "domain_home", "log_folder_path",
    ],
    Database: [
      "product_type", "product_version", "instance_name", "endpoint",
      "listen_port", "cluster_or_replication_details", "log_folder_path",
    ],
    Network: ["device_name", "device_type", "management_ip", "virtual_ip", "listener_port"],
    Application: [
      "application_name", "application_type", "service_url",
      "business_criticality", "owner",
    ],
  };

  function renderTypeFields(componentType, values = {}) {
    const wrap = $("#typeFields");
    wrap.innerHTML = "";
    const fields = TYPE_FIELDS[componentType] || [];
    for (const key of fields) {
      const label = document.createElement("label");
      label.innerHTML = `${key.replaceAll("_", " ")}<input data-field="${key}" value="${escapeAttr(values[key] ?? "")}" />`;
      wrap.appendChild(label);
    }
  }

  function openModal(title) {
    $("#modalTitle").textContent = title;
    $("#componentModal").classList.add("open");
  }

  function closeModal() {
    $("#componentModal").classList.remove("open");
    state.editingId = null;
  }

  function openCreate() {
    state.editingId = null;
    $("#componentForm").reset();
    $("#fieldComponentId").disabled = false;
    const locked = state.inventoryType || "Server";
    $("#fieldType").disabled = !!state.inventoryType;
    $("#fieldType").value = locked;
    renderTypeFields(locked);
    renderCustomInputs(locked, {});
    openModal(state.inventoryType ? `Add ${state.inventoryType}` : "Add component");
  }

  async function openEdit(id, readOnly = false) {
    const doc = await api(`/api/components/${encodeURIComponent(id)}`);
    state.editingId = id;
    $("#fieldComponentId").value = doc.component_id;
    $("#fieldComponentId").disabled = true;
    $("#fieldType").value = doc.component_type;
    $("#fieldType").disabled = true;
    $("#fieldName").value = doc.name || "";
    $("#fieldEnv").value = doc.environment || "";
    $("#fieldStatus").value = doc.status || "active";
    renderTypeFields(doc.component_type, doc);
    renderCustomInputs(doc.component_type, doc.custom_fields || {});
    $$("#componentForm input, #componentForm select, #componentForm textarea").forEach((el) => {
      if (el.id === "fieldComponentId" || el.id === "fieldType") return;
      el.disabled = readOnly;
    });
    $("#btnSaveComponent").style.display = readOnly ? "none" : "inline-block";
    openModal(readOnly ? `View ${id}` : `Edit ${id}`);
  }

  function collectPayload() {
    const component_type = $("#fieldType").value;
    const payload = {
      name: $("#fieldName").value.trim(),
      environment: $("#fieldEnv").value.trim(),
      status: $("#fieldStatus").value,
      custom_fields: collectCustomValues(),
    };
    if (!state.editingId) {
      payload.component_type = component_type;
      const cid = $("#fieldComponentId").value.trim();
      if (cid) payload.component_id = cid;
    }
    for (const input of $$("#typeFields [data-field]")) {
      const key = input.getAttribute("data-field");
      let value = input.value.trim();
      if (value === "") {
        payload[key] = null;
        continue;
      }
      if (key.endsWith("_port") || key === "listen_port" || key === "listener_port") {
        payload[key] = Number(value);
      } else {
        payload[key] = value;
      }
    }
    return payload;
  }

  async function saveComponent(event) {
    event.preventDefault();
    const form = $("#componentForm");
    if (!form.checkValidity()) {
      form.reportValidity();
      toast("Fix highlighted form fields before saving", true);
      return;
    }
    try {
      const payload = collectPayload();
      if (!payload.name || !payload.environment || !payload.component_type) {
        toast("Name, environment, and component type are required", true);
        return;
      }
      // Validate numeric ports in type-specific fields
      for (const [key, value] of Object.entries(payload)) {
        if (
          (key.endsWith("_port") || key === "listen_port" || key === "listener_port") &&
          value !== null &&
          value !== undefined
        ) {
          if (!Number.isInteger(value) || value < 1 || value > 65535) {
            toast(`${key} must be an integer from 1 to 65535`, true);
            return;
          }
        }
      }
      if (state.editingId) {
        await api(`/api/components/${encodeURIComponent(state.editingId)}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast("Component updated");
      } else {
        await api("/api/components", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast("Component created");
      }
      closeModal();
      await loadInventory();
      await refreshComponentIdList();
      await loadRelationships();
      if (state.authenticated) {
        loadDashboard().catch(() => {});
      }
    } catch (err) {
      toast(err.message || "Save failed", true);
    }
  }

  async function beginDelete(id) {
    try {
      const preview = await api(`/api/components/${encodeURIComponent(id)}/delete-preview`);
      state.deleteTarget = id;
      $("#deleteMessage").textContent =
        `Delete component ${id} (${preview.component?.name || ""})? This cannot be undone.`;
      const warning = preview.relationship_warning || {};
      const box = $("#deleteWarn");
      box.style.display = "block";
      if (warning.has_relationships) {
        const ids = (warning.relationships || [])
          .map((r) => r.relationship_id)
          .filter(Boolean)
          .join(", ");
        box.textContent = warning.message + (ids ? ` Linked: ${ids}` : "");
      } else {
        box.textContent = warning.message;
      }
      $("#deleteModal").classList.add("open");
    } catch (err) {
      toast(err.message || "Delete preview failed", true);
    }
  }

  async function confirmDelete() {
    if (!state.deleteTarget) return;
    try {
      await api(
        `/api/components/${encodeURIComponent(state.deleteTarget)}?confirmed=true`,
        { method: "DELETE" }
      );
      toast(`Deleted ${state.deleteTarget}`);
      state.deleteTarget = null;
      $("#deleteModal").classList.remove("open");
      await loadInventory();
      await refreshComponentIdList();
      await loadRelationships();
      if (state.authenticated) {
        loadDashboard().catch(() => {});
      }
    } catch (err) {
      toast(err.message || "Delete failed", true);
    }
  }

  async function loadCustomFields() {
    const data = await api("/api/custom-fields");
    state.customFields = data.items || [];
    const tbody = $("#customFieldBody");
    tbody.innerHTML = "";
    if (!state.customFields.length) {
      tbody.innerHTML = emptyStateHtml(
        "No custom field definitions",
        "Add a definition above to extend inventory forms."
      );
      return;
    }
    for (const item of state.customFields) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(item.field_key)}</td>
        <td>${escapeHtml(item.label)}</td>
        <td>${escapeHtml(item.field_type)}</td>
        <td>${escapeHtml((item.applies_to || []).join(", "))}</td>
        <td>${item.required ? "yes" : "no"}</td>
        <td class="actions">
          <button type="button" class="danger" data-cf-del="${escapeAttr(item.field_key)}">Delete</button>
        </td>`;
      tbody.appendChild(tr);
    }
  }

  function renderCustomInputs(componentType, values) {
    const wrap = $("#customInputs");
    wrap.innerHTML = "";
    const applicable = state.customFields.filter(
      (f) => (f.applies_to || []).includes("*") || (f.applies_to || []).includes(componentType)
    );
    if (!applicable.length) {
      wrap.innerHTML = `<p class="hint">No custom fields configured for ${escapeHtml(componentType)}.</p>`;
      return;
    }
    for (const field of applicable) {
      const label = document.createElement("label");
      const val = values[field.field_key];
      if (field.field_type === "boolean") {
        label.innerHTML = `${escapeHtml(field.label)}
          <select data-cf="${escapeAttr(field.field_key)}">
            <option value="">—</option>
            <option value="true" ${val === true ? "selected" : ""}>true</option>
            <option value="false" ${val === false ? "selected" : ""}>false</option>
          </select>`;
      } else if (field.field_type === "enum") {
        const opts = (field.enum_values || [])
          .map((v) => `<option value="${escapeAttr(v)}" ${val === v ? "selected" : ""}>${escapeHtml(v)}</option>`)
          .join("");
        label.innerHTML = `${escapeHtml(field.label)}
          <select data-cf="${escapeAttr(field.field_key)}">
            <option value="">—</option>${opts}
          </select>`;
      } else {
        label.innerHTML = `${escapeHtml(field.label)}
          <input data-cf="${escapeAttr(field.field_key)}" value="${escapeAttr(val ?? "")}" />`;
      }
      wrap.appendChild(label);
    }
  }

  function collectCustomValues() {
    const out = {};
    for (const el of $$("[data-cf]")) {
      const key = el.getAttribute("data-cf");
      let value = el.value;
      if (value === "") continue;
      const def = state.customFields.find((f) => f.field_key === key);
      if (def?.field_type === "number") value = Number(value);
      if (def?.field_type === "boolean") value = value === "true";
      out[key] = value;
    }
    return out;
  }

  async function saveCustomField(event) {
    event.preventDefault();
    const applies = $("#cfApplies").value;
    const payload = {
      field_key: $("#cfKey").value.trim(),
      label: $("#cfLabel").value.trim(),
      field_type: $("#cfType").value,
      applies_to: [applies || "*"],
      required: $("#cfRequired").checked,
      enum_values: $("#cfEnum").value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    try {
      await api("/api/custom-fields", { method: "POST", body: JSON.stringify(payload) });
      toast("Custom field created");
      $("#customFieldForm").reset();
      $("#cfApplies").value = "*";
      await loadCustomFields();
    } catch (err) {
      toast(err.message || "Custom field save failed", true);
    }
  }

  function showTab(name) {
    const inventoryType = INVENTORY_TABS[name] || null;
    const panelName = inventoryType ? "inventory" : name;
    $$(".tab-panel").forEach((p) => p.classList.add("hidden"));
    $$(".nav-item").forEach((b) => b.classList.remove("active"));
    const panel = $(`#tab-${panelName}`);
    const btn = $(`.nav-item[data-tab="${name}"]`);
    if (!panel || !btn) return;
    panel.classList.remove("hidden");
    btn.classList.add("active");
    state.activeNav = name;
    applyInventoryTypeLock(inventoryType);
    const meta = PAGE_META[name] || { title: name, subtitle: "" };
    if ($("#pageTitle")) $("#pageTitle").textContent = meta.title;
    if ($("#pageSubtitle")) $("#pageSubtitle").textContent = meta.subtitle;
    $("#sidebar")?.classList.remove("open");
    if (name === "dashboard" && state.authenticated) {
      loadDashboard().catch((err) => toast(err.message || "Dashboard failed", true));
    }
    if ((inventoryType || name === "inventory") && state.authenticated) {
      state.page = 1;
      loadInventory().catch((err) => toast(err.message, true));
    }
    if (name === "relationships") {
      loadRelationships().catch((err) => toast(err.message, true));
    }
    if (name === "dependencies") {
      refreshComponentIdList().catch(() => {});
    }
    if (name === "diagnostics") {
      Promise.all([
        refreshComponentIdList(),
        loadDiagnosticProfiles(),
        loadDiagnosticHistory(),
        refreshOllamaStatus(),
      ]).catch((err) => toast(err.message, true));
    }
  }

  async function loadDiagnosticProfiles() {
    const data = await api("/api/diagnostics/profiles");
    $("#diagProfileNotice").textContent = data.notice || "";
    const sel = $("#diagProfile");
    sel.innerHTML = "";
    for (const profile of data.profiles || []) {
      const opt = document.createElement("option");
      opt.value = profile.profile_name;
      opt.textContent = `${profile.display_name || profile.profile_name} [${profile.execution_mode}]`;
      sel.appendChild(opt);
    }
  }

  function renderAnalysis(analysis) {
    const wrap = $("#diagAnalysis");
    if (!analysis) {
      wrap.innerHTML = `<p class="hint">No AI analysis yet.</p>`;
      return;
    }
    const obs = (analysis.observations_vs_hypotheses?.observations || analysis.observed_evidence || [])
      .map((x) => `<li>${escapeHtml(x)}</li>`)
      .join("");
    const hyp = (analysis.observations_vs_hypotheses?.hypotheses || analysis.potential_causes || [])
      .map((x) => `<li>${escapeHtml(x)}</li>`)
      .join("");
    const verify = (analysis.recommended_verification_steps || [])
      .map((x) => `<li>${escapeHtml(x)}</li>`)
      .join("");
    const rem = (analysis.suggested_remediation || [])
      .map((x) => `<li>${escapeHtml(x)}</li>`)
      .join("");
    wrap.innerHTML = `
      <div class="warn-box">${escapeHtml(analysis.labels?.banner || "")}</div>
      <p><strong>${escapeHtml(analysis.analysis_id)}</strong>
        · source ${escapeHtml(analysis.source)}
        · model ${escapeHtml(analysis.model || "—")}
        · evidence ${escapeHtml(analysis.evidence_label)}
        · confidence ${escapeHtml(analysis.confidence)}</p>
      <p>${escapeHtml(analysis.executive_summary)}</p>
      <p class="hint">Uncertainty: ${escapeHtml(analysis.uncertainty)}</p>
      <p class="hint">Potential dependency impact: ${escapeHtml(analysis.potential_dependency_impact)}</p>
      <h3 style="font-size:1rem;margin:10px 0 4px">Observations</h3>
      <ul>${obs || "<li>None</li>"}</ul>
      <h3 style="font-size:1rem;margin:10px 0 4px">Hypotheses</h3>
      <ul>${hyp || "<li>None</li>"}</ul>
      <h3 style="font-size:1rem;margin:10px 0 4px">Recommended verification (manual)</h3>
      <ul>${verify || "<li>None</li>"}</ul>
      <h3 style="font-size:1rem;margin:10px 0 4px">Suggested remediation (not executed)</h3>
      <ul>${rem || "<li>None</li>"}</ul>
      ${analysis.fallback_reason ? `<p class="hint">Fallback reason: ${escapeHtml(analysis.fallback_reason)}</p>` : ""}`;
  }

  function renderDiagnosticResult(doc) {
    if (!doc) {
      $("#diagLatest").innerHTML = `<div class="empty-state"><strong>No diagnostic selected</strong>Run or open a SIMULATED diagnostic.</div>`;
      $("#diagChecksBody").innerHTML = emptyStateHtml("No checks", "Checks appear after a diagnostic run.");
      renderAnalysis(null);
      return;
    }
    state.currentDiagnosticId = doc.diagnostic_id;
    const c = doc.component || {};
    $("#diagLatest").innerHTML = `
      <div class="demo-banner">${escapeHtml(doc.labels?.banner || "SIMULATED / SYNTHETIC_DEMO — not live telemetry")}</div>
      <div style="margin-top:8px">
        <strong class="mono">${escapeHtml(doc.diagnostic_id)}</strong>
        · mode <strong>${escapeHtml(doc.execution_mode)}</strong>
        · profile ${escapeHtml(doc.profile_name)}
        · component <span class="mono">${escapeHtml(doc.component_id)}</span>
        (${escapeHtml(c.component_type || "")} / ${escapeHtml(c.name || "")})
        · ${escapeHtml(doc.timestamp || "")}
      </div>
      <div class="hint">Upstream deps: ${escapeHtml((doc.dependency_context?.upstream_direct || []).length)}
        · Downstream deps: ${escapeHtml((doc.dependency_context?.downstream_direct || []).length)}</div>`;

    const tbody = $("#diagChecksBody");
    tbody.innerHTML = "";
    const checks = doc.checks || [];
    if (!checks.length) {
      tbody.innerHTML = emptyStateHtml("No checks", "This diagnostic record has no check rows.");
    } else {
      for (const check of checks) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${escapeHtml(check.label)}</td>
          <td>${escapeHtml(check.metric_kind)}</td>
          <td class="mono">${escapeHtml(check.value)}</td>
          <td>${escapeHtml(check.unit)}</td>
          <td>${escapeHtml(check.status)}</td>
          <td><strong>${escapeHtml(check.data_source)}</strong></td>
          <td class="hint">${escapeHtml(check.note)}</td>`;
        tbody.appendChild(tr);
      }
    }
    renderAnalysis(doc.ai_analysis || null);
  }

  async function refreshOllamaStatus() {
    try {
      const status = await api("/api/diagnostics/ollama/status");
      if (status.ok) {
        $("#ollamaStatusHint").textContent =
          `Ollama reachable at configured URL. Model=${status.configured_model}; present=${status.model_present}.`;
      } else {
        $("#ollamaStatusHint").textContent =
          `Ollama unavailable (${status.error || "error"}). Analysis will use rule-based fallback.`;
      }
    } catch (err) {
      $("#ollamaStatusHint").textContent = `Ollama status check failed: ${err.message}`;
    }
  }

  async function analyzeCurrentDiagnostic(forceFallback) {
    if (!state.currentDiagnosticId) {
      toast("Run or open a diagnostic first", true);
      return;
    }
    const doc = await api(
      `/api/diagnostics/${encodeURIComponent(state.currentDiagnosticId)}/analyze`,
      {
        method: "POST",
        body: JSON.stringify({ force_fallback: !!forceFallback }),
      }
    );
    toast(
      doc.ai_analysis?.source === "ollama"
        ? "Ollama analysis stored"
        : "Rule-based fallback analysis stored"
    );
    renderDiagnosticResult(doc);
    await loadDiagnosticHistory();
  }

  async function loadDiagnosticHistory() {
    const data = await api("/api/diagnostics?page=1&page_size=25");
    const tbody = $("#diagHistoryBody");
    tbody.innerHTML = "";
    const items = data.items || [];
    if (!items.length) {
      tbody.innerHTML = emptyStateHtml(
        "No diagnostic history",
        "Run a SIMULATED diagnostic to populate history."
      );
      return;
    }
    for (const item of items) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(item.diagnostic_id)}</td>
        <td>${escapeHtml(item.timestamp)}</td>
        <td class="mono">${escapeHtml(item.component_id)}</td>
        <td>${escapeHtml(item.profile_name)}</td>
        <td><strong>${escapeHtml(item.execution_mode)}</strong></td>
        <td>${escapeHtml(item.summary?.overall_status || "—")}</td>
        <td class="actions">
          <button type="button" class="ghost" data-diag-view="${escapeAttr(item.diagnostic_id)}">View</button>
        </td>`;
      tbody.appendChild(tr);
    }
  }

  async function runDiagnostic() {
    const component_id = $("#diagComponentId").value.trim();
    const profile_name = $("#diagProfile").value;
    if (!component_id || !profile_name) {
      toast("Component ID and profile are required", true);
      return;
    }
    const payload = {
      component_id,
      profile_name,
      notes: $("#diagNotes").value.trim() || null,
    };
    const result = await api("/api/diagnostics", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    toast(`Simulated diagnostic ${result.diagnostic_id} saved`);
    renderDiagnosticResult(result);
    await loadDiagnosticHistory();
  }

  function renderDepRows(tbodySel, rows) {
    const tbody = $(tbodySel);
    tbody.innerHTML = "";
    if (!rows || !rows.length) {
      tbody.innerHTML = emptyStateHtml("No rows", "No dependencies in this direction for the selected component.");
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(row.component_id)}</td>
        <td>${escapeHtml(row.name)}</td>
        <td>${escapeHtml(row.component_type)}</td>
        <td>${escapeHtml(row.direct_or_indirect)}</td>
        <td>${escapeHtml(row.relationship_type)}</td>
        <td class="${row.protocol === "—" ? "dash" : ""}">${escapeHtml(row.protocol)}</td>
        <td class="mono ${row.source_port === "—" ? "dash" : ""}">${escapeHtml(row.source_port)}</td>
        <td class="mono ${row.target_port === "—" ? "dash" : ""}">${escapeHtml(row.target_port)}</td>
        <td>${escapeHtml(row.verification_status)}</td>
        <td>${escapeHtml(row.evidence_or_notes)}</td>`;
      tbody.appendChild(tr);
    }
  }

  function renderImpact(apps, disclaimer) {
    if (disclaimer) $("#impactDisclaimer").textContent = disclaimer;
    const wrap = $("#depImpactList");
    if (!apps || !apps.length) {
      wrap.innerHTML = `<p class="hint">No potentially affected applications in scope.</p>`;
      return;
    }
    wrap.innerHTML = apps
      .map((app) => {
        const c = app.component || {};
        const paths = (app.connecting_paths || [])
          .map((p) => `<li>${escapeHtml((p.component_ids || []).join(" → "))}</li>`)
          .join("");
        return `<div class="impact-card">
          <div><strong>${escapeHtml(c.component_id)}</strong> — ${escapeHtml(c.name || "")}
            (${escapeHtml(app.direct_or_indirect)}, depth ${escapeHtml(app.depth)})</div>
          <div class="hint">${escapeHtml(app.note || "")}</div>
          <ul class="paths">${paths || "<li>No path details</li>"}</ul>
        </div>`;
      })
      .join("");
  }

  function renderGraph(graph, cycles) {
    const svg = $("#depGraph");
    const nodes = graph?.nodes || [];
    const edges = graph?.edges || [];
    svg.innerHTML = "";
    if (!nodes.length) {
      svg.setAttribute("viewBox", "0 0 640 200");
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", "24");
      t.setAttribute("y", "40");
      t.setAttribute("fill", "#5a6e68");
      t.textContent = "No graph data";
      svg.appendChild(t);
      return;
    }

    const selected = nodes.find((n) => n.is_selected || (n.roles || []).includes("selected"));
    const upstream = nodes.filter((n) => (n.roles || []).includes("upstream") && !n.is_selected);
    const downstream = nodes.filter((n) => (n.roles || []).includes("downstream") && !n.is_selected);
    const both = nodes.filter(
      (n) =>
        (n.roles || []).includes("upstream") &&
        (n.roles || []).includes("downstream") &&
        !n.is_selected
    );

    const positions = {};
    const colW = 210;
    const rowH = 56;
    const leftX = 80;
    const midX = 320;
    const rightX = 560;
    const height = Math.max(220, (Math.max(upstream.length, downstream.length, 1) + 1) * rowH + 40);
    svg.setAttribute("viewBox", `0 0 640 ${height}`);

    function placeColumn(list, x, startY) {
      list.forEach((n, i) => {
        positions[n.component_id] = { x, y: startY + i * rowH };
      });
    }
    placeColumn(upstream, leftX, 50);
    placeColumn(both.length ? both : [], midX, height / 2);
    if (selected) positions[selected.component_id] = { x: midX, y: 40 };
    placeColumn(
      downstream.filter((n) => !(n.roles || []).includes("upstream")),
      rightX,
      50
    );

    // Ensure every node has a position
    let orphanY = height - 40;
    for (const n of nodes) {
      if (!positions[n.component_id]) {
        positions[n.component_id] = { x: midX, y: orphanY };
        orphanY -= rowH;
      }
    }

    const cycleEdgeIds = new Set();
    for (const cycle of cycles || []) {
      for (const rid of cycle.relationship_ids || []) cycleEdgeIds.add(rid);
    }

    for (const edge of edges) {
      const a = positions[edge.source_component_id];
      const b = positions[edge.target_component_id];
      if (!a || !b) continue;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", a.x);
      line.setAttribute("y1", a.y);
      line.setAttribute("x2", b.x);
      line.setAttribute("y2", b.y);
      line.setAttribute(
        "class",
        cycleEdgeIds.has(edge.relationship_id) ? "edge edge-cycle" : "edge"
      );
      svg.appendChild(line);
    }

    for (const n of nodes) {
      const pos = positions[n.component_id];
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", pos.x);
      circle.setAttribute("cy", pos.y);
      circle.setAttribute("r", 18);
      let cls = "node-upstream";
      if (n.is_selected || (n.roles || []).includes("selected")) cls = "node-selected";
      else if ((n.roles || []).includes("upstream") && (n.roles || []).includes("downstream"))
        cls = "node-both";
      else if ((n.roles || []).includes("downstream")) cls = "node-downstream";
      circle.setAttribute("class", cls);
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", pos.x);
      label.setAttribute("y", pos.y + 32);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", "#1E293B");
      label.textContent = n.component_id;
      g.appendChild(circle);
      g.appendChild(label);
      svg.appendChild(g);
    }

    const box = $("#depCycles");
    if (cycles && cycles.length) {
      box.style.display = "block";
      box.textContent =
        "Cycles detected: " +
        cycles.map((c) => (c.component_ids || []).join(" → ")).join(" | ");
    } else {
      box.style.display = "none";
    }
  }

  async function analyzeDependencies() {
    const componentId = $("#depComponentId").value.trim();
    if (!componentId) {
      toast("Enter a component ID", true);
      return;
    }
    const depth = Number($("#depDepth").value || 5);
    const params = new URLSearchParams({ depth: String(depth) });
    const env = $("#depEnv").value.trim();
    const status = $("#depStatus").value;
    if (env) params.set("environment", env);
    if (status) params.set("status", status);
    const data = await api(
      `/api/dependencies/${encodeURIComponent(componentId)}?${params.toString()}`
    );
    const selected = data.selected || {};
    $("#depSelected").innerHTML = `
      <div><strong class="mono">${escapeHtml(selected.component_id || "")}</strong>
      — ${escapeHtml(selected.name || "")}
      (${escapeHtml(selected.component_type || "")},
      env ${escapeHtml(selected.environment || "—")},
      status ${escapeHtml(selected.status || "—")})</div>`;
    renderDepRows("#depUpstreamBody", data.upstream?.rows || []);
    renderDepRows("#depDownstreamBody", data.downstream?.rows || []);
    renderImpact(
      data.impact?.potentially_affected_applications || [],
      data.disclaimer || data.impact?.disclaimer
    );
    renderGraph(data.graph || {}, data.cycles_detected || []);
    if ((data.missing_components || []).length) {
      toast(`Missing related components: ${data.missing_components.join(", ")}`, true);
    }
  }

  async function refreshComponentIdList() {
    const data = await api("/api/components?page=1&page_size=200");
    state.componentIds = (data.items || []).map((c) => c.component_id);
    const list = $("#componentIdList");
    if (!list) return;
    list.innerHTML = state.componentIds
      .map((id) => `<option value="${escapeAttr(id)}"></option>`)
      .join("");
  }

  async function loadRelationshipTypes() {
    const data = await api("/api/relationships/types");
    state.relTypes = data.types || [];
    const docs = $("#relTypeDocs");
    docs.innerHTML = state.relTypes
      .map(
        (t) =>
          `<div><strong>${escapeHtml(t.relationship_type)}</strong> — ${escapeHtml(t.direction)}: ${escapeHtml(t.meaning)} <em>(${escapeHtml(t.example)})</em></div>`
      )
      .join("");
    for (const sel of ["#relFilterType", "#relType"]) {
      const el = $(sel);
      if (!el) continue;
      const keepFirst = el.getAttribute("data-keep-first") === "1";
      const first = keepFirst ? el.options[0] : null;
      el.innerHTML = "";
      if (first) el.appendChild(first);
      for (const t of state.relTypes) {
        const opt = document.createElement("option");
        opt.value = t.relationship_type;
        opt.textContent = t.relationship_type;
        el.appendChild(opt);
      }
    }
    updateRelTypeHint();
  }

  function updateRelTypeHint() {
    const type = $("#relType")?.value;
    const meta = state.relTypes.find((t) => t.relationship_type === type);
    $("#relTypeHint").textContent = meta
      ? `${meta.relationship_type}: ${meta.direction} — ${meta.meaning}`
      : "";
  }

  function relQueryParams() {
    const params = new URLSearchParams();
    const q = $("#relSearchQ").value.trim();
    const relationship_type = $("#relFilterType").value;
    const component_id = $("#relFilterComponent").value.trim();
    if (q) params.set("q", q);
    if (relationship_type) params.set("relationship_type", relationship_type);
    if (component_id) params.set("component_id", component_id);
    params.set("page", String(state.relPage));
    params.set("page_size", String(state.pageSize));
    return params;
  }

  async function loadRelationships() {
    const data = await api(`/api/relationships?${relQueryParams().toString()}`);
    state.relTotalPages = data.total_pages || 1;
    $("#relPageInfo").textContent =
      `Page ${data.page} / ${state.relTotalPages || 1} · ${data.total} relationships`;
    $("#btnRelPrev").disabled = data.page <= 1;
    $("#btnRelNext").disabled = data.page >= (data.total_pages || 1);
    const tbody = $("#relationshipBody");
    tbody.innerHTML = "";
    const rows = data.rows || [];
    if (!rows.length) {
      tbody.innerHTML = emptyStateHtml(
        "No relationships found",
        "Add a relationship or clear filters. Protocol / Source Port / Target Port stay separate columns."
      );
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(row.relationship_id)}</td>
        <td class="mono">${escapeHtml(row.source_component_id)}</td>
        <td class="mono">${escapeHtml(row.target_component_id)}</td>
        <td>${escapeHtml(row.relationship_type)}</td>
        <td class="${row.protocol === "—" ? "dash" : ""}">${escapeHtml(row.protocol)}</td>
        <td class="mono ${row.source_port === "—" ? "dash" : ""}">${escapeHtml(row.source_port)}</td>
        <td class="mono ${row.target_port === "—" ? "dash" : ""}">${escapeHtml(row.target_port)}</td>
        <td>${escapeHtml(row.environment)}</td>
        <td>${escapeHtml(row.discovery_method)}</td>
        <td>${escapeHtml(row.verification_status)}</td>
        <td class="actions">
          <button type="button" class="secondary" data-rel-edit="${escapeAttr(row.relationship_id)}">Edit</button>
          <button type="button" class="danger" data-rel-del="${escapeAttr(row.relationship_id)}">Delete</button>
        </td>`;
      tbody.appendChild(tr);
    }
  }

  function parseOptionalPort(raw) {
    const value = String(raw ?? "").trim();
    if (!value) return null;
    if (!/^\d+$/.test(value)) {
      throw new Error("Ports must be integers from 1 to 65535 (or blank)");
    }
    const num = Number(value);
    if (!Number.isInteger(num) || num < 1 || num > 65535) {
      throw new Error("Ports must be integers from 1 to 65535 (or blank)");
    }
    return num;
  }

  function openRelCreate() {
    state.editingRelId = null;
    $("#relationshipForm").reset();
    $("#relId").disabled = false;
    $("#relConfidence").value = "medium";
    $("#relDiscovery").value = "manually_configured";
    $("#relVerification").value = "unverified";
    $("#relEnvWarn").style.display = "none";
    if ($("#relType").options.length) $("#relType").selectedIndex = 0;
    updateRelTypeHint();
    $("#relModalTitle").textContent = "Add relationship";
    $("#relationshipModal").classList.add("open");
  }

  async function openRelEdit(id) {
    const doc = await api(`/api/relationships/${encodeURIComponent(id)}`);
    state.editingRelId = id;
    $("#relId").value = doc.relationship_id;
    $("#relId").disabled = true;
    $("#relType").value = doc.relationship_type;
    $("#relSource").value = doc.source_component_id;
    $("#relTarget").value = doc.target_component_id;
    $("#relProtocol").value = doc.protocol || "";
    $("#relSourcePort").value = doc.source_port ?? "";
    $("#relTargetPort").value = doc.target_port ?? "";
    $("#relUrl").value = doc.url_or_path || "";
    $("#relEnv").value = doc.environment || "";
    $("#relDiscovery").value = doc.discovery_method || "manually_configured";
    $("#relVerification").value = doc.verification_status || "unverified";
    $("#relConfidence").value = doc.confidence || "medium";
    $("#relNotes").value = doc.evidence_or_notes || "";
    $("#relEnvWarn").style.display = "none";
    updateRelTypeHint();
    $("#relModalTitle").textContent = `Edit ${id}`;
    $("#relationshipModal").classList.add("open");
  }

  function collectRelPayload() {
    const payload = {
      source_component_id: $("#relSource").value.trim(),
      target_component_id: $("#relTarget").value.trim(),
      relationship_type: $("#relType").value,
      protocol: $("#relProtocol").value.trim() || null,
      source_port: parseOptionalPort($("#relSourcePort").value),
      target_port: parseOptionalPort($("#relTargetPort").value),
      url_or_path: $("#relUrl").value.trim() || null,
      environment: $("#relEnv").value.trim() || null,
      discovery_method: $("#relDiscovery").value,
      verification_status: $("#relVerification").value,
      confidence: $("#relConfidence").value,
      evidence_or_notes: $("#relNotes").value.trim() || null,
    };
    if (!state.editingRelId) {
      const rid = $("#relId").value.trim();
      if (rid) payload.relationship_id = rid;
    }
    return payload;
  }

  function showRelWarnings(result) {
    const box = $("#relEnvWarn");
    const warnings = result?.warnings || [];
    if (!warnings.length) {
      box.style.display = "none";
      return;
    }
    box.style.display = "block";
    box.textContent = warnings
      .flatMap((w) => w.messages || [w.message || JSON.stringify(w)])
      .join(" ");
  }

  async function saveRelationship(event) {
    event.preventDefault();
    const form = $("#relationshipForm");
    if (!form.checkValidity()) {
      form.reportValidity();
      toast("Fix highlighted relationship fields before saving", true);
      return;
    }
    try {
      const payload = collectRelPayload();
      if (!payload.source_component_id || !payload.target_component_id) {
        toast("Source and target component IDs are required", true);
        return;
      }
      if (payload.source_component_id === payload.target_component_id) {
        toast("Source and target cannot be the same component", true);
        return;
      }
      let result;
      if (state.editingRelId) {
        result = await api(`/api/relationships/${encodeURIComponent(state.editingRelId)}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast("Relationship updated");
      } else {
        result = await api("/api/relationships", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast("Relationship created");
      }
      showRelWarnings(result);
      if (!(result.warnings || []).length) {
        $("#relationshipModal").classList.remove("open");
        state.editingRelId = null;
      }
      await loadRelationships();
      if (state.authenticated) {
        loadDashboard().catch(() => {});
      }
    } catch (err) {
      toast(err.message || "Relationship save failed", true);
    }
  }

  function wireEvents() {
    $("#btnConnect")?.addEventListener("click", connect);
    $("#btnOidcLogin")?.addEventListener("click", () => {
      if (!authConfig.oidc_enabled) {
        toast("OIDC is disabled", true);
        return;
      }
      // Prefer expected_origin so login/state cookies land on the redirect host.
      const path = authConfig.login_path || "/auth/login";
      if (authConfig.expected_origin && authConfig.host_matches_redirect === false) {
        window.location.href = `${authConfig.expected_origin}${path}`;
        return;
      }
      window.location.href = path;
    });
    $("#btnLogout")?.addEventListener("click", logout);
    $("#btnMobileNav")?.addEventListener("click", () => {
      $("#sidebar")?.classList.toggle("open");
    });
    $("#tenantSwitcher")?.addEventListener("click", () => {
      toast("Organization switching is a visual placeholder — not functional yet", true);
    });
    $("#btnRefreshDash")?.addEventListener("click", async () => {
      if (!state.authenticated) {
        toast("Connect first", true);
        return;
      }
      setGlobalLoading(true, "Refreshing dashboard…");
      try {
        await loadDashboard();
        toast("Dashboard refreshed");
      } catch (err) {
        toast(err.message || "Dashboard refresh failed", true);
      } finally {
        setGlobalLoading(false);
      }
    });
    $("#btnSearch").addEventListener("click", async () => {
      state.page = 1;
      try { await loadInventory(); } catch (err) { toast(err.message, true); }
    });
    $("#btnAdd").addEventListener("click", () => {
      try { openCreate(); } catch (err) { toast(err.message, true); }
    });
    $("#btnPrev").addEventListener("click", async () => {
      state.page = Math.max(1, state.page - 1);
      await loadInventory();
    });
    $("#btnNext").addEventListener("click", async () => {
      state.page = Math.min(state.totalPages || 1, state.page + 1);
      await loadInventory();
    });
    $("#fieldType").addEventListener("change", (e) => {
      renderTypeFields(e.target.value);
      renderCustomInputs(e.target.value, {});
    });
    $("#componentForm").addEventListener("submit", saveComponent);
    $("#btnCloseModal").addEventListener("click", closeModal);
    $("#btnCancelDelete").addEventListener("click", () => {
      $("#deleteModal").classList.remove("open");
      state.deleteTarget = null;
    });
    $("#btnConfirmDelete").addEventListener("click", confirmDelete);
    $("#customFieldForm").addEventListener("submit", saveCustomField);
    $("#btnAnalyzeDeps").addEventListener("click", async () => {
      try { await analyzeDependencies(); } catch (err) { toast(err.message, true); }
    });
    $("#btnRunDiag").addEventListener("click", async () => {
      try { await runDiagnostic(); } catch (err) { toast(err.message, true); }
    });
    $("#btnAnalyzeDiag").addEventListener("click", async () => {
      try { await analyzeCurrentDiagnostic(false); } catch (err) { toast(err.message, true); }
    });
    $("#btnAnalyzeFallback").addEventListener("click", async () => {
      try { await analyzeCurrentDiagnostic(true); } catch (err) { toast(err.message, true); }
    });
    $("#btnRefreshDiagHistory").addEventListener("click", async () => {
      try { await loadDiagnosticHistory(); } catch (err) { toast(err.message, true); }
    });
    $("#diagHistoryBody").addEventListener("click", async (e) => {
      const id = e.target.getAttribute("data-diag-view");
      if (!id) return;
      try {
        const doc = await api(`/api/diagnostics/${encodeURIComponent(id)}`);
        renderDiagnosticResult(doc);
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnRelSearch").addEventListener("click", async () => {
      state.relPage = 1;
      try { await loadRelationships(); } catch (err) { toast(err.message, true); }
    });
    $("#btnAddRel").addEventListener("click", async () => {
      try {
        await refreshComponentIdList();
        openRelCreate();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnRelPrev").addEventListener("click", async () => {
      state.relPage = Math.max(1, state.relPage - 1);
      await loadRelationships();
    });
    $("#btnRelNext").addEventListener("click", async () => {
      state.relPage = Math.min(state.relTotalPages || 1, state.relPage + 1);
      await loadRelationships();
    });
    $("#relType").addEventListener("change", updateRelTypeHint);
    $("#relationshipForm").addEventListener("submit", saveRelationship);
    $("#btnCloseRelModal").addEventListener("click", () => {
      $("#relationshipModal").classList.remove("open");
      state.editingRelId = null;
    });
    $("#relationshipBody").addEventListener("click", async (e) => {
      const edit = e.target.getAttribute("data-rel-edit");
      const del = e.target.getAttribute("data-rel-del");
      try {
        if (edit) await openRelEdit(edit);
        if (del) {
          if (!confirm(`Delete relationship ${del}?`)) return;
          await api(`/api/relationships/${encodeURIComponent(del)}`, { method: "DELETE" });
          toast(`Deleted ${del}`);
          await loadRelationships();
        }
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#inventoryBody").addEventListener("click", async (e) => {
      const view = e.target.getAttribute("data-view");
      const edit = e.target.getAttribute("data-edit");
      const del = e.target.getAttribute("data-del");
      try {
        if (view) await openEdit(view, true);
        if (edit) await openEdit(edit, false);
        if (del) await beginDelete(del);
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#customFieldBody").addEventListener("click", async (e) => {
      const key = e.target.getAttribute("data-cf-del");
      if (!key) return;
      if (!confirm(`Delete custom field definition '${key}'?`)) return;
      try {
        await api(`/api/custom-fields/${encodeURIComponent(key)}`, { method: "DELETE" });
        toast("Custom field deleted");
        await loadCustomFields();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $$(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => showTab(btn.getAttribute("data-tab")));
    });
    $("#accentSelect")?.addEventListener("change", (e) => {
      applyAccent(e.target.value);
    });
    $$(".accent-swatch").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyAccent(btn.getAttribute("data-accent"));
      });
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    restoreAccent();
    loadAuthIntoForm();
    wireEvents();
    showLoginShell();
    setSessionChip(false);
    showAuthErrorFromQuery();
    await loadAuthConfig();
    // Resume OIDC cookie session or previously stored Basic credentials.
    const resumed = await tryResumeSession();
    if (!resumed && authHeader() && authConfig.basic_auth_enabled) {
      connect().catch(() => {});
    } else if (!resumed) {
      showLoginShell();
    }
  });
})();
