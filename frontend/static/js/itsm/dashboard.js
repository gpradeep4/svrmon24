/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  const CHART_COLORS = {
    p1: "#b91c1c",
    p2: "#c2410c",
    p3: "#4f46e5",
    p4: "#64748b",
    accent: "#4f46e5",
    muted: "#94a3b8",
    change: "#0ea5e9",
    problem: "#7c3aed",
  };

  function esc(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value == null ? "—" : String(value);
  }

  function selectedWindow(selectId, fallback) {
    const el = document.getElementById(selectId);
    const raw = el ? el.value : "";
    if (raw === "7" || raw === "30") return Number(raw);
    return fallback;
  }

  function renderBarChart(containerId, entries, { emptyLabel } = {}) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const rows = (entries || []).filter((row) => row && row.count > 0);
    if (!rows.length) {
      el.innerHTML = `<p class="hint itsm-chart-empty">${esc(emptyLabel || "No data")}</p>`;
      return;
    }
    const max = Math.max(...rows.map((r) => r.count), 1);
    el.innerHTML = rows
      .map((row) => {
        const pct = Math.max(4, Math.round((row.count / max) * 100));
        const color = row.color || CHART_COLORS.accent;
        return `<div class="itsm-bar-row">
          <span class="itsm-bar-label">${esc(row.label)}</span>
          <div class="itsm-bar-track" aria-hidden="true">
            <div class="itsm-bar-fill" style="width:${pct}%;background:${color}"></div>
          </div>
          <span class="itsm-bar-value">${esc(row.count)}</span>
        </div>`;
      })
      .join("");
  }

  function mapCounts(obj, order, colorFn) {
    const source = obj || {};
    const keys = order && order.length ? order : Object.keys(source).sort();
    return keys
      .filter((k) => source[k] != null)
      .map((k) => ({
        label: k,
        count: Number(source[k] || 0),
        color: colorFn ? colorFn(k) : CHART_COLORS.accent,
      }));
  }

  function priorityColor(key) {
    return CHART_COLORS[key] || CHART_COLORS.accent;
  }

  function statusColor(key) {
    if (key === "breached" || key === "cancelled" || key === "rejected") return "#b91c1c";
    if (key === "resolved" || key === "closed" || key === "met") return "#047857";
    if (key === "on_hold" || key === "paused") return "#c2410c";
    return CHART_COLORS.accent;
  }

  function renderDashboard(data) {
    setText("itsmKpiOpen", data.open_incidents ?? 0);
    setText("itsmKpiP1", (data.open_by_priority || {}).p1 || 0);
    setText("itsmKpiChanges", data.open_changes ?? 0);
    setText("itsmKpiProblems", data.open_problems ?? 0);
    setText("itsmKpiApprovals", data.pending_approvals ?? 0);
    setText("itsmKpiSlaBreach", data.sla_breaches ?? 0);
    setText("itsmKpiSlaRisk", data.sla_at_risk ?? 0);
    setText("itsmKpiWorkflows", data.workflows_in_progress ?? 0);
    setText("itsmKpiKnowledge", data.knowledge_published ?? 0);
    setText("itsmKpiNotif", data.notifications_unread ?? 0);

    const created = data.created_in_window || {};
    const resolved = data.resolved_in_window || {};
    const windowLabel = data.window_days
      ? `Last ${data.window_days} days`
      : "All time (select a window for created/resolved)";
    setText("itsmDashWindowLabel", windowLabel);
    setText("itsmDashCreated", created.incidents ?? 0);
    setText("itsmDashCreatedChg", created.changes ?? 0);
    setText("itsmDashCreatedPrb", created.problems ?? 0);
    setText("itsmDashResolved", resolved.incidents ?? 0);

    renderBarChart(
      "itsmDashIncStatusChart",
      mapCounts(data.incidents_by_status || data.by_status, null, statusColor),
      { emptyLabel: "No incidents yet." }
    );
    renderBarChart(
      "itsmDashIncPriorityChart",
      mapCounts(
        data.open_by_priority,
        ["p1", "p2", "p3", "p4"],
        priorityColor
      ),
      { emptyLabel: "No open incidents." }
    );
    renderBarChart(
      "itsmDashChgStatusChart",
      mapCounts(data.changes_by_status, null, statusColor),
      { emptyLabel: "No changes yet." }
    );

    const notes = document.getElementById("itsmDashNotes");
    if (notes) notes.textContent = data.notes || "ITSM dashboard loaded.";
  }

  async function loadItsmDashboard({ toast } = {}) {
    const windowDays = selectedWindow("itsmDashWindow", null);
    try {
      const data = await SVRMON24ItsmApi.dashboardSummary(
        windowDays ? { window_days: windowDays } : {}
      );
      renderDashboard(data);
    } catch (err) {
      const notes = document.getElementById("itsmDashNotes");
      if (notes) notes.textContent = err.message || "Failed to load ITSM dashboard";
      if (toast) toast(err.message || "ITSM dashboard failed", true);
    }
  }

  function initItsmDashboard({ toast } = {}) {
    document.getElementById("itsmDashWindow")?.addEventListener("change", () => {
      loadItsmDashboard({ toast });
    });
  }

  global.SVRMON24ItsmDashboard = {
    loadItsmDashboard,
    initItsmDashboard,
    renderBarChart,
    mapCounts,
    CHART_COLORS,
  };
})(window);
