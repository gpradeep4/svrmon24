/* Service Portal requests list + submit wiring (SP3). */
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

  async function submitNewRequest(item, formValues, collectMode) {
    if (!_api || !item) return null;
    const body = {
      item_id: item.item_id,
      form_values: formValues || {},
      collect_mode: collectMode || item.default_collect_mode || "agentless",
      requested_execution_mode: "SIMULATED",
      submit: true,
    };
    const doc = await _api("/api/portal/requests", {
      method: "POST",
      body: JSON.stringify(body),
    });
    _toast?.(
      `Request ${doc.request_id} submitted · Change ${doc.change_number_display || doc.change_id}`,
      false
    );
    if (typeof _showTab === "function") _showTab("sp-my-requests");
    await loadMyRequests();
    return doc;
  }

  async function cancelRequest(requestId) {
    if (!_api || !requestId) return null;
    const doc = await _api(
      `/api/portal/requests/${encodeURIComponent(requestId)}/cancel`,
      { method: "POST", body: JSON.stringify({ comment: "Cancelled from Portal UI" }) }
    );
    _toast?.(`Request ${doc.request_id} cancelled`, false);
    await loadMyRequests();
    return doc;
  }

  async function loadMyRequests() {
    if (!_api) return;
    const data = await _api("/api/portal/requests?page_size=50");
    const host = document.getElementById("spMyRequestsStub");
    if (!host) return;
    if (!data.items?.length) {
      host.innerHTML = '<p class="hint">No requests yet. Start from Catalog → Request.</p>';
      return;
    }
    host.innerHTML = `
      <table class="data-table portal-requests-table">
        <thead>
          <tr>
            <th>Request</th>
            <th>Item</th>
            <th>Domain</th>
            <th>Collect</th>
            <th>Status</th>
            <th>Change</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${data.items
            .map((r) => {
              const canCancel = ["draft", "submitted", "pending_approval"].includes(
                r.status
              );
              const changeLabel =
                r.change_number_display || r.change_id || "—";
              const changeStatus = r.change_status_snapshot
                ? ` (${esc(r.change_status_snapshot)})`
                : "";
              return `<tr data-request-id="${esc(r.request_id)}">
                <td><code>${esc(r.request_id)}</code></td>
                <td>${esc(r.item_title_snapshot || r.item_key_snapshot || r.item_id)}</td>
                <td>${esc(r.domain || "")}</td>
                <td>${esc(r.collect_mode || "")}</td>
                <td><span class="status-pill">${esc(r.status)}</span></td>
                <td><code>${esc(changeLabel)}</code>${changeStatus}</td>
                <td>${
                  canCancel
                    ? `<button type="button" class="secondary" data-sp-cancel="${esc(r.request_id)}">Cancel</button>`
                    : ""
                }</td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>`;
    host.querySelectorAll("[data-sp-cancel]").forEach((btn) => {
      btn.addEventListener("click", () => {
        cancelRequest(btn.getAttribute("data-sp-cancel")).catch((err) =>
          _toast?.(err.message || "Cancel failed", true)
        );
      });
    });
  }

  function onShowTab(name) {
    if (name === "sp-my-requests") {
      loadMyRequests().catch((err) =>
        _toast?.(err.message || "Requests failed", true)
      );
    }
  }

  global.SVRMON24PortalRequests = {
    bindApi,
    submitNewRequest,
    loadMyRequests,
    cancelRequest,
    onShowTab,
  };
})(typeof window !== "undefined" ? window : globalThis);
