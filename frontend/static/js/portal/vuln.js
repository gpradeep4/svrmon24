/* Service Portal vulnerability reports (SP11). */
(function (global) {
  "use strict";

  let _api = null;
  let _toast = null;

  function bindApi(api, opts) {
    _api = api;
    _toast = opts?.toast;
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
      <table class="data-table">
        <thead>
          <tr>
            <th>Severity</th>
            <th>CVE / ID</th>
            <th>Package</th>
            <th>Server</th>
            <th>Title</th>
            <th>Suggestion</th>
          </tr>
        </thead>
        <tbody>
          ${findings
            .map((f) => {
              const sug = suggestByFinding[f.finding_id]?.suggestion || "—";
              return `<tr>
                <td><span class="status-pill ${severityClass(f.severity)}">${esc(f.severity)}</span></td>
                <td><code>${esc(f.vuln_id)}</code></td>
                <td>${esc(f.package)}</td>
                <td><code>${esc(f.component_id)}</code></td>
                <td>${esc(f.title)}</td>
                <td class="hint">${esc(sug)}</td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>
      <p class="hint">Fix / rollback catalog items land in the next slice (Change-gated apply).</p>`;
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
