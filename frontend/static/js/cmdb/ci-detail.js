/**
 * CMDB C1 — Helix-aligned CI detail (sticky header + General + Specifications).
 *
 * Later slices hook via SVRMON24CmdbCiDetail.registerTabHook / load hooks:
 *   C2 Relationships / Relationship Details
 *   C3 People / Work Info (+ optional ITSM ticket_ref deep link)
 *   C4 Contracts / Outage / Impacted Areas
 *
 * ITSM coupling: related INC/CHG via /api/itsm/*?component_id= only (no Mongo joins).
 */
(function (global) {
  "use strict";

  const HELIX_TABS = [
    { id: "general", label: "General", active: true },
    { id: "specifications", label: "Specifications", active: true },
    { id: "work-info", label: "Work Info", active: false, slice: "C3" },
    { id: "contracts", label: "Contracts", active: false, slice: "C4" },
    { id: "people", label: "People", active: false, slice: "C3" },
    { id: "relationships", label: "Relationships", active: false, slice: "C2" },
    { id: "relationship-details", label: "Relationship Details", active: false, slice: "C2" },
    { id: "outage", label: "Outage", active: false, slice: "C4" },
    { id: "impacted-areas", label: "Impacted Areas", active: false, slice: "C4" },
  ];

  const STATUS_LABELS = {
    active: "Deployed / In Use",
    inactive: "Down / Offline",
    decommissioned: "Decommissioned",
    unknown: "Unknown",
  };

  const LEVEL_OPTS = ["1", "2", "3", "4", "5"];
  const SUPPORTED_OPTS = ["yes", "no", "unknown"];

  let deps = {
    api: null,
    toast: () => {},
    escapeHtml: (s) => String(s ?? ""),
    escapeAttr: (s) => String(s ?? ""),
    can: () => false,
    showTab: null,
    getReturnTab: () => "servers",
    customFields: () => [],
  };

  /** @type {Record<string, (ctx: object) => void>} */
  const tabHooks = {};

  let state = {
    componentId: null,
    doc: null,
    editing: false,
    ciTab: "general",
    returnTab: "servers",
  };

  function $(sel, root = document) {
    return root.querySelector(sel);
  }

  function esc(s) {
    return deps.escapeHtml(s == null ? "" : String(s));
  }

  function esa(s) {
    return deps.escapeAttr(s == null ? "" : String(s));
  }

  function dash(v) {
    if (v == null || v === "") return "—";
    return esc(v);
  }

  function fmtDateInput(v) {
    if (!v) return "";
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return String(v).slice(0, 10);
    return d.toISOString().slice(0, 10);
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || status || "—";
  }

  function typeLabel(ctype) {
    return ctype === "Server" ? "Computer System" : ctype || "CI";
  }

  function optionList(values, selected, { blank = true } = {}) {
    const opts = blank ? `<option value="">—</option>` : "";
    return (
      opts +
      values
        .map(
          (v) =>
            `<option value="${esa(v)}" ${String(selected) === String(v) ? "selected" : ""}>${esc(v)}</option>`
        )
        .join("")
    );
  }

  function fieldRow(label, controlHtml, { required = false, full = false } = {}) {
    return `<label class="${full ? "full" : ""}">${esc(label)}${
      required ? ' <span class="ci-req" aria-hidden="true">*</span>' : ""
    }${controlHtml}</label>`;
  }

  function readInput(key) {
    return $(`#ciDetailForm [data-ci="${CSS.escape(key)}"]`);
  }

  function setEditing(on) {
    state.editing = !!on;
    const form = $("#ciDetailForm");
    if (!form) return;
    form.querySelectorAll("[data-ci], [data-ci-nested], [data-ci-cf]").forEach((el) => {
      if (el.dataset.ciReadonly === "1") {
        el.disabled = true;
        return;
      }
      el.disabled = !state.editing;
    });
    const editBtn = $("#btnCiEdit");
    const saveBtn = $("#btnCiSave");
    const cancelBtn = $("#btnCiCancelEdit");
    if (editBtn) editBtn.hidden = state.editing || !deps.can("cmdb:write");
    if (saveBtn) saveBtn.hidden = !state.editing;
    if (cancelBtn) cancelBtn.hidden = !state.editing;
    form.classList.toggle("is-editing", state.editing);
  }

  function syncHash() {
    if (!state.componentId) return;
    if (global.SVRMON24ItsmRouting?.writeHash) {
      global.SVRMON24ItsmRouting.writeHash(
        {
          tab: "ci-detail",
          component_id: state.componentId,
          ci_tab: state.ciTab,
        },
        { replace: true }
      );
      return;
    }
    const p = new URLSearchParams();
    p.set("tab", "ci-detail");
    p.set("component_id", state.componentId);
    if (state.ciTab) p.set("ci_tab", state.ciTab);
    const url = `${global.location.pathname}${global.location.search}#${p}`;
    global.history.replaceState({}, "", url);
  }

  function renderTabStrip() {
    const strip = $("#ciDetailTabStrip");
    if (!strip) return;
    strip.innerHTML = HELIX_TABS.map((t) => {
      const selected = state.ciTab === t.id;
      const deferred = !t.active;
      return `<button type="button" role="tab" class="ci-tab${selected ? " is-active" : ""}${
        deferred ? " is-deferred" : ""
      }" data-ci-tab="${esa(t.id)}" aria-selected="${selected ? "true" : "false"}" ${
        deferred ? `title="Placeholder — content in ${esa(t.slice)}"` : ""
      }>${esc(t.label)}${deferred ? `<span class="ci-tab-soon">${esc(t.slice)}</span>` : ""}</button>`;
    }).join("");
  }

  function renderHeaderFields(doc, editing) {
    const dis = editing ? "" : "disabled";
    const status = doc.status || "active";
    return `
      <div class="ci-header-identity">
        ${fieldRow(
          "CI Name",
          `<input data-ci="name" value="${esa(doc.name || "")}" ${dis} required />`,
          { required: true }
        )}
        ${fieldRow(
          "Description",
          `<input data-ci="description" value="${esa(doc.description || "")}" ${dis} />`,
          { required: true }
        )}
      </div>
      <div class="ci-header-grid">
        <div class="ci-header-col">
          ${fieldRow(
            "CI ID",
            `<input data-ci="component_id" data-ci-readonly="1" class="mono" value="${esa(
              doc.component_id || ""
            )}" disabled />`
          )}
          ${fieldRow(
            "Tag Number",
            `<input data-ci="tag_number" value="${esa(doc.tag_number || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Serial Number",
            `<input data-ci="serial_number" value="${esa(doc.serial_number || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Part Number",
            `<input data-ci="part_number" value="${esa(doc.part_number || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Supported",
            `<select data-ci="supported" ${dis}>${optionList(
              SUPPORTED_OPTS,
              doc.supported
            )}</select>`
          )}
          ${fieldRow(
            "Inventory Name",
            `<input data-ci="inventory_name" value="${esa(doc.inventory_name || "")}" ${dis} />`
          )}
        </div>
        <div class="ci-header-col">
          ${fieldRow(
            "Company",
            `<input data-ci="company" value="${esa(doc.company || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Primary Capability",
            `<input data-ci-readonly="1" value="${esa(doc.component_type || "")}" disabled />`
          )}
          ${fieldRow(
            "System Role",
            `<input data-ci="system_role" value="${esa(doc.system_role || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Status",
            `<select data-ci="status" ${dis}>${optionList(
              ["active", "inactive", "decommissioned", "unknown"],
              status,
              { blank: false }
            )}</select>`,
            { required: true }
          )}
          <p class="hint ci-status-hint">UI label: <strong>${esc(
            statusLabel(status)
          )}</strong></p>
          ${fieldRow(
            "Status Reason",
            `<input data-ci="status_reason" value="${esa(doc.status_reason || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Environment",
            `<input data-ci="environment" value="${esa(doc.environment || "")}" ${dis} required />`,
            { required: true }
          )}
        </div>
        <div class="ci-header-col">
          ${fieldRow(
            "Impact",
            `<select data-ci="impact" ${dis}>${optionList(LEVEL_OPTS, doc.impact)}</select>`
          )}
          ${fieldRow(
            "Urgency",
            `<select data-ci="urgency" ${dis}>${optionList(LEVEL_OPTS, doc.urgency)}</select>`
          )}
          ${fieldRow(
            "Priority",
            `<select data-ci="priority" ${dis}>${optionList(LEVEL_OPTS, doc.priority)}</select>`
          )}
          ${fieldRow(
            "Users Affected",
            `<input data-ci="users_affected" type="number" min="0" value="${esa(
              doc.users_affected ?? ""
            )}" ${dis} />`
          )}
          ${fieldRow(
            "Additional Information",
            `<textarea data-ci="additional_information" rows="3" ${dis}>${esc(
              doc.additional_information || ""
            )}</textarea>`,
            { full: true }
          )}
        </div>
      </div>`;
  }

  function renderGeneral(doc, editing) {
    const dis = editing ? "" : "disabled";
    const pc = doc.product_categorization || {};
    const life = doc.lifecycle || {};
    return `
      <div class="ci-section-head">
        <h3>General</h3>
        <p class="hint">Product categorization, manufacturer / model, and lifecycle dates.</p>
      </div>
      <div class="form-grid ci-form-grid">
        ${fieldRow(
          "Manufacturer",
          `<input data-ci="manufacturer" value="${esa(doc.manufacturer || "")}" ${dis} />`
        )}
        ${fieldRow(
          "Model",
          `<input data-ci="model" value="${esa(doc.model || "")}" ${dis} />`
        )}
        ${fieldRow(
          "Product Tier 1",
          `<input data-ci-nested="product_categorization.tier1" value="${esa(
            pc.tier1 || ""
          )}" ${dis} />`
        )}
        ${fieldRow(
          "Product Tier 2",
          `<input data-ci-nested="product_categorization.tier2" value="${esa(
            pc.tier2 || ""
          )}" ${dis} />`
        )}
        ${fieldRow(
          "Product Tier 3",
          `<input data-ci-nested="product_categorization.tier3" value="${esa(
            pc.tier3 || ""
          )}" ${dis} />`
        )}
        ${fieldRow(
          "Ordered",
          `<input data-ci-nested="lifecycle.ordered_at" type="date" value="${esa(
            fmtDateInput(life.ordered_at)
          )}" ${dis} />`
        )}
        ${fieldRow(
          "Received",
          `<input data-ci-nested="lifecycle.received_at" type="date" value="${esa(
            fmtDateInput(life.received_at)
          )}" ${dis} />`
        )}
        ${fieldRow(
          "Installed",
          `<input data-ci-nested="lifecycle.installed_at" type="date" value="${esa(
            fmtDateInput(life.installed_at)
          )}" ${dis} />`
        )}
        ${fieldRow(
          "Retirement",
          `<input data-ci-nested="lifecycle.retirement_date" type="date" value="${esa(
            fmtDateInput(life.retirement_date)
          )}" ${dis} />`
        )}
      </div>
      <p class="hint" id="ciOwnerRollup">Owner summary: — (People tab in C3)</p>`;
  }

  function renderServerSpecs(doc, editing) {
    const dis = editing ? "" : "disabled";
    const boolVal =
      doc.is_virtual === true ? "true" : doc.is_virtual === false ? "false" : "";
    return `
      <div class="ci-specs-grid">
        <section class="ci-specs-col">
          <h4>Environment</h4>
          ${fieldRow(
            "System type",
            `<input data-ci="system_type" value="${esa(doc.system_type || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Virtual system type",
            `<input data-ci="virtual_system_type" value="${esa(
              doc.virtual_system_type || ""
            )}" ${dis} />`
          )}
          ${fieldRow(
            "is Virtual",
            `<select data-ci="is_virtual" ${dis}>
              <option value="">—</option>
              <option value="true" ${boolVal === "true" ? "selected" : ""}>Yes</option>
              <option value="false" ${boolVal === "false" ? "selected" : ""}>No</option>
            </select>`
          )}
          ${fieldRow(
            "Impact computation model",
            `<input data-ci="impact_computation_model" value="${esa(
              doc.impact_computation_model || ""
            )}" ${dis} />`
          )}
          ${fieldRow(
            "Reset capability",
            `<input data-ci="reset_capability" value="${esa(
              doc.reset_capability || ""
            )}" ${dis} />`
          )}
          ${fieldRow(
            "OS Family",
            `<input data-ci="os_family" value="${esa(doc.os_family || "")}" ${dis} />`
          )}
          ${fieldRow(
            "OS Version",
            `<input data-ci="os_version" value="${esa(doc.os_version || "")}" ${dis} />`
          )}
        </section>
        <section class="ci-specs-col">
          <h4>Network</h4>
          ${fieldRow(
            "Hostname",
            `<input data-ci="hostname" value="${esa(doc.hostname || "")}" ${dis} />`
          )}
          ${fieldRow(
            "DNS host name",
            `<input data-ci="dns_hostname" value="${esa(doc.dns_hostname || "")}" ${dis} />`
          )}
          ${fieldRow(
            "IP address",
            `<input data-ci="ip_address" value="${esa(doc.ip_address || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Domain",
            `<input data-ci="domain" value="${esa(doc.domain || "")}" ${dis} />`
          )}
          ${fieldRow(
            "Workgroup",
            `<input data-ci="workgroup" value="${esa(doc.workgroup || "")}" ${dis} />`
          )}
        </section>
        <section class="ci-specs-col">
          <h4>Memory</h4>
          ${fieldRow(
            "Total physical memory (MB)",
            `<input data-ci="total_physical_memory_mb" type="number" min="0" value="${esa(
              doc.total_physical_memory_mb ?? ""
            )}" ${dis} />`
          )}
          ${fieldRow(
            "Flash memory (MB)",
            `<input data-ci="flash_memory_mb" type="number" min="0" value="${esa(
              doc.flash_memory_mb ?? ""
            )}" ${dis} />`
          )}
        </section>
      </div>`;
  }

  function renderTypeSpecs(doc, editing) {
    const ctype = doc.component_type;
    if (ctype === "Server") return renderServerSpecs(doc, editing);
    const dis = editing ? "" : "disabled";
    // Non-server: show type-specific keys already on the document as a simple grid.
    const keys = Object.keys(doc).filter((k) =>
      [
        "hostname",
        "ip_address",
        "os_family",
        "os_version",
        "product_type",
        "product_version",
        "instance_name",
        "domain_name",
        "host_server_id",
        "listen_address",
        "listen_port",
        "installation_path",
        "domain_home",
        "log_folder_path",
        "endpoint",
        "cluster_or_replication_details",
        "device_name",
        "device_type",
        "management_ip",
        "virtual_ip",
        "listener_port",
        "application_name",
        "application_type",
        "service_url",
        "business_criticality",
        "owner",
      ].includes(k)
    );
    if (!keys.length) {
      return `<p class="hint">No type-specific specification fields for ${esc(ctype)}.</p>`;
    }
    return `<div class="form-grid ci-form-grid">${keys
      .map((key) =>
        fieldRow(
          key.replaceAll("_", " "),
          `<input data-ci="${esa(key)}" value="${esa(doc[key] ?? "")}" ${dis} />`
        )
      )
      .join("")}</div>`;
  }

  function renderCustomSpecs(doc, editing) {
    const ctype = doc.component_type;
    const defs = (deps.customFields() || []).filter(
      (f) =>
        (f.applies_to || []).includes("*") || (f.applies_to || []).includes(ctype)
    );
    const wrap = $("#ciSpecsCustom");
    if (!wrap) return;
    if (!defs.length) {
      wrap.innerHTML =
        '<p class="hint">No tenant custom fields for this type. Org attrs use field definitions — never hardcoded UOB_*.</p>';
      return;
    }
    const values = doc.custom_fields || {};
    const dis = editing ? "" : "disabled";
    wrap.innerHTML = `
      <div class="ci-section-head">
        <h4>Custom attributes</h4>
        <p class="hint">From cmdb_field_definitions for this type.</p>
      </div>
      <div class="form-grid ci-form-grid">${defs
        .map((field) => {
          const val = values[field.field_key];
          if (field.field_type === "boolean") {
            return fieldRow(
              field.label,
              `<select data-ci-cf="${esa(field.field_key)}" ${dis}>
                <option value="">—</option>
                <option value="true" ${val === true ? "selected" : ""}>true</option>
                <option value="false" ${val === false ? "selected" : ""}>false</option>
              </select>`
            );
          }
          if (field.field_type === "enum") {
            const opts = (field.enum_values || [])
              .map(
                (v) =>
                  `<option value="${esa(v)}" ${val === v ? "selected" : ""}>${esc(v)}</option>`
              )
              .join("");
            return fieldRow(
              field.label,
              `<select data-ci-cf="${esa(field.field_key)}" ${dis}>
                <option value="">—</option>${opts}
              </select>`
            );
          }
          return fieldRow(
            field.label,
            `<input data-ci-cf="${esa(field.field_key)}" value="${esa(val ?? "")}" ${dis} />`
          );
        })
        .join("")}</div>`;
  }

  function renderDeferredPanel(tabId) {
    const meta = HELIX_TABS.find((t) => t.id === tabId);
    return `<div class="ci-deferred panel-inner">
      <h3>${esc(meta?.label || tabId)}</h3>
      <p class="hint">Placeholder for slice <strong>${esc(
        meta?.slice || "later"
      )}</strong>. Data model and APIs land in that slice; C1 keeps the Helix tab strip only.</p>
      <p class="hint">Hooks: <code>SVRMON24CmdbCiDetail.registerTabHook("${esc(
        tabId
      )}", fn)</code></p>
    </div>`;
  }

  function renderBody() {
    const doc = state.doc || {};
    const body = $("#ciDetailTabBody");
    if (!body) return;
    const editing = state.editing;
    if (state.ciTab === "general") {
      body.innerHTML = renderGeneral(doc, editing);
    } else if (state.ciTab === "specifications") {
      body.innerHTML = `
        <div class="ci-section-head">
          <h3>Specifications</h3>
          <p class="hint">Technical profile — Environment / Network / Memory for Computer System.</p>
        </div>
        <div id="ciSpecsNative">${renderTypeSpecs(doc, editing)}</div>
        <div id="ciSpecsCustom"></div>`;
      renderCustomSpecs(doc, editing);
    } else {
      const hook = tabHooks[state.ciTab];
      if (typeof hook === "function") {
        body.innerHTML = "";
        hook({
          container: body,
          componentId: state.componentId,
          doc,
          api: deps.api,
          toast: deps.toast,
          escapeHtml: deps.escapeHtml,
        });
      } else {
        body.innerHTML = renderDeferredPanel(state.ciTab);
      }
    }
    setEditing(editing);
  }

  function renderChrome() {
    const doc = state.doc || {};
    const title = $("#ciDetailTitle");
    const kicker = $("#ciDetailKicker");
    if (kicker) {
      kicker.textContent = `${typeLabel(doc.component_type)} · ${doc.component_id || ""}`;
    }
    if (title) title.textContent = doc.name || doc.component_id || "CI detail";
    const headerFields = $("#ciDetailHeaderFields");
    if (headerFields) headerFields.innerHTML = renderHeaderFields(doc, state.editing);
    renderTabStrip();
    renderBody();
    setEditing(state.editing);
    const statusSelect = readInput("status");
    statusSelect?.addEventListener("change", () => {
      const hint = $(".ci-status-hint");
      if (hint) {
        hint.innerHTML = `UI label: <strong>${esc(statusLabel(statusSelect.value))}</strong>`;
      }
    });
  }

  async function loadRelatedItsm(componentId) {
    const box = $("#ciItsmRelated");
    if (!box) return;
    const canInc = deps.can("itsm:incident:read");
    const canChg = deps.can("itsm:change:read");
    if (!canInc && !canChg) {
      box.innerHTML =
        '<p class="hint">ITSM permissions required to list related tickets.</p>';
      return;
    }
    box.innerHTML = '<p class="hint">Loading related ITSM…</p>';
    const chunks = [];
    try {
      if (canInc) {
        const data = await deps.api(
          `/api/itsm/incidents?component_id=${encodeURIComponent(componentId)}&limit=5`
        );
        const items = data.items || [];
        chunks.push(`<div class="ci-itsm-block">
          <strong>Incidents</strong>
          <span class="hint">(${esc(data.total ?? items.length)})</span>
          <ul>${
            items.length
              ? items
                  .map(
                    (i) =>
                      `<li><button type="button" class="linkish" data-ci-open-inc="${esa(
                        i.incident_id || i.id
                      )}">${esc(i.incident_id || i.id)}</button>
                      ${esc(i.title || "")} · ${esc(i.status || "")}</li>`
                  )
                  .join("")
              : "<li class=\"hint\">None</li>"
          }</ul>
          <button type="button" class="ghost" data-ci-itsm-all="itsm-incidents">Open in ITSM</button>
        </div>`);
      }
      if (canChg) {
        const data = await deps.api(
          `/api/itsm/changes?component_id=${encodeURIComponent(componentId)}&limit=5`
        );
        const items = data.items || [];
        chunks.push(`<div class="ci-itsm-block">
          <strong>Changes</strong>
          <span class="hint">(${esc(data.total ?? items.length)})</span>
          <ul>${
            items.length
              ? items
                  .map(
                    (c) =>
                      `<li><button type="button" class="linkish" data-ci-open-chg="${esa(
                        c.change_id || c.id
                      )}">${esc(c.change_id || c.id)}</button>
                      ${esc(c.title || "")} · ${esc(c.status || "")}</li>`
                  )
                  .join("")
              : "<li class=\"hint\">None</li>"
          }</ul>
          <button type="button" class="ghost" data-ci-itsm-all="itsm-changes">Open in ITSM</button>
        </div>`);
      }
      box.innerHTML =
        chunks.join("") || '<p class="hint">No ITSM modules available.</p>';
      box.querySelectorAll("[data-ci-itsm-all]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const tab = btn.getAttribute("data-ci-itsm-all");
          if (global.SVRMON24ItsmDeeplinks?.openTicketsForComponent) {
            global.SVRMON24ItsmDeeplinks.openTicketsForComponent(
              componentId,
              tab
            );
          }
        });
      });
      box.querySelectorAll("[data-ci-open-inc]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-ci-open-inc");
          global.SVRMON24ItsmRouting?.navigateTo?.({
            tab: "itsm-incidents",
            component_id: componentId,
            incident_id: id,
          });
        });
      });
      box.querySelectorAll("[data-ci-open-chg]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-ci-open-chg");
          global.SVRMON24ItsmRouting?.navigateTo?.({
            tab: "itsm-changes",
            component_id: componentId,
            change_id: id,
          });
        });
      });
    } catch (err) {
      box.innerHTML = `<p class="hint">ITSM lookup failed: ${esc(
        err.message || "error"
      )}</p>`;
    }
  }

  function emptyToNull(v) {
    if (v == null) return null;
    if (typeof v === "string" && v.trim() === "") return null;
    return typeof v === "string" ? v.trim() : v;
  }

  function dateToIso(v) {
    const s = emptyToNull(v);
    if (!s) return null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return `${s}T00:00:00Z`;
    return s;
  }

  function collectPayload() {
    const form = $("#ciDetailForm");
    const payload = {};
    form.querySelectorAll("[data-ci]").forEach((el) => {
      const key = el.getAttribute("data-ci");
      if (!key || el.dataset.ciReadonly === "1") return;
      let value = el.value;
      if (key === "users_affected" || key.endsWith("_mb") || key.endsWith("_port")) {
        value = value === "" ? null : Number(value);
      } else if (key === "is_virtual") {
        value = value === "" ? null : value === "true";
      } else {
        value = emptyToNull(value);
      }
      payload[key] = value;
    });
    const pc = {};
    const life = {};
    form.querySelectorAll("[data-ci-nested]").forEach((el) => {
      const path = el.getAttribute("data-ci-nested");
      const [root, leaf] = path.split(".");
      let value = el.value;
      if (root === "lifecycle") value = dateToIso(value);
      else value = emptyToNull(value);
      if (root === "product_categorization") pc[leaf] = value;
      if (root === "lifecycle") life[leaf] = value;
    });
    payload.product_categorization = {
      tier1: pc.tier1 ?? null,
      tier2: pc.tier2 ?? null,
      tier3: pc.tier3 ?? null,
    };
    payload.lifecycle = {
      ordered_at: life.ordered_at ?? null,
      received_at: life.received_at ?? null,
      installed_at: life.installed_at ?? null,
      retirement_date: life.retirement_date ?? null,
    };
    const custom = {};
    form.querySelectorAll("[data-ci-cf]").forEach((el) => {
      const key = el.getAttribute("data-ci-cf");
      let value = el.value;
      if (value === "") return;
      const def = (deps.customFields() || []).find((f) => f.field_key === key);
      if (def?.field_type === "number") value = Number(value);
      if (def?.field_type === "boolean") value = value === "true";
      custom[key] = value;
    });
    // Preserve existing custom keys not shown; overlay edited ones.
    payload.custom_fields = { ...(state.doc?.custom_fields || {}), ...custom };
    // Clear removed empties for visible defs
    (deps.customFields() || []).forEach((f) => {
      const el = form.querySelector(`[data-ci-cf="${CSS.escape(f.field_key)}"]`);
      if (el && el.value === "") delete payload.custom_fields[f.field_key];
    });
    return payload;
  }

  async function saveCi(event) {
    event?.preventDefault?.();
    if (!state.componentId) return;
    try {
      const payload = collectPayload();
      const doc = await deps.api(
        `/api/components/${encodeURIComponent(state.componentId)}`,
        { method: "PUT", body: JSON.stringify(payload) }
      );
      state.doc = doc;
      state.editing = false;
      deps.toast(`Saved ${doc.component_id}`);
      renderChrome();
      await loadRelatedItsm(state.componentId);
    } catch (err) {
      deps.toast(err.message || "Save failed", true);
    }
  }

  async function openCiDetail(componentId, options = {}) {
    const cid = String(componentId || "").trim();
    if (!cid) {
      deps.toast("component_id required", true);
      return;
    }
    state.returnTab =
      options.returnTab ||
      (typeof deps.getReturnTab === "function" ? deps.getReturnTab() : null) ||
      "servers";
    state.ciTab = options.ciTab || "general";
    if (!HELIX_TABS.some((t) => t.id === state.ciTab && t.active)) {
      // Allow deferred tabs for deep-link readiness; show placeholder.
      if (!HELIX_TABS.some((t) => t.id === state.ciTab)) state.ciTab = "general";
    }
    state.editing = !!options.edit && deps.can("cmdb:write");
    state.componentId = cid;
    try {
      const doc = await deps.api(`/api/components/${encodeURIComponent(cid)}`);
      state.doc = doc;
      if (typeof deps.showTab === "function") deps.showTab("ci-detail");
      renderChrome();
      syncHash();
      loadRelatedItsm(cid);
    } catch (err) {
      deps.toast(err.message || "Failed to load CI", true);
    }
  }

  function closeCiDetail() {
    const ret = state.returnTab || "servers";
    state.componentId = null;
    state.doc = null;
    state.editing = false;
    if (typeof deps.showTab === "function") deps.showTab(ret);
  }

  function selectCiTab(tabId) {
    const meta = HELIX_TABS.find((t) => t.id === tabId);
    if (!meta) return;
    if (!meta.active && !tabHooks[tabId]) {
      // Still allow selecting deferred tabs to show placeholder (Helix strip).
    }
    state.ciTab = tabId;
    renderTabStrip();
    renderBody();
    syncHash();
  }

  function wireUi() {
    $("#btnCiBack")?.addEventListener("click", () => closeCiDetail());
    $("#btnCiRefresh")?.addEventListener("click", async () => {
      if (!state.componentId) return;
      await openCiDetail(state.componentId, {
        returnTab: state.returnTab,
        ciTab: state.ciTab,
        edit: false,
      });
      deps.toast("Refreshed");
    });
    $("#btnCiEdit")?.addEventListener("click", () => {
      if (!deps.can("cmdb:write")) {
        deps.toast("cmdb:write required", true);
        return;
      }
      state.editing = true;
      renderChrome();
    });
    $("#btnCiCancelEdit")?.addEventListener("click", () => {
      state.editing = false;
      renderChrome();
    });
    $("#ciDetailForm")?.addEventListener("submit", saveCi);
    $("#ciDetailTabStrip")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-ci-tab]");
      if (!btn) return;
      selectCiTab(btn.getAttribute("data-ci-tab"));
    });
    $("#btnCiViewItsm")?.addEventListener("click", () => {
      if (!state.componentId) return;
      if (global.SVRMON24ItsmDeeplinks?.openTicketsForComponent) {
        global.SVRMON24ItsmDeeplinks.openTicketsForComponent(state.componentId);
      } else {
        deps.toast("ITSM deep-links unavailable", true);
      }
    });
  }

  function initCiDetail(options) {
    deps = { ...deps, ...(options || {}) };
    wireUi();
  }

  function registerTabHook(tabId, fn) {
    if (!tabId || typeof fn !== "function") return;
    tabHooks[tabId] = fn;
  }

  function applyRoute(route) {
    if (!route || route.tab !== "ci-detail") return false;
    const cid = route.component_id;
    if (!cid) return false;
    openCiDetail(cid, { ciTab: route.ci_tab || "general" });
    return true;
  }

  global.SVRMON24CmdbCiDetail = {
    HELIX_TABS,
    STATUS_LABELS,
    initCiDetail,
    openCiDetail,
    closeCiDetail,
    selectCiTab,
    registerTabHook,
    applyRoute,
    getState: () => ({ ...state }),
  };
})(window);
