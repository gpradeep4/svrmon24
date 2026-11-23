/* Service Portal execution history + simulate-tick (SP6). */
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

  async function loadExecutions() {
    if (!_api) return;
    const host = document.getElementById("spExecutionsStub");
    if (!host) return;
    const data = await _api("/api/portal/executions?page_size=50");
    const toolbar = `
      <div class="toolbar" style="margin-bottom:0.75rem;">
        <button type="button" id="btnSpSimulateTick">Simulate tick</button>
        <p class="hint">Advances queued/running runs (SIMULATED or LIVE when gates are on). DRY_RUN stays plan-only.</p>
      </div>`;
    if (!data.items?.length) {
      host.innerHTML =
        toolbar +
        '<p class="hint">No execution runs yet. Approve a request (ITSM Change) then Sync, then Simulate tick.</p>';
      document.getElementById("btnSpSimulateTick")?.addEventListener("click", () =>
        simulateTick().catch((err) => _toast?.(err.message || "Tick failed", true))
      );
      return;
    }
    host.innerHTML =
      toolbar +
      `<table class="data-table portal-executions-table">
        <thead>
          <tr>
            <th>Run</th>
            <th>Request</th>
            <th>Action</th>
            <th>Collect</th>
            <th>Mode</th>
            <th>Status</th>
            <th>CMDB</th>
          </tr>
        </thead>
        <tbody>
          ${data.items
            .map(
              (r) => `<tr>
                <td><code>${esc(r.run_id)}</code></td>
                <td><code>${esc(r.request_id)}</code></td>
                <td>${esc(r.action_key || "")}</td>
                <td>${esc(r.collect_mode || "")}</td>
                <td>${esc(r.execution_mode || "")}</td>
                <td><span class="status-pill">${esc(r.status)}</span></td>
                <td>${esc(r.cmdb_sync_status || "—")}${
                  r.component_id ? ` · <code>${esc(r.component_id)}</code>` : ""
                }</td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
    document.getElementById("btnSpSimulateTick")?.addEventListener("click", () =>
      simulateTick().catch((err) => _toast?.(err.message || "Tick failed", true))
    );
  }

  async function simulateTick() {
    if (!_api) return;
    const res = await _api("/api/portal/admin/simulate-tick", {
      method: "POST",
      body: JSON.stringify({ limit: 20 }),
    });
    _toast?.(`Simulate tick advanced ${res.advanced || 0} run(s)`, false);
    await loadExecutions();
    return res;
  }

  function onShowTab(name) {
    if (name === "sp-executions") {
      loadExecutions().catch((err) =>
        _toast?.(err.message || "Executions failed", true)
      );
    }
  }

  global.SVRMON24PortalExecutions = {
    bindApi,
    loadExecutions,
    simulateTick,
    onShowTab,
  };
})(typeof window !== "undefined" ? window : globalThis);
