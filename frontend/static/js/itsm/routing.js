/**
 * Bookmarkable SPA routes for ITSM / Monitoring (and shared tab navigation).
 *
 * Supported hashes:
 *   #tab=itsm-incidents&component_id=srv-1
 *   #tab-itsm-incidents&component_id=srv-1   (backlog-style alias)
 *
 * Optional path entries:
 *   /itsm or /itsm/ → ITSM dashboard when no hash
 *   /monitor or /monitor/ → Monitoring dashboard when no hash
 */
(function (global) {
  "use strict";

  const ITSM_TABS = new Set([
    "itsm-dashboard",
    "itsm-reports",
    "itsm-incidents",
    "itsm-changes",
    "itsm-problems",
    "itsm-approvals",
    "itsm-workflows",
    "itsm-sla",
    "itsm-knowledge",
    "itsm-notifications",
    "itsm-groups",
  ]);

  const MONITOR_TABS = new Set([
    "monitor-dashboard",
    "monitor-servers",
    "monitor-network",
    "monitor-applications",
    "monitor-databases",
    "monitor-logs",
    "monitor-alerts",
    "file-monitoring",
    "diagnostics",
  ]);

  let applying = false;
  let showTabFn = null;
  let onRouteApplied = null;

  function isItsmEntryPath(pathname) {
    const p = (pathname || "").replace(/\/+$/, "") || "/";
    return p === "/itsm";
  }

  function isMonitorEntryPath(pathname) {
    const p = (pathname || "").replace(/\/+$/, "") || "/";
    return p === "/monitor";
  }

  function normalizeHashRaw(hash) {
    let raw = String(hash || "").replace(/^#/, "").trim();
    if (!raw) return "";
    // #tab-itsm-incidents&… → #tab=itsm-incidents&…
    if (/^tab-[^=&]+/.test(raw) && !raw.startsWith("tab=")) {
      raw = raw.replace(/^tab-/, "tab=");
    }
    return raw;
  }

  function parseAppRoute(hash) {
    const raw = normalizeHashRaw(hash == null ? global.location?.hash : hash);
    if (!raw) {
      return {
        tab: null,
        component_id: null,
        incident_id: null,
        change_id: null,
        problem_id: null,
      };
    }
    const params = new URLSearchParams(raw);
    const tab = (params.get("tab") || "").trim() || null;
    return {
      tab,
      component_id: (params.get("component_id") || "").trim() || null,
      incident_id: (params.get("incident_id") || "").trim() || null,
      change_id: (params.get("change_id") || "").trim() || null,
      problem_id: (params.get("problem_id") || "").trim() || null,
    };
  }

  function buildAppHash(parts) {
    const p = new URLSearchParams();
    const tab = parts?.tab;
    if (tab) p.set("tab", tab);
    if (parts?.component_id) p.set("component_id", parts.component_id);
    if (parts?.incident_id) p.set("incident_id", parts.incident_id);
    if (parts?.change_id) p.set("change_id", parts.change_id);
    if (parts?.problem_id) p.set("problem_id", parts.problem_id);
    const qs = p.toString();
    return qs ? `#${qs}` : "";
  }

  function writeHash(parts, { replace = true } = {}) {
    if (applying) return;
    const next = buildAppHash(parts);
    const url = `${global.location.pathname}${global.location.search}${next}`;
    if (replace) {
      global.history.replaceState({}, "", url);
    } else {
      global.history.pushState({}, "", url);
    }
  }

  function syncTabHash(tabName, extra) {
    if (!tabName) return;
    const current = parseAppRoute();
    writeHash(
      {
        tab: tabName,
        component_id: extra?.component_id ?? current.component_id,
        incident_id: extra?.incident_id ?? null,
        change_id: extra?.change_id ?? null,
        problem_id: extra?.problem_id ?? null,
      },
      { replace: true }
    );
  }

  function resolveInitialTab() {
    const route = parseAppRoute();
    if (route.tab) return route;
    if (isItsmEntryPath(global.location?.pathname)) {
      return { ...route, tab: "itsm-dashboard" };
    }
    if (isMonitorEntryPath(global.location?.pathname)) {
      return { ...route, tab: "monitor-dashboard" };
    }
    return route;
  }

  async function applyRoute(route, { write = false } = {}) {
    const r = route || parseAppRoute();
    if (!r.tab || !showTabFn) return false;
    applying = true;
    try {
      if (write) {
        writeHash(r, { replace: true });
      } else if (
        !global.location.hash &&
        (isItsmEntryPath(global.location.pathname) ||
          isMonitorEntryPath(global.location.pathname))
      ) {
        writeHash({ tab: r.tab }, { replace: true });
      }
      showTabFn(r.tab);
      if (typeof onRouteApplied === "function") {
        await onRouteApplied(r);
      }
      return true;
    } finally {
      applying = false;
    }
  }

  async function applyDeepLinkExtras(route) {
    const r = route || parseAppRoute();
    if (r.component_id && global.SVRMON24ItsmDeeplinks?.setAllCiFilters) {
      global.SVRMON24ItsmDeeplinks.setAllCiFilters(r.component_id);
    }
    if (r.tab === "itsm-incidents" && r.component_id) {
      await global.SVRMON24ItsmIncidents?.filterByComponent?.(r.component_id);
    } else if (r.tab === "itsm-changes" && r.component_id) {
      await global.SVRMON24ItsmChanges?.filterByComponent?.(r.component_id);
    } else if (r.tab === "itsm-problems" && r.component_id) {
      await global.SVRMON24ItsmProblems?.filterByComponent?.(r.component_id);
    }
    if (r.incident_id && r.tab === "itsm-incidents") {
      await global.SVRMON24ItsmIncidents?.openIncident?.(r.incident_id);
    }
    if (r.change_id && r.tab === "itsm-changes") {
      await global.SVRMON24ItsmChanges?.openChange?.(r.change_id);
    }
    if (r.problem_id && r.tab === "itsm-problems") {
      await global.SVRMON24ItsmProblems?.openProblem?.(r.problem_id);
    }
  }

  function bindRouting({ showTab, onApplied } = {}) {
    if (typeof showTab === "function") showTabFn = showTab;
    if (typeof onApplied === "function") onRouteApplied = onApplied;
    global.addEventListener("hashchange", () => {
      if (applying) return;
      applyRoute(parseAppRoute());
    });
  }

  function navigateTo(parts, { replace = false } = {}) {
    writeHash(parts, { replace });
    return applyRoute(parseAppRoute(), { write: false });
  }

  global.SVRMON24ItsmRouting = {
    ITSM_TABS,
    MONITOR_TABS,
    isItsmEntryPath,
    isMonitorEntryPath,
    parseAppRoute,
    buildAppHash,
    writeHash,
    syncTabHash,
    resolveInitialTab,
    applyRoute,
    applyDeepLinkExtras,
    bindRouting,
    navigateTo,
    get isApplying() {
      return applying;
    },
  };
})(window);
