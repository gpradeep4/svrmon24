/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  async function loadItsmDashboard({ toast } = {}) {
    const openEl = document.getElementById("itsmKpiOpen");
    const p1El = document.getElementById("itsmKpiP1");
    const chgEl = document.getElementById("itsmKpiChanges");
    const prbEl = document.getElementById("itsmKpiProblems");
    const notes = document.getElementById("itsmDashNotes");
    try {
      const data = await SVRMON24ItsmApi.dashboardSummary();
      if (openEl) openEl.textContent = String(data.open_incidents ?? 0);
      if (p1El) p1El.textContent = String((data.open_by_priority || {}).p1 || 0);
      if (chgEl) chgEl.textContent = String(data.open_changes ?? 0);
      if (prbEl) prbEl.textContent = String(data.open_problems ?? 0);
      if (notes) notes.textContent = data.notes || "ITSM dashboard loaded.";
    } catch (err) {
      if (notes) notes.textContent = err.message || "Failed to load ITSM dashboard";
      if (toast) toast(err.message || "ITSM dashboard failed", true);
    }
  }

  global.SVRMON24ItsmDashboard = { loadItsmDashboard };
})(window);
