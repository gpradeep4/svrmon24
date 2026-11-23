/* Service Portal vulnerability reports + fix/rollback (SP11/SP12). */
(function (global) {
  "use strict";

  let _api = null;
  let _toast = null;
  let _showTab = null;

  function bindApi(api, opts) {
    _api = api;
    _toast = opts?.toast;
    _showTab = opts?.showTab || global.SvrmonPortalShowTab;
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function severityClass(sev) {
    const s = String(sev || "").toLowerCase();
    if (s === "critical" || s === "high") return "danger";
    if (s === "medium") return "warning";
    return "muted";
  }

  async function catalogItemByKey(key) {
    const data = await _api("/api/portal/catalog?domain=vulnerability&page_size=50");
    return (data.items || []).find((i) => i.key === key) || null;
  }

  async function submitCatalogRequest(itemKey, formValues) {
    const item = await catalogItemByKey(itemKey);
    if (!item) throw new Error(`Catalog item ${itemKey} not found — seed catalog first`);
    const doc = await _api("/api/portal/requests", {
      method: "POST",
      body: JSON.stringify({
        item_id: item.item_id,
        form_values: formValues,
        collect_mode: item.default_collect_mode || "agentless",
        requested_execution_mode: "SIMULATED",
        submit: true,
      }),
    });
    _toast?.(
      `Request ${doc.request_id} submitted · Change ${doc.change_number_display || doc.change_id} (approve in ITSM)`,
      false
    );
    if (typeof _showTab === "function") _showTab("sp-my-requests");
    return doc;
  }

  async function loadReports() {
    if (!_api) return;
    const host = document.getElementById("spVulnReportsStub");
    if (!host) return;
    const data = await _api("/api/portal/vuln/reports?page_size=50");
    if (!data.items?.length) {
      host.innerHTML =
        '<p class="hint">No vulnerability reports yet. Request <strong>Vulnerability scan (one server)</strong> or <strong>bulk</strong> from Catalog, approve the Change, then Simulate tick.</p>';
      return;
    }
    host.innerHTML = `<table class="data-table portal-vuln-table">
      <thead>
        <tr>
          <th>Report</th>
          <th>Scope</th>
          <th>Servers</th>
          <th>Findings</th>
          <th>Mode</th>
          <th>Created</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${data.items
          .map(
            (row) => `<tr data-report-id="${esc(row.report_id)}">
          <td><code>${esc(row.report_id)}</code></td>
          <td>${esc(row.scope)}</td>
          <td>${esc((row.component_ids || []).length)}</td>
          <td>${esc(row.finding_count)}</td>
          <td><span class="status-pill muted">${esc(row.execution_mode)}</span></td>
          <td>${esc(row.created_at || "")}</td>
          <td><button type="button" class="secondary" data-sp-vuln-open="${esc(row.report_id)}">Open</button></td>
        </tr>`
          )
          .join("")}
      </tbody>
    </table>
    <div id="spVulnReportDetail" class="portal-vuln-detail"></div>`;
    host.querySelectorAll("[data-sp-vuln-open]").forEach((btn) => {
      btn.addEventListener("click", () => {
        openReport(btn.getAttribute("data-sp-vuln-open")).catch((err) =>
          _toast?.(err.message || "Report failed", true)
        );
      });
    });
  }

  async function openReport(reportId) {
    if (!_api || !reportId) return;
    const report = await _api(
      `/api/portal/vuln/reports/${encodeURIComponent(reportId)}`
    );
    const detail = document.getElementById("spVulnReportDetail");
    if (!detail) return;
    const findings = report.findings || [];
    const suggestions = report.suggestions || [];
    const suggestByFinding = Object.fromEntries(
      suggestions.map((s) => [s.finding_id, s])
    );
    detail.innerHTML = `
      <h3>Report ${esc(report.report_id)}</h3>
      <p class="hint">Request <code>${esc(report.request_id || "—")}</code> ·
        servers: ${(report.component_ids || []).map((c) => `<code>${esc(c)}</code>`).join(" ")}</p>
      <p class="hint">Fix and rollback create an <strong>ITSM Change</strong> for approval before execution.</p>
      <table class="data-table">
        <thead>
          <tr>
            <th>Severity</th>
            <th>CVE / ID</th>
            <th>Package</th>
            <th>Server</th>
            <th>Status</th>
            <th>Suggestion</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${findings
            .map((f) => {
              const sug = suggestByFinding[f.finding_id]?.suggestion || "—";
              const status = f.status || "open";
              const fixBtn =
                status === "open" || status === "fixing"
                  ? `<button type="button" class="secondary" data-sp-vuln-fix="${esc(f.finding_id)}">Request fix</button>`
                  : "";
              const rbBtn =
                status === "fixed" && f.fix_run_id
                  ? `<button type="button" class="secondary" data-sp-vuln-rollback="${esc(f.fix_run_id)}">Request rollback</button>`
                  : "";
              return `<tr data-finding-id="${esc(f.finding_id)}" data-vuln-id="${esc(f.vuln_id)}" data-component-id="${esc(f.component_id)}" data-fix-run-id="${esc(f.fix_run_id || "")}">
                <td><span class="status-pill ${severityClass(f.severity)}">${esc(f.severity)}</span></td>
                <td><code>${esc(f.vuln_id)}</code></td>
                <td>${esc(f.package)}</td>
                <td><code>${esc(f.component_id)}</code></td>
                <td><span class="status-pill muted">${esc(status)}</span></td>
                <td class="hint">${esc(sug)}</td>
                <td>${fixBtn} ${rbBtn}</td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>`;

    detail.querySelectorAll("[data-sp-vuln-fix]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const row = btn.closest("tr");
        submitCatalogRequest("vuln.fix.apply", {
          report_id: report.report_id,
          vuln_id: row.getAttribute("data-vuln-id"),
          component_ids: row.getAttribute("data-component-id"),
          finding_ids: row.getAttribute("data-finding-id"),
        }).catch((err) => _toast?.(err.message || "Fix request failed", true));
      });
    });
    detail.querySelectorAll("[data-sp-vuln-rollback]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const fixRunId = btn.getAttribute("data-sp-vuln-rollback");
        submitCatalogRequest("vuln.fix.rollback", {
          fix_run_id: fixRunId,
        }).catch((err) => _toast?.(err.message || "Rollback request failed", true));
      });
    });
  }

  function onShowTab(name) {
    if (name === "sp-vuln-reports") {
      loadReports().catch((err) => _toast?.(err.message || "Vuln reports failed", true));
    }
  }

  global.SVRMON24PortalVuln = {
    bindApi,
    loadReports,
    openReport,
    onShowTab,
  };
})(window);
