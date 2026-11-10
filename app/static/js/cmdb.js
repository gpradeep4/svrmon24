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
    editingCfKey: null,
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
    columnConfigs: {
      inventory: null,
      relationships: null,
    },
    columnEditor: {
      grid_key: "inventory",
      columns: [],
      is_default: true,
    },
    customTables: [],
    selectedCustomTableKey: null,
    editingCtKey: null,
    editingCcKey: null,
    customRecordPage: 1,
    customRecordTotalPages: 1,
    editingCustomRecordId: null,
    entityRefs: [],
    tenantId: "tenant-svrmon24-legacy",
    orgSwitcherEnabled: false,
    switchableForUser: false,
    isPlatformAdmin: false,
    membershipRole: null,
    effectiveRole: null,
    permissions: [],
    permissionCatalog: [],
    permissionMatrix: {},
    memberships: [],
    entitlements: null,
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

  function can(permission) {
    if (state.isPlatformAdmin) return true;
    return (state.permissions || []).includes(permission);
  }

  function setRbacControl(el, allowed, { titleWhenDenied } = {}) {
    if (!el) return;
    if (allowed) {
      el.disabled = false;
      el.removeAttribute("data-rbac-disabled");
      if (el.dataset.rbacTitleRestore) {
        el.title = el.dataset.rbacTitleRestore;
        delete el.dataset.rbacTitleRestore;
      }
    } else {
      if (!el.dataset.rbacTitleRestore) {
        el.dataset.rbacTitleRestore = el.title || "";
      }
      el.disabled = true;
      el.setAttribute("data-rbac-disabled", "true");
      el.title = titleWhenDenied || "Your role cannot perform this action";
    }
  }

  function applyPermissionGates() {
    const writeCmdb = can("cmdb:write");
    const writeRel = can("relationships:write");
    const runDiag = can("diagnostics:run");
    const writeConfig = can("config:write");
    const readAudit = can("audit:read");
    const readUsers = can("users:read");

    setRbacControl($("#btnAdd"), writeCmdb, {
      titleWhenDenied: "Requires cmdb:write (member+)",
    });
    setRbacControl($("#btnSaveComponent"), writeCmdb);
    setRbacControl($("#btnConfirmDelete"), writeCmdb);
    setRbacControl($("#btnAddRel"), writeRel, {
      titleWhenDenied: "Requires relationships:write (member+)",
    });
    setRbacControl($("#btnSaveRel"), writeRel);
    setRbacControl($("#btnAddCustomRecord"), writeCmdb);
    setRbacControl($("#btnSaveCustomRecord"), writeCmdb);
    setRbacControl($("#btnRunDiag"), runDiag, {
      titleWhenDenied: "Requires diagnostics:run (member+)",
    });
    setRbacControl($("#btnAnalyzeDiag"), runDiag);
    setRbacControl($("#btnAnalyzeFallback"), runDiag);
    setRbacControl($("#btnColSave"), writeConfig, {
      titleWhenDenied: "Requires config:write (admin+)",
    });
    setRbacControl($("#btnColReset"), writeConfig);
    setRbacControl($("#cfSubmitBtn"), writeConfig, {
      titleWhenDenied: "Requires config:write (admin+)",
    });
    setRbacControl($("#ctSubmitBtn"), writeConfig);
    setRbacControl($("#ccSubmitBtn"), writeConfig);
    setRbacControl($("#btnCtEditSelected"), writeConfig);
    setRbacControl($("#btnCtDelete"), writeConfig);
    setRbacControl($("#btnRefreshAudit"), readAudit);

    const auditNav = $(`.nav-item[data-tab="audit"]`);
    if (auditNav) {
      // Dim / mark Audit for viewers/members without audit:read (still openable → in-page explanation).
      const showAudit = !!readAudit;
      auditNav.classList.toggle("rbac-nav-denied", !showAudit);
      auditNav.setAttribute("aria-disabled", showAudit ? "false" : "true");
      auditNav.title = showAudit
        ? ""
        : "Requires audit:read (admin / owner / platform admin)";
    }
    const usersNav = $(`.nav-item[data-tab="users"]`);
    if (usersNav && !readUsers && !state.isPlatformAdmin) {
      // Users page still shows "my memberships"; keep reachable.
      usersNav.title = "Member list requires users:read";
    }
  }

  function renderRolesSignedOut() {
    const cta = $("#rbacSignInCta");
    const summary = $("#rbacCurrentSummary");
    const list = $("#rbacCurrentPerms");
    const head = $("#rbacMatrixHead");
    const body = $("#rbacMatrixBody");
    const permsBlock = $("#rbacPermsBlock");
    const matrixBlock = $("#rbacMatrixBlock");
    if (cta) cta.classList.remove("hidden");
    if (summary) {
      summary.classList.add("hidden");
      summary.textContent = "Sign in to load your role and permissions.";
    }
    if (permsBlock) permsBlock.classList.add("hidden");
    if (matrixBlock) matrixBlock.classList.add("hidden");
    if (list) list.innerHTML = `<li class="hint">Sign in to load.</li>`;
    if (head) head.innerHTML = `<tr><th>Permission</th></tr>`;
    if (body) {
      body.innerHTML =
        `<tr><td class="hint">Sign in to load the matrix.</td></tr>`;
    }
    const oidcBtn = $("#btnRbacOidcLogin");
    const basicBtn = $("#btnRbacBasicFocus");
    const hint = $("#rbacSignInHint");
    if (oidcBtn) {
      oidcBtn.classList.toggle("hidden", !authConfig.oidc_enabled);
      oidcBtn.disabled = !authConfig.oidc_enabled;
    }
    if (basicBtn) {
      basicBtn.classList.toggle("hidden", !authConfig.basic_auth_enabled);
      basicBtn.disabled = !authConfig.basic_auth_enabled;
    }
    if (hint) {
      if (authConfig.oidc_enabled && authConfig.basic_auth_enabled) {
        hint.textContent =
          "Use SSO (OIDC) or HTTP Basic (feature-flagged) from the sign-in screen.";
      } else if (authConfig.oidc_enabled) {
        hint.textContent = "Sign in with SSO (OIDC). HTTP Basic is disabled.";
      } else if (authConfig.basic_auth_enabled) {
        hint.textContent =
          "Sign in with HTTP Basic on the login screen (OIDC is disabled).";
      } else {
        hint.textContent =
          "No auth method is enabled on the server. Configure OIDC or Basic.";
      }
    }
  }

  function renderRolesSignedInShell() {
    $("#rbacSignInCta")?.classList.add("hidden");
    $("#rbacCurrentSummary")?.classList.remove("hidden");
    $("#rbacPermsBlock")?.classList.remove("hidden");
    $("#rbacMatrixBlock")?.classList.remove("hidden");
  }

  function showAuditDenied(detail) {
    const denied = $("#auditDenied");
    const detailEl = $("#auditDeniedDetail");
    const wrap = $("#auditTableWrap");
    const toolbar = $("#auditToolbar");
    const hint = $("#auditHint");
    if (denied) denied.classList.remove("hidden");
    if (wrap) wrap.classList.add("hidden");
    if (toolbar) toolbar.classList.add("hidden");
    if (detailEl) {
      const role =
        state.membershipRole || state.effectiveRole || "unknown";
      detailEl.textContent =
        detail ||
        `Current role=${role}; platform_admin=${!!state.isPlatformAdmin}. ` +
          "audit:read is granted to admin, owner, and platform admin.";
    }
    if (hint) {
      hint.textContent =
        "Audit Logs are restricted. Promote to admin/owner to view tenant audit events.";
    }
  }

  function showAuditAllowed() {
    $("#auditDenied")?.classList.add("hidden");
    $("#auditTableWrap")?.classList.remove("hidden");
    $("#auditToolbar")?.classList.remove("hidden");
  }

  async function loadRolesPanel() {
    const summary = $("#rbacCurrentSummary");
    const list = $("#rbacCurrentPerms");
    const head = $("#rbacMatrixHead");
    const body = $("#rbacMatrixBody");
    if (!summary || !list || !head || !body) return;
    if (!state.authenticated) {
      renderRolesSignedOut();
      return;
    }
    renderRolesSignedInShell();
    try {
      const data = await api("/api/permissions");
      state.permissionCatalog = data.permissions || [];
      state.permissionMatrix = data.matrix || {};
      const current = data.current || {};
      state.permissions = current.permissions || state.permissions || [];
      state.membershipRole = current.membership_role || state.membershipRole;
      state.effectiveRole =
        current.effective_role || current.membership_role || state.effectiveRole;
      state.isPlatformAdmin = !!current.is_platform_admin || state.isPlatformAdmin;
      const roleLabel =
        current.effective_role || current.membership_role || "none";
      summary.textContent =
        `Effective role: ${roleLabel}` +
        (current.membership_role && current.membership_role !== current.effective_role
          ? ` (membership=${current.membership_role})`
          : "") +
        ` · platform_admin=${!!current.is_platform_admin}` +
        ` · auth=${current.auth_method || state.authMethod || "—"}` +
        ` · tenant=${current.tenant_id || state.tenantId}`;
      const perms = current.permissions || [];
      if (!perms.length) {
        list.innerHTML = `<li class="hint">No permissions in this tenant context.</li>`;
      } else {
        const labels = Object.fromEntries(
          (data.permissions || []).map((p) => [p.permission, p.description])
        );
        list.innerHTML = perms
          .map(
            (p) =>
              `<li><code>${escapeHtml(p)}</code> — ${escapeHtml(
                labels[p] || p
              )}</li>`
          )
          .join("");
      }
      const roles = data.roles || Object.keys(data.matrix || {});
      head.innerHTML = `<tr><th>Permission</th>${roles
        .map((r) => {
          const cls =
            r === (current.effective_role || current.membership_role)
              ? ' class="rbac-role-current"'
              : "";
          return `<th${cls}>${escapeHtml(r)}</th>`;
        })
        .join("")}</tr>`;
      const catalog = data.permissions || [];
      body.innerHTML = catalog
        .map((entry) => {
          const key = entry.permission;
          const cells = roles
            .map((role) => {
              const yes = (data.matrix[role] || []).includes(key);
              return `<td class="${yes ? "rbac-yes" : "rbac-no"}">${
                yes ? "✓" : "—"
              }</td>`;
            })
            .join("");
          return `<tr><td><code>${escapeHtml(key)}</code><div class="hint">${escapeHtml(
            entry.description || ""
          )}</div></td>${cells}</tr>`;
        })
        .join("");
      applyPermissionGates();
    } catch (err) {
      if (err.status === 401) {
        renderRolesSignedOut();
        return;
      }
      summary.textContent = err.message || "Failed to load permissions";
      list.innerHTML = `<li class="hint">Unavailable</li>`;
      body.innerHTML = `<tr><td class="hint">${escapeHtml(
        err.message || "Failed"
      )}</td></tr>`;
    }
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
    dependencies: { title: "Dependencies", subtitle: "Tenant-scoped graph wrap · CMDB + custom edges · potentially affected apps" },
    diagnostics: { title: "Diagnostics", subtitle: "DEMO / SIMULATED evidence only — no live probes" },
    custom: { title: "Custom Fields", subtitle: "Extend inventory forms with typed definitions" },
    "custom-tables": {
      title: "Custom Tables",
      subtitle: "Define tenant-scoped entity tables, columns, and references",
    },
    "custom-records": {
      title: "Custom records",
      subtitle: "Browse and edit rows for a custom entity table",
    },
    columns: { title: "Column Settings", subtitle: "Tenant-scoped grid visibility, order, width, and pin" },
    users: { title: "Users", subtitle: "Memberships, invites, and org members" },
    roles: {
      title: "Roles and Permissions",
      subtitle: "Live RBAC role, permissions, and matrix (viewer / member / admin / owner)",
    },
    organizations: { title: "Organizations", subtitle: "Membership orgs + isolation; switcher in Settings" },
    plans: { title: "Subscription Plans", subtitle: "Entitlements-only plan catalog (no payment provider)" },
    settings: { title: "Settings", subtitle: "Organization switcher and accent colour" },
    audit: {
      title: "Audit Logs",
      subtitle: "Tenant-scoped audit_events for mutating admin / CMDB actions",
    },
  };

  function setTenantBanner(connected, tenantName = "", tenantId = "") {
    const banner = $("#tenantBanner");
    const nameEl = $("#tenantDisplayName");
    const idEl = $("#tenantIdSub");
    const displayName = tenantName || "SVRMON24 Legacy";
    const stableId = tenantId || "tenant-svrmon24-legacy";
    if (nameEl) nameEl.textContent = connected ? displayName : "—";
    if (idEl) idEl.textContent = connected ? stableId : "—";
    if (banner) {
      banner.hidden = !connected;
      banner.title = connected ? stableId : "";
      banner.setAttribute(
        "aria-label",
        connected ? `Current organization: ${displayName}` : "Current organization"
      );
    }
  }

  function setSessionChip(connected, username = "", authMethod = "", tenant = null) {
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
    const tenantName =
      (tenant && tenant.display_name) ||
      (tenant && tenant.current_tenant_display_name) ||
      "SVRMON24 Legacy";
    const tenantId =
      (tenant && tenant.tenant_id) ||
      (tenant && tenant.current_tenant_id) ||
      "tenant-svrmon24-legacy";
    if (sub) {
      sub.textContent = connected
        ? `Authenticated via ${methodLabel} · ${tenantName} (tenant isolation on)`
        : "Sign in with OIDC (or Basic if enabled) to load APIs";
    }
    setTenantBanner(connected, connected ? tenantName : "", connected ? tenantId : "");
  }

  function renderMembershipTables(mem) {
    const body = $("#myMembershipsBody");
    if (body) {
      const items = (mem && mem.items) || [];
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="4" class="hint">${escapeHtml(
            (mem && mem.notes) || "No memberships for this session."
          )}</td></tr>`;
      } else {
        body.innerHTML = items
          .map((m) => {
            const current =
              m.tenant_id === state.tenantId
                ? ' <span class="badge-soon">current</span>'
                : "";
            return `<tr>
              <td>${escapeHtml(m.tenant_display_name || m.tenant_id || "")}${current}</td>
              <td><code>${escapeHtml(m.tenant_id || "")}</code></td>
              <td>${escapeHtml(m.role || "")}</td>
              <td>${escapeHtml(m.plan_code || "—")}</td>
            </tr>`;
          })
          .join("");
      }
    }
  }

  async function loadAuditEvents() {
    const body = $("#auditBody");
    const hint = $("#auditHint");
    if (!body) return;
    if (!state.authenticated) {
      showAuditDenied("Sign in first. Audit Logs require audit:read.");
      body.innerHTML =
        `<tr><td colspan="6" class="hint">Sign in to load audit events.</td></tr>`;
      return { denied: true };
    }
    if (!can("audit:read")) {
      showAuditDenied();
      body.innerHTML =
        `<tr><td colspan="6" class="hint">Permission audit:read required (admin / owner).</td></tr>`;
      return { denied: true };
    }
    showAuditAllowed();
    const action = ($("#auditActionFilter")?.value || "").trim();
    const qs = new URLSearchParams({ page: "1", page_size: "50" });
    if (action) qs.set("action", action);
    try {
      const data = await api(`/api/audit-events?${qs.toString()}`);
      if (hint) {
        hint.textContent =
          `${data.total || 0} event(s) for ${data.tenant_id || state.tenantId} ` +
          `(collection ${data.collection || "audit_events"}). Requires audit:read.`;
      }
      const items = data.items || [];
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="6" class="hint">No audit events yet for this tenant.</td></tr>`;
        return data;
      }
      body.innerHTML = items
        .map((ev) => {
          const actor = ev.actor || {};
          const actorLabel =
            actor.username || actor.user_id || actor.email || "—";
          const when = ev.timestamp
            ? String(ev.timestamp).replace("T", " ").replace(/\.\d+.*/, "")
            : "—";
          const resource = ev.resource_id
            ? `${ev.resource_type || ""}:${ev.resource_id}`
            : ev.resource_type || "—";
          return `<tr>
            <td>${escapeHtml(when)}</td>
            <td><code>${escapeHtml(ev.action || "")}</code></td>
            <td>${escapeHtml(resource)}</td>
            <td>${escapeHtml(actorLabel)} <span class="hint">(${escapeHtml(
              actor.auth_method || ""
            )})</span></td>
            <td>${escapeHtml(ev.outcome || "")}</td>
            <td><code>${escapeHtml(ev.audit_id || "")}</code></td>
          </tr>`;
        })
        .join("");
      return data;
    } catch (err) {
      if (err.status === 403) {
        showAuditDenied(err.message || "Permission audit:read required");
        body.innerHTML =
          `<tr><td colspan="6" class="hint">Permission audit:read required (admin / owner).</td></tr>`;
        return { denied: true, error: err.message };
      }
      body.innerHTML = `<tr><td colspan="6" class="hint">${escapeHtml(
        err.message || "Failed to load audit events"
      )}</td></tr>`;
      throw err;
    }
  }

  async function loadTenantMembersPanel() {
    const body = $("#tenantMembersBody");
    const hint = $("#tenantMembersHint");
    if (!body) return;
    if (state.authMethod === "basic") {
      if (hint) {
        hint.textContent =
          "HTTP Basic sessions cannot list org members (no tenant-admin context). Use OIDC.";
      }
      body.innerHTML =
        `<tr><td colspan="5" class="hint">OIDC tenant-admin / platform-admin session required.</td></tr>`;
      return;
    }
    const canList = can("users:read");
    if (!canList) {
      if (hint) {
        hint.textContent =
          "Requires users:read (admin / owner / platform admin) to list members of the current organization.";
      }
      body.innerHTML =
        `<tr><td colspan="5" class="hint">Insufficient role to list members.</td></tr>`;
      return;
    }
    const canAdmin = can("users:admin") || state.isPlatformAdmin;
    try {
      const data = await api(
        `/api/tenants/${encodeURIComponent(state.tenantId)}/members`
      );
      if (hint) {
        hint.textContent =
          `${data.count || 0} member(s) in ${state.tenantId}` +
          (canAdmin
            ? " · Change role below to grant audit:read (admin/owner)."
            : " · Role changes require users:admin.");
      }
      const items = data.items || [];
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="5" class="hint">No members yet.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((m) => {
          const label =
            m.display_name || m.username || m.user_id || "unknown";
          const mid = m.membership_id || "";
          let changeCell = `<span class="hint">—</span>`;
          if (canAdmin && mid) {
            const roles = ["viewer", "member", "admin", "owner"];
            changeCell = `<div class="member-role-edit">
              <select class="member-role-select" data-membership-id="${escapeHtml(
                mid
              )}" aria-label="Role for ${escapeHtml(label)}">
                ${roles
                  .map(
                    (r) =>
                      `<option value="${r}"${
                        r === m.role ? " selected" : ""
                      }>${r}</option>`
                  )
                  .join("")}
              </select>
              <button type="button" class="ghost btn-member-role-save" data-membership-id="${escapeHtml(
                mid
              )}">Save</button>
            </div>`;
          } else if (!canAdmin) {
            changeCell = `<span class="hint">Requires users:admin</span>`;
          }
          return `<tr>
            <td>${escapeHtml(label)}</td>
            <td>${escapeHtml(m.email || "—")}</td>
            <td><code>${escapeHtml(m.role || "")}</code></td>
            <td>${m.is_platform_admin ? "yes" : "no"}</td>
            <td>${changeCell}</td>
          </tr>`;
        })
        .join("");
    } catch (err) {
      if (hint) hint.textContent = err.message || "Could not load members";
      body.innerHTML = `<tr><td colspan="5" class="hint">${escapeHtml(
        err.message || "Could not load members"
      )}</td></tr>`;
    }
  }

  async function loadOrgInvitesPanel() {
    const body = $("#orgInvitesBody");
    const hint = $("#orgInvitesHint");
    const form = $("#orgInviteForm");
    if (!body) return;
    if (!can("users:admin")) {
      if (hint) hint.textContent = "Requires users:admin to create or revoke invites.";
      if (form) form.classList.add("hidden");
      return;
    }
    if (form) form.classList.remove("hidden");
    try {
      const data = await api(
        `/api/tenants/${encodeURIComponent(state.tenantId)}/invites`
      );
      const items = data.items || [];
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="5" class="hint">No pending invites.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((inv) => {
          const who =
            inv.invitee_email ||
            inv.invitee_username ||
            inv.invite_id ||
            "—";
          const tok = inv.token
            ? `<code title="share with invitee">${escapeHtml(
                String(inv.token).slice(0, 12)
              )}…</code>`
            : "—";
          const revoke =
            inv.status === "pending"
              ? `<button type="button" class="ghost btn-revoke-invite" data-invite-id="${escapeHtml(
                  inv.invite_id
                )}">Revoke</button>`
              : "";
          return `<tr>
            <td>${escapeHtml(who)}</td>
            <td><code>${escapeHtml(inv.role || "")}</code></td>
            <td>${escapeHtml(inv.status || "")}</td>
            <td>${tok}</td>
            <td>${revoke}</td>
          </tr>`;
        })
        .join("");
    } catch (err) {
      body.innerHTML = `<tr><td colspan="5" class="hint">${escapeHtml(
        err.message || "Could not load invites"
      )}</td></tr>`;
    }
  }

  async function loadCustomRolesPanel() {
    const body = $("#customRolesBody");
    const form = $("#customRoleForm");
    if (!body) return;
    if (!can("users:admin")) {
      if (form) form.classList.add("hidden");
      body.innerHTML =
        `<tr><td colspan="4" class="hint">Requires users:admin.</td></tr>`;
      return;
    }
    if (form) form.classList.remove("hidden");
    try {
      const data = await api(
        `/api/tenants/${encodeURIComponent(state.tenantId)}/custom-roles`
      );
      const items = data.items || [];
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="4" class="hint">No custom roles yet.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map(
          (r) => `<tr>
          <td><code>${escapeHtml(r.membership_role || r.role_key)}</code></td>
          <td>${escapeHtml(r.display_name || "")}</td>
          <td>${(r.permissions || [])
            .map((p) => `<code>${escapeHtml(p)}</code>`)
            .join(" ")}</td>
          <td><button type="button" class="ghost btn-delete-custom-role" data-role-key="${escapeHtml(
            r.role_key
          )}">Delete</button></td>
        </tr>`
        )
        .join("");
    } catch (err) {
      body.innerHTML = `<tr><td colspan="4" class="hint">${escapeHtml(
        err.message
      )}</td></tr>`;
    }
  }

  async function loadOidcSettingsPanel() {
    const status = $("#oidcSettingsStatus");
    const block = $("#settingsOidcBlock");
    if (!block) return;
    if (!state.isPlatformAdmin) {
      block.classList.add("hidden");
      return;
    }
    block.classList.remove("hidden");
    try {
      const data = await api("/api/platform/oidc-settings");
      $("#oidcDbActive").checked = !!data.active_db_config;
      $("#oidcDbEnabled").checked = !!data.oidc_enabled;
      $("#oidcDbIssuer").value = data.issuer || "";
      $("#oidcDbClientId").value = data.client_id || "";
      $("#oidcDbRedirect").value = data.redirect_uri || "";
      $("#oidcDbScopes").value = data.scopes || "openid profile email";
      $("#oidcDbSecretRef").value = data.client_secret_env_ref || "OIDC_CLIENT_SECRET";
      if (status) {
        status.textContent =
          `secret_configured=${!!data.client_secret_configured}; ` +
          (data.notes || "");
      }
    } catch (err) {
      if (status) status.textContent = err.message || "Could not load OIDC settings";
    }
  }

  async function saveMemberRole(membershipId, role) {
    if (!membershipId || !role) return;
    await api(
      `/api/tenants/${encodeURIComponent(
        state.tenantId
      )}/members/${encodeURIComponent(membershipId)}`,
      { method: "PUT", body: JSON.stringify({ role }) }
    );
    toast(`Membership role updated to ${role}`);
    await loadTenantMembersPanel();
    // Refresh gates if the actor changed their own role.
    try {
      await loadRolesPanel();
    } catch (_) {
      /* roles panel optional here */
    }
  }

  function renderOrgList(tenantsPayload) {
    const body = $("#orgListBody");
    if (!body) return;
    const catalog =
      (tenantsPayload &&
        tenantsPayload.catalog_items &&
        tenantsPayload.catalog_items.length &&
        tenantsPayload.catalog_items) ||
      (tenantsPayload && tenantsPayload.items) ||
      [];
    if (!catalog.length) {
      body.innerHTML =
        `<tr><td colspan="5" class="hint">No organizations visible.</td></tr>`;
      return;
    }
    body.innerHTML = catalog
      .map((t) => {
        const isCurrent = t.tenant_id === state.tenantId || t.is_current;
        return `<tr>
          <td>${escapeHtml(t.display_name || t.tenant_id || "")}</td>
          <td><code>${escapeHtml(t.tenant_id || "")}</code></td>
          <td>${escapeHtml(t.plan_code || "—")}</td>
          <td>${escapeHtml(t.membership_role || "—")}</td>
          <td>${isCurrent ? "yes" : "no"}</td>
        </tr>`;
      })
      .join("");
  }

  function populateTenantSwitcher(tenantsPayload, currentTenantId) {
    const switcher = $("#tenantSwitcher");
    const note = $("#tenantSwitcherNote");
    if (!switcher) return;
    const items = (tenantsPayload && tenantsPayload.items) || [];
    const orgEnabled = !!(
      tenantsPayload && tenantsPayload.org_switcher_enabled
    );
    const switchable = !!(
      tenantsPayload && tenantsPayload.switchable_for_user
    );
    state.orgSwitcherEnabled = orgEnabled;
    state.switchableForUser = switchable;

    switcher.innerHTML = "";
    if (!items.length) {
      const opt = document.createElement("option");
      opt.value = currentTenantId || "tenant-svrmon24-legacy";
      opt.textContent = "SVRMON24 Legacy";
      opt.selected = true;
      switcher.appendChild(opt);
    } else {
      for (const t of items) {
        const opt = document.createElement("option");
        opt.value = t.tenant_id;
        const role = t.membership_role ? ` · ${t.membership_role}` : "";
        opt.textContent = `${t.display_name || t.tenant_id}${role}`;
        if (t.tenant_id === currentTenantId) opt.selected = true;
        switcher.appendChild(opt);
      }
    }

    const canSwitch = orgEnabled && switchable;
    switcher.disabled = !canSwitch;
    switcher.setAttribute("aria-disabled", canSwitch ? "false" : "true");
    if (note) {
      if (!orgEnabled) {
        note.textContent = "Organization switcher disabled by server.";
      } else if (state.authMethod === "basic") {
        note.textContent =
          "HTTP Basic cannot switch orgs — migration tenant only.";
      } else if (!switchable) {
        note.textContent =
          items.length <= 1
            ? "Only one membership — add another org to switch."
            : "Switcher unavailable for this session.";
      } else {
        note.textContent = `Switchable · ${items.length} organization(s)`;
      }
    }
  }

  async function switchOrganization(tenantId) {
    if (!tenantId || tenantId === state.tenantId) return;
    if (!state.orgSwitcherEnabled || !state.switchableForUser) {
      toast("Organization switching is not available for this session", true);
      return;
    }
    setGlobalLoading(true, "Switching organization…");
    try {
      const result = await api("/api/tenants/switch", {
        method: "POST",
        body: JSON.stringify({ tenant_id: tenantId }),
      });
      const t = result.tenant || {};
      state.tenantId = t.tenant_id || tenantId;
      state.membershipRole = result.membership_role || null;
      if (Array.isArray(result.permissions)) {
        state.permissions = result.permissions;
        applyPermissionGates();
      }
      setTenantBanner(
        true,
        t.display_name || state.tenantId,
        state.tenantId
      );
      toast(`Switched to ${t.display_name || state.tenantId}`);
      await loadTenancyContext({
        current_tenant_id: state.tenantId,
        current_tenant_display_name: t.display_name,
      });
      // Refresh active tab data under the new tenant scope.
      if (state.activeNav) showTab(state.activeNav);
    } catch (err) {
      toast(err.message || "Organization switch failed", true);
      await loadTenancyContext();
    } finally {
      setGlobalLoading(false);
    }
  }

  async function loadTenancyContext(me) {
    const memEl = $("#membershipSummary");
    const orgEl = $("#orgTenantSummary");
    const platformEl = $("#platformAdminStatus");
    let tenantName =
      (me && me.current_tenant_display_name) || "SVRMON24 Legacy";
    let tenantId =
      (me && me.current_tenant_id) || state.tenantId || "tenant-svrmon24-legacy";
    if (me) {
      state.isPlatformAdmin = !!me.is_platform_admin;
      if (me.auth_method) state.authMethod = me.auth_method;
    }
    setTenantBanner(true, tenantName, tenantId);
    let tenantsPayload = null;
    try {
      const current = await api("/api/tenants/current");
      const t = current.tenant || {};
      tenantName = t.display_name || tenantName;
      tenantId = t.tenant_id || tenantId;
      state.tenantId = tenantId;
      state.membershipRole = current.membership_role || null;
      state.isPlatformAdmin = !!current.is_platform_admin;
      state.permissions = Array.isArray(current.permissions)
        ? current.permissions
        : state.permissions;
      state.orgSwitcherEnabled = !!current.org_switcher_enabled;
      applyPermissionGates();
      setTenantBanner(true, tenantName, tenantId);
      if (orgEl) {
        const plan = t.plan_code || "legacy_unlimited";
        orgEl.textContent =
          `${tenantName} (${tenantId}) · plan=${plan} · ` +
          `role=${state.membershipRole || "—"} · isolation_enforced=true · ` +
          `org_switcher_enabled=${!!current.org_switcher_enabled}`;
      }
    } catch (err) {
      if (orgEl) orgEl.textContent = err.message || "Could not load tenant";
    }
    try {
      tenantsPayload = await api("/api/tenants");
      populateTenantSwitcher(tenantsPayload, state.tenantId);
      renderOrgList(tenantsPayload);
    } catch (err) {
      populateTenantSwitcher(
        {
          items: [
            {
              tenant_id: state.tenantId,
              display_name: tenantName,
            },
          ],
          org_switcher_enabled: state.orgSwitcherEnabled,
          switchable_for_user: false,
        },
        state.tenantId
      );
      if (orgEl && !orgEl.textContent) {
        orgEl.textContent = err.message || "Could not list tenants";
      }
    }
    try {
      const mem = await api("/api/memberships");
      state.memberships = mem.items || [];
      state.isPlatformAdmin = !!mem.is_platform_admin || state.isPlatformAdmin;
      if (memEl) {
        if (!mem.user_id) {
          memEl.textContent =
            mem.notes ||
            "No local user identity (Basic sessions do not create memberships).";
        } else {
          const roles =
            (mem.items || [])
              .map((m) => `${m.tenant_display_name || m.tenant_id}: ${m.role}`)
              .join("; ") || "none";
          memEl.textContent =
            `user_id=${mem.user_id}; platform_admin=${!!mem.is_platform_admin}; ` +
            `memberships=[${roles}]; switchable_for_user=${!!mem.switchable_for_user}`;
        }
      }
      renderMembershipTables(mem);
      if (platformEl) {
        platformEl.textContent = state.isPlatformAdmin
          ? "You are a platform admin (CLI or first OIDC user). You can create orgs, assign plans, and edit SSO settings."
          : "You are not a platform admin. Bootstrap via scripts/bootstrap_platform_admin.py or be the first OIDC user.";
      }
      loadOidcSettingsPanel().catch(() => {});
    } catch (err) {
      if (memEl) memEl.textContent = err.message || "Could not load memberships";
      if (platformEl) {
        platformEl.textContent = err.message || "Could not load platform status";
      }
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
    state.authenticated = false;
    document.body.classList.add("is-login");
    document.body.classList.remove("is-app");
    document.body.setAttribute("data-auth", "anonymous");
    const gate = $("#loginGate");
    if (gate) {
      gate.classList.remove("hidden");
      gate.removeAttribute("hidden");
      gate.setAttribute("aria-hidden", "false");
    }
    const shell = $("#appShell");
    if (shell) {
      shell.classList.add("hidden");
      shell.setAttribute("hidden", "");
      shell.setAttribute("aria-hidden", "true");
    }
    // Legacy embedded sign-in must never appear inside the app shell.
    $("#authPanel")?.setAttribute("hidden", "");
    $("#authPanel")?.classList.add("hidden");
  }

  function showAppShell() {
    state.authenticated = true;
    document.body.classList.remove("is-login");
    document.body.classList.add("is-app");
    document.body.setAttribute("data-auth", "authenticated");
    const gate = $("#loginGate");
    if (gate) {
      gate.classList.add("hidden");
      gate.setAttribute("hidden", "");
      gate.setAttribute("aria-hidden", "true");
    }
    const shell = $("#appShell");
    if (shell) {
      shell.classList.remove("hidden");
      shell.removeAttribute("hidden");
      shell.setAttribute("aria-hidden", "false");
    }
    // Belt-and-suspenders: purge any legacy embedded sign-in card.
    const legacy = $("#authPanel");
    if (legacy) {
      legacy.setAttribute("hidden", "");
      legacy.classList.add("hidden");
      legacy.remove();
    }
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
    const remember = $("#authRemember")?.checked !== false;
    if (remember) {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ username, password }));
    } else {
      sessionStorage.removeItem(STORAGE_KEY);
    }
    return true;
  }

  function loadAuthIntoForm() {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    const remember = $("#authRemember");
    if (!raw) {
      if (remember) remember.checked = false;
      return;
    }
    try {
      const { username, password } = JSON.parse(raw);
      $("#authUser").value = username || "";
      $("#authPass").value = password || "";
      if (remember) remember.checked = true;
    } catch { /* ignore */ }
  }

  function toggleAuthPasswordVisibility() {
    const input = $("#authPass");
    const btn = $("#btnAuthPassToggle");
    if (!input || !btn) return;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-pressed", show ? "true" : "false");
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    btn.setAttribute("title", show ? "Hide password" : "Show password");
    btn.querySelector(".ico-show")?.classList.toggle("hidden", show);
    btn.querySelector(".ico-hide")?.classList.toggle("hidden", !show);
  }

  async function afterAuthenticated(me, { toastMessage = "Connected" } = {}) {
    setSessionChip(true, me.username, me.auth_method || "", me);
    showAppShell();
    if (toastMessage) toast(toastMessage);
    await Promise.all([
      loadDashboard(),
      loadTypes(),
      loadCustomFields(),
      loadCustomTables(),
      loadColumnConfigurations(),
      loadInventory(),
      loadRelationshipTypes(),
      loadRelationships(),
      refreshComponentIdList(),
      refreshEntityIdList(),
      loadDiagnosticProfiles(),
      loadDiagnosticHistory(),
      loadTenancyContext(me),
      loadEntitlements(),
    ]);
    syncDepPickers();
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
      showLoginShell();
      toast(err.message || "Auth failed", true);
    } finally {
      setGlobalLoading(false);
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function clearQueryParams(keys) {
    const params = new URLSearchParams(window.location.search);
    let changed = false;
    for (const key of keys) {
      if (params.has(key)) {
        params.delete(key);
        changed = true;
      }
    }
    if (!changed) return;
    const next = `${window.location.pathname}${params.toString() ? `?${params}` : ""}${window.location.hash || ""}`;
    window.history.replaceState({}, "", next);
  }

  async function tryResumeSession() {
    const params = new URLSearchParams(window.location.search);
    const justSignedIn = params.get("signed_in") === "1";
    // Keep login gate visible until /api/me succeeds — never paint app chrome early.
    showLoginShell();
    setGlobalLoading(true, justSignedIn ? "Completing sign-in…" : "Checking session…");
    const attempts = justSignedIn ? 6 : 2;
    try {
      for (let i = 0; i < attempts; i += 1) {
        try {
          const me = await api("/api/me");
          clearQueryParams(["signed_in", "auth_error"]);
          await afterAuthenticated(me, {
            toastMessage: justSignedIn ? "Signed in" : "Session restored",
          });
          return true;
        } catch (_) {
          if (i < attempts - 1) await sleep(justSignedIn ? 200 : 120);
        }
      }
      setSessionChip(false);
      showLoginShell();
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
    const orDivider = $("#authOrDivider");
    const misconfigured = $("#authMisconfigured");
    const hostBanner = $("#hostMismatchBanner");

    if (hint) {
      if (cfg.oidc_enabled && cfg.basic_auth_enabled) {
        hint.textContent =
          "Sign in with your credentials or continue with Keycloak SSO.";
      } else if (cfg.oidc_enabled) {
        hint.textContent =
          "Continue with your organization’s Keycloak identity provider.";
      } else if (cfg.basic_auth_enabled) {
        hint.textContent =
          "Migration HTTP Basic only — OIDC is disabled on this server.";
      } else {
        hint.textContent = "No authentication method is currently enabled.";
      }
    }
    oidcRow?.classList.toggle("hidden", !cfg.oidc_enabled);
    oidcRow?.classList.toggle("oidc-only", !!(cfg.oidc_enabled && !cfg.basic_auth_enabled));
    basicRow?.classList.toggle("hidden", !cfg.basic_auth_enabled);
    const both = !!(cfg.oidc_enabled && cfg.basic_auth_enabled);
    orDivider?.classList.toggle("hidden", !both);
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

  function customFieldAppliesToCurrentType(col) {
    if (col.source !== "custom_field") return true;
    const applies = col.applies_to || ["*"];
    if (applies.includes("*")) return true;
    // Unfiltered inventory shows every custom column; typed ops pages filter.
    if (!state.inventoryType) return true;
    return applies.includes(state.inventoryType);
  }

  function visibleColumns(gridKey) {
    const cfg = state.columnConfigs[gridKey];
    const cols = (cfg && cfg.columns) || [];
    return cols
      .filter((c) => c.visible !== false)
      .filter((c) => (gridKey === "inventory" ? customFieldAppliesToCurrentType(c) : true))
      .slice()
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  }

  function formatCustomFieldCell(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "object") {
      try {
        return JSON.stringify(value);
      } catch {
        return String(value);
      }
    }
    return String(value);
  }

  function applyHeadRow(headSel, columns) {
    const head = $(headSel);
    if (!head) return;
    head.innerHTML = columns
      .map((c) => {
        const style = [];
        if (c.width) style.push(`width:${Number(c.width)}px`);
        if (c.pinned === "left" || c.pinned === "right") {
          style.push(`position:sticky;${c.pinned}:0;z-index:1;background:var(--surface)`);
        }
        const styleAttr = style.length ? ` style="${style.join(";")}"` : "";
        return `<th data-col="${escapeAttr(c.column_key)}"${styleAttr}>${escapeHtml(c.label || c.column_key)}</th>`;
      })
      .join("");
  }

  function inventoryCellHtml(row, columnKey) {
    switch (columnKey) {
      case "component_id":
        return `<td class="mono">${escapeHtml(row.component_id)}</td>`;
      case "hostname_or_name":
        return `<td>${escapeHtml(row.hostname_or_name)}</td>`;
      case "component_type":
        return `<td>${escapeHtml(row.component_type)}</td>`;
      case "os_family":
        return `<td class="${row.os_family === "—" ? "dash" : ""}">${escapeHtml(row.os_family)}</td>`;
      case "os_version":
        return `<td class="${row.os_version === "—" ? "dash" : ""}">${escapeHtml(row.os_version)}</td>`;
      case "product_type":
        return `<td class="${row.product_type === "—" ? "dash" : ""}">${escapeHtml(row.product_type)}</td>`;
      case "product_version":
        return `<td class="${row.product_version === "—" ? "dash" : ""}">${escapeHtml(row.product_version)}</td>`;
      case "environment":
        return `<td>${escapeHtml(row.environment)}</td>`;
      case "status":
        return `<td><span class="status-pill ${statusClass(row.status)}">${escapeHtml(row.status)}</span></td>`;
      case "actions": {
        const write = can("cmdb:write");
        return `<td class="actions">
            <button type="button" class="ghost" data-view="${escapeAttr(row.component_id)}">View</button>
            ${
              write
                ? `<button type="button" class="secondary" data-edit="${escapeAttr(row.component_id)}">Edit</button>
            <button type="button" class="danger" data-del="${escapeAttr(row.component_id)}">Delete</button>`
                : ""
            }
          </td>`;
      }
      default: {
        const cf = (row.custom_fields && row.custom_fields[columnKey] !== undefined)
          ? row.custom_fields[columnKey]
          : undefined;
        const text = formatCustomFieldCell(cf);
        return `<td class="${text === "—" ? "dash" : ""}">${escapeHtml(text)}</td>`;
      }
    }
  }

  function relationshipCellHtml(row, columnKey) {
    switch (columnKey) {
      case "relationship_id":
        return `<td class="mono">${escapeHtml(row.relationship_id)}</td>`;
      case "source_component_id":
        return `<td class="mono">${escapeHtml(row.source_component_id)}</td>`;
      case "target_component_id":
        return `<td class="mono">${escapeHtml(row.target_component_id)}</td>`;
      case "source_table":
        return `<td class="mono ${row.source_table === "—" ? "dash" : ""}">${escapeHtml(row.source_table || "—")}</td>`;
      case "target_table":
        return `<td class="mono ${row.target_table === "—" ? "dash" : ""}">${escapeHtml(row.target_table || "—")}</td>`;
      case "relationship_type":
        return `<td>${escapeHtml(row.relationship_type)}</td>`;
      case "protocol":
        return `<td class="${row.protocol === "—" ? "dash" : ""}">${escapeHtml(row.protocol)}</td>`;
      case "source_port":
        return `<td class="mono ${row.source_port === "—" ? "dash" : ""}">${escapeHtml(row.source_port)}</td>`;
      case "target_port":
        return `<td class="mono ${row.target_port === "—" ? "dash" : ""}">${escapeHtml(row.target_port)}</td>`;
      case "environment":
        return `<td>${escapeHtml(row.environment)}</td>`;
      case "discovery_method":
        return `<td>${escapeHtml(row.discovery_method)}</td>`;
      case "verification_status":
        return `<td>${escapeHtml(row.verification_status)}</td>`;
      case "actions":
        if (!can("relationships:write")) {
          return `<td class="actions"><span class="hint">Read-only</span></td>`;
        }
        return `<td class="actions">
          <button type="button" class="secondary" data-rel-edit="${escapeAttr(row.relationship_id)}">Edit</button>
          <button type="button" class="danger" data-rel-del="${escapeAttr(row.relationship_id)}">Delete</button>
        </td>`;
      default:
        return `<td></td>`;
    }
  }

  async function loadColumnConfigurations() {
    const data = await api("/api/column-configurations");
    for (const item of data.items || []) {
      if (item.grid_key === "inventory" || item.grid_key === "relationships") {
        state.columnConfigs[item.grid_key] = item;
      }
    }
    applyHeadRow("#inventoryHeadRow", visibleColumns("inventory"));
    applyHeadRow("#relationshipHeadRow", visibleColumns("relationships"));
  }

  async function loadInventory() {
    setOverlayLoading("#inventoryLoading", true);
    try {
      if (!state.columnConfigs.inventory) {
        await loadColumnConfigurations();
      }
      const columns = visibleColumns("inventory");
      applyHeadRow("#inventoryHeadRow", columns);
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
        tr.innerHTML = columns.map((c) => inventoryCellHtml(row, c.column_key)).join("");
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
      const locked = !!item.locked || item.origin === "builtin";
      const tr = document.createElement("tr");
      const actions = locked
        ? `<span class="hint">Locked</span>`
        : can("config:write")
          ? `<button type="button" class="secondary" data-cf-edit="${escapeAttr(item.field_key)}">Edit</button>
          <button type="button" class="danger" data-cf-del="${escapeAttr(item.field_key)}">Delete</button>`
          : `<span class="hint">Read-only</span>`;
      tr.innerHTML = `
        <td class="mono">${escapeHtml(item.field_key)}</td>
        <td>${escapeHtml(item.label)}</td>
        <td>${escapeHtml(item.field_type)}</td>
        <td>${escapeHtml((item.applies_to || []).join(", "))}</td>
        <td>${item.required ? "yes" : "no"}</td>
        <td class="actions">${actions}</td>`;
      tbody.appendChild(tr);
    }
  }

  function resetCustomFieldForm() {
    state.editingCfKey = null;
    const form = $("#customFieldForm");
    form?.reset();
    if ($("#cfApplies")) $("#cfApplies").value = "*";
    if ($("#cfKey")) {
      $("#cfKey").disabled = false;
      $("#cfKey").readOnly = false;
    }
    if ($("#cfSubmitBtn")) $("#cfSubmitBtn").textContent = "Add definition";
    $("#cfEditHint")?.classList.add("hidden");
    $("#btnCfCancelEdit")?.classList.add("hidden");
  }

  function beginEditCustomField(fieldKey) {
    const item = state.customFields.find((f) => f.field_key === fieldKey);
    if (!item) {
      toast(`Custom field '${fieldKey}' not found`, true);
      return;
    }
    if (item.locked || item.origin === "builtin") {
      toast("Built-in OS/product fields cannot be edited here", true);
      return;
    }
    state.editingCfKey = fieldKey;
    $("#cfKey").value = item.field_key;
    $("#cfKey").disabled = true;
    $("#cfKey").readOnly = true;
    $("#cfLabel").value = item.label || "";
    $("#cfType").value = item.field_type || "string";
    const applies = (item.applies_to || ["*"])[0] || "*";
    $("#cfApplies").value = applies === "*" ? "*" : applies;
    $("#cfEnum").value = (item.enum_values || []).join(", ");
    $("#cfRequired").checked = !!item.required;
    if ($("#cfSubmitBtn")) $("#cfSubmitBtn").textContent = "Save definition";
    $("#cfEditHint")?.classList.remove("hidden");
    $("#btnCfCancelEdit")?.classList.remove("hidden");
    $("#cfLabel")?.focus();
    $("#customFieldForm")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
    const fieldKey = (state.editingCfKey || $("#cfKey").value.trim()).trim();
    const fieldType = $("#cfType").value;
    const enumValues =
      fieldType === "enum"
        ? $("#cfEnum").value
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        : [];
    const shared = {
      label: $("#cfLabel").value.trim(),
      field_type: fieldType,
      applies_to: [applies || "*"],
      required: $("#cfRequired").checked,
      enum_values: enumValues,
    };
    try {
      if (state.editingCfKey) {
        await api(`/api/custom-fields/${encodeURIComponent(state.editingCfKey)}`, {
          method: "PUT",
          body: JSON.stringify(shared),
        });
        toast(`Custom field '${state.editingCfKey}' updated`);
      } else {
        await api("/api/custom-fields", {
          method: "POST",
          body: JSON.stringify({ field_key: fieldKey, ...shared }),
        });
        toast("Custom field created");
      }
      resetCustomFieldForm();
      await loadCustomFields();
      // Field defs drive Inventory columns (visible by default) + Column Settings entries.
      await loadColumnConfigurations();
      if (state.inventoryType || state.activeNav === "inventory") {
        await loadInventory();
      }
    } catch (err) {
      toast(err.message || "Custom field save failed", true);
    }
  }

  function showTab(name) {
    const inventoryType = INVENTORY_TABS[name] || null;
    const customTableKey =
      name && name.startsWith("ct:") ? name.slice(3) : null;
    let panelName = inventoryType ? "inventory" : name;
    if (customTableKey) panelName = "custom-records";
    $$(".tab-panel").forEach((p) => p.classList.add("hidden"));
    $$(".nav-item").forEach((b) => b.classList.remove("active"));
    const panel = $(`#tab-${panelName}`);
    const btn = $(`.nav-item[data-tab="${name}"]`);
    if (!panel || !btn) return;
    panel.classList.remove("hidden");
    btn.classList.add("active");
    state.activeNav = name;
    applyInventoryTypeLock(inventoryType);
    const customTableMeta = customTableKey
      ? (state.customTables || []).find((t) => t.table_key === customTableKey)
      : null;
    const meta = PAGE_META[name] ||
      (customTableKey
        ? {
            title: formatTableChoiceLabel(customTableMeta || customTableKey),
            subtitle: `Custom table records (${customTableKey})`,
          }
        : { title: name, subtitle: "" });
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
      Promise.all([loadRelationships(), refreshEntityIdList(), populateRelTableSelects()])
        .catch((err) => toast(err.message, true));
    }
    if (name === "dependencies") {
      Promise.all([
        refreshComponentIdList(),
        refreshEntityIdList(),
        loadCustomTables(),
      ])
        .then(() => syncDepPickers())
        .catch((err) => toast(err.message, true));
    }
    if (name === "diagnostics") {
      Promise.all([
        refreshComponentIdList(),
        loadDiagnosticProfiles(),
        loadDiagnosticHistory(),
        refreshDiagEntitlementHint(),
        refreshOllamaStatus(),
      ]).catch((err) => toast(err.message, true));
    }
    if (name === "columns" && state.authenticated) {
      openColumnSettings($("#colGridKey")?.value || "inventory").catch((err) =>
        toast(err.message || "Column settings failed", true)
      );
    }
    if (name === "custom-tables" && state.authenticated) {
      loadCustomTables().catch((err) => toast(err.message, true));
    }
    if (name === "plans" && state.authenticated) {
      loadEntitlements().catch((err) => toast(err.message, true));
    }
    if (name === "users" && state.authenticated) {
      loadTenancyContext()
        .then(() => Promise.all([loadTenantMembersPanel(), loadOrgInvitesPanel()]))
        .catch((err) => toast(err.message, true));
    }
    if (name === "roles") {
      if (state.authenticated) {
        loadRolesPanel()
          .then(() => loadCustomRolesPanel())
          .catch((err) => toast(err.message, true));
      } else {
        renderRolesSignedOut();
      }
    }
    if (name === "organizations" && state.authenticated) {
      loadTenancyContext().catch((err) => toast(err.message, true));
    }
    if (name === "settings" && state.authenticated) {
      loadTenancyContext()
        .then(() => loadOidcSettingsPanel())
        .catch((err) => toast(err.message, true));
    }
    if (name === "audit") {
      loadAuditEvents()
        .then((result) => {
          if (result && result.denied) return;
        })
        .catch((err) => toast(err.message, true));
    }
    if (customTableKey && state.authenticated) {
      state.selectedCustomTableKey = customTableKey;
      state.customRecordPage = 1;
      loadCustomRecords().catch((err) => toast(err.message, true));
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

  async function refreshDiagEntitlementHint() {
    const el = $("#diagEntitlementHint");
    if (!el) return;
    try {
      const data = state.entitlements || (await api("/api/entitlements"));
      state.entitlements = data;
      const diagLimit = data.limits?.max_diagnostic_runs;
      const ollamaLimit = data.limits?.max_ollama_analyses;
      const diagShown = diagLimit == null ? "unlimited" : String(diagLimit);
      const ollamaShown = ollamaLimit == null ? "unlimited" : String(ollamaLimit);
      el.textContent =
        `Entitlements: max_diagnostic_runs = ${diagShown} · max_ollama_analyses = ${ollamaShown} (Plans). ` +
        `SIMULATED only — no live probes. Ollama also needs OLLAMA_ENABLED=true.`;
    } catch (err) {
      el.textContent = `Entitlements unavailable (${err.message || "error"}).`;
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
    const tid = doc.tenant_id || state.tenantId || "—";
    $("#diagLatest").innerHTML = `
      <div class="demo-banner">${escapeHtml(doc.labels?.banner || "SIMULATED / SYNTHETIC_DEMO — not live telemetry")}</div>
      <div style="margin-top:8px">
        <strong class="mono">${escapeHtml(doc.diagnostic_id)}</strong>
        · mode <strong>${escapeHtml(doc.execution_mode)}</strong>
        · profile ${escapeHtml(doc.profile_name)}
        · component <span class="mono">${escapeHtml(doc.component_id)}</span>
        (${escapeHtml(c.component_type || "")} / ${escapeHtml(c.name || "")})
        · tenant <span class="mono">${escapeHtml(tid)}</span>
        · ${escapeHtml(doc.timestamp || "")}
      </div>
      <div class="hint">Upstream deps: ${escapeHtml((doc.dependency_context?.upstream_direct || []).length)}
        · Downstream deps: ${escapeHtml((doc.dependency_context?.downstream_direct || []).length)}
        · safety: remote=${escapeHtml(String(!!doc.safety?.remote_execution))} shell=${escapeHtml(String(!!doc.safety?.shell))} sql=${escapeHtml(String(!!doc.safety?.sql))} scan=${escapeHtml(String(!!doc.safety?.network_scan))}</div>`;

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
    const hint = $("#ollamaStatusHint");
    const contention = $("#ollamaContentionHint");
    const analyzeBtn = $("#btnAnalyzeDiag");
    try {
      const status = await api("/api/diagnostics/ollama/status");
      const ent = status.entitlement || {};
      const lim =
        ent.limit == null ? "unlimited" : `${ent.used || 0}/${ent.limit}`;
      if (contention && status.shared_local_contention) {
        contention.textContent = status.shared_local_contention;
      }
      if (!status.enabled) {
        if (hint) {
          hint.textContent =
            `Ollama disabled (OLLAMA_ENABLED=false). Analyze uses rule-based fallback. ` +
            `Entitlement max_ollama_analyses=${lim}.`;
        }
        if (analyzeBtn) {
          analyzeBtn.textContent = "Analyze (Ollama disabled — rule fallback)";
          analyzeBtn.disabled = false;
        }
        return;
      }
      if (ent.limited) {
        if (hint) {
          hint.textContent =
            `Ollama limited by entitlements (${lim}). Analyze uses rule-based fallback. ` +
            `Model=${status.configured_model || "—"}.`;
        }
        if (analyzeBtn) {
          analyzeBtn.textContent = "Analyze (Ollama limited — rule fallback)";
          analyzeBtn.disabled = false;
        }
        return;
      }
      if (status.ok) {
        if (hint) {
          hint.textContent =
            `Ollama enabled and reachable. Model=${status.configured_model}; ` +
            `present=${status.model_present}; entitlement=${lim}.`;
        }
        if (analyzeBtn) {
          analyzeBtn.textContent =
            "Analyze with Ollama (fallback if unavailable)";
        }
      } else {
        if (hint) {
          hint.textContent =
            `Ollama enabled but unavailable (${status.error || "error"}). ` +
            `Analysis will use rule-based fallback. Entitlement=${lim}.`;
        }
        if (analyzeBtn) {
          analyzeBtn.textContent =
            "Analyze with Ollama (fallback if unavailable)";
        }
      }
    } catch (err) {
      if (hint) {
        hint.textContent = `Ollama status check failed: ${err.message}`;
      }
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
    await refreshOllamaStatus();
  }

  async function loadDiagnosticHistory() {
    const data = await api("/api/diagnostics?page=1&page_size=25");
    const meta = $("#diagHistoryMeta");
    if (meta) {
      const tid = data.tenant_id || state.tenantId || "—";
      meta.textContent = `Tenant-scoped history · tenant_id ${tid} · mode ${
        data.execution_mode || "SIMULATED"
      } · ${data.total || 0} run(s)`;
    }
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
      tbody.innerHTML = emptyStateHtml("No rows", "No dependencies in this direction for the selected entity.");
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      const typeLabel =
        row.kind === "custom"
          ? `${row.component_type || row.ref_table || "custom"} (custom)`
          : row.component_type || row.ref_table || "—";
      tr.innerHTML = `
        <td class="mono">${escapeHtml(row.component_id)}</td>
        <td>${escapeHtml(row.name)}</td>
        <td>${escapeHtml(typeLabel)}</td>
        <td>${escapeHtml(row.direct_or_indirect)}</td>
        <td>${escapeHtml(row.relationship_type)}</td>
        <td class="mono ${row.source_table === "—" ? "dash" : ""}">${escapeHtml(row.source_table || "—")}</td>
        <td class="mono ${row.target_table === "—" ? "dash" : ""}">${escapeHtml(row.target_table || "—")}</td>
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
      toast("Enter an entity ID (CMDB or custom record)", true);
      return;
    }
    const depth = Number($("#depDepth").value || 5);
    const params = new URLSearchParams({ depth: String(depth) });
    const env = $("#depEnv").value.trim();
    const status = $("#depStatus").value;
    const table = ($("#depTable")?.value || "").trim();
    if (env) params.set("environment", env);
    if (status) params.set("status", status);
    if (table) params.set("table", table);
    const data = await api(
      `/api/dependencies/${encodeURIComponent(componentId)}?${params.toString()}`
    );
    const selected = data.selected || {};
    const kindLabel = selected.kind === "custom" ? "custom" : "CMDB";
    const tableLabel = selected.ref_table || selected.component_type || "—";
    $("#depSelected").innerHTML = `
      <div><strong class="mono">${escapeHtml(selected.component_id || "")}</strong>
      — ${escapeHtml(selected.name || "")}
      (${escapeHtml(kindLabel)} · ${escapeHtml(tableLabel)},
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
      toast(`Missing related entities: ${data.missing_components.join(", ")}`, true);
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

  function syncDepPickers() {
    const entityList = $("#depEntityIdList");
    if (entityList) {
      const refs = state.entityRefs || [];
      entityList.innerHTML = refs
        .map(
          (e) =>
            `<option value="${escapeAttr(e.entity_id)}">${escapeHtml(
              `${e.display_name || e.entity_id} [${e.ref_table}]`
            )}</option>`
        )
        .join("");
    }
    const tableList = $("#depTableList");
    if (tableList) {
      const builtins = ["Server", "Network", "Middleware", "Database", "Application"];
      const customs = (state.customTables || []).map((t) => t.table_key);
      const keys = [...builtins, ...customs];
      tableList.innerHTML = keys
        .map((k) => `<option value="${escapeAttr(k)}"></option>`)
        .join("");
    }
  }

  function entityRefOptionHtml(e) {
    return `<option value="${escapeAttr(e.entity_id)}">${escapeHtml(
      `${e.display_name || e.entity_id} [${e.ref_table}]`
    )}</option>`;
  }

  function filterEntityRefs(tableKey) {
    const refs = state.entityRefs || [];
    const key = (tableKey || "").trim();
    if (!key) {
      // Blank table = CMDB-only picker (compat edges with null tables).
      return refs.filter((e) => e.kind === "component");
    }
    return refs.filter((e) => e.ref_table === key);
  }

  function syncRelEntityDatalists() {
    const sourceTable = $("#relSourceTable")?.value || "";
    const targetTable = $("#relTargetTable")?.value || "";
    const sourceList = $("#entityIdListSource");
    const targetList = $("#entityIdListTarget");
    const legacyList = $("#entityIdList");
    const sourceOpts = filterEntityRefs(sourceTable)
      .map(entityRefOptionHtml)
      .join("");
    const targetOpts = filterEntityRefs(targetTable)
      .map(entityRefOptionHtml)
      .join("");
    if (sourceList) sourceList.innerHTML = sourceOpts;
    if (targetList) targetList.innerHTML = targetOpts;
    // Keep legacy shared list for any other consumers.
    if (legacyList) {
      legacyList.innerHTML = (state.entityRefs || []).map(entityRefOptionHtml).join("");
    }
  }

  async function refreshEntityIdList() {
    const data = await api("/api/entity-refs?limit=200");
    state.entityRefs = data.items || [];
    syncRelEntityDatalists();
    syncDepPickers();
  }

  async function loadPlansCatalog() {
    const body = $("#plansCatalogBody");
    if (!body) return;
    try {
      const data = await api("/api/entitlements/plans");
      const items = data.items || [];
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="3" class="hint">No plans in catalog.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((plan) => {
          const limits = plan.limits || {};
          const summary = Object.keys(limits)
            .sort()
            .map((k) => {
              const v = limits[k];
              return `${k}=${v == null ? "unlimited" : v}`;
            })
            .join(", ");
          return `<tr>
            <td><code>${escapeHtml(plan.plan_code || "")}</code></td>
            <td>${escapeHtml(plan.plan_label || "")}</td>
            <td class="hint">${escapeHtml(summary)}</td>
          </tr>`;
        })
        .join("");
    } catch (err) {
      body.innerHTML = `<tr><td colspan="3" class="hint">${escapeHtml(
        err.message || "Could not load plan catalog"
      )}</td></tr>`;
    }
  }

  async function loadEntitlements() {
    const label = $("#entitlementsPlanLabel");
    const notes = $("#entitlementsNotes");
    const limitsEl = $("#entitlementsLimits");
    if (!label) return;
    try {
      const data = await api("/api/entitlements");
      state.entitlements = data;
      label.textContent = data.plan_label || data.plan_code || "Plan";
      if (notes) {
        notes.textContent =
          data.notes ||
          "Entitlements-only; no payment provider.";
      }
      if (limitsEl) {
        const limits = data.limits || {};
        const rows = Object.keys(limits)
          .sort()
          .map((key) => {
            const val = limits[key];
            const shown = val == null ? "unlimited" : String(val);
            return `<div><strong>${escapeHtml(key)}</strong>: ${escapeHtml(shown)}</div>`;
          })
          .join("");
        limitsEl.innerHTML =
          rows +
          `<div class="hint" style="margin-top:8px">tenant_id=${escapeHtml(
            String(data.tenant_id || state.tenantId || "")
          )} · billing_enabled=${escapeHtml(
            String(!!data.billing_enabled)
          )} · payment_provider=${escapeHtml(
            data.payment_provider == null ? "none" : String(data.payment_provider)
          )}</div>`;
      }
      await loadPlansCatalog();
    } catch (err) {
      label.textContent = "Entitlements unavailable";
      if (notes) notes.textContent = err.message || "Could not load entitlements";
      if (limitsEl) limitsEl.innerHTML = "";
    }
  }

  function selectedCustomTable() {
    return (state.customTables || []).find(
      (t) => t.table_key === state.selectedCustomTableKey
    ) || null;
  }

  const TABLE_COMBO_SELECT_IDS = [
    "ctSelectedTable",
    "ccRefTable",
    "relSourceTable",
    "relTargetTable",
  ];

  function setComboSelectOpen(wrap, open) {
    if (!wrap) return;
    const list = wrap.querySelector(".combo-select-list");
    const trigger = wrap.querySelector(".combo-select-trigger");
    wrap.classList.toggle("open", !!open);
    if (list) {
      list.hidden = !open;
      list.setAttribute("aria-hidden", open ? "false" : "true");
    }
    if (trigger) trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function closeAllComboSelects(exceptWrap = null) {
    $$(".combo-select.open").forEach((wrap) => {
      if (exceptWrap && wrap === exceptWrap) return;
      setComboSelectOpen(wrap, false);
    });
  }

  function syncReferenceTargetControl() {
    const typeEl = $("#ccType");
    const refSel = $("#ccRefTable");
    if (!refSel) return;
    const isRef = typeEl?.value === "reference";
    refSel.disabled = !isRef;
    refSel.removeAttribute("required");
    if (!isRef) {
      refSel.value = "";
      const wrap = refSel.closest(".combo-select");
      if (wrap) setComboSelectOpen(wrap, false);
    }
    upgradeComboSelect(refSel);
  }

  function optionDisplayText(opt) {
    if (!opt) return "(none)";
    const text = String(opt.textContent || opt.label || "").trim();
    if (text) return text;
    const value = String(opt.value || "").trim();
    return value || "(unnamed)";
  }

  function rebuildComboSelect(selectEl) {
    if (!selectEl) return;
    const wrap = selectEl.closest(".combo-select");
    if (!wrap) return;
    const list = wrap.querySelector(".combo-select-list");
    const trigger = wrap.querySelector(".combo-select-trigger");
    const labelEl = wrap.querySelector(".combo-select-trigger-label");
    if (!list || !trigger || !labelEl) return;

    list.innerHTML = "";
    for (const opt of [...selectEl.options]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "combo-select-option";
      btn.setAttribute("role", "option");
      btn.dataset.value = opt.value;
      btn.textContent = optionDisplayText(opt);
      btn.setAttribute("aria-selected", opt.selected ? "true" : "false");
      if (opt.disabled) {
        btn.disabled = true;
        btn.setAttribute("aria-disabled", "true");
      }
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (opt.disabled) return;
        selectEl.value = opt.value;
        selectEl.dispatchEvent(new Event("change", { bubbles: true }));
        closeAllComboSelects();
        rebuildComboSelect(selectEl);
      });
      list.appendChild(btn);
    }

    const selected = selectEl.selectedOptions?.[0] || selectEl.options[selectEl.selectedIndex];
    labelEl.textContent = optionDisplayText(selected);
    trigger.disabled = !!selectEl.disabled;
    trigger.title = labelEl.textContent;
    if (selectEl.disabled) setComboSelectOpen(wrap, false);
  }

  function upgradeComboSelect(selectEl) {
    if (!selectEl || selectEl.dataset.comboReady === "1") {
      rebuildComboSelect(selectEl);
      return selectEl?.closest(".combo-select") || null;
    }
    const wrap = document.createElement("div");
    wrap.className = "combo-select";
    selectEl.parentNode.insertBefore(wrap, selectEl);
    wrap.appendChild(selectEl);
    selectEl.classList.add("combo-select-native");
    selectEl.dataset.comboReady = "1";
    selectEl.setAttribute("tabindex", "-1");
    selectEl.setAttribute("aria-hidden", "true");

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "combo-select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.innerHTML =
      `<span class="combo-select-trigger-label"></span><span class="combo-select-caret" aria-hidden="true">▾</span>`;

    const list = document.createElement("div");
    list.className = "combo-select-list";
    list.hidden = true;
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-hidden", "true");

    wrap.appendChild(trigger);
    wrap.appendChild(list);

    trigger.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (selectEl.disabled || trigger.disabled) return;
      const willOpen = !wrap.classList.contains("open");
      closeAllComboSelects(willOpen ? wrap : null);
      setComboSelectOpen(wrap, willOpen);
    });

    selectEl.addEventListener("change", () => rebuildComboSelect(selectEl));
    rebuildComboSelect(selectEl);
    return wrap;
  }

  function syncTableComboSelects() {
    for (const id of TABLE_COMBO_SELECT_IDS) {
      const sel = document.getElementById(id);
      if (sel) upgradeComboSelect(sel);
    }
  }

  /** Visible select/nav text: always include display name + table_key (never blank). */
  function formatTableChoiceLabel(tableOrKey, { prefix = "" } = {}) {
    let key = "";
    let label = "";
    if (typeof tableOrKey === "string") {
      key = tableOrKey;
      const found = (state.customTables || []).find((t) => t.table_key === key);
      label = (found && found.label) || "";
    } else if (tableOrKey && typeof tableOrKey === "object") {
      key = String(tableOrKey.table_key || "").trim();
      label = String(tableOrKey.label || "").trim();
    }
    const display = label || key || "(unnamed table)";
    const text =
      key && display !== key ? `${display} (${key})` : display || key || "(unnamed table)";
    return prefix ? `${prefix}${text}` : text;
  }

  function formatBuiltinTableChoiceLabel(typeName) {
    return `CMDB: ${typeName} (${typeName})`;
  }

  function renderCustomTablesNav() {
    const wrap = $("#navCustomTables");
    const section = $("#navCustomTablesSection");
    if (!wrap) return;
    const tables = state.customTables || [];
    if (section) section.hidden = tables.length === 0;
    wrap.innerHTML = tables
      .map(
        (t) => `
      <button type="button" class="nav-item" data-tab="ct:${escapeAttr(t.table_key)}" title="${escapeAttr(
          formatTableChoiceLabel(t)
        )}">
        <span class="nav-ico" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg></span>
        ${escapeHtml(formatTableChoiceLabel(t))}
      </button>`
      )
      .join("");
    wrap.querySelectorAll(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => showTab(btn.getAttribute("data-tab")));
    });
  }

  function populateCustomTableSelects() {
    const sel = $("#ctSelectedTable");
    if (sel) {
      const prev = sel.value || state.selectedCustomTableKey || "";
      const tables = state.customTables || [];
      if (!tables.length) {
        sel.innerHTML = `<option value="">— no custom tables yet —</option>`;
      } else {
        sel.innerHTML = tables
          .map(
            (t) =>
              `<option value="${escapeAttr(t.table_key)}">${escapeHtml(
                formatTableChoiceLabel(t)
              )}</option>`
          )
          .join("");
      }
      if (prev && [...sel.options].some((o) => o.value === prev)) {
        sel.value = prev;
      }
      if (sel.value) state.selectedCustomTableKey = sel.value;
    }
    populateRefTableSelect();
    populateRelTableSelects();
    syncTableComboSelects();
  }

  function populateRefTableSelect() {
    const sel = $("#ccRefTable");
    if (!sel) return;
    const prev = sel.value;
    const builtins = ["Server", "Network", "Middleware", "Database", "Application"];
    const customs = (state.customTables || []).filter(
      (t) => t.table_key !== state.selectedCustomTableKey
    );
    sel.innerHTML =
      `<option value="">— select target —</option>` +
      builtins
        .map(
          (t) =>
            `<option value="${escapeAttr(t)}">${escapeHtml(
              formatBuiltinTableChoiceLabel(t)
            )}</option>`
        )
        .join("") +
      customs
        .map(
          (t) =>
            `<option value="${escapeAttr(t.table_key)}">${escapeHtml(
              formatTableChoiceLabel(t, { prefix: "Custom: " })
            )}</option>`
        )
        .join("");
    if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
    upgradeComboSelect(sel);
  }

  function populateRelTableSelects() {
    for (const id of ["#relSourceTable", "#relTargetTable"]) {
      const sel = $(id);
      if (!sel) continue;
      const prev = sel.value;
      const builtins = ["Server", "Network", "Middleware", "Database", "Application"];
      sel.innerHTML =
        `<option value="">CMDB component (any)</option>` +
        builtins
          .map(
            (t) =>
              `<option value="${escapeAttr(t)}">${escapeHtml(
                formatBuiltinTableChoiceLabel(t)
              )}</option>`
          )
          .join("") +
        (state.customTables || [])
          .map(
            (t) =>
              `<option value="${escapeAttr(t.table_key)}">${escapeHtml(
                formatTableChoiceLabel(t, { prefix: "Custom: " })
              )}</option>`
          )
          .join("");
      if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
      upgradeComboSelect(sel);
    }
    syncRelEntityDatalists();
  }

  function renderCustomTableList() {
    const tbody = $("#customTableBody");
    if (!tbody) return;
    tbody.innerHTML = "";
    for (const t of state.customTables || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(t.table_key)}</td>
        <td>${escapeHtml(t.label || "")}</td>
        <td>${(t.columns || []).length}</td>
        <td>${t.active === false ? "no" : "yes"}</td>
        <td class="actions">
          ${
            can("config:write")
              ? `<button type="button" class="secondary" data-ct-edit="${escapeAttr(
                  t.table_key
                )}">Edit</button>`
              : ""
          }
          <button type="button" class="secondary" data-ct-browse="${escapeAttr(
            t.table_key
          )}">Open</button>
        </td>`;
      tbody.appendChild(tr);
    }
  }

  function renderCustomColumns() {
    const tbody = $("#customColumnBody");
    if (!tbody) return;
    tbody.innerHTML = "";
    const table = selectedCustomTable();
    if (!table) return;
    for (const col of table.columns || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(col.column_key)}</td>
        <td>${escapeHtml(col.label || "")}</td>
        <td>${escapeHtml(col.field_type || "")}</td>
        <td class="mono">${escapeHtml(col.reference_table || "—")}</td>
        <td>${col.required ? "yes" : "no"}</td>
        <td class="actions">
          ${
            can("config:write")
              ? `<button type="button" class="secondary" data-cc-edit="${escapeAttr(
                  col.column_key
                )}">Edit</button>
          <button type="button" class="danger" data-cc-del="${escapeAttr(
            col.column_key
          )}">Delete</button>`
              : `<span class="hint">Read-only</span>`
          }
        </td>`;
      tbody.appendChild(tr);
    }
  }

  function resetCustomTableForm() {
    state.editingCtKey = null;
    const form = $("#customTableForm");
    form?.reset();
    if ($("#ctKey")) {
      $("#ctKey").disabled = false;
      $("#ctKey").readOnly = false;
    }
    if ($("#ctActive")) $("#ctActive").checked = true;
    $("#ctActiveWrap")?.classList.add("hidden");
    if ($("#ctSubmitBtn")) $("#ctSubmitBtn").textContent = "Create table";
    $("#ctEditHint")?.classList.add("hidden");
    $("#btnCtCancelEdit")?.classList.add("hidden");
  }

  function beginEditCustomTable(tableKey) {
    const item = (state.customTables || []).find((t) => t.table_key === tableKey);
    if (!item) {
      toast(`Custom table '${tableKey}' not found`, true);
      return;
    }
    state.editingCtKey = tableKey;
    state.selectedCustomTableKey = tableKey;
    if ($("#ctSelectedTable")) $("#ctSelectedTable").value = tableKey;
    $("#ctKey").value = item.table_key;
    $("#ctKey").disabled = true;
    $("#ctKey").readOnly = true;
    $("#ctLabel").value = item.label || "";
    $("#ctDesc").value = item.description || "";
    if ($("#ctActive")) $("#ctActive").checked = item.active !== false;
    $("#ctActiveWrap")?.classList.remove("hidden");
    if ($("#ctSubmitBtn")) $("#ctSubmitBtn").textContent = "Save table";
    $("#ctEditHint")?.classList.remove("hidden");
    $("#btnCtCancelEdit")?.classList.remove("hidden");
    $("#ctLabel")?.focus();
    $("#customTableForm")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    populateRefTableSelect();
    renderCustomColumns();
  }

  function resetCustomColumnForm() {
    state.editingCcKey = null;
    const form = $("#customColumnForm");
    form?.reset();
    if ($("#ccKey")) {
      $("#ccKey").disabled = false;
      $("#ccKey").readOnly = false;
    }
    if ($("#ccType")) $("#ccType").value = "string";
    syncReferenceTargetControl();
    if ($("#ccSubmitBtn")) $("#ccSubmitBtn").textContent = "Add column";
    $("#ccEditHint")?.classList.add("hidden");
    $("#btnCcCancelEdit")?.classList.add("hidden");
  }

  function beginEditCustomColumn(columnKey) {
    const table = selectedCustomTable();
    const col = (table?.columns || []).find((c) => c.column_key === columnKey);
    if (!col) {
      toast(`Column '${columnKey}' not found`, true);
      return;
    }
    state.editingCcKey = columnKey;
    $("#ccKey").value = col.column_key;
    $("#ccKey").disabled = true;
    $("#ccKey").readOnly = true;
    $("#ccLabel").value = col.label || "";
    $("#ccType").value = col.field_type || "string";
    $("#ccEnum").value = (col.enum_values || []).join(", ");
    $("#ccRequired").checked = !!col.required;
    const isRef = col.field_type === "reference";
    populateRefTableSelect();
    if (isRef && $("#ccRefTable")) {
      $("#ccRefTable").value = col.reference_table || "";
    }
    syncReferenceTargetControl();
    if ($("#ccSubmitBtn")) $("#ccSubmitBtn").textContent = "Save column";
    $("#ccEditHint")?.classList.remove("hidden");
    $("#btnCcCancelEdit")?.classList.remove("hidden");
    $("#ccLabel")?.focus();
    $("#customColumnForm")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function loadCustomTables() {
    const data = await api("/api/custom-tables");
    state.customTables = data.items || [];
    if (
      state.selectedCustomTableKey &&
      !state.customTables.some((t) => t.table_key === state.selectedCustomTableKey)
    ) {
      state.selectedCustomTableKey = state.customTables[0]?.table_key || null;
    }
    if (!state.selectedCustomTableKey && state.customTables[0]) {
      state.selectedCustomTableKey = state.customTables[0].table_key;
    }
    renderCustomTablesNav();
    populateCustomTableSelects();
    renderCustomTableList();
    renderCustomColumns();
  }

  async function saveCustomTable(event) {
    event.preventDefault();
    const tableKey = (state.editingCtKey || $("#ctKey").value.trim()).trim();
    const label = $("#ctLabel").value.trim();
    const description = $("#ctDesc").value.trim() || null;
    try {
      if (state.editingCtKey) {
        await api(`/api/custom-tables/${encodeURIComponent(state.editingCtKey)}`, {
          method: "PUT",
          body: JSON.stringify({
            label,
            description,
            active: $("#ctActive")?.checked !== false,
          }),
        });
        toast(`Custom table '${state.editingCtKey}' updated`);
      } else {
        await api("/api/custom-tables", {
          method: "POST",
          body: JSON.stringify({
            table_key: tableKey,
            label,
            description,
            columns: [],
          }),
        });
        toast("Custom table created");
        state.selectedCustomTableKey = tableKey;
      }
      resetCustomTableForm();
      await loadCustomTables();
    } catch (err) {
      toast(err.message || "Save table failed", true);
    }
  }

  async function saveCustomColumn(event) {
    event.preventDefault();
    const tableKey = $("#ctSelectedTable")?.value || state.selectedCustomTableKey;
    if (!tableKey) {
      toast("Select a table first", true);
      return;
    }
    const field_type = $("#ccType").value;
    const columnKey = (state.editingCcKey || $("#ccKey").value.trim()).trim();
    const refTarget = ($("#ccRefTable")?.value || "").trim();
    // Reference target is required only for reference columns; empty OK for string/other.
    if (field_type === "reference" && !refTarget) {
      toast("Reference target is required when type is reference", true);
      const wrap = $("#ccRefTable")?.closest(".combo-select");
      if (wrap) {
        closeAllComboSelects(wrap);
        setComboSelectOpen(wrap, true);
      }
      return;
    }
    const payload = {
      label: $("#ccLabel").value.trim(),
      field_type,
      required: $("#ccRequired").checked,
      enum_values:
        field_type === "enum"
          ? $("#ccEnum")
              .value.split(",")
              .map((s) => s.trim())
              .filter(Boolean)
          : [],
      reference_table: field_type === "reference" ? refTarget || null : null,
    };
    try {
      if (state.editingCcKey) {
        await api(
          `/api/custom-tables/${encodeURIComponent(tableKey)}/columns/${encodeURIComponent(
            state.editingCcKey
          )}`,
          {
            method: "PUT",
            body: JSON.stringify(payload),
          }
        );
        toast(`Column '${state.editingCcKey}' updated`);
      } else {
        await api(`/api/custom-tables/${encodeURIComponent(tableKey)}/columns`, {
          method: "POST",
          body: JSON.stringify({ column_key: columnKey, ...payload }),
        });
        toast("Column added");
      }
      resetCustomColumnForm();
      await loadCustomTables();
    } catch (err) {
      toast(err.message || "Save column failed", true);
    }
  }

  async function loadCustomRecords() {
    const tableKey = state.selectedCustomTableKey;
    const table = selectedCustomTable();
    if (!tableKey || !table) {
      $("#customRecordsTitle").textContent = "Custom records";
      $("#customRecordsHint").textContent = "Select a custom table from the sidebar.";
      $("#customRecordBody").innerHTML = "";
      return;
    }
    $("#customRecordsTitle").textContent = formatTableChoiceLabel(table);
    $("#customRecordsHint").textContent = `table_key=${tableKey} · records in cmdb_custom_records`;
    const params = new URLSearchParams({
      page: String(state.customRecordPage),
      page_size: String(state.pageSize),
    });
    const q = $("#customRecordSearch")?.value.trim();
    if (q) params.set("q", q);
    const data = await api(
      `/api/custom-tables/${encodeURIComponent(tableKey)}/records?${params}`
    );
    state.customRecordTotalPages = data.total_pages || 1;
    $("#customRecordPageInfo").textContent =
      `Page ${data.page} / ${state.customRecordTotalPages || 1} · ${data.total} records`;
    $("#btnCustomRecordPrev").disabled = data.page <= 1;
    $("#btnCustomRecordNext").disabled = data.page >= (data.total_pages || 1);
    const cols = table.columns || [];
    const head = $("#customRecordHeadRow");
    head.innerHTML =
      `<th>Record ID</th><th>Display name</th>` +
      cols
        .slice(0, 6)
        .map((c) => `<th>${escapeHtml(c.label || c.column_key)}</th>`)
        .join("") +
      `<th>Actions</th>`;
    const tbody = $("#customRecordBody");
    tbody.innerHTML = "";
    for (const row of data.items || []) {
      const fields = row.fields || {};
      const tr = document.createElement("tr");
      const fieldCells = cols
        .slice(0, 6)
        .map((c) => {
          const v = fields[c.column_key];
          if (v && typeof v === "object" && v.ref_id) {
            return `<td class="mono">${escapeHtml(v.ref_id)} [${escapeHtml(
              v.ref_table || ""
            )}]</td>`;
          }
          return `<td>${escapeHtml(v == null ? "—" : String(v))}</td>`;
        })
        .join("");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(row.record_id)}</td>
        <td>${escapeHtml(row.display_name || "")}</td>
        ${fieldCells}
        <td>
          ${
            can("cmdb:write")
              ? `<button type="button" class="secondary" data-cr-edit="${escapeAttr(
                  row.record_id
                )}">Edit</button>
          <button type="button" class="danger" data-cr-del="${escapeAttr(
            row.record_id
          )}">Delete</button>`
              : `<span class="hint">Read-only</span>`
          }
        </td>`;
      tbody.appendChild(tr);
    }
  }

  function buildCustomRecordFieldInputs(table, values = {}) {
    const wrap = $("#customRecordFields");
    if (!wrap) return;
    wrap.innerHTML = `
      <label>Record ID<input id="crId" placeholder="auto if blank" ${
        state.editingCustomRecordId ? "disabled" : ""
      } /></label>
      <label>Display name<input id="crDisplayName" required /></label>`;
    for (const col of table.columns || []) {
      const key = col.column_key;
      const val = values[key];
      const id = `crField_${key}`;
      let control = "";
      if (col.field_type === "boolean") {
        control = `<label><span>${escapeHtml(col.label)}</span><input id="${id}" type="checkbox" ${
          val ? "checked" : ""
        } /></label>`;
      } else if (col.field_type === "enum") {
        const opts = (col.enum_values || [])
          .map(
            (e) =>
              `<option value="${escapeAttr(e)}" ${
                val === e ? "selected" : ""
              }>${escapeHtml(e)}</option>`
          )
          .join("");
        control = `<label>${escapeHtml(col.label)}
          <select id="${id}" ${col.required ? "required" : ""}>
            <option value="">—</option>${opts}
          </select></label>`;
      } else if (col.field_type === "reference") {
        const refId = val && typeof val === "object" ? val.ref_id || "" : "";
        control = `<label>${escapeHtml(col.label)} → ${escapeHtml(col.reference_table || "")}
          <input id="${id}" class="mono" list="entityIdList" placeholder="ref id"
            value="${escapeAttr(refId)}" ${col.required ? "required" : ""} />
        </label>`;
      } else if (col.field_type === "number") {
        control = `<label>${escapeHtml(col.label)}
          <input id="${id}" type="number" value="${escapeAttr(
          val == null ? "" : String(val)
        )}" ${col.required ? "required" : ""} /></label>`;
      } else {
        control = `<label>${escapeHtml(col.label)}
          <input id="${id}" value="${escapeAttr(val == null ? "" : String(val))}" ${
          col.required ? "required" : ""
        } /></label>`;
      }
      wrap.insertAdjacentHTML("beforeend", control);
    }
  }

  function collectCustomRecordFields(table) {
    const fields = {};
    for (const col of table.columns || []) {
      const el = $(`#crField_${col.column_key}`);
      if (!el) continue;
      if (col.field_type === "boolean") {
        fields[col.column_key] = el.checked;
      } else if (col.field_type === "reference") {
        const refId = el.value.trim();
        fields[col.column_key] = refId
          ? { ref_id: refId, ref_table: col.reference_table }
          : null;
      } else if (col.field_type === "number") {
        const raw = el.value.trim();
        fields[col.column_key] = raw === "" ? null : Number(raw);
      } else {
        fields[col.column_key] = el.value.trim() || null;
      }
    }
    return fields;
  }

  function openCustomRecordCreate() {
    const table = selectedCustomTable();
    if (!table) {
      toast("Select a custom table first", true);
      return;
    }
    state.editingCustomRecordId = null;
    buildCustomRecordFieldInputs(table, {});
    $("#crId").disabled = false;
    $("#crId").value = "";
    $("#crDisplayName").value = "";
    $("#customRecordModalTitle").textContent = `Add ${table.label || table.table_key}`;
    $("#customRecordModal").classList.add("open");
  }

  async function openCustomRecordEdit(recordId) {
    const table = selectedCustomTable();
    if (!table) return;
    const doc = await api(
      `/api/custom-tables/${encodeURIComponent(table.table_key)}/records/${encodeURIComponent(
        recordId
      )}`
    );
    state.editingCustomRecordId = recordId;
    buildCustomRecordFieldInputs(table, doc.fields || {});
    $("#crId").value = doc.record_id;
    $("#crId").disabled = true;
    $("#crDisplayName").value = doc.display_name || "";
    $("#customRecordModalTitle").textContent = `Edit ${recordId}`;
    $("#customRecordModal").classList.add("open");
  }

  async function saveCustomRecord(event) {
    event.preventDefault();
    const table = selectedCustomTable();
    if (!table) return;
    const payload = {
      display_name: $("#crDisplayName").value.trim(),
      fields: collectCustomRecordFields(table),
    };
    try {
      if (state.editingCustomRecordId) {
        await api(
          `/api/custom-tables/${encodeURIComponent(table.table_key)}/records/${encodeURIComponent(
            state.editingCustomRecordId
          )}`,
          { method: "PUT", body: JSON.stringify(payload) }
        );
        toast("Record updated");
      } else {
        const rid = $("#crId").value.trim();
        if (rid) payload.record_id = rid;
        await api(
          `/api/custom-tables/${encodeURIComponent(table.table_key)}/records`,
          { method: "POST", body: JSON.stringify(payload) }
        );
        toast("Record created");
      }
      $("#customRecordModal").classList.remove("open");
      state.editingCustomRecordId = null;
      await loadCustomRecords();
      await refreshEntityIdList();
    } catch (err) {
      toast(err.message || "Record save failed", true);
    }
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
    if (!state.columnConfigs.relationships) {
      await loadColumnConfigurations();
    }
    const columns = visibleColumns("relationships");
    applyHeadRow("#relationshipHeadRow", columns);
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
      tr.innerHTML = columns.map((c) => relationshipCellHtml(row, c.column_key)).join("");
      tbody.appendChild(tr);
    }
  }

  function renderColumnSettingsEditor() {
    const tbody = $("#columnSettingsBody");
    const meta = $("#colConfigMeta");
    if (!tbody) return;
    const cols = (state.columnEditor.columns || [])
      .slice()
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    state.columnEditor.columns = cols.map((c, idx) => ({ ...c, order: idx }));
    if (meta) {
      const src = state.columnEditor.is_default ? "catalog defaults" : "saved tenant config";
      meta.textContent = `Editing ${state.columnEditor.grid_key} · ${src}. Locked columns cannot be hidden. Custom fields appear as toggleable columns.`;
    }
    tbody.innerHTML = "";
    cols.forEach((col, idx) => {
      const tr = document.createElement("tr");
      const locked = !!col.locked;
      const customHint = col.source === "custom_field"
        ? ` · custom${(col.applies_to || []).length ? ` · ${(col.applies_to || []).join(",")}` : ""}`
        : "";
      tr.innerHTML = `
        <td class="mono">${idx + 1}</td>
        <td>
          ${escapeHtml(col.label || col.column_key)}
          <div class="hint mono">${escapeHtml(col.column_key)}${locked ? " · locked" : ""}${customHint}</div>
        </td>
        <td>
          <input type="checkbox" data-col-vis="${escapeAttr(col.column_key)}"
            ${col.visible !== false ? "checked" : ""} ${locked ? "disabled" : ""} />
        </td>
        <td>
          <input type="number" min="40" max="1200" placeholder="auto"
            data-col-width="${escapeAttr(col.column_key)}"
            value="${col.width != null ? escapeAttr(col.width) : ""}" />
        </td>
        <td>
          <select data-col-pin="${escapeAttr(col.column_key)}">
            <option value="" ${!col.pinned ? "selected" : ""}>None</option>
            <option value="left" ${col.pinned === "left" ? "selected" : ""}>Left</option>
            <option value="right" ${col.pinned === "right" ? "selected" : ""}>Right</option>
          </select>
        </td>
        <td class="actions">
          <button type="button" class="secondary" data-col-up="${escapeAttr(col.column_key)}" ${idx === 0 ? "disabled" : ""}>Up</button>
          <button type="button" class="secondary" data-col-down="${escapeAttr(col.column_key)}" ${idx === cols.length - 1 ? "disabled" : ""}>Down</button>
        </td>`;
      tbody.appendChild(tr);
    });
  }

  function syncColumnEditorFromDom() {
    const byKey = Object.fromEntries(
      (state.columnEditor.columns || []).map((c) => [c.column_key, { ...c }])
    );
    for (const el of $$("[data-col-vis]")) {
      const key = el.getAttribute("data-col-vis");
      if (!byKey[key]) continue;
      if (!byKey[key].locked) byKey[key].visible = el.checked;
      else byKey[key].visible = true;
    }
    for (const el of $$("[data-col-width]")) {
      const key = el.getAttribute("data-col-width");
      if (!byKey[key]) continue;
      const raw = String(el.value || "").trim();
      byKey[key].width = raw ? Number(raw) : null;
      if (Number.isNaN(byKey[key].width)) byKey[key].width = null;
    }
    for (const el of $$("[data-col-pin]")) {
      const key = el.getAttribute("data-col-pin");
      if (!byKey[key]) continue;
      const val = el.value;
      byKey[key].pinned = val === "left" || val === "right" ? val : null;
    }
    state.columnEditor.columns = Object.values(byKey).sort(
      (a, b) => (a.order ?? 0) - (b.order ?? 0)
    );
  }

  function moveColumnEditor(key, direction) {
    syncColumnEditorFromDom();
    const cols = state.columnEditor.columns.slice().sort((a, b) => a.order - b.order);
    const idx = cols.findIndex((c) => c.column_key === key);
    if (idx < 0) return;
    const swap = idx + direction;
    if (swap < 0 || swap >= cols.length) return;
    const tmp = cols[idx];
    cols[idx] = cols[swap];
    cols[swap] = tmp;
    state.columnEditor.columns = cols.map((c, i) => ({ ...c, order: i }));
    renderColumnSettingsEditor();
  }

  async function openColumnSettings(gridKey) {
    const key = gridKey || $("#colGridKey")?.value || "inventory";
    if ($("#colGridKey")) $("#colGridKey").value = key;
    const cfg = await api(`/api/column-configurations/${encodeURIComponent(key)}`);
    state.columnConfigs[key] = cfg;
    state.columnEditor = {
      grid_key: key,
      columns: (cfg.columns || []).map((c) => ({ ...c })),
      is_default: !!cfg.is_default,
    };
    renderColumnSettingsEditor();
  }

  async function saveColumnSettings() {
    syncColumnEditorFromDom();
    const key = state.columnEditor.grid_key;
    const payload = {
      columns: state.columnEditor.columns.map((c) => ({
        column_key: c.column_key,
        visible: c.locked ? true : !!c.visible,
        order: c.order,
        width: c.width == null || c.width === "" ? null : Number(c.width),
        pinned: c.pinned || null,
      })),
    };
    const saved = await api(`/api/column-configurations/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    state.columnConfigs[key] = saved;
    state.columnEditor = {
      grid_key: key,
      columns: (saved.columns || []).map((c) => ({ ...c })),
      is_default: !!saved.is_default,
    };
    renderColumnSettingsEditor();
    if (key === "inventory") await loadInventory();
    if (key === "relationships") await loadRelationships();
    toast(`Saved ${key} column settings`);
  }

  async function resetColumnSettings() {
    const key = state.columnEditor.grid_key || $("#colGridKey")?.value || "inventory";
    if (!confirm(`Reset ${key} columns to catalog defaults?`)) return;
    const reset = await api(`/api/column-configurations/${encodeURIComponent(key)}`, {
      method: "DELETE",
    });
    state.columnConfigs[key] = reset;
    state.columnEditor = {
      grid_key: key,
      columns: (reset.columns || []).map((c) => ({ ...c })),
      is_default: !!reset.is_default,
    };
    renderColumnSettingsEditor();
    if (key === "inventory") await loadInventory();
    if (key === "relationships") await loadRelationships();
    toast(`Reset ${key} column settings`);
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
    populateRelTableSelects();
    if ($("#relSourceTable")) $("#relSourceTable").value = "";
    if ($("#relTargetTable")) $("#relTargetTable").value = "";
    syncTableComboSelects();
    syncRelEntityDatalists();
    if ($("#relType").options.length) $("#relType").selectedIndex = 0;
    updateRelTypeHint();
    $("#relModalTitle").textContent = "Add relationship";
    $("#relationshipModal").classList.add("open");
  }

  async function openRelEdit(id) {
    const doc = await api(`/api/relationships/${encodeURIComponent(id)}`);
    state.editingRelId = id;
    populateRelTableSelects();
    $("#relId").value = doc.relationship_id;
    $("#relId").disabled = true;
    $("#relType").value = doc.relationship_type;
    if ($("#relSourceTable")) $("#relSourceTable").value = doc.source_table || "";
    if ($("#relTargetTable")) $("#relTargetTable").value = doc.target_table || "";
    syncTableComboSelects();
    syncRelEntityDatalists();
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
    const sourceTable = $("#relSourceTable")?.value.trim() || null;
    const targetTable = $("#relTargetTable")?.value.trim() || null;
    const payload = {
      source_component_id: $("#relSource").value.trim(),
      target_component_id: $("#relTarget").value.trim(),
      source_table: sourceTable,
      target_table: targetTable,
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
        toast("Source and target entity IDs are required", true);
        return;
      }
      if (
        payload.source_component_id === payload.target_component_id &&
        (payload.source_table || "") === (payload.target_table || "")
      ) {
        toast("Source and target cannot be the same entity", true);
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
    // Keep help “i” balloons from toggling parent <label> controls.
    document.addEventListener("click", (e) => {
      const tip = e.target.closest?.(".help-balloon");
      if (tip) {
        e.preventDefault();
        e.stopPropagation();
        tip.focus();
        return;
      }
      if (!e.target.closest?.(".combo-select")) closeAllComboSelects();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAllComboSelects();
    });
    $("#btnConnect")?.addEventListener("click", connect);
    $("#loginBasicForm")?.addEventListener("submit", (e) => {
      e.preventDefault();
      connect();
    });
    $("#btnAuthPassToggle")?.addEventListener("click", toggleAuthPasswordVisibility);
    $("#authRemember")?.addEventListener("change", (e) => {
      if (!e.target?.checked) sessionStorage.removeItem(STORAGE_KEY);
    });
    $("#btnLoginPortalToggle")?.addEventListener("click", () => {
      const gate = $("#loginGate");
      const btn = $("#btnLoginPortalToggle");
      if (!gate || !btn) return;
      const open = gate.classList.toggle("portal-open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
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
    $("#tenantSwitcher")?.addEventListener("change", async (e) => {
      const next = e.target?.value;
      if (!next) return;
      if (!state.switchableForUser) {
        toast(
          state.authMethod === "basic"
            ? "HTTP Basic cannot switch organizations"
            : "Organization switching requires multiple memberships",
          true
        );
        e.target.value = state.tenantId;
        return;
      }
      await switchOrganization(next);
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
    $("#btnRefreshAudit")?.addEventListener("click", async () => {
      if (!state.authenticated) {
        toast("Connect first", true);
        return;
      }
      try {
        const result = await loadAuditEvents();
        if (result && result.denied) return;
        toast("Audit log refreshed");
      } catch (err) {
        toast(err.message || "Audit refresh failed", true);
      }
    });
    $("#btnRbacOidcLogin")?.addEventListener("click", () => {
      $("#btnOidcLogin")?.click();
    });
    $("#btnRbacBasicFocus")?.addEventListener("click", () => {
      showLoginShell();
      $("#authUser")?.focus();
    });
    $("#tenantMembersBody")?.addEventListener("click", async (e) => {
      const btn = e.target?.closest?.(".btn-member-role-save");
      if (!btn) return;
      const mid = btn.getAttribute("data-membership-id");
      const select = $(
        `.member-role-select[data-membership-id="${CSS.escape(mid)}"]`
      );
      const role = select?.value;
      if (!mid || !role) return;
      btn.disabled = true;
      try {
        await saveMemberRole(mid, role);
      } catch (err) {
        toast(err.message || "Role update failed", true);
      } finally {
        btn.disabled = false;
      }
    });
    $("#orgInviteForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!can("users:admin")) {
        toast("Requires users:admin", true);
        return;
      }
      try {
        const res = await api(
          `/api/tenants/${encodeURIComponent(state.tenantId)}/invites`,
          {
            method: "POST",
            body: JSON.stringify({
              invitee_email: ($("#inviteEmail")?.value || "").trim() || null,
              invitee_username: ($("#inviteUsername")?.value || "").trim() || null,
              role: $("#inviteRole")?.value || "member",
            }),
          }
        );
        toast(`Invite created — token ${res.invite?.token || ""}`);
        await loadOrgInvitesPanel();
      } catch (err) {
        toast(err.message || "Invite failed", true);
      }
    });
    $("#orgInvitesBody")?.addEventListener("click", async (e) => {
      const btn = e.target?.closest?.(".btn-revoke-invite");
      if (!btn) return;
      const iid = btn.getAttribute("data-invite-id");
      if (!iid) return;
      try {
        await api(
          `/api/tenants/${encodeURIComponent(state.tenantId)}/invites/${encodeURIComponent(iid)}`,
          { method: "DELETE" }
        );
        toast("Invite revoked");
        await loadOrgInvitesPanel();
      } catch (err) {
        toast(err.message || "Revoke failed", true);
      }
    });
    $("#inviteAcceptForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const token = ($("#inviteAcceptToken")?.value || "").trim();
      if (!token) return;
      try {
        await api("/api/invites/accept", {
          method: "POST",
          body: JSON.stringify({ token }),
        });
        toast("Invite accepted");
        await loadTenancyContext();
      } catch (err) {
        toast(err.message || "Accept failed", true);
      }
    });
    $("#customRoleForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const perms = ($("#customRolePerms")?.value || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      try {
        await api(
          `/api/tenants/${encodeURIComponent(state.tenantId)}/custom-roles`,
          {
            method: "POST",
            body: JSON.stringify({
              role_key: ($("#customRoleKey")?.value || "").trim(),
              display_name: ($("#customRoleLabel")?.value || "").trim(),
              permissions: perms,
            }),
          }
        );
        toast("Custom role created");
        await Promise.all([loadCustomRolesPanel(), loadRolesPanel()]);
      } catch (err) {
        toast(err.message || "Custom role failed", true);
      }
    });
    $("#customRolesBody")?.addEventListener("click", async (e) => {
      const btn = e.target?.closest?.(".btn-delete-custom-role");
      if (!btn) return;
      const key = btn.getAttribute("data-role-key");
      if (!key) return;
      try {
        await api(
          `/api/tenants/${encodeURIComponent(state.tenantId)}/custom-roles/${encodeURIComponent(key)}`,
          { method: "DELETE" }
        );
        toast("Custom role deleted");
        await Promise.all([loadCustomRolesPanel(), loadRolesPanel()]);
      } catch (err) {
        toast(err.message || "Delete failed", true);
      }
    });
    $("#oidcSettingsForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!state.isPlatformAdmin) {
        toast("Platform admin required", true);
        return;
      }
      try {
        await api("/api/platform/oidc-settings", {
          method: "PUT",
          body: JSON.stringify({
            active: !!$("#oidcDbActive")?.checked,
            oidc_enabled: !!$("#oidcDbEnabled")?.checked,
            issuer: ($("#oidcDbIssuer")?.value || "").trim(),
            client_id: ($("#oidcDbClientId")?.value || "").trim(),
            redirect_uri: ($("#oidcDbRedirect")?.value || "").trim(),
            scopes: ($("#oidcDbScopes")?.value || "").trim(),
            client_secret_env_ref: ($("#oidcDbSecretRef")?.value || "").trim(),
          }),
        });
        toast("OIDC settings saved");
        await loadOidcSettingsPanel();
      } catch (err) {
        toast(err.message || "OIDC settings failed", true);
      }
    });
    $("#auditActionFilter")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        loadAuditEvents()
          .then((result) => {
            if (result && result.denied) return;
          })
          .catch((err) => toast(err.message, true));
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
    $("#btnCfCancelEdit")?.addEventListener("click", () => {
      resetCustomFieldForm();
    });
    $("#colGridKey")?.addEventListener("change", async () => {
      try {
        await openColumnSettings($("#colGridKey").value);
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnColReload")?.addEventListener("click", async () => {
      try {
        await openColumnSettings($("#colGridKey")?.value || "inventory");
        toast("Column settings reloaded");
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnColSave")?.addEventListener("click", async () => {
      try {
        await saveColumnSettings();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnColReset")?.addEventListener("click", async () => {
      try {
        await resetColumnSettings();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#columnSettingsBody")?.addEventListener("click", (e) => {
      const up = e.target.getAttribute("data-col-up");
      const down = e.target.getAttribute("data-col-down");
      if (up) moveColumnEditor(up, -1);
      if (down) moveColumnEditor(down, 1);
    });
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
        await Promise.all([refreshComponentIdList(), refreshEntityIdList(), populateRelTableSelects()]);
        openRelCreate();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#customTableForm")?.addEventListener("submit", saveCustomTable);
    $("#customColumnForm")?.addEventListener("submit", saveCustomColumn);
    $("#btnCtCancelEdit")?.addEventListener("click", () => resetCustomTableForm());
    $("#btnCcCancelEdit")?.addEventListener("click", () => resetCustomColumnForm());
    $("#btnCtEditSelected")?.addEventListener("click", () => {
      const key = $("#ctSelectedTable")?.value || state.selectedCustomTableKey;
      if (!key) {
        toast("Select a table first", true);
        return;
      }
      beginEditCustomTable(key);
    });
    $("#ctSelectedTable")?.addEventListener("change", () => {
      state.selectedCustomTableKey = $("#ctSelectedTable").value;
      if (state.editingCcKey) resetCustomColumnForm();
      populateRefTableSelect();
      renderCustomColumns();
    });
    $("#ccType")?.addEventListener("change", () => {
      syncReferenceTargetControl();
    });
    $("#btnCtDelete")?.addEventListener("click", async () => {
      const key = $("#ctSelectedTable")?.value || state.selectedCustomTableKey;
      if (!key) return;
      if (!confirm(`Delete custom table '${key}' and all its records?`)) return;
      try {
        await api(`/api/custom-tables/${encodeURIComponent(key)}`, { method: "DELETE" });
        toast(`Deleted table ${key}`);
        state.selectedCustomTableKey = null;
        if (state.editingCtKey === key) resetCustomTableForm();
        resetCustomColumnForm();
        await loadCustomTables();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#customColumnBody")?.addEventListener("click", async (e) => {
      const editKey = e.target.getAttribute("data-cc-edit");
      if (editKey) {
        beginEditCustomColumn(editKey);
        return;
      }
      const key = e.target.getAttribute("data-cc-del");
      if (!key) return;
      const tableKey = $("#ctSelectedTable")?.value || state.selectedCustomTableKey;
      if (!tableKey) return;
      if (!confirm(`Delete column '${key}'?`)) return;
      try {
        await api(
          `/api/custom-tables/${encodeURIComponent(tableKey)}/columns/${encodeURIComponent(key)}`,
          { method: "DELETE" }
        );
        toast("Column deleted");
        if (state.editingCcKey === key) resetCustomColumnForm();
        await loadCustomTables();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#customTableBody")?.addEventListener("click", (e) => {
      const editKey = e.target.getAttribute("data-ct-edit");
      if (editKey) {
        beginEditCustomTable(editKey);
        return;
      }
      const key = e.target.getAttribute("data-ct-browse");
      if (key) showTab(`ct:${key}`);
    });
    $("#btnAddCustomRecord")?.addEventListener("click", async () => {
      try {
        await refreshEntityIdList();
        openCustomRecordCreate();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnReloadCustomRecords")?.addEventListener("click", async () => {
      try {
        await loadCustomRecords();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnCustomRecordSearch")?.addEventListener("click", async () => {
      state.customRecordPage = 1;
      try {
        await loadCustomRecords();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnCustomRecordPrev")?.addEventListener("click", async () => {
      state.customRecordPage = Math.max(1, state.customRecordPage - 1);
      await loadCustomRecords();
    });
    $("#btnCustomRecordNext")?.addEventListener("click", async () => {
      state.customRecordPage = Math.min(
        state.customRecordTotalPages || 1,
        state.customRecordPage + 1
      );
      await loadCustomRecords();
    });
    $("#customRecordForm")?.addEventListener("submit", saveCustomRecord);
    $("#btnCloseCustomRecordModal")?.addEventListener("click", () => {
      $("#customRecordModal").classList.remove("open");
      state.editingCustomRecordId = null;
    });
    $("#customRecordBody")?.addEventListener("click", async (e) => {
      const edit = e.target.getAttribute("data-cr-edit");
      const del = e.target.getAttribute("data-cr-del");
      try {
        if (edit) {
          await refreshEntityIdList();
          await openCustomRecordEdit(edit);
        }
        if (del) {
          const tableKey = state.selectedCustomTableKey;
          if (!tableKey) return;
          if (!confirm(`Delete record ${del}?`)) return;
          await api(
            `/api/custom-tables/${encodeURIComponent(tableKey)}/records/${encodeURIComponent(
              del
            )}`,
            { method: "DELETE" }
          );
          toast(`Deleted ${del}`);
          await loadCustomRecords();
          await refreshEntityIdList();
        }
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
    $("#relSourceTable")?.addEventListener("change", () => {
      syncRelEntityDatalists();
    });
    $("#relTargetTable")?.addEventListener("change", () => {
      syncRelEntityDatalists();
    });
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
      const editKey = e.target.getAttribute("data-cf-edit");
      if (editKey) {
        beginEditCustomField(editKey);
        return;
      }
      const key = e.target.getAttribute("data-cf-del");
      if (!key) return;
      if (!confirm(`Delete custom field definition '${key}'?`)) return;
      try {
        await api(`/api/custom-fields/${encodeURIComponent(key)}`, { method: "DELETE" });
        toast("Custom field deleted");
        if (state.editingCfKey === key) resetCustomFieldForm();
        await loadCustomFields();
        await loadColumnConfigurations();
        if (state.inventoryType || state.activeNav === "inventory") {
          await loadInventory();
        }
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
    // Default: full-page login only — app shell stays hidden until /api/me OK.
    showLoginShell();
    setSessionChip(false);
    showAuthErrorFromQuery();
    await loadAuthConfig();
    const resumed = await tryResumeSession();
    if (resumed) return;
    if (authHeader() && authConfig.basic_auth_enabled) {
      try {
        await connect();
      } catch (_) {
        showLoginShell();
      }
      return;
    }
    showLoginShell();
  });
})();
