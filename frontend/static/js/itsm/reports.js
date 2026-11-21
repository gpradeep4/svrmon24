/* global SVRMON24ItsmApi, SVRMON24ItsmDashboard */
(function (global) {
  "use strict";

  let toastFn = null;
  let escapeHtmlFn = (s) => String(s ?? "");
  let canFn = () => false;
  let editingId = null;

  function toast(msg, isErr) {
    if (toastFn) toastFn(msg, isErr);
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value == null ? "—" : String(value);
  }

  function selectedWindow() {
    const el = document.getElementById("itsmReportsWindow");
    const raw = el ? el.value : "30";
    return raw === "7" ? 7 : 30;
  }

  function canReadReports() {
    return canFn("itsm:reports:read") || canFn("itsm:dashboard:read");
  }

  function canWriteReports() {
    return canFn("itsm:reports:write");
  }

  function applyWriteGates() {
    const write = canWriteReports();
    document.querySelectorAll("[data-itsm-reports-write='1']").forEach((el) => {
      el.hidden = !write;
      if ("disabled" in el) el.disabled = !write;
    });
    const read = canReadReports();
    document.querySelectorAll("[data-itsm-reports-read='1']").forEach((el) => {
      el.hidden = !read;
      if ("disabled" in el) el.disabled = !read;
    });
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

  async function loadItsmReports({ toast: t } = {}) {
    if (t) toastFn = t;
    applyWriteGates();
    const windowDays = selectedWindow();
    try {
      const data = await SVRMON24ItsmApi.dashboardReports({ window_days: windowDays });
      renderReports(data);
    } catch (err) {
      const notes = document.getElementById("itsmReportsNotes");
      if (notes) notes.textContent = err.message || "Failed to load ITSM reports";
      toast(err.message || "ITSM reports failed", true);
    }
  }

  async function downloadDashboardExport(format) {
    if (!canReadReports()) {
      toast("Missing itsm:reports:read permission", true);
      return;
    }
    const windowDays = selectedWindow();
    try {
      const q = new URLSearchParams({
        format,
        window_days: String(windowDays),
        include_tickets: "true",
      });
      await SVRMON24ItsmApi.downloadBinary(
        `/dashboard/export?${q.toString()}`,
        format === "xlsx" ? `itsm-reports-${windowDays}d.xlsx` : `itsm-reports-${windowDays}d.csv`
      );
      toast(`Exported ITSM reports as ${format.toUpperCase()}`);
    } catch (err) {
      toast(err.message || "Export failed", true);
    }
  }

  function checkedValues(name) {
    return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map(
      (el) => el.value
    );
  }

  function setCheckedValues(name, values) {
    const set = new Set(values || []);
    document.querySelectorAll(`input[name="${name}"]`).forEach((el) => {
      el.checked = set.has(el.value);
    });
  }

  function splitCsv(raw) {
    return String(raw || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function resetCustomForm() {
    editingId = null;
    const form = document.getElementById("itsmCustomReportForm");
    if (form) form.hidden = true;
    setText("itsmCustomReportFormTitle", "New custom report");
    const idEl = document.getElementById("itsmCustomReportId");
    if (idEl) idEl.value = "";
    const name = document.getElementById("itsmCustomReportName");
    if (name) name.value = "";
    const desc = document.getElementById("itsmCustomReportDesc");
    if (desc) desc.value = "";
    const win = document.getElementById("itsmCustomReportWindow");
    if (win) win.value = "30";
    const cat = document.getElementById("itsmCustomReportCategory");
    if (cat) cat.value = "";
    const tier = document.getElementById("itsmCustomReportTier");
    if (tier) tier.value = "";
    const pri = document.getElementById("itsmCustomReportPriorities");
    if (pri) pri.value = "";
    const st = document.getElementById("itsmCustomReportStatuses");
    if (st) st.value = "";
    setCheckedValues("itsmCustomReportType", ["incident", "change", "problem"]);
    setCheckedValues("itsmCustomReportMetric", [
      "open_incidents",
      "sla_breaches",
      "ticket_rows",
    ]);
    setCheckedValues("itsmCustomReportColumn", [
      "ticket_type",
      "ticket_id",
      "number",
      "title",
      "status",
      "priority",
      "category",
      "service_tier",
      "created_at",
    ]);
  }

  function showCustomForm(doc) {
    const form = document.getElementById("itsmCustomReportForm");
    if (!form) return;
    form.hidden = false;
    if (!doc) {
      resetCustomForm();
      form.hidden = false;
      editingId = null;
      setText("itsmCustomReportFormTitle", "New custom report");
      return;
    }
    editingId = doc.report_id;
    setText("itsmCustomReportFormTitle", `Edit ${doc.name || doc.report_id}`);
    const idEl = document.getElementById("itsmCustomReportId");
    if (idEl) idEl.value = doc.report_id || "";
    const name = document.getElementById("itsmCustomReportName");
    if (name) name.value = doc.name || "";
    const desc = document.getElementById("itsmCustomReportDesc");
    if (desc) desc.value = doc.description || "";
    const filters = doc.filters || {};
    const win = document.getElementById("itsmCustomReportWindow");
    if (win) win.value = filters.window_days == null ? "" : String(filters.window_days);
    const cat = document.getElementById("itsmCustomReportCategory");
    if (cat) cat.value = filters.category || "";
    const tier = document.getElementById("itsmCustomReportTier");
    if (tier) tier.value = filters.service_tier || "";
    const pri = document.getElementById("itsmCustomReportPriorities");
    if (pri) pri.value = (filters.priorities || []).join(",");
    const st = document.getElementById("itsmCustomReportStatuses");
    if (st) st.value = (filters.statuses || []).join(",");
    setCheckedValues("itsmCustomReportType", filters.ticket_types || ["incident", "change", "problem"]);
    setCheckedValues("itsmCustomReportMetric", doc.metrics || []);
    setCheckedValues("itsmCustomReportColumn", doc.columns || []);
  }

  function buildPayloadFromForm() {
    const name = document.getElementById("itsmCustomReportName")?.value?.trim();
    if (!name) throw new Error("Name is required");
    const metrics = checkedValues("itsmCustomReportMetric");
    if (!metrics.length) throw new Error("Select at least one metric");
    const columns = checkedValues("itsmCustomReportColumn");
    const types = checkedValues("itsmCustomReportType");
    if (!types.length) throw new Error("Select at least one ticket type");
    const winRaw = document.getElementById("itsmCustomReportWindow")?.value;
    const windowDays = winRaw === "" ? null : Number(winRaw);
    return {
      name,
      description: document.getElementById("itsmCustomReportDesc")?.value?.trim() || null,
      metrics,
      columns: columns.length ? columns : undefined,
      filters: {
        ticket_types: types,
        statuses: splitCsv(document.getElementById("itsmCustomReportStatuses")?.value),
        priorities: splitCsv(document.getElementById("itsmCustomReportPriorities")?.value),
        category: document.getElementById("itsmCustomReportCategory")?.value?.trim() || null,
        service_tier: document.getElementById("itsmCustomReportTier")?.value?.trim() || null,
        window_days: windowDays,
      },
    };
  }

  async function loadCustomReports() {
    applyWriteGates();
    if (!canFn("itsm:reports:read")) {
      setText("itsmCustomReportListMeta", "Custom reports require itsm:reports:read.");
      const tbody = document.querySelector("#itsmCustomReportTable tbody");
      if (tbody) tbody.innerHTML = "";
      return;
    }
    try {
      const data = await SVRMON24ItsmApi.listReportDefinitions({ page: 1, page_size: 100 });
      const items = data.items || [];
      setText(
        "itsmCustomReportListMeta",
        items.length ? `${data.total} saved report(s)` : "No custom reports yet."
      );
      const tbody = document.querySelector("#itsmCustomReportTable tbody");
      if (!tbody) return;
      const write = canWriteReports();
      tbody.innerHTML = items
        .map((row) => {
          const metrics = (row.metrics || []).join(", ");
          const win =
            row.filters?.window_days == null ? "—" : `${row.filters.window_days}d`;
          const updated = row.updated_at
            ? String(row.updated_at).replace("T", " ").slice(0, 19)
            : "—";
          const id = escapeHtmlFn(row.report_id);
          const editBtn = write
            ? `<button type="button" class="secondary itsm-mini-btn" data-rpt-edit="${id}">Edit</button>`
            : "";
          const delBtn = write
            ? `<button type="button" class="secondary itsm-mini-btn" data-rpt-del="${id}">Delete</button>`
            : "";
          return `<tr>
            <td><strong>${escapeHtmlFn(row.name)}</strong><div class="hint">${id}</div></td>
            <td class="itsm-metric-cell">${escapeHtmlFn(metrics)}</td>
            <td>${escapeHtmlFn(win)}</td>
            <td>${escapeHtmlFn(updated)}</td>
            <td class="itsm-report-actions">
              <button type="button" class="secondary itsm-mini-btn" data-rpt-run="${id}">Run</button>
              <button type="button" class="secondary itsm-mini-btn" data-rpt-csv="${id}">CSV</button>
              <button type="button" class="secondary itsm-mini-btn" data-rpt-xlsx="${id}">Excel</button>
              ${editBtn}${delBtn}
            </td>
          </tr>`;
        })
        .join("");
    } catch (err) {
      setText("itsmCustomReportListMeta", err.message || "Failed to load custom reports");
      toast(err.message || "Custom reports failed", true);
    }
  }

  function renderRunResult(result) {
    const panel = document.getElementById("itsmCustomReportRunPanel");
    if (panel) panel.hidden = false;
    setText("itsmCustomReportRunName", result.name ? `· ${result.name}` : "");
    setText(
      "itsmCustomReportRunMeta",
      `${result.ticket_row_count || 0} ticket row(s) · generated ${result.generated_at || ""}`
    );
    const mbody = document.querySelector("#itsmCustomReportMetricsTable tbody");
    if (mbody) {
      const rows = result.summary_metrics || [];
      mbody.innerHTML = rows.length
        ? rows
            .map(
              (r) =>
                `<tr><td>${escapeHtmlFn(r.metric)}</td><td>${escapeHtmlFn(r.value)}</td></tr>`
            )
            .join("")
        : `<tr><td colspan="2">No summary metrics</td></tr>`;
    }
    const thead = document.querySelector("#itsmCustomReportTicketsTable thead");
    const tbody = document.querySelector("#itsmCustomReportTicketsTable tbody");
    const cols = result.columns || [];
    if (thead) {
      thead.innerHTML = `<tr>${cols.map((c) => `<th>${escapeHtmlFn(c)}</th>`).join("")}</tr>`;
    }
    if (tbody) {
      const rows = result.ticket_rows || [];
      tbody.innerHTML = rows.length
        ? rows
            .map(
              (row) =>
                `<tr>${cols
                  .map((c) => `<td>${escapeHtmlFn(row[c] ?? "")}</td>`)
                  .join("")}</tr>`
            )
            .join("")
        : `<tr><td colspan="${Math.max(cols.length, 1)}">No ticket rows</td></tr>`;
    }
  }

  async function runCustomReport(reportId) {
    try {
      const result = await SVRMON24ItsmApi.runReportDefinition(reportId);
      renderRunResult(result);
      toast(`Ran report ${result.name || reportId}`);
    } catch (err) {
      toast(err.message || "Run failed", true);
    }
  }

  async function exportCustomReport(reportId, format) {
    try {
      await SVRMON24ItsmApi.downloadBinary(
        `/reports/definitions/${encodeURIComponent(reportId)}/export?format=${format}`,
        format === "xlsx"
          ? `itsm-report-${reportId}.xlsx`
          : `itsm-report-${reportId}.csv`
      );
      toast(`Downloaded ${format.toUpperCase()}`);
    } catch (err) {
      toast(err.message || "Download failed", true);
    }
  }

  async function saveCustomReport(ev) {
    ev?.preventDefault?.();
    if (!canWriteReports()) {
      toast("Missing itsm:reports:write permission", true);
      return;
    }
    try {
      const payload = buildPayloadFromForm();
      const id = editingId || document.getElementById("itsmCustomReportId")?.value;
      if (id) {
        await SVRMON24ItsmApi.updateReportDefinition(id, payload);
        toast("Report updated");
      } else {
        await SVRMON24ItsmApi.createReportDefinition(payload);
        toast("Report created");
      }
      resetCustomForm();
      const form = document.getElementById("itsmCustomReportForm");
      if (form) form.hidden = true;
      await loadCustomReports();
    } catch (err) {
      toast(err.message || "Save failed", true);
    }
  }

  async function deleteCustomReport(reportId) {
    if (!canWriteReports()) return;
    if (!global.confirm(`Delete custom report ${reportId}?`)) return;
    try {
      await SVRMON24ItsmApi.deleteReportDefinition(reportId);
      toast("Report deleted");
      await loadCustomReports();
    } catch (err) {
      toast(err.message || "Delete failed", true);
    }
  }

  async function editCustomReport(reportId) {
    try {
      const doc = await SVRMON24ItsmApi.getReportDefinition(reportId);
      showCustomForm(doc);
    } catch (err) {
      toast(err.message || "Load failed", true);
    }
  }

  function onCustomTableClick(ev) {
    const btn = ev.target.closest("button[data-rpt-run],button[data-rpt-csv],button[data-rpt-xlsx],button[data-rpt-edit],button[data-rpt-del]");
    if (!btn) return;
    const run = btn.getAttribute("data-rpt-run");
    const csv = btn.getAttribute("data-rpt-csv");
    const xlsx = btn.getAttribute("data-rpt-xlsx");
    const edit = btn.getAttribute("data-rpt-edit");
    const del = btn.getAttribute("data-rpt-del");
    if (run) runCustomReport(run);
    else if (csv) exportCustomReport(csv, "csv");
    else if (xlsx) exportCustomReport(xlsx, "xlsx");
    else if (edit) editCustomReport(edit);
    else if (del) deleteCustomReport(del);
  }

  async function fillScheduleReportOptions(selectedId) {
    const sel = document.getElementById("itsmReportScheduleReportId");
    if (!sel) return;
    try {
      const data = await SVRMON24ItsmApi.listReportDefinitions({ page_size: "100" });
      const items = data.items || [];
      sel.innerHTML = items.length
        ? items
            .map(
              (r) =>
                `<option value="${escapeHtmlFn(r.report_id)}">${escapeHtmlFn(r.name)} (${escapeHtmlFn(r.report_id)})</option>`
            )
            .join("")
        : `<option value="">No custom reports</option>`;
      if (selectedId) sel.value = selectedId;
    } catch (_) {
      sel.innerHTML = `<option value="">Failed to load reports</option>`;
    }
  }

  function showScheduleForm(doc) {
    const form = document.getElementById("itsmReportScheduleForm");
    if (!form) return;
    form.hidden = false;
    const title = document.getElementById("itsmReportScheduleFormTitle");
    if (title) title.textContent = doc ? "Edit schedule" : "New schedule";
    document.getElementById("itsmReportScheduleId").value = doc?.schedule_id || "";
    document.getElementById("itsmReportScheduleName").value = doc?.name || "";
    document.getElementById("itsmReportScheduleInterval").value = String(
      doc?.interval_minutes || 1440
    );
    document.getElementById("itsmReportScheduleTz").value = doc?.timezone || "UTC";
    document.getElementById("itsmReportScheduleFormat").value = doc?.format || "csv";
    document.getElementById("itsmReportScheduleRecipients").value = (
      doc?.recipients || []
    ).join(", ");
    document.getElementById("itsmReportScheduleActive").checked =
      doc?.active !== false;
    fillScheduleReportOptions(doc?.report_id);
  }

  async function loadReportSchedules() {
    const body = document.getElementById("itsmReportScheduleBody");
    const meta = document.getElementById("itsmReportScheduleListMeta");
    if (!body) return;
    try {
      const data = await SVRMON24ItsmApi.listReportSchedules({ page_size: "50" });
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} schedule(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="6" class="hint">No schedules yet.</td></tr>`;
        return;
      }
      const write = canWriteReports();
      body.innerHTML = items
        .map((row) => {
          const id = escapeHtmlFn(row.schedule_id);
          const next = row.next_run_at
            ? String(row.next_run_at).replace("T", " ").slice(0, 19)
            : "—";
          const last = row.last_run_at
            ? `${String(row.last_run_at).replace("T", " ").slice(0, 19)} (${escapeHtmlFn(row.last_status || "")})`
            : "—";
          const runBtn = write
            ? `<button type="button" class="secondary itsm-mini-btn" data-sch-run="${id}">Run now</button>`
            : "";
          const editBtn = write
            ? `<button type="button" class="secondary itsm-mini-btn" data-sch-edit="${id}">Edit</button>`
            : "";
          const delBtn = write
            ? `<button type="button" class="secondary itsm-mini-btn" data-sch-del="${id}">Delete</button>`
            : "";
          const toggleBtn = write
            ? `<button type="button" class="secondary itsm-mini-btn" data-sch-toggle="${id}" data-active="${row.active ? "1" : "0"}">${row.active ? "Disable" : "Enable"}</button>`
            : "";
          return `<tr>
            <td><strong>${escapeHtmlFn(row.name || row.schedule_id)}</strong>
              <div class="hint">${id} · ${row.active ? "active" : "inactive"}</div></td>
            <td>${escapeHtmlFn(row.report_name || row.report_id)}</td>
            <td>${escapeHtmlFn(String(row.interval_minutes))}m · ${escapeHtmlFn(row.format)}</td>
            <td>${escapeHtmlFn((row.recipients || []).join(", "))}</td>
            <td><div>${escapeHtmlFn(next)}</div><div class="hint">${last}</div></td>
            <td class="itsm-report-actions">${runBtn}${toggleBtn}${editBtn}${delBtn}</td>
          </tr>`;
        })
        .join("");
    } catch (err) {
      if (meta) meta.textContent = err.message || "Failed to load schedules";
      body.innerHTML = `<tr><td colspan="6" class="hint">${escapeHtmlFn(err.message || "Failed")}</td></tr>`;
    }
  }

  async function saveReportSchedule(ev) {
    ev?.preventDefault?.();
    if (!canWriteReports()) {
      toast("Missing itsm:reports:write permission", true);
      return;
    }
    try {
      const recipients = String(
        document.getElementById("itsmReportScheduleRecipients")?.value || ""
      )
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const payload = {
        report_id: document.getElementById("itsmReportScheduleReportId")?.value,
        name: document.getElementById("itsmReportScheduleName")?.value || null,
        interval_minutes: Number(
          document.getElementById("itsmReportScheduleInterval")?.value || 1440
        ),
        timezone: document.getElementById("itsmReportScheduleTz")?.value || "UTC",
        format: document.getElementById("itsmReportScheduleFormat")?.value || "csv",
        recipients,
        channels: ["email"],
        active: !!document.getElementById("itsmReportScheduleActive")?.checked,
      };
      const id = document.getElementById("itsmReportScheduleId")?.value;
      if (id) {
        const { report_id: _rid, ...patch } = payload;
        await SVRMON24ItsmApi.updateReportSchedule(id, patch);
        toast("Schedule updated");
      } else {
        await SVRMON24ItsmApi.createReportSchedule(payload);
        toast("Schedule created");
      }
      const form = document.getElementById("itsmReportScheduleForm");
      if (form) form.hidden = true;
      await loadReportSchedules();
    } catch (err) {
      toast(err.message || "Save schedule failed", true);
    }
  }

  async function onScheduleTableClick(ev) {
    const btn = ev.target.closest(
      "button[data-sch-run],button[data-sch-edit],button[data-sch-del],button[data-sch-toggle]"
    );
    if (!btn) return;
    const run = btn.getAttribute("data-sch-run");
    const edit = btn.getAttribute("data-sch-edit");
    const del = btn.getAttribute("data-sch-del");
    const toggle = btn.getAttribute("data-sch-toggle");
    try {
      if (run) {
        const result = await SVRMON24ItsmApi.runReportSchedule(run);
        toast(`Schedule run ${result.status || "done"}`);
        await loadReportSchedules();
      } else if (edit) {
        const doc = await SVRMON24ItsmApi.getReportSchedule(edit);
        showScheduleForm(doc);
      } else if (del) {
        if (!global.confirm(`Delete schedule ${del}?`)) return;
        await SVRMON24ItsmApi.deleteReportSchedule(del);
        toast("Schedule deleted");
        await loadReportSchedules();
      } else if (toggle) {
        const active = btn.getAttribute("data-active") === "1";
        await SVRMON24ItsmApi.updateReportSchedule(toggle, { active: !active });
        toast(active ? "Schedule disabled" : "Schedule enabled");
        await loadReportSchedules();
      }
    } catch (err) {
      toast(err.message || "Schedule action failed", true);
    }
  }

  function initItsmReports({ toast: t, escapeHtml, can } = {}) {
    if (t) toastFn = t;
    if (escapeHtml) escapeHtmlFn = escapeHtml;
    if (can) canFn = can;

    document.getElementById("itsmReportsWindow")?.addEventListener("change", () => {
      loadItsmReports({ toast: toastFn });
    });
    document.getElementById("btnExportItsmReportsCsv")?.addEventListener("click", () => {
      downloadDashboardExport("csv");
    });
    document.getElementById("btnExportItsmReportsXlsx")?.addEventListener("click", () => {
      downloadDashboardExport("xlsx");
    });
    document.getElementById("btnRefreshItsmCustomReports")?.addEventListener("click", () => {
      loadCustomReports();
    });
    document.getElementById("btnNewItsmCustomReport")?.addEventListener("click", () => {
      showCustomForm(null);
    });
    document.getElementById("btnCancelItsmCustomReport")?.addEventListener("click", () => {
      resetCustomForm();
      const form = document.getElementById("itsmCustomReportForm");
      if (form) form.hidden = true;
    });
    document.getElementById("itsmCustomReportForm")?.addEventListener("submit", saveCustomReport);
    document.getElementById("itsmCustomReportTable")?.addEventListener("click", onCustomTableClick);
    document.getElementById("btnRefreshItsmReportSchedules")?.addEventListener("click", () => {
      loadReportSchedules();
    });
    document.getElementById("btnNewItsmReportSchedule")?.addEventListener("click", () => {
      showScheduleForm(null);
    });
    document.getElementById("btnCancelItsmReportSchedule")?.addEventListener("click", () => {
      const form = document.getElementById("itsmReportScheduleForm");
      if (form) form.hidden = true;
    });
    document.getElementById("itsmReportScheduleForm")?.addEventListener("submit", saveReportSchedule);
    document.getElementById("itsmReportScheduleTable")?.addEventListener("click", onScheduleTableClick);
    applyWriteGates();
  }

  global.SVRMON24ItsmReports = {
    loadItsmReports,
    loadCustomReports,
    loadReportSchedules,
    initItsmReports,
    applyWriteGates,
  };
})(window);
