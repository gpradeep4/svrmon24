/* Service Portal Change-status view (SP4) — ITSM Change is SoT. */
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

  function openInItsm(changeId) {
    if (!changeId) return;
    if (global.SVRMON24ItsmRouting?.navigateTo) {
      global.SVRMON24ItsmRouting.navigateTo(
        { tab: "itsm-changes", change_id: changeId },
        { replace: false }
      );
      return;
    }
    const nav = document.querySelector('[data-tab="itsm-changes"]');
    if (nav) nav.click();
    window.setTimeout(() => {
      global.SVRMON24ItsmChanges?.openChange?.(changeId);
    }, 150);
  }

  async function syncAll() {
    if (!_api) return;
    const res = await _api("/api/portal/changes/sync", {
      method: "POST",
      body: "{}",
    });
    _toast?.(
      `Synced ${res.synced || 0} · transitioned ${res.transitioned || 0}`,
      false
    );
    await loadChangeStatus();
    return res;
  }

  async function syncOne(requestId) {
    if (!_api || !requestId) return;
    const doc = await _api(
      `/api/portal/changes/${encodeURIComponent(requestId)}/sync`,
      { method: "POST", body: "{}" }
    );
    _toast?.(
      `${doc.request_id}: ${doc.status} (Change ${doc.change_status_snapshot})`,
      false
    );
    await loadChangeStatus();
    return doc;
  }

  async function loadChangeStatus() {
    if (!_api) return;
    const host = document.getElementById("spApprovalsStub");
    if (!host) return;
    const data = await _api("/api/portal/changes?page_size=50");
    if (!data.items?.length) {
      host.innerHTML =
        '<p class="hint">No linked Changes yet. Submit a request from Catalog to create an ITSM Change.</p>';
      return;
    }
    host.innerHTML = `
      <div class="toolbar" style="margin-bottom:0.75rem;">
        <button type="button" id="btnSpSyncChanges">Sync from ITSM</button>
        <p class="hint">Decide in ITSM Changes / Approvals — Portal mirrors status only.</p>
      </div>
      <table class="data-table portal-changes-table">
        <thead>
          <tr>
            <th>Request</th>
            <th>Item</th>
            <th>Portal status</th>
            <th>Change</th>
            <th>Change status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${data.items
            .map((r) => {
              const changeLabel =
                r.change_number_display || r.change_id || "—";
              return `<tr>
                <td><code>${esc(r.request_id)}</code></td>
                <td>${esc(r.item_title_snapshot || r.item_key_snapshot || "")}</td>
                <td><span class="status-pill">${esc(r.status)}</span></td>
                <td><code>${esc(changeLabel)}</code></td>
                <td>${esc(r.change_status_snapshot || "—")}</td>
                <td class="toolbar" style="gap:0.35rem;">
                  <button type="button" class="secondary" data-sp-open-chg="${esc(r.change_id || "")}">Open in ITSM</button>
                  <button type="button" class="secondary" data-sp-sync-one="${esc(r.request_id)}">Sync</button>
                </td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>`;
    document.getElementById("btnSpSyncChanges")?.addEventListener("click", () =>
      syncAll().catch((err) => _toast?.(err.message || "Sync failed", true))
    );
    host.querySelectorAll("[data-sp-open-chg]").forEach((btn) => {
      btn.addEventListener("click", () =>
        openInItsm(btn.getAttribute("data-sp-open-chg"))
      );
    });
    host.querySelectorAll("[data-sp-sync-one]").forEach((btn) => {
      btn.addEventListener("click", () =>
        syncOne(btn.getAttribute("data-sp-sync-one")).catch((err) =>
          _toast?.(err.message || "Sync failed", true)
        )
      );
    });
  }

  function onShowTab(name) {
    if (name === "sp-approvals") {
      loadChangeStatus().catch((err) =>
        _toast?.(err.message || "Change status failed", true)
      );
    }
  }

  global.SVRMON24PortalApprovals = {
    bindApi,
    loadChangeStatus,
    syncAll,
    openInItsm,
    onShowTab,
  };
})(typeof window !== "undefined" ? window : globalThis);
