/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  async function loadItsmDashboard({ toast } = {}) {
    const openEl = document.getElementById("itsmKpiOpen");
    const p1El = document.getElementById("itsmKpiP1");
    const apprEl = document.getElementById("itsmKpiApprovals");
    const slaEl = document.getElementById("itsmKpiSla");
    const notes = document.getElementById("itsmDashNotes");
    try {
      const data = await SVRMON24ItsmApi.dashboardSummary();
      if (openEl) openEl.textContent = String(data.open_incidents ?? 0);
      if (p1El) p1El.textContent = String((data.open_by_priority || {}).p1 || 0);
      if (apprEl) apprEl.textContent = String(data.pending_approvals ?? 0);
      if (slaEl) slaEl.textContent = String(data.sla_breaches ?? 0);
      if (notes) notes.textContent = data.notes || "ITSM dashboard loaded.";
    } catch (err) {
      if (notes) notes.textContent = err.message || "Failed to load ITSM dashboard";
      if (toast) toast(err.message || "ITSM dashboard failed", true);
    }
  }

  global.SVRMON24ItsmDashboard = { loadItsmDashboard };
})(window);
