/* Service Portal requests list + submit wiring (SP3+; SP8 incident/Change links). */
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

  function openItsmChange(changeId) {
    if (!changeId) return;
    if (global.SVRMON24ItsmRouting?.navigateTo) {
      global.SVRMON24ItsmRouting.navigateTo(
        { tab: "itsm-changes", change_id: changeId },
        { replace: false }
      );
      return;
    }
    document.querySelector('[data-tab="itsm-changes"]')?.click();
    window.setTimeout(() => {
      global.SVRMON24ItsmChanges?.openChange?.(changeId);
    }, 150);
  }

  function openItsmIncident(incidentId) {
    if (!incidentId) return;
    if (global.SVRMON24ItsmRouting?.navigateTo) {
      global.SVRMON24ItsmRouting.navigateTo(
        { tab: "itsm-incidents", incident_id: incidentId },
        { replace: false }
      );
      return;
    }
    document.querySelector('[data-tab="itsm-incidents"]')?.click();
    window.setTimeout(() => {
      global.SVRMON24ItsmIncidents?.openIncident?.(incidentId);
    }, 150);
  }

  async function submitNewRequest(item, formValues, collectMode, linkedIncidentId) {
    if (!_api || !item) return null;
    const body = {
      item_id: item.item_id,
      form_values: formValues || {},
      collect_mode: collectMode || item.default_collect_mode || "agentless",
      requested_execution_mode: "SIMULATED",
      submit: true,
    };
    if (linkedIncidentId) body.linked_incident_id = linkedIncidentId;
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

  async function linkIncident(requestId, incidentId) {
    if (!_api || !requestId || !incidentId) return null;
    const doc = await _api(
      `/api/portal/requests/${encodeURIComponent(requestId)}/link-incident`,
      { method: "POST", body: JSON.stringify({ linked_incident_id: incidentId }) }
    );
    _toast?.(`Linked incident ${incidentId} to ${doc.request_id}`, false);
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
            <th>Status</th>
            <th>Change</th>
            <th>Incident</th>
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
                <td><span class="status-pill">${esc(r.status)}</span></td>
                <td>
                  ${
                    r.change_id
                      ? `<button type="button" class="secondary" data-sp-open-chg="${esc(r.change_id)}"><code>${esc(changeLabel)}</code>${changeStatus}</button>`
                      : "—"
                  }
                </td>
                <td>
                  ${
                    r.linked_incident_id
                      ? `<button type="button" class="secondary" data-sp-open-inc="${esc(r.linked_incident_id)}"><code>${esc(r.linked_incident_id)}</code></button>`
                      : `<button type="button" class="secondary" data-sp-link-inc="${esc(r.request_id)}">Link</button>`
                  }
                </td>
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
    host.querySelectorAll("[data-sp-open-chg]").forEach((btn) => {
      btn.addEventListener("click", () =>
        openItsmChange(btn.getAttribute("data-sp-open-chg"))
      );
    });
    host.querySelectorAll("[data-sp-open-inc]").forEach((btn) => {
      btn.addEventListener("click", () =>
        openItsmIncident(btn.getAttribute("data-sp-open-inc"))
      );
    });
    host.querySelectorAll("[data-sp-link-inc]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = window.prompt("ITSM incident id to link (e.g. INC-…)");
        if (!id) return;
        linkIncident(btn.getAttribute("data-sp-link-inc"), id.trim()).catch((err) =>
          _toast?.(err.message || "Link failed", true)
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
    linkIncident,
    openItsmChange,
    openItsmIncident,
    onShowTab,
  };
})(typeof window !== "undefined" ? window : globalThis);
