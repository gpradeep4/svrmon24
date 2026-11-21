/* global SVRMON24ItsmIncidents, SVRMON24ItsmChanges, SVRMON24ItsmProblems */
(function (global) {
  "use strict";

  let deps = {
    api: null,
    toast: () => {},
    escapeHtml: (s) => s,
    can: () => false,
  };

  const CI_FILTER_IDS = {
    "itsm-incidents": "itsmIncCiFilter",
    "itsm-changes": "itsmChgCiFilter",
    "itsm-problems": "itsmPrbCiFilter",
  };

  const PICKER_INPUT_IDS = [
    "itsmFieldCi",
    "itsmChgFieldCi",
    "itsmPrbFieldCi",
    "itsmCiComponentId",
    "itsmChgCiComponentId",
    "itsmPrbCiComponentId",
    "itsmIncCiFilter",
    "itsmChgCiFilter",
    "itsmPrbCiFilter",
  ];

  function $(sel) {
    return document.querySelector(sel);
  }

  function esc(s) {
    return deps.escapeHtml(s == null ? "" : String(s));
  }

  function showTab(name) {
    const nav = document.querySelector(`[data-tab="${name}"]`);
    if (nav) nav.click();
  }

  function setAllCiFilters(componentId) {
    Object.values(CI_FILTER_IDS).forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = componentId || "";
    });
  }

  function openTicketsForComponent(componentId, preferredTab) {
    const cid = (componentId || "").trim();
    if (!cid) {
      deps.toast("component_id required", true);
      return;
    }
    setAllCiFilters(cid);
    const tab = preferredTab || "itsm-incidents";
    showTab(tab);
    window.setTimeout(() => {
      if (tab === "itsm-incidents") {
        global.SVRMON24ItsmIncidents?.loadIncidents?.();
      } else if (tab === "itsm-changes") {
        global.SVRMON24ItsmChanges?.loadChanges?.();
      } else if (tab === "itsm-problems") {
        global.SVRMON24ItsmProblems?.loadProblems?.();
      }
    }, 120);
  }

  async function refreshCiPicker() {
    if (!deps.api) return;
    const list = document.getElementById("itsmCiPickerList");
    if (!list) return;
    try {
      const data = await deps.api("/api/entity-refs?limit=200");
      const items = (data.items || []).filter(
        (e) => !e.kind || e.kind === "component"
      );
      list.innerHTML = items
        .map((e) => {
          const id = e.entity_id || e.component_id || "";
          const label = e.display_name || e.name || id;
          const table = e.ref_table || e.component_type || "";
          return `<option value="${esc(id)}">${esc(label)}${
            table ? ` [${esc(table)}]` : ""
          }</option>`;
        })
        .join("");
    } catch (err) {
      // Soft-fail: typed component_id still works without the picker list.
      list.innerHTML = "";
    }
  }

  function wirePickerLists() {
    PICKER_INPUT_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (el && !el.getAttribute("list")) {
        el.setAttribute("list", "itsmCiPickerList");
      }
    });
  }

  function summarizeRows(rows, limit) {
    return (rows || [])
      .slice(0, limit)
      .map((r) => {
        const id = r.component_id || r.entity_id || r.id || "";
        const name = r.name || r.hostname_or_name || "";
        return name ? `${id} (${name})` : id;
      })
      .filter(Boolean);
  }

  async function renderImpactPanel(container, ciLinks) {
    if (!container) return;
    const links = Array.isArray(ciLinks) ? ciLinks : [];
    if (!links.length) {
      container.innerHTML =
        '<p class="hint">Link a CI to load a read-only CMDB dependency / impact snippet.</p>';
      return;
    }
    if (!deps.api) {
      container.innerHTML = '<p class="hint">CMDB API not bound.</p>';
      return;
    }
    const chunks = [];
    for (const link of links.slice(0, 3)) {
      const cid = String(link.component_id || "").trim();
      if (!cid) continue;
      try {
        const data = await deps.api(
          `/api/dependencies/${encodeURIComponent(cid)}?depth=3`
        );
        const up = summarizeRows(data.upstream?.rows || [], 5);
        const down = summarizeRows(data.downstream?.rows || [], 5);
        const apps = (data.impact?.potentially_affected_applications || [])
          .slice(0, 5)
          .map((a) => {
            const c = a.component || a;
            return c.component_id || c.name || a.name || "";
          })
          .filter(Boolean);
        const disclaimer =
          data.disclaimer || data.impact?.disclaimer || "";
        chunks.push(`
          <div class="itsm-impact-card" data-component-id="${esc(cid)}">
            <p><strong class="mono">${esc(cid)}</strong>
              <span class="hint"> · ${esc(link.name_snapshot || link.component_type || "")}</span>
              <button type="button" class="ghost itsm-open-cmdb-ci" data-id="${esc(cid)}">Open in CMDB</button>
            </p>
            <p class="hint">Upstream: ${esc(up.join(", ") || "—")}</p>
            <p class="hint">Downstream: ${esc(down.join(", ") || "—")}</p>
            <p class="hint">Potentially affected apps: ${esc(apps.join(", ") || "—")}</p>
            ${
              disclaimer
                ? `<p class="hint itsm-impact-disclaimer">${esc(disclaimer)}</p>`
                : ""
            }
          </div>`);
      } catch (err) {
        const msg = err?.message || "not found";
        chunks.push(`
          <div class="itsm-impact-card is-missing" data-component-id="${esc(cid)}">
            <p><strong class="mono">${esc(cid)}</strong>
              <span class="hint"> · dependency view unavailable (${esc(msg)})</span></p>
          </div>`);
      }
    }
    container.innerHTML =
      chunks.join("") ||
      '<p class="hint">No CI dependency data to show.</p>';
    container.querySelectorAll(".itsm-open-cmdb-ci").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        showTab("inventory");
        window.setTimeout(() => {
          const viewBtn = document.querySelector(
            `#inventoryBody [data-view="${CSS.escape(id)}"]`
          );
          if (viewBtn) viewBtn.click();
        }, 200);
      });
    });
  }

  function initItsmDeeplinks(options) {
    deps = { ...deps, ...(options || {}) };
    wirePickerLists();
    refreshCiPicker();
  }

  global.SVRMON24ItsmDeeplinks = {
    initItsmDeeplinks,
    openTicketsForComponent,
    setAllCiFilters,
    renderImpactPanel,
    refreshCiPicker,
  };
})(window);
