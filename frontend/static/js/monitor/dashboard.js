/* Monitoring Dashboard shell — SIMULATED meta only (no real aggregates in M2). */
(function (global) {
  "use strict";

  let apiFn = null;
  let toastFn = null;

  function bindApi(api, { toast } = {}) {
    if (typeof api === "function") apiFn = api;
    if (typeof toast === "function") toastFn = toast;
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

  async function loadMonitorDashboard({ toast } = {}) {
    const notify = toast || toastFn;
    const banner = document.getElementById("monitorDashBanner");
    const notes = document.getElementById("monitorDashNotes");
    if (!apiFn) {
      if (notes) notes.textContent = "API not bound.";
      return;
    }
    try {
      const meta = await apiFn("/api/monitor/meta");
      if (banner) {
        banner.textContent =
          meta.banner ||
          "SIMULATED / SYNTHETIC_DEMO — Monitoring does not run live probes or agents.";
      }
      const live = meta.live_probes === true;
      const liveEl = document.getElementById("monitorDashLiveProbes");
      if (liveEl) {
        liveEl.textContent = live ? "true" : "false";
        liveEl.className = live ? "status-pill ok" : "status-pill warning";
      }
      setText("monitorDashExecMode", meta.execution_mode || "SIMULATED");
      setText("monitorDashCollectModes", meta.collect_modes);
      setText("monitorDashDomains", meta.domains);
      setText("monitorDashDb", meta.monitor_database || meta.database || "—");
      if (notes) {
        notes.textContent =
          meta.notice ||
          "Dashboard aggregates arrive in a later slice. Shell shows module meta only.";
      }
    } catch (err) {
      if (notes) notes.textContent = err.message || "Failed to load Monitoring meta.";
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
