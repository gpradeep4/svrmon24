/* Service Portal catalog list + request form renderer (SP2). */
(function (global) {
  "use strict";

  let _api = null;
  let _toast = null;
  let _showTab = null;
  let _selectedItem = null;

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

  async function loadCatalog(domain) {
    if (!_api) return;
    const params = new URLSearchParams({ page_size: "100" });
    if (domain) params.set("domain", domain);
    const data = await _api(`/api/portal/catalog?${params}`);
    const host = document.getElementById("spCatalogStub");
    const filters = document.getElementById("spCatalogFilters");
    if (filters && data.domains) {
      filters.innerHTML = ["", ...data.domains]
        .map((d) => {
          const label = d || "all";
          const active = (domain || "") === (d || "");
          return `<button type="button" class="secondary${active ? " active" : ""}" data-sp-domain="${esc(d)}">${esc(label)}</button>`;
        })
        .join(" ");
      filters.querySelectorAll("[data-sp-domain]").forEach((btn) => {
        btn.addEventListener("click", () => {
          loadCatalog(btn.getAttribute("data-sp-domain") || "").catch((err) =>
            _toast?.(err.message || "Catalog failed", true)
          );
        });
      });
    }
    if (!host) return;
    if (!data.items?.length) {
      host.innerHTML =
        '<p class="hint">No catalog items. Admins can seed via Catalog admin.</p>';
      return;
    }
    host.innerHTML = `<div class="portal-catalog-list">${data.items
      .map(
        (item) => `
      <article class="portal-catalog-card" data-item-id="${esc(item.item_id)}">
        <header>
          <strong>${esc(item.title)}</strong>
          <span class="status-pill muted">${esc(item.domain)}</span>
          <span class="status-pill warning">${esc(item.risk_tier)}</span>
        </header>
        <p class="hint">${esc(item.description || "")}</p>
        <p class="hint">Change type: <code>${esc(item.change_type_key)}</code> · collect: ${(item.allowed_collect_modes || []).join(", ")}</p>
        <button type="button" data-sp-request="${esc(item.item_id)}">Request</button>
      </article>`
      )
      .join("")}</div>`;
    host.querySelectorAll("[data-sp-request]").forEach((btn) => {
      btn.addEventListener("click", () => openRequestForm(btn.getAttribute("data-sp-request")));
    });
  }

  function fieldInput(field) {
    const name = esc(field.name);
    const req = field.required ? "required" : "";
    if (field.type === "boolean") {
      return `<label><input type="checkbox" name="${name}" ${field.default ? "checked" : ""}/> ${esc(field.label)}</label>`;
    }
    if (field.type === "enum") {
      const opts = (field.options || [])
        .map((o) => `<option value="${esc(o)}">${esc(o)}</option>`)
        .join("");
      return `<label>${esc(field.label)}<select name="${name}" ${req}>${opts}</select></label>`;
    }
    if (field.type === "text") {
      return `<label>${esc(field.label)}<textarea name="${name}" ${req} rows="3"></textarea></label>`;
    }
    const type =
      field.type === "integer" || field.type === "number"
        ? "number"
        : field.type === "datetime"
          ? "datetime-local"
          : "text";
    return `<label>${esc(field.label)}<input type="${type}" name="${name}" ${req} /></label>`;
  }

  async function openRequestForm(itemId) {
    if (!_api) return;
    const item = await _api(`/api/portal/catalog/${encodeURIComponent(itemId)}`);
    _selectedItem = item;
    if (typeof _showTab === "function") _showTab("sp-request-new");
    const stub = document.getElementById("spRequestNewStub");
    if (!stub) return;
    const fields = item.form_schema?.fields || [];
    const modes = (item.allowed_collect_modes || ["agentless"]).map(
      (m) => `<option value="${esc(m)}">${esc(m)}</option>`
    );
    stub.innerHTML = `
      <form id="spRequestForm" class="portal-request-form">
        <p class="hint"><strong>${esc(item.title)}</strong> · ${esc(item.domain)} · Change: <code>${esc(item.change_type_key)}</code></p>
        <label>Collect mode<select name="collect_mode">${modes.join("")}</select></label>
        ${fields.map(fieldInput).join("")}
        <div class="toolbar" style="grid-template-columns:1fr auto auto;">
          <p class="hint" id="spRequestFormErrors"></p>
          <button type="button" class="secondary" id="spRequestValidate">Validate</button>
          <button type="submit" id="spRequestSubmit" disabled title="Submit lands in SP3 (creates ITSM Change)">Submit (SP3)</button>
        </div>
      </form>`;
    document.getElementById("spRequestValidate")?.addEventListener("click", () =>
      validateCurrentForm().catch((err) => _toast?.(err.message || "Validate failed", true))
    );
    document.getElementById("spRequestForm")?.addEventListener("submit", (ev) => {
      ev.preventDefault();
      _toast?.("Request submit arrives in SP3 (ITSM Change on submit).", false);
    });
  }

  function readFormValues(form) {
    const data = {};
    const fd = new FormData(form);
    for (const [k, v] of fd.entries()) {
      if (k === "collect_mode") continue;
      data[k] = v;
    }
    form.querySelectorAll('input[type="checkbox"]').forEach((el) => {
      data[el.name] = el.checked;
    });
    return data;
  }

  async function validateCurrentForm() {
    if (!_selectedItem || !_api) return;
    const form = document.getElementById("spRequestForm");
    const errEl = document.getElementById("spRequestFormErrors");
    const body = { form_values: readFormValues(form) };
    try {
      const res = await _api(
        `/api/portal/catalog/${encodeURIComponent(_selectedItem.item_id)}/validate`,
        { method: "POST", body: JSON.stringify(body) }
      );
      if (errEl) errEl.textContent = "Form OK";
      _toast?.("Form validated", false);
      return res;
    } catch (err) {
      const detail = err?.detail || err?.message;
      const fieldErrors =
        detail && typeof detail === "object" ? detail.field_errors : null;
      if (errEl) {
        errEl.textContent = fieldErrors
          ? Object.entries(fieldErrors)
              .map(([k, v]) => `${k}: ${v}`)
              .join("; ")
          : String(detail || err.message || "validation failed");
      }
      throw err;
    }
  }

  async function seedCatalog() {
    if (!_api) return;
    const res = await _api("/api/portal/catalog/seed", { method: "POST", body: "{}" });
    _toast?.(
      `Seeded catalog: created ${res.created}, updated ${res.updated}`,
      false
    );
    await loadCatalog();
    return res;
  }

  function initCatalogUi() {
    const admin = document.getElementById("spCatalogAdminStub");
    if (admin && !document.getElementById("btnSpSeedCatalog")) {
      admin.innerHTML = `
        <button type="button" id="btnSpSeedCatalog">Seed catalog (all domains)</button>
        <p class="hint">Seeds OS / Middleware / Database / Networking / Cloud / Generic / Other items with change_type_key for ITSM Change approvals.</p>`;
      document
        .getElementById("btnSpSeedCatalog")
        ?.addEventListener("click", () =>
          seedCatalog().catch((err) => _toast?.(err.message || "Seed failed", true))
        );
    }
    const catalogPanel = document.getElementById("tab-sp-catalog");
    if (catalogPanel && !document.getElementById("spCatalogFilters")) {
      const banner = document.getElementById("spCatalogBanner");
      const filters = document.createElement("div");
      filters.id = "spCatalogFilters";
      filters.className = "toolbar portal-domain-filters";
      banner?.parentNode?.insertBefore(filters, banner.nextSibling);
    }
  }

  function onShowTab(name) {
    if (name === "sp-catalog") {
      loadCatalog().catch((err) => _toast?.(err.message || "Catalog failed", true));
    }
    if (name === "sp-catalog-admin") {
      initCatalogUi();
    }
  }

  global.SVRMON24PortalCatalog = {
    bindApi,
    loadCatalog,
    openRequestForm,
    seedCatalog,
    onShowTab,
    initCatalogUi,
  };
})(typeof window !== "undefined" ? window : globalThis);
