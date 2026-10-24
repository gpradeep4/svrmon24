(() => {
  const STORAGE_KEY = "svrmon24.basicAuth";
  const state = {
    page: 1,
    pageSize: 25,
    totalPages: 1,
    editingId: null,
    customFields: [],
    deleteTarget: null,
    relPage: 1,
    relTotalPages: 1,
    editingRelId: null,
    relTypes: [],
    componentIds: [],
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function toast(message, isError = false) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("show"), 3200);
  }

  function authHeader() {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
      const { username, password } = JSON.parse(raw);
      if (!username || !password) return null;
      return "Basic " + btoa(`${username}:${password}`);
    } catch {
      return null;
    }
  }

  async function api(path, options = {}) {
    const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    const auth = authHeader();
    if (auth) headers.Authorization = auth;
    if (options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, { ...options, headers });
    let data = null;
    const text = await res.text();
    if (text) {
      try { data = JSON.parse(text); } catch { data = { detail: text }; }
    }
    if (!res.ok) {
      const detail = data?.error?.message || data?.detail || res.statusText;
      const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
      const err = new Error(msg);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function dash(value) {
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  }

  function statusClass(status) {
    if (status === "inactive") return "inactive";
    if (status === "decommissioned") return "decommissioned";
    return "";
  }

  function saveAuthFromForm() {
    const username = $("#authUser").value.trim();
    const password = $("#authPass").value;
    if (!username || !password) {
      toast("Enter username and password", true);
      return false;
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ username, password }));
    return true;
  }

  function loadAuthIntoForm() {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const { username, password } = JSON.parse(raw);
      $("#authUser").value = username || "";
      $("#authPass").value = password || "";
    } catch { /* ignore */ }
  }

  async function connect() {
    if (!saveAuthFromForm()) return;
    try {
      await api("/api/me");
      toast("Connected");
      await Promise.all([
        loadTypes(),
        loadCustomFields(),
        loadInventory(),
        loadRelationshipTypes(),
        loadRelationships(),
        refreshComponentIdList(),
      ]);
      // Prefill dependency analyzer if a component id was typed earlier
      if ($("#depComponentId") && !$("#depComponentId").value && state.componentIds[0]) {
        $("#depComponentId").value = state.componentIds[0];
      }
    } catch (err) {
      toast(err.message || "Auth failed", true);
    }
  }

  async function loadTypes() {
    const data = await api("/api/components/types");
    const selects = ["#filterType", "#fieldType", "#cfApplies"];
    for (const sel of selects) {
      const el = $(sel);
      if (!el) continue;
      const keepFirst = el.getAttribute("data-keep-first") === "1";
      const first = keepFirst ? el.options[0] : null;
      el.innerHTML = "";
      if (first) el.appendChild(first);
      for (const t of data.types) {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t;
        el.appendChild(opt);
      }
      if (sel === "#cfApplies") {
        const all = document.createElement("option");
        all.value = "*";
        all.textContent = "All types";
        el.insertBefore(all, el.firstChild);
        el.value = "*";
      }
    }
  }

  function queryParams() {
    const params = new URLSearchParams();
    const q = $("#searchQ").value.trim();
    const component_type = $("#filterType").value;
    const environment = $("#filterEnv").value.trim();
    const status = $("#filterStatus").value;
    if (q) params.set("q", q);
    if (component_type) params.set("component_type", component_type);
    if (environment) params.set("environment", environment);
    if (status) params.set("status", status);
    params.set("page", String(state.page));
    params.set("page_size", String(state.pageSize));
    params.set("sort_by", "updated_at");
    params.set("sort_dir", "desc");
    return params;
  }

  async function loadInventory() {
    const data = await api(`/api/components?${queryParams().toString()}`);
    state.totalPages = data.total_pages || 1;
    $("#pageInfo").textContent = `Page ${data.page} / ${state.totalPages || 1} · ${data.total} components`;
    $("#btnPrev").disabled = data.page <= 1;
    $("#btnNext").disabled = data.page >= (data.total_pages || 1);

    const tbody = $("#inventoryBody");
    tbody.innerHTML = "";
    for (const row of data.inventory || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(row.component_id)}</td>
        <td>${escapeHtml(row.hostname_or_name)}</td>
        <td>${escapeHtml(row.component_type)}</td>
        <td class="${row.os_family === "—" ? "dash" : ""}">${escapeHtml(row.os_family)}</td>
        <td class="${row.os_version === "—" ? "dash" : ""}">${escapeHtml(row.os_version)}</td>
        <td class="${row.product_type === "—" ? "dash" : ""}">${escapeHtml(row.product_type)}</td>
        <td class="${row.product_version === "—" ? "dash" : ""}">${escapeHtml(row.product_version)}</td>
        <td>${escapeHtml(row.environment)}</td>
        <td><span class="status-pill ${statusClass(row.status)}">${escapeHtml(row.status)}</span></td>
        <td class="actions">
          <button type="button" class="ghost" data-view="${escapeAttr(row.component_id)}">View</button>
          <button type="button" class="secondary" data-edit="${escapeAttr(row.component_id)}">Edit</button>
          <button type="button" class="danger" data-del="${escapeAttr(row.component_id)}">Delete</button>
        </td>`;
      tbody.appendChild(tr);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll("'", "&#39;");
  }

  const TYPE_FIELDS = {
    Server: ["hostname", "ip_address", "os_family", "os_version"],
    Middleware: [
      "product_type", "product_version", "instance_name", "domain_name",
      "host_server_id", "listen_address", "listen_port", "installation_path",
      "domain_home", "log_folder_path",
    ],
    Database: [
      "product_type", "product_version", "instance_name", "endpoint",
      "listen_port", "cluster_or_replication_details", "log_folder_path",
    ],
    Network: ["device_name", "device_type", "management_ip", "virtual_ip", "listener_port"],
    Application: [
      "application_name", "application_type", "service_url",
      "business_criticality", "owner",
    ],
  };

  function renderTypeFields(componentType, values = {}) {
    const wrap = $("#typeFields");
    wrap.innerHTML = "";
    const fields = TYPE_FIELDS[componentType] || [];
    for (const key of fields) {
      const label = document.createElement("label");
      label.innerHTML = `${key.replaceAll("_", " ")}<input data-field="${key}" value="${escapeAttr(values[key] ?? "")}" />`;
      wrap.appendChild(label);
    }
  }

  function openModal(title) {
    $("#modalTitle").textContent = title;
    $("#componentModal").classList.add("open");
  }

  function closeModal() {
    $("#componentModal").classList.remove("open");
    state.editingId = null;
  }

  function openCreate() {
    state.editingId = null;
    $("#componentForm").reset();
    $("#fieldComponentId").disabled = false;
    $("#fieldType").disabled = false;
    $("#fieldType").value = "Server";
    renderTypeFields("Server");
    renderCustomInputs("Server", {});
    openModal("Add component");
  }

  async function openEdit(id, readOnly = false) {
    const doc = await api(`/api/components/${encodeURIComponent(id)}`);
    state.editingId = id;
    $("#fieldComponentId").value = doc.component_id;
    $("#fieldComponentId").disabled = true;
    $("#fieldType").value = doc.component_type;
    $("#fieldType").disabled = true;
    $("#fieldName").value = doc.name || "";
    $("#fieldEnv").value = doc.environment || "";
    $("#fieldStatus").value = doc.status || "active";
    renderTypeFields(doc.component_type, doc);
    renderCustomInputs(doc.component_type, doc.custom_fields || {});
    $$("#componentForm input, #componentForm select, #componentForm textarea").forEach((el) => {
      if (el.id === "fieldComponentId" || el.id === "fieldType") return;
      el.disabled = readOnly;
    });
    $("#btnSaveComponent").style.display = readOnly ? "none" : "inline-block";
    openModal(readOnly ? `View ${id}` : `Edit ${id}`);
  }

  function collectPayload() {
    const component_type = $("#fieldType").value;
    const payload = {
      name: $("#fieldName").value.trim(),
      environment: $("#fieldEnv").value.trim(),
      status: $("#fieldStatus").value,
      custom_fields: collectCustomValues(),
    };
    if (!state.editingId) {
      payload.component_type = component_type;
      const cid = $("#fieldComponentId").value.trim();
      if (cid) payload.component_id = cid;
    }
    for (const input of $$("#typeFields [data-field]")) {
      const key = input.getAttribute("data-field");
      let value = input.value.trim();
      if (value === "") {
        payload[key] = null;
        continue;
      }
      if (key.endsWith("_port") || key === "listen_port" || key === "listener_port") {
        payload[key] = Number(value);
      } else {
        payload[key] = value;
      }
    }
    return payload;
  }

  async function saveComponent(event) {
    event.preventDefault();
    const payload = collectPayload();
    try {
      if (state.editingId) {
        await api(`/api/components/${encodeURIComponent(state.editingId)}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast("Component updated");
      } else {
        await api("/api/components", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast("Component created");
      }
      closeModal();
      await loadInventory();
      await refreshComponentIdList();
      await loadRelationships();
    } catch (err) {
      toast(err.message || "Save failed", true);
    }
  }

  async function beginDelete(id) {
    try {
      const preview = await api(`/api/components/${encodeURIComponent(id)}/delete-preview`);
      state.deleteTarget = id;
      $("#deleteMessage").textContent =
        `Delete component ${id} (${preview.component?.name || ""})? This cannot be undone.`;
      const warning = preview.relationship_warning || {};
      const box = $("#deleteWarn");
      box.style.display = "block";
      if (warning.has_relationships) {
        const ids = (warning.relationships || [])
          .map((r) => r.relationship_id)
          .filter(Boolean)
          .join(", ");
        box.textContent = warning.message + (ids ? ` Linked: ${ids}` : "");
      } else {
        box.textContent = warning.message;
      }
      $("#deleteModal").classList.add("open");
    } catch (err) {
      toast(err.message || "Delete preview failed", true);
    }
  }

  async function confirmDelete() {
    if (!state.deleteTarget) return;
    try {
      await api(
        `/api/components/${encodeURIComponent(state.deleteTarget)}?confirmed=true`,
        { method: "DELETE" }
      );
      toast(`Deleted ${state.deleteTarget}`);
      state.deleteTarget = null;
      $("#deleteModal").classList.remove("open");
      await loadInventory();
      await refreshComponentIdList();
      await loadRelationships();
    } catch (err) {
      toast(err.message || "Delete failed", true);
    }
  }

  async function loadCustomFields() {
    const data = await api("/api/custom-fields");
    state.customFields = data.items || [];
    const tbody = $("#customFieldBody");
    tbody.innerHTML = "";
    for (const item of state.customFields) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(item.field_key)}</td>
        <td>${escapeHtml(item.label)}</td>
        <td>${escapeHtml(item.field_type)}</td>
        <td>${escapeHtml((item.applies_to || []).join(", "))}</td>
        <td>${item.required ? "yes" : "no"}</td>
        <td class="actions">
          <button type="button" class="danger" data-cf-del="${escapeAttr(item.field_key)}">Delete</button>
        </td>`;
      tbody.appendChild(tr);
    }
  }

  function renderCustomInputs(componentType, values) {
    const wrap = $("#customInputs");
    wrap.innerHTML = "";
    const applicable = state.customFields.filter(
      (f) => (f.applies_to || []).includes("*") || (f.applies_to || []).includes(componentType)
    );
    if (!applicable.length) {
      wrap.innerHTML = `<p class="hint">No custom fields configured for ${escapeHtml(componentType)}.</p>`;
      return;
    }
    for (const field of applicable) {
      const label = document.createElement("label");
      const val = values[field.field_key];
      if (field.field_type === "boolean") {
        label.innerHTML = `${escapeHtml(field.label)}
          <select data-cf="${escapeAttr(field.field_key)}">
            <option value="">—</option>
            <option value="true" ${val === true ? "selected" : ""}>true</option>
            <option value="false" ${val === false ? "selected" : ""}>false</option>
          </select>`;
      } else if (field.field_type === "enum") {
        const opts = (field.enum_values || [])
          .map((v) => `<option value="${escapeAttr(v)}" ${val === v ? "selected" : ""}>${escapeHtml(v)}</option>`)
          .join("");
        label.innerHTML = `${escapeHtml(field.label)}
          <select data-cf="${escapeAttr(field.field_key)}">
            <option value="">—</option>${opts}
          </select>`;
      } else {
        label.innerHTML = `${escapeHtml(field.label)}
          <input data-cf="${escapeAttr(field.field_key)}" value="${escapeAttr(val ?? "")}" />`;
      }
      wrap.appendChild(label);
    }
  }

  function collectCustomValues() {
    const out = {};
    for (const el of $$("[data-cf]")) {
      const key = el.getAttribute("data-cf");
      let value = el.value;
      if (value === "") continue;
      const def = state.customFields.find((f) => f.field_key === key);
      if (def?.field_type === "number") value = Number(value);
      if (def?.field_type === "boolean") value = value === "true";
      out[key] = value;
    }
    return out;
  }

  async function saveCustomField(event) {
    event.preventDefault();
    const applies = $("#cfApplies").value;
    const payload = {
      field_key: $("#cfKey").value.trim(),
      label: $("#cfLabel").value.trim(),
      field_type: $("#cfType").value,
      applies_to: [applies || "*"],
      required: $("#cfRequired").checked,
      enum_values: $("#cfEnum").value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    try {
      await api("/api/custom-fields", { method: "POST", body: JSON.stringify(payload) });
      toast("Custom field created");
      $("#customFieldForm").reset();
      $("#cfApplies").value = "*";
      await loadCustomFields();
    } catch (err) {
      toast(err.message || "Custom field save failed", true);
    }
  }

  function showTab(name) {
    $$(".tab-panel").forEach((p) => p.classList.add("hidden"));
    $$(".tabs button").forEach((b) => b.classList.remove("active"));
    $(`#tab-${name}`).classList.remove("hidden");
    $(`.tabs button[data-tab="${name}"]`).classList.add("active");
    if (name === "relationships") {
      loadRelationships().catch((err) => toast(err.message, true));
    }
    if (name === "dependencies") {
      refreshComponentIdList().catch(() => {});
    }
  }

  function renderDepRows(tbodySel, rows) {
    const tbody = $(tbodySel);
    tbody.innerHTML = "";
    if (!rows || !rows.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="dash">None</td></tr>`;
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(row.component_id)}</td>
        <td>${escapeHtml(row.name)}</td>
        <td>${escapeHtml(row.component_type)}</td>
        <td>${escapeHtml(row.direct_or_indirect)}</td>
        <td>${escapeHtml(row.relationship_type)}</td>
        <td class="${row.protocol === "—" ? "dash" : ""}">${escapeHtml(row.protocol)}</td>
        <td class="mono ${row.source_port === "—" ? "dash" : ""}">${escapeHtml(row.source_port)}</td>
        <td class="mono ${row.target_port === "—" ? "dash" : ""}">${escapeHtml(row.target_port)}</td>
        <td>${escapeHtml(row.verification_status)}</td>
        <td>${escapeHtml(row.evidence_or_notes)}</td>`;
      tbody.appendChild(tr);
    }
  }

  function renderImpact(apps, disclaimer) {
    if (disclaimer) $("#impactDisclaimer").textContent = disclaimer;
    const wrap = $("#depImpactList");
    if (!apps || !apps.length) {
      wrap.innerHTML = `<p class="hint">No potentially affected applications in scope.</p>`;
      return;
    }
    wrap.innerHTML = apps
      .map((app) => {
        const c = app.component || {};
        const paths = (app.connecting_paths || [])
          .map((p) => `<li>${escapeHtml((p.component_ids || []).join(" → "))}</li>`)
          .join("");
        return `<div class="impact-card">
          <div><strong>${escapeHtml(c.component_id)}</strong> — ${escapeHtml(c.name || "")}
            (${escapeHtml(app.direct_or_indirect)}, depth ${escapeHtml(app.depth)})</div>
          <div class="hint">${escapeHtml(app.note || "")}</div>
          <ul class="paths">${paths || "<li>No path details</li>"}</ul>
        </div>`;
      })
      .join("");
  }

  function renderGraph(graph, cycles) {
    const svg = $("#depGraph");
    const nodes = graph?.nodes || [];
    const edges = graph?.edges || [];
    svg.innerHTML = "";
    if (!nodes.length) {
      svg.setAttribute("viewBox", "0 0 640 200");
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", "24");
      t.setAttribute("y", "40");
      t.setAttribute("fill", "#5a6e68");
      t.textContent = "No graph data";
      svg.appendChild(t);
      return;
    }

    const selected = nodes.find((n) => n.is_selected || (n.roles || []).includes("selected"));
    const upstream = nodes.filter((n) => (n.roles || []).includes("upstream") && !n.is_selected);
    const downstream = nodes.filter((n) => (n.roles || []).includes("downstream") && !n.is_selected);
    const both = nodes.filter(
      (n) =>
        (n.roles || []).includes("upstream") &&
        (n.roles || []).includes("downstream") &&
        !n.is_selected
    );

    const positions = {};
    const colW = 210;
    const rowH = 56;
    const leftX = 80;
    const midX = 320;
    const rightX = 560;
    const height = Math.max(220, (Math.max(upstream.length, downstream.length, 1) + 1) * rowH + 40);
    svg.setAttribute("viewBox", `0 0 640 ${height}`);

    function placeColumn(list, x, startY) {
      list.forEach((n, i) => {
        positions[n.component_id] = { x, y: startY + i * rowH };
      });
    }
    placeColumn(upstream, leftX, 50);
    placeColumn(both.length ? both : [], midX, height / 2);
    if (selected) positions[selected.component_id] = { x: midX, y: 40 };
    placeColumn(
      downstream.filter((n) => !(n.roles || []).includes("upstream")),
      rightX,
      50
    );

    // Ensure every node has a position
    let orphanY = height - 40;
    for (const n of nodes) {
      if (!positions[n.component_id]) {
        positions[n.component_id] = { x: midX, y: orphanY };
        orphanY -= rowH;
      }
    }

    const cycleEdgeIds = new Set();
    for (const cycle of cycles || []) {
      for (const rid of cycle.relationship_ids || []) cycleEdgeIds.add(rid);
    }

    for (const edge of edges) {
      const a = positions[edge.source_component_id];
      const b = positions[edge.target_component_id];
      if (!a || !b) continue;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", a.x);
      line.setAttribute("y1", a.y);
      line.setAttribute("x2", b.x);
      line.setAttribute("y2", b.y);
      line.setAttribute(
        "class",
        cycleEdgeIds.has(edge.relationship_id) ? "edge edge-cycle" : "edge"
      );
      svg.appendChild(line);
    }

    for (const n of nodes) {
      const pos = positions[n.component_id];
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", pos.x);
      circle.setAttribute("cy", pos.y);
      circle.setAttribute("r", 18);
      let cls = "node-upstream";
      if (n.is_selected || (n.roles || []).includes("selected")) cls = "node-selected";
      else if ((n.roles || []).includes("upstream") && (n.roles || []).includes("downstream"))
        cls = "node-both";
      else if ((n.roles || []).includes("downstream")) cls = "node-downstream";
      circle.setAttribute("class", cls);
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", pos.x);
      label.setAttribute("y", pos.y + 32);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", "#14201d");
      label.textContent = n.component_id;
      g.appendChild(circle);
      g.appendChild(label);
      svg.appendChild(g);
    }

    const box = $("#depCycles");
    if (cycles && cycles.length) {
      box.style.display = "block";
      box.textContent =
        "Cycles detected: " +
        cycles.map((c) => (c.component_ids || []).join(" → ")).join(" | ");
    } else {
      box.style.display = "none";
    }
  }

  async function analyzeDependencies() {
    const componentId = $("#depComponentId").value.trim();
    if (!componentId) {
      toast("Enter a component ID", true);
      return;
    }
    const depth = Number($("#depDepth").value || 5);
    const params = new URLSearchParams({ depth: String(depth) });
    const env = $("#depEnv").value.trim();
    const status = $("#depStatus").value;
    if (env) params.set("environment", env);
    if (status) params.set("status", status);
    const data = await api(
      `/api/dependencies/${encodeURIComponent(componentId)}?${params.toString()}`
    );
    const selected = data.selected || {};
    $("#depSelected").innerHTML = `
      <div><strong class="mono">${escapeHtml(selected.component_id || "")}</strong>
      — ${escapeHtml(selected.name || "")}
      (${escapeHtml(selected.component_type || "")},
      env ${escapeHtml(selected.environment || "—")},
      status ${escapeHtml(selected.status || "—")})</div>`;
    renderDepRows("#depUpstreamBody", data.upstream?.rows || []);
    renderDepRows("#depDownstreamBody", data.downstream?.rows || []);
    renderImpact(
      data.impact?.potentially_affected_applications || [],
      data.disclaimer || data.impact?.disclaimer
    );
    renderGraph(data.graph || {}, data.cycles_detected || []);
    if ((data.missing_components || []).length) {
      toast(`Missing related components: ${data.missing_components.join(", ")}`, true);
    }
  }

  async function refreshComponentIdList() {
    const data = await api("/api/components?page=1&page_size=200");
    state.componentIds = (data.items || []).map((c) => c.component_id);
    const list = $("#componentIdList");
    if (!list) return;
    list.innerHTML = state.componentIds
      .map((id) => `<option value="${escapeAttr(id)}"></option>`)
      .join("");
  }

  async function loadRelationshipTypes() {
    const data = await api("/api/relationships/types");
    state.relTypes = data.types || [];
    const docs = $("#relTypeDocs");
    docs.innerHTML = state.relTypes
      .map(
        (t) =>
          `<div><strong>${escapeHtml(t.relationship_type)}</strong> — ${escapeHtml(t.direction)}: ${escapeHtml(t.meaning)} <em>(${escapeHtml(t.example)})</em></div>`
      )
      .join("");
    for (const sel of ["#relFilterType", "#relType"]) {
      const el = $(sel);
      if (!el) continue;
      const keepFirst = el.getAttribute("data-keep-first") === "1";
      const first = keepFirst ? el.options[0] : null;
      el.innerHTML = "";
      if (first) el.appendChild(first);
      for (const t of state.relTypes) {
        const opt = document.createElement("option");
        opt.value = t.relationship_type;
        opt.textContent = t.relationship_type;
        el.appendChild(opt);
      }
    }
    updateRelTypeHint();
  }

  function updateRelTypeHint() {
    const type = $("#relType")?.value;
    const meta = state.relTypes.find((t) => t.relationship_type === type);
    $("#relTypeHint").textContent = meta
      ? `${meta.relationship_type}: ${meta.direction} — ${meta.meaning}`
      : "";
  }

  function relQueryParams() {
    const params = new URLSearchParams();
    const q = $("#relSearchQ").value.trim();
    const relationship_type = $("#relFilterType").value;
    const component_id = $("#relFilterComponent").value.trim();
    if (q) params.set("q", q);
    if (relationship_type) params.set("relationship_type", relationship_type);
    if (component_id) params.set("component_id", component_id);
    params.set("page", String(state.relPage));
    params.set("page_size", String(state.pageSize));
    return params;
  }

  async function loadRelationships() {
    const data = await api(`/api/relationships?${relQueryParams().toString()}`);
    state.relTotalPages = data.total_pages || 1;
    $("#relPageInfo").textContent =
      `Page ${data.page} / ${state.relTotalPages || 1} · ${data.total} relationships`;
    $("#btnRelPrev").disabled = data.page <= 1;
    $("#btnRelNext").disabled = data.page >= (data.total_pages || 1);
    const tbody = $("#relationshipBody");
    tbody.innerHTML = "";
    for (const row of data.rows || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(row.relationship_id)}</td>
        <td class="mono">${escapeHtml(row.source_component_id)}</td>
        <td class="mono">${escapeHtml(row.target_component_id)}</td>
        <td>${escapeHtml(row.relationship_type)}</td>
        <td class="${row.protocol === "—" ? "dash" : ""}">${escapeHtml(row.protocol)}</td>
        <td class="mono ${row.source_port === "—" ? "dash" : ""}">${escapeHtml(row.source_port)}</td>
        <td class="mono ${row.target_port === "—" ? "dash" : ""}">${escapeHtml(row.target_port)}</td>
        <td>${escapeHtml(row.environment)}</td>
        <td>${escapeHtml(row.discovery_method)}</td>
        <td>${escapeHtml(row.verification_status)}</td>
        <td class="actions">
          <button type="button" class="secondary" data-rel-edit="${escapeAttr(row.relationship_id)}">Edit</button>
          <button type="button" class="danger" data-rel-del="${escapeAttr(row.relationship_id)}">Delete</button>
        </td>`;
      tbody.appendChild(tr);
    }
  }

  function parseOptionalPort(raw) {
    const value = String(raw ?? "").trim();
    if (!value) return null;
    return Number(value);
  }

  function openRelCreate() {
    state.editingRelId = null;
    $("#relationshipForm").reset();
    $("#relId").disabled = false;
    $("#relConfidence").value = "medium";
    $("#relDiscovery").value = "manually_configured";
    $("#relVerification").value = "unverified";
    $("#relEnvWarn").style.display = "none";
    if ($("#relType").options.length) $("#relType").selectedIndex = 0;
    updateRelTypeHint();
    $("#relModalTitle").textContent = "Add relationship";
    $("#relationshipModal").classList.add("open");
  }

  async function openRelEdit(id) {
    const doc = await api(`/api/relationships/${encodeURIComponent(id)}`);
    state.editingRelId = id;
    $("#relId").value = doc.relationship_id;
    $("#relId").disabled = true;
    $("#relType").value = doc.relationship_type;
    $("#relSource").value = doc.source_component_id;
    $("#relTarget").value = doc.target_component_id;
    $("#relProtocol").value = doc.protocol || "";
    $("#relSourcePort").value = doc.source_port ?? "";
    $("#relTargetPort").value = doc.target_port ?? "";
    $("#relUrl").value = doc.url_or_path || "";
    $("#relEnv").value = doc.environment || "";
    $("#relDiscovery").value = doc.discovery_method || "manually_configured";
    $("#relVerification").value = doc.verification_status || "unverified";
    $("#relConfidence").value = doc.confidence || "medium";
    $("#relNotes").value = doc.evidence_or_notes || "";
    $("#relEnvWarn").style.display = "none";
    updateRelTypeHint();
    $("#relModalTitle").textContent = `Edit ${id}`;
    $("#relationshipModal").classList.add("open");
  }

  function collectRelPayload() {
    const payload = {
      source_component_id: $("#relSource").value.trim(),
      target_component_id: $("#relTarget").value.trim(),
      relationship_type: $("#relType").value,
      protocol: $("#relProtocol").value.trim() || null,
      source_port: parseOptionalPort($("#relSourcePort").value),
      target_port: parseOptionalPort($("#relTargetPort").value),
      url_or_path: $("#relUrl").value.trim() || null,
      environment: $("#relEnv").value.trim() || null,
      discovery_method: $("#relDiscovery").value,
      verification_status: $("#relVerification").value,
      confidence: $("#relConfidence").value,
      evidence_or_notes: $("#relNotes").value.trim() || null,
    };
    if (!state.editingRelId) {
      const rid = $("#relId").value.trim();
      if (rid) payload.relationship_id = rid;
    }
    return payload;
  }

  function showRelWarnings(result) {
    const box = $("#relEnvWarn");
    const warnings = result?.warnings || [];
    if (!warnings.length) {
      box.style.display = "none";
      return;
    }
    box.style.display = "block";
    box.textContent = warnings
      .flatMap((w) => w.messages || [w.message || JSON.stringify(w)])
      .join(" ");
  }

  async function saveRelationship(event) {
    event.preventDefault();
    const payload = collectRelPayload();
    try {
      let result;
      if (state.editingRelId) {
        result = await api(`/api/relationships/${encodeURIComponent(state.editingRelId)}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast("Relationship updated");
      } else {
        result = await api("/api/relationships", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast("Relationship created");
      }
      showRelWarnings(result);
      if (!(result.warnings || []).length) {
        $("#relationshipModal").classList.remove("open");
        state.editingRelId = null;
      }
      await loadRelationships();
    } catch (err) {
      toast(err.message || "Relationship save failed", true);
    }
  }

  function wireEvents() {
    $("#btnConnect").addEventListener("click", connect);
    $("#btnSearch").addEventListener("click", async () => {
      state.page = 1;
      try { await loadInventory(); } catch (err) { toast(err.message, true); }
    });
    $("#btnAdd").addEventListener("click", () => {
      try { openCreate(); } catch (err) { toast(err.message, true); }
    });
    $("#btnPrev").addEventListener("click", async () => {
      state.page = Math.max(1, state.page - 1);
      await loadInventory();
    });
    $("#btnNext").addEventListener("click", async () => {
      state.page = Math.min(state.totalPages || 1, state.page + 1);
      await loadInventory();
    });
    $("#fieldType").addEventListener("change", (e) => {
      renderTypeFields(e.target.value);
      renderCustomInputs(e.target.value, {});
    });
    $("#componentForm").addEventListener("submit", saveComponent);
    $("#btnCloseModal").addEventListener("click", closeModal);
    $("#btnCancelDelete").addEventListener("click", () => {
      $("#deleteModal").classList.remove("open");
      state.deleteTarget = null;
    });
    $("#btnConfirmDelete").addEventListener("click", confirmDelete);
    $("#customFieldForm").addEventListener("submit", saveCustomField);
    $("#btnAnalyzeDeps").addEventListener("click", async () => {
      try { await analyzeDependencies(); } catch (err) { toast(err.message, true); }
    });
    $("#btnRelSearch").addEventListener("click", async () => {
      state.relPage = 1;
      try { await loadRelationships(); } catch (err) { toast(err.message, true); }
    });
    $("#btnAddRel").addEventListener("click", async () => {
      try {
        await refreshComponentIdList();
        openRelCreate();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#btnRelPrev").addEventListener("click", async () => {
      state.relPage = Math.max(1, state.relPage - 1);
      await loadRelationships();
    });
    $("#btnRelNext").addEventListener("click", async () => {
      state.relPage = Math.min(state.relTotalPages || 1, state.relPage + 1);
      await loadRelationships();
    });
    $("#relType").addEventListener("change", updateRelTypeHint);
    $("#relationshipForm").addEventListener("submit", saveRelationship);
    $("#btnCloseRelModal").addEventListener("click", () => {
      $("#relationshipModal").classList.remove("open");
      state.editingRelId = null;
    });
    $("#relationshipBody").addEventListener("click", async (e) => {
      const edit = e.target.getAttribute("data-rel-edit");
      const del = e.target.getAttribute("data-rel-del");
      try {
        if (edit) await openRelEdit(edit);
        if (del) {
          if (!confirm(`Delete relationship ${del}?`)) return;
          await api(`/api/relationships/${encodeURIComponent(del)}`, { method: "DELETE" });
          toast(`Deleted ${del}`);
          await loadRelationships();
        }
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#inventoryBody").addEventListener("click", async (e) => {
      const view = e.target.getAttribute("data-view");
      const edit = e.target.getAttribute("data-edit");
      const del = e.target.getAttribute("data-del");
      try {
        if (view) await openEdit(view, true);
        if (edit) await openEdit(edit, false);
        if (del) await beginDelete(del);
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("#customFieldBody").addEventListener("click", async (e) => {
      const key = e.target.getAttribute("data-cf-del");
      if (!key) return;
      if (!confirm(`Delete custom field definition '${key}'?`)) return;
      try {
        await api(`/api/custom-fields/${encodeURIComponent(key)}`, { method: "DELETE" });
        toast("Custom field deleted");
        await loadCustomFields();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $$(".tabs button").forEach((btn) => {
      btn.addEventListener("click", () => showTab(btn.getAttribute("data-tab")));
    });
  }

  // minimal hidden helper class
  const style = document.createElement("style");
  style.textContent = `.hidden{display:none!important}`;
  document.head.appendChild(style);

  document.addEventListener("DOMContentLoaded", () => {
    loadAuthIntoForm();
    wireEvents();
    showTab("inventory");
    if (authHeader()) {
      connect().catch(() => {});
    }
  });
})();
