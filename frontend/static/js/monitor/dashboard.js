/* Monitoring Dashboard — real aggregates from /api/monitor/dashboard (SIMULATED). */
(function (global) {
  "use strict";

  let apiFn = null;
  let toastFn = null;

  function bindApi(api, { toast } = {}) {
    if (typeof api === "function") apiFn = api;
    if (typeof toast === "function") toastFn = toast;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function listToText(value) {
    if (Array.isArray(value)) return value.join(", ") || "—";
    if (value == null || value === "") return "—";
    return String(value);
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = listToText(value);
  }

  function formatWhen(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return esc(iso);
      return esc(d.toLocaleString());
    } catch (_err) {
      return esc(iso);
    }
  }

  function countsLine(obj) {
    if (!obj || typeof obj !== "object") return "—";
    const keys = Object.keys(obj).sort();
    if (!keys.length) return "none";
    return keys.map((k) => `${k}: ${obj[k]}`).join(" · ");
  }

  function statusPill(status) {
    const s = String(status || "").toLowerCase();
    let cls = "status-pill";
    if (s === "firing" || s === "down" || s === "critical" || s === "error") {
      cls += " danger";
    } else if (s === "acked" || s === "degraded" || s === "warning") {
      cls += " warning";
    } else if (s === "healthy" || s === "resolved" || s === "info") {
      cls += " ok";
    } else {
      cls += " muted";
    }
    return `<span class="${cls}">${esc(s || "—")}</span>`;
  }

  function renderRecentAlerts(items) {
    const body = document.getElementById("monitorDashAlertsBody");
    if (!body) return;
    if (!items || !items.length) {
      body.innerHTML =
        `<tr><td colspan="5" class="hint">No open alerts.</td></tr>`;
      return;
    }
    body.innerHTML = items
      .map(
        (row) => `<tr>
          <td class="mono">${formatWhen(row.fired_at)}</td>
          <td>${statusPill(row.status)}</td>
          <td>${statusPill(row.severity)}</td>
          <td>${esc(row.rule_name || row.rule_id || "—")}</td>
          <td>${esc(row.summary || "")}</td>
        </tr>`
      )
      .join("");
  }

  function renderRecentLogs(items) {
    const body = document.getElementById("monitorDashLogsBody");
    if (!body) return;
    if (!items || !items.length) {
      body.innerHTML =
        `<tr><td colspan="4" class="hint">No log events yet.</td></tr>`;
      return;
    }
    body.innerHTML = items
      .map(
        (row) => `<tr>
          <td class="mono">${formatWhen(row.observed_at)}</td>
          <td>${statusPill(row.severity)}</td>
          <td class="mono">${esc(row.component_id || "—")}</td>
          <td>${esc(row.message || "")}</td>
        </tr>`
      )
      .join("");
  }

  function renderRecentFiles(items) {
    const body = document.getElementById("monitorDashFilesBody");
    if (!body) return;
    if (!items || !items.length) {
      body.innerHTML =
        `<tr><td colspan="4" class="hint">No file events yet.</td></tr>`;
      return;
    }
    body.innerHTML = items
      .map(
        (row) => `<tr>
          <td class="mono">${formatWhen(row.changed_at)}</td>
          <td class="mono">${esc(row.path || "—")}</td>
          <td class="mono">v${esc(row.version == null ? "—" : row.version)}</td>
          <td>${esc(row.changed_by || "—")}</td>
        </tr>`
      )
      .join("");
  }

  async function loadMonitorDashboard({ toast } = {}) {
    const notify = toast || toastFn;
    const banner = document.getElementById("monitorDashBanner");
    const notes = document.getElementById("monitorDashNotes");
    if (!apiFn) {
      if (notes) notes.textContent = "API not bound.";
      return;
    }
    try {
      const [meta, dash] = await Promise.all([
        apiFn("/api/monitor/meta"),
        apiFn("/api/monitor/dashboard"),
      ]);
      if (banner) {
        banner.textContent =
          dash.banner ||
          meta.banner ||
          "SIMULATED / SYNTHETIC_DEMO — Monitoring does not run live probes or agents.";
      }
      const live = dash.live_probes === true || meta.live_probes === true;
      const liveEl = document.getElementById("monitorDashLiveProbes");
      if (liveEl) {
        liveEl.textContent = live ? "true" : "false";
        liveEl.className = live ? "status-pill ok" : "status-pill warning";
      }
      setText("monitorDashExecMode", dash.execution_mode || meta.execution_mode || "SIMULATED");
      setText("monitorDashCollectModes", meta.collect_modes);
      setText("monitorDashDomains", meta.domains);
      setText("monitorDashDb", dash.monitor_database || meta.monitor_database || "—");

      setText("monitorDashTargetsTotal", dash.targets_total ?? 0);
      setText("monitorDashOpenAlerts", dash.open_alerts ?? 0);
      setText("monitorDashLogVolume", dash.log_events_total ?? 0);
      setText("monitorDashFileEvents", dash.file_events_total ?? 0);
      setText("monitorDashTargetsByStatus", countsLine(dash.targets_by_status));
      setText("monitorDashTargetsByDomain", countsLine(dash.targets_by_domain));
      setText("monitorDashAlertsBySeverity", countsLine(dash.alerts_by_severity));

      renderRecentAlerts(dash.recent_open_alerts || []);
      renderRecentLogs(dash.recent_log_events || []);
      renderRecentFiles(dash.recent_file_events || []);

      if (notes) {
        notes.textContent =
          `Aggregates from monitor collections · open alerts ${dash.open_alerts ?? 0} · ` +
          `targets ${dash.targets_total ?? 0} · SIMULATED · no auto-incident`;
      }
    } catch (err) {
      if (notes) notes.textContent = err.message || "Failed to load Monitoring dashboard.";
      if (typeof notify === "function") {
        notify(err.message || "Monitoring dashboard failed", true);
      }
    }
  }

  global.SVRMON24MonitorDashboard = {
    bindApi,
    loadMonitorDashboard,
  };
})(window);
