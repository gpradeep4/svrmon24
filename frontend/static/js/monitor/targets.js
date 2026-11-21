/* Monitoring domain health — SIMULATED targets synced from CMDB. */
(function (global) {
  "use strict";

  let apiFn = null;
  let toastFn = null;
  let canFn = () => false;

  const DOMAIN_TABS = {
    "monitor-servers": "server",
    "monitor-network": "network",
    "monitor-applications": "application",
    "monitor-databases": "database",
  };

  const DOMAIN_PREFIX = {
    server: "mtSrv",
    network: "mtNet",
    application: "mtApp",
    database: "mtDb",
  };

  function bindApi(api, { toast, can } = {}) {
    if (typeof api === "function") apiFn = api;
    if (typeof toast === "function") toastFn = toast;
    if (typeof can === "function") canFn = can;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function idFor(domain, suffix) {
    return `${DOMAIN_PREFIX[domain]}${suffix}`;
  }

  function statusPill(status) {
    const s = String(status || "unknown").toLowerCase();
    let cls = "status-pill";
    if (s === "healthy") cls += " ok";
    else if (s === "degraded") cls += " warning";
    else if (s === "down") cls += " danger";
    else if (s === "maintenance") cls += " warning";
    else cls += " muted";
    return `<span class="${cls}">${esc(s)}</span>`;
  }

  function metricsSummary(metrics) {
    const rows = Array.isArray(metrics) ? metrics : [];
    if (!rows.length) return "—";
    return rows
      .slice(0, 3)
      .map((m) => {
        const unit = m.unit ? ` ${m.unit}` : "";
        return `${m.metric_name}=${m.value}${unit}`;
      })
      .join(" · ");
  }

  function openCmdbCi(componentId, componentType) {
    const cid = (componentId || "").trim();
    if (!cid) return;
    const typeMap = {
      Server: "servers",
      Network: "network",
      Application: "applications",
      Database: "databases",
      Middleware: "middleware",
    };
    const tab = typeMap[componentType] || "inventory";
    const nav = document.querySelector(`.nav-item[data-tab="${tab}"]`);
    if (nav) nav.click();
    else {
      const inv = document.querySelector('.nav-item[data-tab="inventory"]');
      inv?.click();
    }
    window.setTimeout(() => {
      const viewBtn =
        document.querySelector(
          `#inventoryBody [data-view="${CSS.escape(cid)}"]`
        ) ||
        document.querySelector(`[data-view="${CSS.escape(cid)}"]`);
      if (viewBtn) viewBtn.click();
      else if (typeof toastFn === "function") {
        toastFn(`Open CMDB inventory and search for ${cid}`, false);
      }
    }, 220);
  }

  function readFilters(domain) {
    const q = document.getElementById(idFor(domain, "Search"))?.value?.trim() || "";
    const status =
      document.getElementById(idFor(domain, "Status"))?.value?.trim() || "";
    const collectMode =
      document.getElementById(idFor(domain, "CollectMode"))?.value?.trim() || "";
    const osFamily =
      document.getElementById(idFor(domain, "OsFamily"))?.value?.trim() || "";
    const targetKind =
      document.getElementById(idFor(domain, "TargetKind"))?.value?.trim() || "";
    return { q, status, collect_mode: collectMode, os_family: osFamily, target_kind: targetKind };
  }

  async function loadDomain(domain, { toast } = {}) {
    const notify = toast || toastFn;
    const body = document.getElementById(idFor(domain, "Body"));
    const meta = document.getElementById(idFor(domain, "Meta"));
    if (!apiFn || !body) return;
    const filters = readFilters(domain);
    const params = new URLSearchParams();
    params.set("domain", domain);
    params.set("page_size", "50");
    Object.entries(filters).forEach(([k, v]) => {
      if (v) params.set(k, v);
    });
    try {
      const data = await apiFn(`/api/monitor/targets?${params.toString()}`);
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} target(s) · SIMULATED · live_probes=false`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="8" class="hint">No targets yet. Use <strong>Sync from CMDB</strong> to create SIMULATED monitor targets for this domain.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const metrics = metricsSummary(row.latest_metrics);
          const kind = row.target_kind || "—";
          const os = row.os_family || row.os_name || "—";
          return `<tr data-target-id="${esc(row.target_id)}" data-component-id="${esc(row.component_id)}">
            <td>${esc(row.name_snapshot || "—")}</td>
            <td class="mono">${esc(row.component_id)}</td>
            <td>${esc(kind)}</td>
            <td>${esc(domain === "server" ? os : kind)}</td>
            <td>${esc(row.collect_mode || "—")}</td>
            <td>${statusPill(row.status)}</td>
            <td class="hint">${esc(metrics)}</td>
            <td>
              <button type="button" class="ghost mt-open-cmdb" data-id="${esc(row.component_id)}" data-type="${esc(row.component_type || "")}">Open CI</button>
            </td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".mt-open-cmdb").forEach((btn) => {
        btn.addEventListener("click", () => {
          openCmdbCi(btn.getAttribute("data-id"), btn.getAttribute("data-type"));
        });
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="8" class="hint">${esc(err.message || "Failed to load targets")}</td></tr>`;
      if (typeof notify === "function") notify(err.message || "Targets load failed", true);
    }
  }

  async function syncFromCmdb({ toast } = {}) {
    const notify = toast || toastFn;
    if (!apiFn) return;
    if (!canFn("monitor:targets:write")) {
      if (typeof notify === "function") {
        notify("Missing permission monitor:targets:write", true);
      }
      return;
    }
    try {
      const result = await apiFn("/api/monitor/targets/sync-from-cmdb", {
        method: "POST",
      });
      const msg = `Synced ${result.created || 0} new / ${result.updated || 0} updated` +
        (result.entitlement_truncated ? " (entitlement truncated)" : "");
      if (typeof notify === "function") notify(msg, false);
      Object.values(DOMAIN_TABS).forEach((domain) => {
        loadDomain(domain, { toast: notify });
      });
    } catch (err) {
      if (typeof notify === "function") {
        notify(err.message || "Sync failed", true);
      }
    }
  }

  function wireDomainControls(domain) {
    const refresh = document.getElementById(idFor(domain, "Refresh"));
    const sync = document.getElementById(idFor(domain, "Sync"));
    const search = document.getElementById(idFor(domain, "Search"));
    const selects = [
      idFor(domain, "Status"),
      idFor(domain, "CollectMode"),
      idFor(domain, "OsFamily"),
      idFor(domain, "TargetKind"),
    ]
      .map((id) => document.getElementById(id))
      .filter(Boolean);

    refresh?.addEventListener("click", () => loadDomain(domain));
    sync?.addEventListener("click", () => syncFromCmdb());
    const onEnter = (ev) => {
      if (ev.key === "Enter") loadDomain(domain);
    };
    search?.addEventListener("keydown", onEnter);
    const kindInput = document.getElementById(idFor(domain, "TargetKind"));
    if (kindInput && kindInput.tagName === "INPUT") {
      kindInput.addEventListener("keydown", onEnter);
    }
    selects.forEach((el) => el.addEventListener("change", () => loadDomain(domain)));
  }

  function initTargetsUi() {
    Object.values(DOMAIN_TABS).forEach((domain) => wireDomainControls(domain));
  }

  function onShowTab(name) {
    const domain = DOMAIN_TABS[name];
    if (!domain) return;
    loadDomain(domain);
  }

  global.SVRMON24MonitorTargets = {
    bindApi,
    initTargetsUi,
    loadDomain,
    syncFromCmdb,
    onShowTab,
    DOMAIN_TABS,
  };
})(window);
