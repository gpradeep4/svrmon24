/**
 * CMDB C1–C3 — Helix-aligned CI detail.
 *
 * C1: sticky header + General + Specifications.
 * C2: Relationships (HOSTS + child/parent) + Relationship Details tree.
 * C3: People + Work Info via registerTabHook (+ optional ITSM ticket_ref).
 *
 * Later slices hook via SVRMON24CmdbCiDetail.registerTabHook:
 *   C4 Contracts / Outage / Impacted Areas
 *
 * ITSM coupling: related INC/CHG via /api/itsm/*?component_id= for this CI and
 * HOSTS/HOSTED_ON children (no Mongo cross-DB joins). Work Info stores optional
 * itsm_ticket_ref only — tickets stay in ITSM DB.
 */
(function (global) {
  "use strict";

  const HELIX_TABS = [
    { id: "general", label: "General", active: true },
    { id: "specifications", label: "Specifications", active: true },
    { id: "work-info", label: "Work Info", active: true },
    { id: "contracts", label: "Contracts", active: false, slice: "C4" },
    { id: "people", label: "People", active: true },
    { id: "relationships", label: "Relationships", active: true },
    { id: "relationship-details", label: "Relationship Details", active: true },
    { id: "outage", label: "Outage", active: false, slice: "C4" },
    { id: "impacted-areas", label: "Impacted Areas", active: false, slice: "C4" },
  ];

  const PEOPLE_ROLES = [
    { value: "managed_by", label: "Managed by" },
    { value: "supported_by", label: "Supported by" },
    { value: "owned_by", label: "Owned by" },
    { value: "approved_by", label: "Approved by" },
  ];

  const WORK_INFO_TYPES = [
    { value: "general", label: "General" },
    { value: "customer_communication", label: "Customer Communication" },
    { value: "incident", label: "Incident" },
    { value: "problem", label: "Problem" },
    { value: "change", label: "Change" },
    { value: "note", label: "Note" },
    { value: "other", label: "Other" },
  ];

  const REL_TYPE_FILTERS = [
    { value: "", label: "All types" },
    { value: "HOSTS", label: "HOSTS (hosted children)" },
    { value: "HOSTED_ON", label: "HOSTED_ON" },
    { value: "DEPENDS_ON", label: "DEPENDS_ON" },
    { value: "CONNECTS_TO", label: "CONNECTS_TO" },
    { value: "ROUTES_TO", label: "ROUTES_TO" },
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
    relDirection: "child",
    relType: "HOSTS",
    relDetailsGroup: "ip_endpoint",
    childComponentIds: [],
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

  function relTypeOptions(selected) {
    return REL_TYPE_FILTERS.map(
      (t) =>
        `<option value="${esa(t.value)}" ${
          String(selected) === String(t.value) ? "selected" : ""
        }>${esc(t.label)}</option>`
    ).join("");
  }

  function renderRelationshipsShell(doc) {
    const primaryIp = doc.ip_address || "—";
    return `
      <div class="ci-section-head">
        <h3>Relationships</h3>
        <p class="hint">Related assets for this CI. Primary inventory IP stays on the Server
          (<code>${esc(primaryIp)}</code>); extra IPs are Network/IP children via <strong>HOSTS</strong>.</p>
      </div>
      <div class="ci-rel-filters">
        <label>Show
          <select id="ciRelDirection">
            <option value="child" ${state.relDirection === "child" ? "selected" : ""}>Child</option>
            <option value="parent" ${state.relDirection === "parent" ? "selected" : ""}>Parent</option>
            <option value="both" ${state.relDirection === "both" ? "selected" : ""}>Both</option>
          </select>
        </label>
        <label>Relationship type
          <select id="ciRelType">${relTypeOptions(state.relType)}</select>
        </label>
        <button type="button" class="secondary" id="ciRelRefresh">Refresh</button>
      </div>
      <div class="ci-rel-actions">
        <button type="button" class="secondary" id="ciRelLinkExisting" ${
          deps.can("relationships:write") ? "" : "disabled"
        }>Link existing (HOSTS)</button>
        <button type="button" class="secondary" id="ciRelCreateIp" ${
          deps.can("cmdb:write") && deps.can("relationships:write") ? "" : "disabled"
        }>Create IP child</button>
        <button type="button" class="secondary" id="ciRelCreateSoft" ${
          deps.can("cmdb:write") && deps.can("relationships:write") ? "" : "disabled"
        }>Create software child</button>
      </div>
      <div id="ciRelCreatePanel" class="ci-rel-create-panel" hidden></div>
      <div class="table-wrap">
        <table class="inventory ci-rel-table">
          <thead>
            <tr>
              <th>Relationship</th>
              <th>Related CI</th>
              <th>Component ID</th>
              <th>Category</th>
              <th>Product</th>
              <th>Version</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="ciRelBody"><tr><td colspan="7" class="hint">Loading…</td></tr></tbody>
        </table>
      </div>
      <p class="hint" id="ciRelEmpty" hidden>No related assets.</p>
      <div id="ciRelItsm" class="ci-rel-itsm" aria-live="polite"></div>`;
  }

  async function loadRelationshipsGrid() {
    const body = $("#ciRelBody");
    const empty = $("#ciRelEmpty");
    if (!body || !state.componentId) return;
    body.innerHTML = `<tr><td colspan="7" class="hint">Loading…</td></tr>`;
    try {
      const params = new URLSearchParams();
      params.set("component_id", state.componentId);
      params.set("direction", state.relDirection || "child");
      params.set("enrich", "true");
      params.set("page_size", "100");
      if (state.relType) params.set("relationship_type", state.relType);
      const data = await deps.api(`/api/relationships?${params}`);
      const items = data.items || [];
      state.childComponentIds = [
        ...new Set(
          items
            .map((e) => e.related_component_id)
            .filter((id) => id && id !== state.componentId)
        ),
      ];
      if (!items.length) {
        body.innerHTML = "";
        if (empty) empty.hidden = false;
      } else {
        if (empty) empty.hidden = true;
        body.innerHTML = items
          .map((edge) => {
            const rid = edge.related_component_id || "—";
            const canOpen = !!edge.related_component_id && !edge.related_table;
            return `<tr>
              <td>${esc(edge.relationship_type || "—")}</td>
              <td>${
                canOpen
                  ? `<button type="button" class="linkish" data-ci-open-rel="${esa(
                      rid
                    )}">${esc(edge.related_name || rid)}</button>`
                  : esc(edge.related_name || rid)
              }</td>
              <td class="mono">${esc(rid)}</td>
              <td>${esc(edge.related_category || "—")}</td>
              <td>${esc(edge.related_product || "—")}</td>
              <td>${esc(edge.related_version || "—")}</td>
              <td>${
                deps.can("relationships:write")
                  ? `<button type="button" class="ghost" data-ci-unlink-rel="${esa(
                      edge.relationship_id || ""
                    )}">Remove</button>`
                  : ""
              }</td>
            </tr>`;
          })
          .join("");
      }
      body.querySelectorAll("[data-ci-open-rel]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-ci-open-rel");
          if (id) openCiDetail(id, { returnTab: "ci-detail", ciTab: "general" });
        });
      });
      body.querySelectorAll("[data-ci-unlink-rel]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.getAttribute("data-ci-unlink-rel");
          if (!id || !confirm(`Remove relationship ${id}?`)) return;
          try {
            await deps.api(`/api/relationships/${encodeURIComponent(id)}`, {
              method: "DELETE",
            });
            deps.toast(`Removed ${id}`);
            await loadRelationshipsGrid();
            await loadRelatedItsm(state.componentId);
          } catch (err) {
            deps.toast(err.message || "Remove failed", true);
          }
        });
      });
      await loadRelationshipsItsmStrip();
    } catch (err) {
      body.innerHTML = `<tr><td colspan="7" class="hint">${esc(
        err.message || "Failed to load relationships"
      )}</td></tr>`;
    }
  }

  async function loadRelationshipsItsmStrip() {
    const box = $("#ciRelItsm");
    if (!box) return;
    const ids = [state.componentId, ...(state.childComponentIds || [])].filter(Boolean);
    const unique = [...new Set(ids)].slice(0, 12);
    const canInc = deps.can("itsm:incident:read");
    const canChg = deps.can("itsm:change:read");
    if (!canInc && !canChg) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML = `<p class="hint">Related ITSM for this CI and child CIs (API filter by component_id)…</p>`;
    const incRows = [];
    const chgRows = [];
    try {
      for (const cid of unique) {
        if (canInc) {
          const data = await deps.api(
            `/api/itsm/incidents?component_id=${encodeURIComponent(cid)}&limit=5`
          );
          (data.items || []).forEach((i) =>
            incRows.push({ ...i, _via: cid })
          );
        }
        if (canChg) {
          const data = await deps.api(
            `/api/itsm/changes?component_id=${encodeURIComponent(cid)}&limit=5`
          );
          (data.items || []).forEach((c) =>
            chgRows.push({ ...c, _via: cid })
          );
        }
      }
      const dedupe = (rows, idKey) => {
        const seen = new Set();
        return rows.filter((r) => {
          const id = r[idKey] || r.id;
          if (!id || seen.has(id)) return false;
          seen.add(id);
          return true;
        });
      };
      const incs = dedupe(incRows, "incident_id");
      const chgs = dedupe(chgRows, "change_id");
      box.innerHTML = `
        <div class="ci-itsm-block">
          <strong>ITSM on CI + children</strong>
          <p class="hint">Incidents ${esc(incs.length)} · Changes ${esc(chgs.length)}
            (queried ${esc(unique.length)} component_id value(s) via ITSM APIs)</p>
          <ul>${
            incs.length
              ? incs
                  .slice(0, 8)
                  .map(
                    (i) =>
                      `<li>${esc(i.incident_id || i.id)} — ${esc(i.title || "")}
                        <span class="hint">(via ${esc(i._via)})</span></li>`
                  )
                  .join("")
              : '<li class="hint">No incidents</li>'
          }</ul>
          <ul>${
            chgs.length
              ? chgs
                  .slice(0, 8)
                  .map(
                    (c) =>
                      `<li>${esc(c.change_id || c.id)} — ${esc(c.title || "")}
                        <span class="hint">(via ${esc(c._via)})</span></li>`
                  )
                  .join("")
              : '<li class="hint">No changes</li>'
          }</ul>
        </div>`;
    } catch (err) {
      box.innerHTML = `<p class="hint">ITSM child lookup failed: ${esc(
        err.message || "error"
      )}</p>`;
    }
  }

  function showRelCreatePanel(kind) {
    const panel = $("#ciRelCreatePanel");
    if (!panel) return;
    if (kind === "ip") {
      panel.hidden = false;
      panel.innerHTML = `
        <h4>Create IP child (Network + HOSTS)</h4>
        <p class="hint">Primary <code>ip_address</code> on the Server is unchanged. This adds an extra IP endpoint CI.</p>
        <div class="form-grid ci-form-grid">
          <label>IP address *<input id="ciRelNewIp" required placeholder="10.1.2.3" /></label>
          <label>Name<input id="ciRelNewIpName" placeholder="auto from IP" /></label>
          <label>Environment<input id="ciRelNewIpEnv" value="${esa(
            state.doc?.environment || ""
          )}" /></label>
        </div>
        <div class="ci-rel-actions">
          <button type="button" class="primary" id="ciRelNewIpSave">Create &amp; link HOSTS</button>
          <button type="button" class="ghost" id="ciRelCreateCancel">Cancel</button>
        </div>`;
      $("#ciRelCreateCancel")?.addEventListener("click", () => {
        panel.hidden = true;
        panel.innerHTML = "";
      });
      $("#ciRelNewIpSave")?.addEventListener("click", createIpChild);
    } else if (kind === "soft") {
      panel.hidden = false;
      panel.innerHTML = `
        <h4>Create software / agent child (Application + HOSTS)</h4>
        <div class="form-grid ci-form-grid">
          <label>Name *<input id="ciRelNewSoftName" required placeholder="BigFix Agent" /></label>
          <label>Application type<input id="ciRelNewSoftType" placeholder="agent / package / os" /></label>
          <label>Version<input id="ciRelNewSoftVer" placeholder="1.0" /></label>
          <label>Environment<input id="ciRelNewSoftEnv" value="${esa(
            state.doc?.environment || ""
          )}" /></label>
        </div>
        <div class="ci-rel-actions">
          <button type="button" class="primary" id="ciRelNewSoftSave">Create &amp; link HOSTS</button>
          <button type="button" class="ghost" id="ciRelCreateCancel">Cancel</button>
        </div>`;
      $("#ciRelCreateCancel")?.addEventListener("click", () => {
        panel.hidden = true;
        panel.innerHTML = "";
      });
      $("#ciRelNewSoftSave")?.addEventListener("click", createSoftwareChild);
    } else if (kind === "link") {
      panel.hidden = false;
      panel.innerHTML = `
        <h4>Link existing CI via HOSTS</h4>
        <p class="hint">Source = this CI. Target = existing component_id (IP / OS / agent / software).</p>
        <div class="form-grid ci-form-grid">
          <label>Target component_id *<input id="ciRelLinkTarget" required class="mono" /></label>
        </div>
        <div class="ci-rel-actions">
          <button type="button" class="primary" id="ciRelLinkSave">Create HOSTS edge</button>
          <button type="button" class="ghost" id="ciRelCreateCancel">Cancel</button>
          <button type="button" class="ghost" id="ciRelOpenModal">Open full relationship form</button>
        </div>`;
      $("#ciRelCreateCancel")?.addEventListener("click", () => {
        panel.hidden = true;
        panel.innerHTML = "";
      });
      $("#ciRelLinkSave")?.addEventListener("click", linkHostsExisting);
      $("#ciRelOpenModal")?.addEventListener("click", () => {
        if (typeof global.SVRMON24Cmdb?.openRelCreatePrefill === "function") {
          global.SVRMON24Cmdb.openRelCreatePrefill({
            relationship_type: "HOSTS",
            source_component_id: state.componentId,
          });
        } else {
          deps.toast("Relationship form unavailable — use Link save here", true);
        }
      });
    }
  }

  async function createIpChild() {
    const ip = ($("#ciRelNewIp")?.value || "").trim();
    if (!ip) {
      deps.toast("IP address required", true);
      return;
    }
    const name = ($("#ciRelNewIpName")?.value || "").trim() || `IP ${ip}`;
    const env =
      ($("#ciRelNewIpEnv")?.value || "").trim() || state.doc?.environment || "unknown";
    try {
      const child = await deps.api("/api/components", {
        method: "POST",
        body: JSON.stringify({
          component_type: "Network",
          name,
          environment: env,
          status: "active",
          device_type: "ip_endpoint",
          management_ip: ip,
        }),
      });
      await deps.api("/api/relationships", {
        method: "POST",
        body: JSON.stringify({
          source_component_id: state.componentId,
          target_component_id: child.component_id,
          relationship_type: "HOSTS",
          discovery_method: "manually_configured",
          verification_status: "unverified",
          confidence: "medium",
          evidence_or_notes: "Created from CI detail Relationships tab",
        }),
      });
      deps.toast(`HOSTS → ${child.component_id}`);
      const panel = $("#ciRelCreatePanel");
      if (panel) {
        panel.hidden = true;
        panel.innerHTML = "";
      }
      state.relType = "HOSTS";
      state.relDirection = "child";
      const typeSel = $("#ciRelType");
      const dirSel = $("#ciRelDirection");
      if (typeSel) typeSel.value = "HOSTS";
      if (dirSel) dirSel.value = "child";
      await loadRelationshipsGrid();
      await loadRelatedItsm(state.componentId);
    } catch (err) {
      deps.toast(err.message || "Create IP child failed", true);
    }
  }

  async function createSoftwareChild() {
    const name = ($("#ciRelNewSoftName")?.value || "").trim();
    if (!name) {
      deps.toast("Name required", true);
      return;
    }
    const appType = ($("#ciRelNewSoftType")?.value || "").trim() || "agent";
    const ver = ($("#ciRelNewSoftVer")?.value || "").trim() || null;
    const env =
      ($("#ciRelNewSoftEnv")?.value || "").trim() || state.doc?.environment || "unknown";
    const isOs = ["os", "operating_system", "operating system"].includes(
      appType.toLowerCase()
    );
    try {
      const payload = isOs
        ? {
            component_type: "Application",
            name,
            environment: env,
            status: "active",
            application_name: name,
            application_type: "os",
          }
        : {
            component_type: "Middleware",
            name,
            environment: env,
            status: "active",
            product_type: appType,
            product_version: ver,
            instance_name: name,
          };
      const child = await deps.api("/api/components", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await deps.api("/api/relationships", {
        method: "POST",
        body: JSON.stringify({
          source_component_id: state.componentId,
          target_component_id: child.component_id,
          relationship_type: "HOSTS",
          discovery_method: "manually_configured",
          verification_status: "unverified",
          confidence: "medium",
          evidence_or_notes: "Created from CI detail Relationships tab",
        }),
      });
      deps.toast(`HOSTS → ${child.component_id}`);
      const panel = $("#ciRelCreatePanel");
      if (panel) {
        panel.hidden = true;
        panel.innerHTML = "";
      }
      state.relType = "HOSTS";
      state.relDirection = "child";
      await loadRelationshipsGrid();
      await loadRelatedItsm(state.componentId);
    } catch (err) {
      deps.toast(err.message || "Create software child failed", true);
    }
  }

  async function linkHostsExisting() {
    const target = ($("#ciRelLinkTarget")?.value || "").trim();
    if (!target) {
      deps.toast("Target component_id required", true);
      return;
    }
    try {
      await deps.api("/api/relationships", {
        method: "POST",
        body: JSON.stringify({
          source_component_id: state.componentId,
          target_component_id: target,
          relationship_type: "HOSTS",
          discovery_method: "manually_configured",
          verification_status: "unverified",
          confidence: "medium",
        }),
      });
      deps.toast(`HOSTS → ${target}`);
      const panel = $("#ciRelCreatePanel");
      if (panel) {
        panel.hidden = true;
        panel.innerHTML = "";
      }
      await loadRelationshipsGrid();
      await loadRelatedItsm(state.componentId);
    } catch (err) {
      deps.toast(err.message || "Link failed", true);
    }
  }

  function wireRelationshipsTab() {
    $("#ciRelDirection")?.addEventListener("change", (e) => {
      state.relDirection = e.target.value || "child";
      loadRelationshipsGrid();
    });
    $("#ciRelType")?.addEventListener("change", (e) => {
      state.relType = e.target.value || "";
      loadRelationshipsGrid();
    });
    $("#ciRelRefresh")?.addEventListener("click", () => loadRelationshipsGrid());
    $("#ciRelLinkExisting")?.addEventListener("click", () => showRelCreatePanel("link"));
    $("#ciRelCreateIp")?.addEventListener("click", () => showRelCreatePanel("ip"));
    $("#ciRelCreateSoft")?.addEventListener("click", () => showRelCreatePanel("soft"));
    loadRelationshipsGrid();
  }

  function renderRelationshipDetailsShell() {
    return `
      <div class="ci-section-head">
        <h3>Relationship Details</h3>
        <p class="hint">Hierarchical browse of hosted children by class (projection over relationships).</p>
      </div>
      <div class="ci-rel-details">
        <aside class="ci-rel-tree" id="ciRelTree" aria-label="Related CI classes">
          <p class="hint">Loading…</p>
        </aside>
        <div class="ci-rel-detail-grid">
          <div class="ci-rel-detail-head">
            <strong id="ciRelDetailTitle">Select a class</strong>
            <span class="hint" id="ciRelDetailCount"></span>
            <button type="button" class="secondary" id="ciRelDetailsRefresh">Refresh</button>
          </div>
          <div class="table-wrap">
            <table class="inventory">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Component ID</th>
                  <th>Type</th>
                  <th>Product</th>
                  <th>Version</th>
                  <th>Relationship</th>
                </tr>
              </thead>
              <tbody id="ciRelDetailBody">
                <tr><td colspan="6" class="hint">Select a tree node</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>`;
  }

  async function loadRelationshipDetails() {
    const tree = $("#ciRelTree");
    const tbody = $("#ciRelDetailBody");
    if (!tree || !state.componentId) return;
    tree.innerHTML = `<p class="hint">Loading…</p>`;
    try {
      const data = await deps.api(
        `/api/components/${encodeURIComponent(state.componentId)}/relationship-details`
      );
      state._relDetails = data;
      state.childComponentIds = data.related_component_ids || [];
      const groups = data.groups || {};
      tree.innerHTML = (data.tree || [])
        .map((node) => {
          const selected = state.relDetailsGroup === node.key;
          const count = node.count ?? 0;
          if (count === 0) {
            return `<button type="button" class="ci-rel-tree-node is-empty${
              selected ? " is-active" : ""
            }" data-rel-group="${esa(node.key)}" disabled>
              ${esc(node.label)} <span class="hint">0</span>
            </button>`;
          }
          return `<button type="button" class="ci-rel-tree-node${
            selected ? " is-active" : ""
          }" data-rel-group="${esa(node.key)}">
            ${esc(node.label)} <span class="hint">${esc(count)}</span>
          </button>`;
        })
        .join("");
      // Prefer first non-empty group if current empty
      const current = groups[state.relDetailsGroup];
      if (!current || !current.total) {
        const first = (data.tree || []).find((n) => (n.count || 0) > 0);
        if (first) state.relDetailsGroup = first.key;
      }
      tree.querySelectorAll("[data-rel-group]").forEach((btn) => {
        btn.addEventListener("click", () => {
          state.relDetailsGroup = btn.getAttribute("data-rel-group");
          renderRelDetailsGrid();
          tree.querySelectorAll(".ci-rel-tree-node").forEach((n) => {
            n.classList.toggle(
              "is-active",
              n.getAttribute("data-rel-group") === state.relDetailsGroup
            );
          });
        });
      });
      renderRelDetailsGrid();
    } catch (err) {
      tree.innerHTML = `<p class="hint">${esc(err.message || "Failed")}</p>`;
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="6" class="hint">${esc(
          err.message || "Failed"
        )}</td></tr>`;
      }
    }
  }

  function renderRelDetailsGrid() {
    const data = state._relDetails;
    const tbody = $("#ciRelDetailBody");
    const title = $("#ciRelDetailTitle");
    const countEl = $("#ciRelDetailCount");
    if (!data || !tbody) return;
    const group = (data.groups || {})[state.relDetailsGroup] || {
      label: state.relDetailsGroup,
      items: [],
      total: 0,
    };
    if (title) title.textContent = group.label || state.relDetailsGroup;
    const items = group.items || [];
    if (countEl) {
      countEl.textContent = items.length
        ? `Showing ${items.length} of ${group.total || items.length}`
        : "Empty";
    }
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="hint">No items in this class.</td></tr>`;
      return;
    }
    tbody.innerHTML = items
      .map((it) => {
        const canOpen = it.component_id && !it.synthetic;
        return `<tr>
          <td>${
            canOpen
              ? `<button type="button" class="linkish" data-ci-open-rel="${esa(
                  it.component_id
                )}">${esc(it.name || it.component_id)}</button>`
              : esc(it.name || "—")
          }${it.synthetic ? ' <span class="hint">(from Server os_*)</span>' : ""}</td>
          <td class="mono">${esc(it.component_id || "—")}</td>
          <td>${esc(it.component_type || it.category || "—")}</td>
          <td>${esc(it.product || "—")}</td>
          <td>${esc(it.version || "—")}</td>
          <td>${esc(it.relationship_type || (it.synthetic ? "—" : "—"))}</td>
        </tr>`;
      })
      .join("");
    tbody.querySelectorAll("[data-ci-open-rel]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-ci-open-rel");
        if (id) openCiDetail(id, { returnTab: "ci-detail", ciTab: "general" });
      });
    });
  }

  function wireRelationshipDetailsTab() {
    $("#ciRelDetailsRefresh")?.addEventListener("click", () => loadRelationshipDetails());
    loadRelationshipDetails();
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
    } else if (state.ciTab === "relationships") {
      body.innerHTML = renderRelationshipsShell(doc);
      wireRelationshipsTab();
    } else if (state.ciTab === "relationship-details") {
      body.innerHTML = renderRelationshipDetailsShell();
      wireRelationshipDetailsTab();
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

  async function fetchChildComponentIds(componentId) {
    try {
      const data = await deps.api(
        `/api/relationships?component_id=${encodeURIComponent(
          componentId
        )}&direction=child&enrich=true&page_size=50`
      );
      const ids = (data.items || [])
        .map((e) => e.related_component_id)
        .filter((id) => id && id !== componentId);
      state.childComponentIds = [...new Set(ids)];
      return state.childComponentIds;
    } catch {
      return state.childComponentIds || [];
    }
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
      const childIds = await fetchChildComponentIds(componentId);
      const scopeIds = [componentId, ...childIds].slice(0, 12);

      async function collect(kind) {
        const rows = [];
        for (const cid of scopeIds) {
          const path =
            kind === "inc"
              ? `/api/itsm/incidents?component_id=${encodeURIComponent(cid)}&limit=5`
              : `/api/itsm/changes?component_id=${encodeURIComponent(cid)}&limit=5`;
          const data = await deps.api(path);
          (data.items || []).forEach((row) => rows.push({ ...row, _via: cid }));
        }
        const idKey = kind === "inc" ? "incident_id" : "change_id";
        const seen = new Set();
        return rows.filter((r) => {
          const id = r[idKey] || r.id;
          if (!id || seen.has(id)) return false;
          seen.add(id);
          return true;
        });
      }

      if (canInc) {
        const items = await collect("inc");
        chunks.push(`<div class="ci-itsm-block">
          <strong>Incidents</strong>
          <span class="hint">(${esc(items.length)}${
            childIds.length ? ` · incl. ${esc(childIds.length)} child CI(s)` : ""
          })</span>
          <ul>${
            items.length
              ? items
                  .slice(0, 8)
                  .map(
                    (i) =>
                      `<li><button type="button" class="linkish" data-ci-open-inc="${esa(
                        i.incident_id || i.id
                      )}">${esc(i.incident_id || i.id)}</button>
                      ${esc(i.title || "")} · ${esc(i.status || "")}
                      ${
                        i._via && i._via !== componentId
                          ? `<span class="hint">(child ${esc(i._via)})</span>`
                          : ""
                      }</li>`
                  )
                  .join("")
              : "<li class=\"hint\">None</li>"
          }</ul>
          <button type="button" class="ghost" data-ci-itsm-all="itsm-incidents">Open in ITSM</button>
        </div>`);
      }
      if (canChg) {
        const items = await collect("chg");
        chunks.push(`<div class="ci-itsm-block">
          <strong>Changes</strong>
          <span class="hint">(${esc(items.length)}${
            childIds.length ? ` · incl. ${esc(childIds.length)} child CI(s)` : ""
          })</span>
          <ul>${
            items.length
              ? items
                  .slice(0, 8)
                  .map(
                    (c) =>
                      `<li><button type="button" class="linkish" data-ci-open-chg="${esa(
                        c.change_id || c.id
                      )}">${esc(c.change_id || c.id)}</button>
                      ${esc(c.title || "")} · ${esc(c.status || "")}
                      ${
                        c._via && c._via !== componentId
                          ? `<span class="hint">(child ${esc(c._via)})</span>`
                          : ""
                      }</li>`
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

  // ---------------------------------------------------------------------------
  // C3 — People + Work Info (registerTabHook)
  // ---------------------------------------------------------------------------

  async function openCreateRelatedItsm(componentId, kind) {
    const tab = kind === "change" ? "itsm-changes" : "itsm-incidents";
    let assignmentGroup = null;
    try {
      const primary = await deps.api(
        `/api/components/${encodeURIComponent(componentId)}/people/primary`
      );
      const hint = primary?.assignment_hint;
      if (hint?.assignment_group) assignmentGroup = hint.assignment_group;
    } catch (_err) {
      // Soft-fail: still open ITSM create with CI only.
    }
    if (global.SVRMON24ItsmDeeplinks?.openCreateRelated) {
      global.SVRMON24ItsmDeeplinks.openCreateRelated(componentId, {
        tab,
        assignmentGroup,
      });
      return;
    }
    if (global.SVRMON24ItsmDeeplinks?.openTicketsForComponent) {
      global.SVRMON24ItsmDeeplinks.openTicketsForComponent(componentId, tab);
    } else {
      deps.toast("ITSM deep-links unavailable", true);
    }
  }

  function openItsmTicketRef(ref) {
    if (!ref || !ref.ticket_id) return;
    const module = String(ref.module || "").toLowerCase();
    const tid = ref.ticket_id;
    if (module === "incident") {
      global.SVRMON24ItsmRouting?.navigateTo?.({
        tab: "itsm-incidents",
        incident_id: tid,
      });
    } else if (module === "change") {
      global.SVRMON24ItsmRouting?.navigateTo?.({
        tab: "itsm-changes",
        change_id: tid,
      });
    } else if (module === "problem") {
      global.SVRMON24ItsmRouting?.navigateTo?.({
        tab: "itsm-problems",
        problem_id: tid,
      });
    } else if (global.SVRMON24ItsmDeeplinks?.openTicketsForComponent) {
      global.SVRMON24ItsmDeeplinks.openTicketsForComponent(state.componentId);
    }
  }

  function peopleRoleOptions(selected) {
    const known = PEOPLE_ROLES.map(
      (r) =>
        `<option value="${esa(r.value)}" ${
          selected === r.value ? "selected" : ""
        }>${esc(r.label)}</option>`
    ).join("");
    if (selected && !PEOPLE_ROLES.some((r) => r.value === selected)) {
      return (
        `<option value="${esa(selected)}" selected>${esc(selected)}</option>` +
        known
      );
    }
    return known;
  }

  function workInfoTypeOptions(selected) {
    return WORK_INFO_TYPES.map(
      (t) =>
        `<option value="${esa(t.value)}" ${
          selected === t.value ? "selected" : ""
        }>${esc(t.label)}</option>`
    ).join("");
  }

  function renderPeopleHook(ctx) {
    const { container, componentId, api, toast } = ctx;
    const canWrite = deps.can("cmdb:write");
    container.innerHTML = `
      <div class="ci-section-head">
        <h3>People</h3>
        <p class="hint">Support groups and ownership roles for this CI — not an end-user directory.</p>
      </div>
      <div class="ci-people-actions">
        <button type="button" class="secondary" id="ciPeopleRefresh">Refresh</button>
        <button type="button" class="secondary" id="ciPeopleAdd" ${
          canWrite ? "" : "disabled"
        }>Add</button>
        <button type="button" class="ghost" id="ciPeopleCreateInc">Create related incident</button>
        <button type="button" class="ghost" id="ciPeopleCreateChg">Create related change</button>
      </div>
      <div id="ciPeopleForm" class="ci-people-form hidden">
        <h4>Add / modify people link</h4>
        <input type="hidden" id="ciPeopleLinkId" value="" />
        <div class="ci-form-grid two-col">
          <label>Type
            <select id="ciPeoplePartyType">
              <option value="support_group">Support group</option>
              <option value="person">Person</option>
            </select>
          </label>
          <label>Role
            <select id="ciPeopleRole">${peopleRoleOptions("managed_by")}</select>
          </label>
          <label>Display name *<input id="ciPeopleDisplay" required maxlength="300" placeholder="UOB Group→SIS…" /></label>
          <label>Source id *<input id="ciPeoplePartyId" required maxlength="200" placeholder="group or user id" /></label>
          <label class="check"><input type="checkbox" id="ciPeoplePrimary" /> Primary contact</label>
          <label class="check"><input type="checkbox" id="ciPeopleNotify" /> Notify on unavailability</label>
          <label class="check"><input type="checkbox" id="ciPeopleAssign" checked /> Assignment enabled</label>
          <label class="check"><input type="checkbox" id="ciPeopleAccess" /> Access permission</label>
        </div>
        <div class="ci-people-form-actions">
          <button type="button" class="primary" id="ciPeopleSave">${
            canWrite ? "Save" : "Save (need cmdb:write)"
          }</button>
          <button type="button" class="ghost" id="ciPeopleCancel">Cancel</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="data-table ci-people-table">
          <thead>
            <tr>
              <th>Full name</th>
              <th>Role</th>
              <th>Type</th>
              <th>Source id</th>
              <th>Unavail. notify</th>
              <th>Assignment</th>
              <th>Primary</th>
              <th>Access</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="ciPeopleBody"><tr><td colspan="9" class="hint">Loading…</td></tr></tbody>
        </table>
      </div>
      <p class="hint" id="ciPeopleEmpty" hidden>No people or support groups linked.</p>
      <p class="hint ci-people-itsm-hint" id="ciPeopleItsmHint"></p>`;

    const formEl = container.querySelector("#ciPeopleForm");
    const bodyEl = container.querySelector("#ciPeopleBody");
    const emptyEl = container.querySelector("#ciPeopleEmpty");
    const hintEl = container.querySelector("#ciPeopleItsmHint");

    function clearFormFields() {
      container.querySelector("#ciPeopleLinkId").value = "";
      container.querySelector("#ciPeoplePartyType").value = "support_group";
      container.querySelector("#ciPeopleRole").innerHTML =
        peopleRoleOptions("managed_by");
      container.querySelector("#ciPeopleDisplay").value = "";
      container.querySelector("#ciPeoplePartyId").value = "";
      container.querySelector("#ciPeoplePrimary").checked = false;
      container.querySelector("#ciPeopleNotify").checked = false;
      container.querySelector("#ciPeopleAssign").checked = true;
      container.querySelector("#ciPeopleAccess").checked = false;
    }

    function hideForm() {
      clearFormFields();
      formEl?.classList.add("hidden");
    }

    function showForm(row) {
      if (!row) {
        clearFormFields();
      } else {
        container.querySelector("#ciPeopleLinkId").value = row.link_id || "";
        container.querySelector("#ciPeoplePartyType").value =
          row.party_type || "support_group";
        container.querySelector("#ciPeopleRole").innerHTML = peopleRoleOptions(
          row.role || "managed_by"
        );
        container.querySelector("#ciPeopleDisplay").value = row.display_name || "";
        container.querySelector("#ciPeoplePartyId").value = row.party_id || "";
        container.querySelector("#ciPeoplePrimary").checked = !!row.primary_contact;
        container.querySelector("#ciPeopleNotify").checked =
          !!row.notify_on_unavailability;
        container.querySelector("#ciPeopleAssign").checked =
          !!row.assignment_enabled;
        container.querySelector("#ciPeopleAccess").checked =
          !!row.access_permission;
      }
      formEl?.classList.remove("hidden");
    }

    async function loadPeople() {
      bodyEl.innerHTML =
        '<tr><td colspan="9" class="hint">Loading…</td></tr>';
      try {
        const data = await api(
          `/api/components/${encodeURIComponent(componentId)}/people`
        );
        const items = data.items || [];
        if (!items.length) {
          bodyEl.innerHTML = "";
          if (emptyEl) emptyEl.hidden = false;
        } else {
          if (emptyEl) emptyEl.hidden = true;
          bodyEl.innerHTML = items
            .map((row) => {
              const yesNo = (v) => (v ? "Yes" : "No");
              return `<tr data-link-id="${esa(row.link_id)}">
                <td>${esc(row.display_name)}</td>
                <td>${esc(row.role)}</td>
                <td>${esc(row.party_type)}</td>
                <td class="mono">${esc(row.party_id)}</td>
                <td>${yesNo(row.notify_on_unavailability)}</td>
                <td>${yesNo(row.assignment_enabled)}</td>
                <td>${yesNo(row.primary_contact)}</td>
                <td>${yesNo(row.access_permission)}</td>
                <td class="ci-people-row-actions">
                  <button type="button" class="ghost" data-people-edit="${esa(
                    row.link_id
                  )}" ${canWrite ? "" : "disabled"}>Modify</button>
                  <button type="button" class="ghost danger" data-people-del="${esa(
                    row.link_id
                  )}" ${canWrite ? "" : "disabled"}>Remove</button>
                </td>
              </tr>`;
            })
            .join("");
        }
        const primary = await api(
          `/api/components/${encodeURIComponent(componentId)}/people/primary`
        );
        if (hintEl) {
          const h = primary?.assignment_hint;
          if (h?.assignment_group) {
            hintEl.textContent = `ITSM assignment hint: support group “${h.assignment_group}” (API-only; applied when creating related tickets).`;
          } else if (h?.assignee_hint) {
            hintEl.textContent = `ITSM assignee hint: “${h.assignee_hint}”.`;
          } else {
            hintEl.textContent =
              "No primary contact — related ITSM creates will prefill CI only.";
          }
        }
        bodyEl.querySelectorAll("[data-people-edit]").forEach((btn) => {
          btn.addEventListener("click", () => {
            const id = btn.getAttribute("data-people-edit");
            const row = items.find((r) => r.link_id === id);
            if (row) showForm(row);
          });
        });
        bodyEl.querySelectorAll("[data-people-del]").forEach((btn) => {
          btn.addEventListener("click", async () => {
            const id = btn.getAttribute("data-people-del");
            if (!id || !canWrite) return;
            if (!window.confirm("Remove this people link?")) return;
            try {
              await api(
                `/api/components/${encodeURIComponent(
                  componentId
                )}/people/${encodeURIComponent(id)}`,
                { method: "DELETE" }
              );
              toast("People link removed");
              await loadPeople();
            } catch (err) {
              toast(err.message || "Remove failed", true);
            }
          });
        });
      } catch (err) {
        bodyEl.innerHTML = `<tr><td colspan="9" class="hint">${esc(
          err.message || "Failed to load"
        )}</td></tr>`;
      }
    }

    container.querySelector("#ciPeopleRefresh")?.addEventListener("click", () => {
      loadPeople();
      toast("Refreshed");
    });
    container.querySelector("#ciPeopleAdd")?.addEventListener("click", () => {
      showForm(null);
    });
    container.querySelector("#ciPeopleCancel")?.addEventListener("click", hideForm);
    container.querySelector("#ciPeopleSave")?.addEventListener("click", async () => {
      if (!canWrite) {
        toast("cmdb:write required", true);
        return;
      }
      const linkId = container.querySelector("#ciPeopleLinkId")?.value?.trim();
      const payload = {
        party_type: container.querySelector("#ciPeoplePartyType")?.value,
        party_id: container.querySelector("#ciPeoplePartyId")?.value?.trim(),
        display_name: container.querySelector("#ciPeopleDisplay")?.value?.trim(),
        role: container.querySelector("#ciPeopleRole")?.value,
        primary_contact: !!container.querySelector("#ciPeoplePrimary")?.checked,
        notify_on_unavailability: !!container.querySelector("#ciPeopleNotify")
          ?.checked,
        assignment_enabled: !!container.querySelector("#ciPeopleAssign")?.checked,
        access_permission: !!container.querySelector("#ciPeopleAccess")?.checked,
      };
      if (!payload.party_id || !payload.display_name) {
        toast("Display name and source id are required", true);
        return;
      }
      try {
        if (linkId) {
          await api(
            `/api/components/${encodeURIComponent(
              componentId
            )}/people/${encodeURIComponent(linkId)}`,
            { method: "PATCH", body: JSON.stringify(payload) }
          );
          toast("People link updated");
        } else {
          await api(`/api/components/${encodeURIComponent(componentId)}/people`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          toast("People link added");
        }
        hideForm();
        await loadPeople();
      } catch (err) {
        toast(err.message || "Save failed", true);
      }
    });
    container
      .querySelector("#ciPeopleCreateInc")
      ?.addEventListener("click", () => openCreateRelatedItsm(componentId, "incident"));
    container
      .querySelector("#ciPeopleCreateChg")
      ?.addEventListener("click", () => openCreateRelatedItsm(componentId, "change"));

    loadPeople();
  }

  function renderWorkInfoHook(ctx) {
    const { container, componentId, api, toast } = ctx;
    const canWrite = deps.can("cmdb:write");
    container.innerHTML = `
      <div class="ci-section-head">
        <h3>Work Info</h3>
        <p class="hint">CMDB-local activity log. Optional ITSM ticket deep link — tickets are not stored in CMDB.</p>
      </div>
      <div class="ci-work-layout">
        <div class="ci-work-add panel-inner">
          <h4>Add Work Info</h4>
          <div class="ci-form-grid">
            <label>Type
              <select id="ciWorkType">${workInfoTypeOptions("general")}</select>
            </label>
            <label>Source<input id="ciWorkSource" maxlength="200" placeholder="Web Client / operator" /></label>
            <label class="full">Summary *<input id="ciWorkSummary" required maxlength="500" /></label>
            <label class="full">Notes<textarea id="ciWorkNotes" rows="4" maxlength="10000"></textarea></label>
            <label>View access
              <select id="ciWorkAccess">
                <option value="internal">Internal</option>
                <option value="public">Public</option>
              </select>
            </label>
            <label class="check"><input type="checkbox" id="ciWorkLocked" /> Locked</label>
            <label>ITSM module
              <select id="ciWorkItsmModule">
                <option value="">— none —</option>
                <option value="incident">Incident</option>
                <option value="change">Change</option>
                <option value="problem">Problem</option>
              </select>
            </label>
            <label>ITSM ticket id<input id="ciWorkItsmId" maxlength="80" placeholder="INC-… / CHG-…" /></label>
            <label class="full">Attachments<input type="file" id="ciWorkFiles" multiple /></label>
          </div>
          <div class="ci-work-add-actions">
            <button type="button" class="primary" id="ciWorkSave" ${
              canWrite ? "" : "disabled"
            }>Add</button>
            <button type="button" class="ghost" id="ciWorkCreateInc">Create related incident</button>
            <button type="button" class="ghost" id="ciWorkCreateChg">Create related change</button>
          </div>
        </div>
        <div class="ci-work-history panel-inner">
          <div class="ci-section-head">
            <h4>History</h4>
            <button type="button" class="secondary" id="ciWorkRefresh">Refresh</button>
          </div>
          <div class="table-wrap">
            <table class="data-table ci-work-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Summary</th>
                  <th>Attachments</th>
                  <th>Submit date</th>
                  <th>ITSM</th>
                  <th></th>
                </tr>
              </thead>
              <tbody id="ciWorkBody"><tr><td colspan="6" class="hint">Loading…</td></tr></tbody>
            </table>
          </div>
          <p class="hint" id="ciWorkEmpty" hidden>No work info yet.</p>
        </div>
      </div>`;

    const bodyEl = container.querySelector("#ciWorkBody");
    const emptyEl = container.querySelector("#ciWorkEmpty");

    function clearAddForm() {
      container.querySelector("#ciWorkType").value = "general";
      container.querySelector("#ciWorkSource").value = "";
      container.querySelector("#ciWorkSummary").value = "";
      container.querySelector("#ciWorkNotes").value = "";
      container.querySelector("#ciWorkAccess").value = "internal";
      container.querySelector("#ciWorkLocked").checked = false;
      container.querySelector("#ciWorkItsmModule").value = "";
      container.querySelector("#ciWorkItsmId").value = "";
      const files = container.querySelector("#ciWorkFiles");
      if (files) files.value = "";
    }

    async function loadWorkInfo() {
      bodyEl.innerHTML =
        '<tr><td colspan="6" class="hint">Loading…</td></tr>';
      try {
        const data = await api(
          `/api/components/${encodeURIComponent(componentId)}/work-info`
        );
        const items = data.items || [];
        if (!items.length) {
          bodyEl.innerHTML = "";
          if (emptyEl) emptyEl.hidden = false;
          return;
        }
        if (emptyEl) emptyEl.hidden = true;
        bodyEl.innerHTML = items
          .map((row) => {
            const ref = row.itsm_ticket_ref;
            const itsmCell = ref
              ? `<button type="button" class="linkish" data-work-itsm-mod="${esa(
                  ref.module
                )}" data-work-itsm-id="${esa(ref.ticket_id)}">Open in ITSM (${esc(
                  ref.ticket_id
                )})</button>`
              : "—";
            const when = row.created_at
              ? String(row.created_at).replace("T", " ").slice(0, 19)
              : "—";
            const locked = row.locked ? " 🔒" : "";
            return `<tr data-wid="${esa(row.work_info_id)}">
              <td>${esc(row.work_info_type)}${locked}</td>
              <td>${esc(row.summary)}</td>
              <td>${esc(row.attachment_count || 0)}</td>
              <td>${esc(when)}</td>
              <td>${itsmCell}</td>
              <td class="ci-work-row-actions">
                <button type="button" class="ghost" data-work-view="${esa(
                  row.work_info_id
                )}">View</button>
                <button type="button" class="ghost danger" data-work-del="${esa(
                  row.work_info_id
                )}" ${canWrite && !row.locked ? "" : "disabled"}>Delete</button>
              </td>
            </tr>`;
          })
          .join("");

        bodyEl.querySelectorAll("[data-work-itsm-mod]").forEach((btn) => {
          btn.addEventListener("click", () => {
            openItsmTicketRef({
              module: btn.getAttribute("data-work-itsm-mod"),
              ticket_id: btn.getAttribute("data-work-itsm-id"),
            });
          });
        });
        bodyEl.querySelectorAll("[data-work-view]").forEach((btn) => {
          btn.addEventListener("click", async () => {
            const wid = btn.getAttribute("data-work-view");
            try {
              const detail = await api(
                `/api/components/${encodeURIComponent(
                  componentId
                )}/work-info/${encodeURIComponent(wid)}`
              );
              const atts = (detail.attachments || [])
                .map((a) => a.filename || a.attachment_id)
                .join(", ");
              const notes = detail.notes || "—";
              window.alert(
                `Work Info ${detail.work_info_id}\n` +
                  `Type: ${detail.work_info_type}\n` +
                  `Summary: ${detail.summary}\n` +
                  `Notes: ${notes}\n` +
                  `Attachments: ${atts || "none"}\n` +
                  `Locked: ${detail.locked ? "yes" : "no"}`
              );
            } catch (err) {
              toast(err.message || "View failed", true);
            }
          });
        });
        bodyEl.querySelectorAll("[data-work-del]").forEach((btn) => {
          btn.addEventListener("click", async () => {
            const wid = btn.getAttribute("data-work-del");
            if (!wid || !canWrite) return;
            if (!window.confirm("Delete this work info entry?")) return;
            try {
              await api(
                `/api/components/${encodeURIComponent(
                  componentId
                )}/work-info/${encodeURIComponent(wid)}`,
                { method: "DELETE" }
              );
              toast("Work info deleted");
              await loadWorkInfo();
            } catch (err) {
              toast(err.message || "Delete failed", true);
            }
          });
        });
      } catch (err) {
        bodyEl.innerHTML = `<tr><td colspan="6" class="hint">${esc(
          err.message || "Failed to load"
        )}</td></tr>`;
      }
    }

    container.querySelector("#ciWorkRefresh")?.addEventListener("click", () => {
      loadWorkInfo();
      toast("Refreshed");
    });
    container
      .querySelector("#ciWorkCreateInc")
      ?.addEventListener("click", () => openCreateRelatedItsm(componentId, "incident"));
    container
      .querySelector("#ciWorkCreateChg")
      ?.addEventListener("click", () => openCreateRelatedItsm(componentId, "change"));
    container.querySelector("#ciWorkSave")?.addEventListener("click", async () => {
      if (!canWrite) {
        toast("cmdb:write required", true);
        return;
      }
      const summary = container.querySelector("#ciWorkSummary")?.value?.trim();
      if (!summary) {
        toast("Summary is required", true);
        return;
      }
      const module = container.querySelector("#ciWorkItsmModule")?.value || "";
      const ticketId = container.querySelector("#ciWorkItsmId")?.value?.trim() || "";
      const payload = {
        work_info_type: container.querySelector("#ciWorkType")?.value || "general",
        source: container.querySelector("#ciWorkSource")?.value?.trim() || null,
        summary,
        notes: container.querySelector("#ciWorkNotes")?.value?.trim() || null,
        locked: !!container.querySelector("#ciWorkLocked")?.checked,
        view_access: container.querySelector("#ciWorkAccess")?.value || "internal",
        itsm_ticket_ref:
          module && ticketId ? { module, ticket_id: ticketId } : null,
      };
      try {
        const created = await api(
          `/api/components/${encodeURIComponent(componentId)}/work-info`,
          { method: "POST", body: JSON.stringify(payload) }
        );
        const fileInput = container.querySelector("#ciWorkFiles");
        const files = fileInput?.files ? Array.from(fileInput.files) : [];
        for (const file of files) {
          const form = new FormData();
          form.append("file", file, file.name || "attachment.bin");
          await api(
            `/api/components/${encodeURIComponent(
              componentId
            )}/work-info/${encodeURIComponent(created.work_info_id)}/attachments`,
            { method: "POST", body: form }
          );
        }
        toast("Work info added");
        clearAddForm();
        await loadWorkInfo();
      } catch (err) {
        toast(err.message || "Add failed", true);
      }
    });

    loadWorkInfo();
  }

  // Activate C3 tabs through the C1 hook surface.
  registerTabHook("people", renderPeopleHook);
  registerTabHook("work-info", renderWorkInfoHook);

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
