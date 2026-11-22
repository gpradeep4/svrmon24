/* Monitoring domain health — SIMULATED targets + LIVE row badges when gated. */
(function (global) {
  "use strict";

  let apiFn = null;
  let toastFn = null;
  let canFn = () => false;

  const DOMAIN_TABS = {
    "monitor-servers": "server",
    "monitor-network": "network",
    "monitor-applications": "application",
    "monitor-middleware": "middleware",
    "monitor-databases": "database",
  };

  const DOMAIN_PREFIX = {
    server: "mtSrv",
    network: "mtNet",
    application: "mtApp",
    middleware: "mtMw",
    database: "mtDb",
  };

  const BANNER_SIM = {
    server:
      "SIMULATED — synthetic server health + metrics. Live probes / agents remain off.",
    network:
      "SIMULATED — switches, routers, firewalls, load balancers, APs. Live ICMP/SNMP stay off until gates + allowlist.",
    application:
      "SIMULATED — application health from CMDB Application CIs. Live APM stays off.",
    middleware:
      "SIMULATED — middleware health from CMDB Middleware CIs. Live HTTP/TCP checks stay off until gates + allowlist.",
    database:
      "SIMULATED — database health from CMDB Database CIs. Live DB agents stay off.",
  };

  const BANNER_LIVE = {
    server:
      "Live gates ON — rows may be SIMULATED or LIVE (agentless HTTP/TCP/ICMP). Per-row Mode badge shows execution_mode.",
    network:
      "Live gates ON — rows may be SIMULATED or LIVE (agentless ICMP/SNMP/HTTP/TCP). Per-row Mode badge shows execution_mode.",
    application:
      "Live gates ON — series may be SIMULATED or LIVE. Application live checks use agentless HTTP/TCP when configured.",
    middleware:
      "Live gates ON — series may be SIMULATED or LIVE. Middleware live checks use agentless HTTP/TCP from CMDB listen fields.",
    database:
      "Live gates ON — series may be SIMULATED or LIVE. Database live checks use agentless paths when configured.",
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

  function modeBadge(executionMode) {
    const mode = String(executionMode || "SIMULATED").toUpperCase();
    const live = mode === "LIVE";
    const cls = live ? "status-pill ok monitor-mode-live" : "status-pill muted monitor-mode-sim";
    return `<span class="${cls}" title="execution_mode">${esc(mode)}</span>`;
  }

  function metricsSummary(metrics) {
    const rows = Array.isArray(metrics) ? metrics : [];
    if (!rows.length) return "—";
    return rows
      .slice(0, 3)
      .map((m) => {
        const unit = m.unit ? ` ${m.unit}` : "";
        const mode = m.execution_mode === "LIVE" ? " · LIVE" : "";
        return `${m.metric_name}=${m.value}${unit}${mode}`;
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

  function updateBanner(domain, { liveProbes, hasLiveRows }) {
    const banner = document.getElementById(idFor(domain, "Banner"));
    if (!banner) return;
    if (liveProbes || hasLiveRows) {
      banner.textContent = BANNER_LIVE[domain] || BANNER_LIVE.server;
      banner.removeAttribute("data-monitor-simulated");
      banner.setAttribute("data-monitor-live", "1");
    } else {
      banner.textContent = BANNER_SIM[domain] || BANNER_SIM.server;
      banner.setAttribute("data-monitor-simulated", "1");
      banner.removeAttribute("data-monitor-live");
    }
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
      let liveProbes = false;
      try {
        const metaBody = await apiFn("/api/monitor/meta");
        liveProbes = Boolean(metaBody.live_probes);
      } catch (_err) {
        liveProbes = false;
      }
      const data = await apiFn(`/api/monitor/targets?${params.toString()}`);
      const items = data.items || [];
      const hasLiveRows = items.some(
        (row) => String(row.execution_mode || "").toUpperCase() === "LIVE"
      );
      updateBanner(domain, { liveProbes, hasLiveRows });
      const modeLabel = liveProbes || hasLiveRows ? "SIMULATED/LIVE mix" : "SIMULATED";
      if (meta) {
        meta.textContent = `${data.total || 0} target(s) · ${modeLabel} · live_probes=${liveProbes}`;
      }
      const colSpan = domain === "server" || domain === "network" ? 9 : 8;
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="${colSpan}" class="hint">No targets yet. Use <strong>Sync from CMDB</strong> to create SIMULATED monitor targets for this domain.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const metrics = metricsSummary(row.latest_metrics);
          const kind = row.target_kind || "—";
          const os = row.os_family || row.os_name || "—";
          const showModeCol = domain === "server" || domain === "network";
          const modeCell = showModeCol
            ? `<td>${modeBadge(row.execution_mode)}</td>`
            : "";
          const reason =
            row.live_status_reason && String(row.execution_mode).toUpperCase() === "LIVE"
              ? ` <span class="hint" title="${esc(row.live_status_reason)}">·</span>`
              : "";
          const suggestBtn =
            domain === "middleware"
              ? `<button type="button" class="ghost mt-suggest-check" data-target-id="${esc(row.target_id)}">Suggest check</button>`
              : "";
          return `<tr data-target-id="${esc(row.target_id)}" data-component-id="${esc(row.component_id)}" data-execution-mode="${esc(row.execution_mode || "SIMULATED")}">
            <td>${esc(row.name_snapshot || "—")}</td>
            <td class="mono">${esc(row.component_id)}</td>
            <td>${esc(kind)}</td>
            <td>${esc(domain === "server" ? os : kind)}</td>
            <td>${esc(row.collect_mode || "—")}</td>
            ${modeCell}
            <td>${statusPill(row.status)}${reason}</td>
            <td class="hint">${esc(metrics)}</td>
            <td>
              <button type="button" class="ghost mt-open-cmdb" data-id="${esc(row.component_id)}" data-type="${esc(row.component_type || "")}">Open CI</button>
              ${suggestBtn}
            </td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".mt-open-cmdb").forEach((btn) => {
        btn.addEventListener("click", () => {
          openCmdbCi(btn.getAttribute("data-id"), btn.getAttribute("data-type"));
        });
      });
      body.querySelectorAll(".mt-suggest-check").forEach((btn) => {
        btn.addEventListener("click", () => {
          suggestCheck(btn.getAttribute("data-target-id"), { toast: notify });
        });
      });
    } catch (err) {
      const colSpan = domain === "server" || domain === "network" ? 9 : 8;
      body.innerHTML = `<tr><td colspan="${colSpan}" class="hint">${esc(err.message || "Failed to load targets")}</td></tr>`;
      if (typeof notify === "function") notify(err.message || "Targets load failed", true);
    }
  }

  async function suggestCheck(targetId, { toast } = {}) {
    const notify = toast || toastFn;
    const tid = (targetId || "").trim();
    if (!apiFn || !tid) return;
    try {
      const result = await apiFn(
        `/api/monitor/targets/${encodeURIComponent(tid)}/suggest-check`
      );
      if (!result.draft) {
        if (typeof notify === "function") {
          notify(result.reason || "No check draft available", true);
        }
        return;
      }
      if (!canFn("monitor:targets:write")) {
        if (typeof notify === "function") {
          notify(
            `Draft ${result.draft.protocol} check ready — missing monitor:targets:write to save`,
            true
          );
        }
        return;
      }
      const save = window.confirm(
        `Save suggested ${result.draft.protocol.toUpperCase()} check for ${tid}?\n` +
          JSON.stringify(result.draft.endpoint || {}, null, 2)
      );
      if (!save) {
        if (typeof notify === "function") {
          notify("Check draft discarded (not saved)", false);
        }
        return;
      }
      await apiFn("/api/monitor/checks", {
        method: "POST",
        body: JSON.stringify(result.draft),
      });
      if (typeof notify === "function") {
        notify("Suggested check saved (human confirm)", false);
      }
    } catch (err) {
      if (typeof notify === "function") {
        notify(err.message || "Suggest check failed", true);
      }
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
    suggestCheck,
    onShowTab,
    DOMAIN_TABS,
  };
})(window);
