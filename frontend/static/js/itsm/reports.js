/* global SVRMON24ItsmApi, SVRMON24ItsmDashboard */
(function (global) {
  "use strict";

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value == null ? "—" : String(value);
  }

  function selectedWindow() {
    const el = document.getElementById("itsmReportsWindow");
    const raw = el ? el.value : "30";
    return raw === "7" ? 7 : 30;
  }

  function renderSparkline(containerId, series) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const rows = series || [];
    if (!rows.length) {
      el.innerHTML = '<p class="hint itsm-chart-empty">No volume in this window.</p>';
      return;
    }
    const max = Math.max(...rows.map((r) => Number(r.total || 0)), 1);
    el.innerHTML = `<div class="itsm-sparkline" role="img" aria-label="Daily created tickets">
      ${rows
        .map((row) => {
          const total = Number(row.total || 0);
          const h = Math.max(total ? 8 : 2, Math.round((total / max) * 100));
          const title = `${row.date}: ${total} created`;
          return `<span class="itsm-spark-bar" title="${title}" style="height:${h}%"></span>`;
        })
        .join("")}
    </div>
    <div class="itsm-spark-legend">
      <span>${rows[0].date}</span>
      <span>${rows[rows.length - 1].date}</span>
    </div>`;
  }

  function renderReports(data) {
    const days = data.window_days || 30;
    setText("itsmReportsWindowLabel", `Last ${days} days`);
    setText("itsmRepOpenInc", data.open_incidents ?? 0);
    setText("itsmRepOpenChg", data.open_changes ?? 0);
    setText("itsmRepOpenPrb", data.open_problems ?? 0);
    setText("itsmRepApprovals", data.pending_approvals ?? 0);
    setText("itsmRepSlaBreach", data.sla_breaches ?? 0);
    setText("itsmRepSlaRisk", data.sla_at_risk ?? 0);
    setText("itsmRepWorkflows", data.workflows_in_progress ?? 0);
    setText("itsmRepKnowledge", data.knowledge_published ?? 0);
    setText("itsmRepNotif", data.notifications_unread ?? 0);

    const created = data.created_in_window || {};
    const resolved = data.resolved_in_window || {};
    setText("itsmRepCreatedInc", created.incidents ?? 0);
    setText("itsmRepCreatedChg", created.changes ?? 0);
    setText("itsmRepCreatedPrb", created.problems ?? 0);
    setText("itsmRepResolvedInc", resolved.incidents ?? 0);
    setText("itsmRepResolvedChg", resolved.changes ?? 0);
    setText("itsmRepResolvedPrb", resolved.problems ?? 0);

    const dash = global.SVRMON24ItsmDashboard;
    if (dash) {
      dash.renderBarChart(
        "itsmRepIncStatusChart",
        dash.mapCounts(data.incidents_by_status || data.by_status, null, (k) =>
          k === "resolved" || k === "closed" ? "#047857" : dash.CHART_COLORS.accent
        ),
        { emptyLabel: "No incidents in tenant." }
      );
      dash.renderBarChart(
        "itsmRepPriorityChart",
        dash.mapCounts(data.open_by_priority, ["p1", "p2", "p3", "p4"], (k) =>
          dash.CHART_COLORS[k] || dash.CHART_COLORS.accent
        ),
        { emptyLabel: "No open incidents." }
      );
      dash.renderBarChart(
        "itsmRepChgStatusChart",
        dash.mapCounts(data.changes_by_status, null, () => dash.CHART_COLORS.change),
        { emptyLabel: "No changes in tenant." }
      );
      dash.renderBarChart(
        "itsmRepPrbStatusChart",
        dash.mapCounts(data.problems_by_status, null, () => dash.CHART_COLORS.problem),
        { emptyLabel: "No problems in tenant." }
      );
    }

    renderSparkline("itsmRepVolumeChart", data.series_daily_created || []);

    const notes = document.getElementById("itsmReportsNotes");
    if (notes) notes.textContent = data.notes || "ITSM reports loaded.";
  }

  async function loadItsmReports({ toast } = {}) {
    const windowDays = selectedWindow();
    try {
      const data = await SVRMON24ItsmApi.dashboardReports({ window_days: windowDays });
      renderReports(data);
    } catch (err) {
      const notes = document.getElementById("itsmReportsNotes");
      if (notes) notes.textContent = err.message || "Failed to load ITSM reports";
      if (toast) toast(err.message || "ITSM reports failed", true);
    }
  }

  function initItsmReports({ toast } = {}) {
    document.getElementById("itsmReportsWindow")?.addEventListener("change", () => {
      loadItsmReports({ toast });
    });
  }

  global.SVRMON24ItsmReports = {
    loadItsmReports,
    initItsmReports,
  };
})(window);
