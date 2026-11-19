/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  let selectedPolicyId = null;
  let deps = { can: () => false, toast: () => {}, escapeHtml: (s) => s };
  let viewMode = "policies"; // policies | tracking

  function $(sel) {
    return document.querySelector(sel);
  }

  function esc(s) {
    return deps.escapeHtml(s == null ? "" : String(s));
  }

  function fmtWhen(value) {
    if (!value) return "—";
    try {
      return new Date(value).toLocaleString();
    } catch (_) {
      return String(value);
    }
  }

  function applyWriteGates() {
    const canAdmin = deps.can("itsm:sla:admin");
    const btn = $("#btnNewItsmSla");
    if (btn) btn.hidden = !canAdmin;
  }

  function setView(mode) {
    viewMode = mode;
    const polPanel = $("#itsmSlaPoliciesPanel");
    const trkPanel = $("#itsmSlaTrackingPanel");
    const tabPol = $("#btnItsmSlaTabPolicies");
    const tabTrk = $("#btnItsmSlaTabTracking");
    if (polPanel) polPanel.hidden = mode !== "policies";
    if (trkPanel) trkPanel.hidden = mode !== "tracking";
    tabPol?.classList.toggle("active", mode === "policies");
    tabTrk?.classList.toggle("active", mode === "tracking");
    if (mode === "policies") loadPolicies();
    else loadTracking();
  }

  function openModal(editDoc) {
    const modal = $("#itsmSlaModal");
    if (!modal) return;
    modal.classList.add("open");
    $("#itsmSlaModalTitle").textContent = editDoc ? "Edit SLA policy" : "New SLA policy";
    $("#itsmSlaEditId").value = editDoc?.policy_id || "";
    $("#itsmSlaFieldName").value = editDoc?.name || "";
    $("#itsmSlaFieldDescription").value = editDoc?.description || "";
    $("#itsmSlaFieldAppliesTo").value = editDoc?.applies_to || "incident";
    $("#itsmSlaFieldActive").checked = editDoc ? !!editDoc.active : true;
    $("#itsmSlaFieldPause").value = (editDoc?.pause_on_statuses || []).join(", ");
    $("#itsmSlaFieldPriorityOrder").value =
      editDoc?.priority_order != null ? editDoc.priority_order : 100;
    const m = editDoc?.match || {};
    $("#itsmSlaMatchTier").value = m.service_tier || "";
    $("#itsmSlaMatchCustomer").value = m.customer_class || "";
    $("#itsmSlaMatchCategory").value = m.category || "";
    $("#itsmSlaMatchSubcategory").value = m.subcategory || "";
    $("#itsmSlaMatchGroup").value = m.assignment_group || "";
    $("#itsmSlaMatchUrgency").value = m.urgency || "";
    $("#itsmSlaMatchImpact").value = m.impact || "";
    $("#itsmSlaMatchCiCrit").value = m.ci_criticality || "";
    $("#itsmSlaMatchCiTier").value = m.ci_tier || "";
    $("#itsmSlaMatchPriorities").value = (m.priorities || []).join(",");
    const cal = editDoc?.calendar || {};
    $("#itsmSlaCalTz").value = cal.timezone || "UTC";
    $("#itsmSlaCalBiz").checked = !!cal.business_hours_only;
    $("#itsmSlaCalStart").value = cal.business_hours_start || "";
    $("#itsmSlaCalEnd").value = cal.business_hours_end || "";
    const targets = editDoc?.targets || [];
    const response = targets.find((t) => t.metric === "response");
    const resolution = targets.find((t) => t.metric === "resolution");
    fillPriorityInputs("resp", response);
    fillPriorityInputs("res", resolution);
    $("#itsmSlaFieldName")?.focus();
  }

  function matchSummary(match) {
    const m = match || {};
    const parts = [];
    if (m.service_tier) parts.push(`tier=${m.service_tier}`);
    if (m.customer_class) parts.push(`class=${m.customer_class}`);
    if (m.category) parts.push(`cat=${m.category}`);
    if (m.subcategory) parts.push(`sub=${m.subcategory}`);
    if (m.assignment_group) parts.push(`group=${m.assignment_group}`);
    if (m.urgency) parts.push(`urg=${m.urgency}`);
    if (m.impact) parts.push(`imp=${m.impact}`);
    if (m.ci_criticality) parts.push(`ciCrit=${m.ci_criticality}`);
    if (m.ci_tier) parts.push(`ciTier=${m.ci_tier}`);
    if (m.priorities && m.priorities.length) parts.push(`prio=${m.priorities.join("|")}`);
    return parts.length ? parts.join(", ") : "(any)";
  }

  function collectMatchFromForm() {
    const priorities = ($("#itsmSlaMatchPriorities")?.value || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    const match = {
      service_tier: $("#itsmSlaMatchTier")?.value?.trim() || null,
      customer_class: $("#itsmSlaMatchCustomer")?.value?.trim() || null,
      category: $("#itsmSlaMatchCategory")?.value?.trim() || null,
      subcategory: $("#itsmSlaMatchSubcategory")?.value?.trim() || null,
      assignment_group: $("#itsmSlaMatchGroup")?.value?.trim() || null,
      urgency: $("#itsmSlaMatchUrgency")?.value?.trim() || null,
      impact: $("#itsmSlaMatchImpact")?.value?.trim() || null,
      ci_criticality: $("#itsmSlaMatchCiCrit")?.value?.trim() || null,
      ci_tier: $("#itsmSlaMatchCiTier")?.value?.trim() || null,
      priorities: priorities.length ? priorities : null,
    };
    return match;
  }

  function fillPriorityInputs(prefix, target) {
    const map = {};
    (target?.priority_targets || []).forEach((row) => {
      map[row.priority] = row.minutes;
    });
    ["p1", "p2", "p3", "p4"].forEach((p) => {
      const el = $(`#itsmSla${prefix}_${p}`);
      if (el) el.value = map[p] != null ? map[p] : defaultsFor(prefix, p);
    });
  }

  function defaultsFor(prefix, p) {
    if (prefix === "resp") {
      return { p1: 15, p2: 30, p3: 60, p4: 240 }[p];
    }
    return { p1: 60, p2: 240, p3: 480, p4: 1440 }[p];
  }

  function closeModal() {
    const modal = $("#itsmSlaModal");
    if (!modal) return;
    modal.classList.remove("open");
    $("#itsmSlaForm")?.reset();
    $("#itsmSlaEditId").value = "";
  }

  function openDrawer() {
    const drawer = $("#itsmSlaDrawer");
    if (!drawer) return;
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    const drawer = $("#itsmSlaDrawer");
    if (!drawer) return;
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    selectedPolicyId = null;
  }

  function collectTargetsFromForm() {
    function collect(prefix, metric) {
      const priority_targets = [];
      ["p1", "p2", "p3", "p4"].forEach((p) => {
        const raw = $(`#itsmSla${prefix}_${p}`)?.value;
        const minutes = Number(raw);
        if (Number.isFinite(minutes) && minutes > 0) {
          priority_targets.push({ priority: p, minutes });
        }
      });
      if (!priority_targets.length) return null;
      return { metric, priority_targets };
    }
    const targets = [];
    const resp = collect("resp", "response");
    const res = collect("res", "resolution");
    if (resp) targets.push(resp);
    if (res) targets.push(res);
    return targets;
  }

  async function savePolicy(ev) {
    ev.preventDefault();
    if (!deps.can("itsm:sla:admin")) {
      deps.toast("SLA admin permission required", true);
      return;
    }
    const name = $("#itsmSlaFieldName")?.value?.trim();
    if (!name) {
      deps.toast("Name is required", true);
      return;
    }
    const targets = collectTargetsFromForm();
    if (!targets.length) {
      deps.toast("Add at least one priority target for response or resolution", true);
      return;
    }
    const pauseRaw = $("#itsmSlaFieldPause")?.value || "";
    const pause_on_statuses = pauseRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const orderRaw = Number($("#itsmSlaFieldPriorityOrder")?.value);
    const payload = {
      name,
      description: $("#itsmSlaFieldDescription")?.value?.trim() || null,
      applies_to: $("#itsmSlaFieldAppliesTo")?.value || "incident",
      active: !!$("#itsmSlaFieldActive")?.checked,
      priority_order: Number.isFinite(orderRaw) ? orderRaw : 100,
      match: collectMatchFromForm(),
      pause_on_statuses,
      targets,
      calendar: {
        timezone: $("#itsmSlaCalTz")?.value?.trim() || "UTC",
        business_hours_only: !!$("#itsmSlaCalBiz")?.checked,
        business_hours_start: $("#itsmSlaCalStart")?.value?.trim() || null,
        business_hours_end: $("#itsmSlaCalEnd")?.value?.trim() || null,
      },
    };
    const editId = $("#itsmSlaEditId")?.value?.trim();
    try {
      let doc;
      if (editId) {
        const { applies_to: _a, ...patch } = payload;
        doc = await SVRMON24ItsmApi.updateSlaPolicy(editId, patch);
        deps.toast(`Updated ${doc.policy_id}`);
      } else {
        doc = await SVRMON24ItsmApi.createSlaPolicy(payload);
        deps.toast(`Created ${doc.policy_id}`);
      }
      closeModal();
      await loadPolicies();
      await openPolicy(doc.policy_id);
    } catch (err) {
      deps.toast(err.message || "Save failed", true);
    }
  }

  async function loadPolicies() {
    const body = $("#itsmSlaPolBody");
    const meta = $("#itsmSlaPolListMeta");
    if (!body) return;
    const params = { page: "1", page_size: "50", sort_by: "updated_at", sort_dir: "desc" };
    const q = $("#itsmSlaPolSearch")?.value?.trim();
    const applies = $("#itsmSlaPolApplies")?.value;
    const active = $("#itsmSlaPolActive")?.value;
    if (q) params.q = q;
    if (applies) params.applies_to = applies;
    if (active === "true" || active === "false") params.active = active;
    try {
      const data = await SVRMON24ItsmApi.listSlaPolicies(params);
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} policy(ies) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="8" class="hint">No SLA policies yet. Create one to auto-attach tracking on new tickets.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const metrics = (row.targets || []).map((t) => t.metric).join(", ") || "—";
          return `<tr data-policy-id="${esc(row.policy_id)}">
            <td><code>${esc(row.policy_id)}</code></td>
            <td>${esc(row.name)}</td>
            <td>${esc(row.applies_to)}</td>
            <td class="hint">${esc(matchSummary(row.match))}</td>
            <td>${esc(row.priority_order != null ? row.priority_order : 100)}</td>
            <td><span class="itsm-status is-${row.active ? "approved" : "cancelled"}">${
              row.active ? "active" : "inactive"
            }</span></td>
            <td>${esc(metrics)}</td>
            <td><button type="button" class="ghost itsm-open-sla-pol" data-id="${esc(
              row.policy_id
            )}">Open</button></td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".itsm-open-sla-pol").forEach((btn) => {
        btn.addEventListener("click", () => openPolicy(btn.getAttribute("data-id")));
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="8" class="hint">${esc(err.message || "Failed")}</td></tr>`;
      deps.toast(err.message || "Policies failed", true);
    }
  }

  async function openPolicy(policyId) {
    selectedPolicyId = policyId;
    openDrawer();
    const detail = $("#itsmSlaDrawerDetail");
    const title = $("#itsmSlaDrawerTitle");
    const sub = $("#itsmSlaDrawerSub");
    const actions = $("#itsmSlaDrawerActions");
    try {
      const doc = await SVRMON24ItsmApi.getSlaPolicy(policyId);
      if (title) title.textContent = doc.name || doc.policy_id;
      if (sub) {
        sub.textContent = `${doc.applies_to} · ${doc.active ? "active" : "inactive"} · ${doc.policy_id}`;
      }
      const targetHtml = (doc.targets || [])
        .map((t) => {
          const mins = (t.priority_targets || [])
            .map((p) => `${p.priority}:${p.minutes}m`)
            .join(" · ");
          return `<li><strong>${esc(t.metric)}</strong> — ${esc(mins)}</li>`;
        })
        .join("");
      if (detail) {
        detail.innerHTML = `
          <p class="hint">${esc(doc.description || "No description")}</p>
          <p class="hint">Match: ${esc(matchSummary(doc.match))} · precedence ${esc(
            doc.priority_order != null ? doc.priority_order : 100
          )}</p>
          <p class="hint">Pause on: ${esc((doc.pause_on_statuses || []).join(", ") || "—")}</p>
          <p class="hint">Calendar: ${esc(doc.calendar?.timezone || "UTC")}${
            doc.calendar?.business_hours_only ? " · business hours" : " · 24×7"
          }${
            doc.calendar?.business_hours_start
              ? ` · ${esc(doc.calendar.business_hours_start)}–${esc(
                  doc.calendar.business_hours_end || ""
                )}`
              : ""
          }</p>
          <ul class="itsm-sla-target-list">${targetHtml || "<li class='hint'>No targets</li>"}</ul>
          <p class="hint">Updated ${esc(fmtWhen(doc.updated_at))}</p>
        `;
      }
      if (actions) {
        const canAdmin = deps.can("itsm:sla:admin");
        actions.innerHTML = canAdmin
          ? `<button type="button" class="secondary" id="btnEditItsmSla">Edit</button>`
          : "";
        $("#btnEditItsmSla")?.addEventListener("click", () => openModal(doc));
      }
    } catch (err) {
      if (detail) detail.textContent = err.message || "Failed to load policy";
      deps.toast(err.message || "Policy detail failed", true);
    }
  }

  async function loadTracking() {
    const body = $("#itsmSlaTrkBody");
    const meta = $("#itsmSlaTrkListMeta");
    if (!body) return;
    const params = { page: "1", page_size: "50", sort_by: "due_at", sort_dir: "asc" };
    const q = $("#itsmSlaTrkSearch")?.value?.trim();
    const status = $("#itsmSlaTrkStatus")?.value;
    const ticketType = $("#itsmSlaTrkTicketType")?.value;
    const ticketId = $("#itsmSlaTrkTicketId")?.value?.trim();
    const overdue = $("#itsmSlaTrkOverdue")?.checked;
    if (q) params.q = q;
    if (status) params.status = status;
    if (ticketType) params.ticket_type = ticketType;
    if (ticketId) params.ticket_id = ticketId;
    if (overdue) params.overdue = "true";
    try {
      const data = await SVRMON24ItsmApi.listSlaTracking(params);
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} tracking record(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="8" class="hint">No SLA tracking yet. Create an active policy and a matching ticket.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const why =
            row.match_reason ||
            (row.matched_fields && Object.keys(row.matched_fields).length
              ? Object.entries(row.matched_fields)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ")
              : "wildcard");
          return `<tr>
            <td><code>${esc(row.tracking_id)}</code></td>
            <td>${esc(row.metric)}</td>
            <td><span class="itsm-status is-${esc(statusClass(row.status))}">${esc(
              row.status
            )}</span></td>
            <td>${esc(row.ticket_type)} / <code>${esc(row.ticket_id)}</code></td>
            <td>${esc(row.policy_name_snapshot || row.policy_id)}${
              row.match_score != null ? ` <span class="hint">(score ${esc(row.match_score)})</span>` : ""
            }</td>
            <td class="hint">${esc(why)}</td>
            <td>${esc(row.priority_at_start)} · ${esc(row.target_minutes)}m</td>
            <td>${esc(fmtWhen(row.due_at))}</td>
          </tr>`;
        })
        .join("");
    } catch (err) {
      body.innerHTML = `<tr><td colspan="8" class="hint">${esc(err.message || "Failed")}</td></tr>`;
      deps.toast(err.message || "Tracking failed", true);
    }
  }

  function statusClass(status) {
    if (status === "breached") return "rejected";
    if (status === "met") return "approved";
    if (status === "paused") return "pending";
    if (status === "cancelled") return "cancelled";
    return "in_progress";
  }

  /** Render compact SLA badges into a container element. */
  async function renderTicketBadges(container, ticketType, ticketId) {
    if (!container || !ticketType || !ticketId) return;
    if (!deps.can("itsm:sla:read")) {
      container.innerHTML = "";
      return;
    }
    container.innerHTML = `<span class="hint">Loading SLA…</span>`;
    try {
      const summary = await SVRMON24ItsmApi.slaSummary(ticketType, ticketId);
      const items = summary.items || [];
      if (!items.length) {
        container.innerHTML = `<span class="hint">No SLA tracking</span>`;
        return;
      }
      container.innerHTML = items
        .map((row) => {
          return `<span class="itsm-sla-badge is-${esc(statusClass(row.status))}" title="${esc(
            row.policy_name_snapshot || row.policy_id
          )} · due ${esc(fmtWhen(row.due_at))}">${esc(row.metric)} · ${esc(
            row.status
          )}</span>`;
        })
        .join(" ");
    } catch (_) {
      container.innerHTML = `<span class="hint">SLA unavailable</span>`;
    }
  }

  function initItsmSla(options) {
    deps = { ...deps, ...(options || {}) };
    applyWriteGates();
    $("#btnNewItsmSla")?.addEventListener("click", () => openModal(null));
    $("#btnCloseItsmSlaModal")?.addEventListener("click", closeModal);
    $("#btnCancelItsmSlaModal")?.addEventListener("click", closeModal);
    $("#itsmSlaForm")?.addEventListener("submit", savePolicy);
    $("#btnCloseItsmSlaDrawer")?.addEventListener("click", closeDrawer);
    $("#btnRefreshItsmSlaPol")?.addEventListener("click", () => loadPolicies());
    $("#btnRefreshItsmSlaTrk")?.addEventListener("click", () => loadTracking());
    $("#btnItsmSlaTabPolicies")?.addEventListener("click", () => setView("policies"));
    $("#btnItsmSlaTabTracking")?.addEventListener("click", () => setView("tracking"));
    $("#itsmSlaPolSearch")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") loadPolicies();
    });
    $("#itsmSlaPolApplies")?.addEventListener("change", () => loadPolicies());
    $("#itsmSlaPolActive")?.addEventListener("change", () => loadPolicies());
    $("#itsmSlaTrkSearch")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") loadTracking();
    });
    $("#itsmSlaTrkStatus")?.addEventListener("change", () => loadTracking());
    $("#itsmSlaTrkTicketType")?.addEventListener("change", () => loadTracking());
    $("#itsmSlaTrkOverdue")?.addEventListener("change", () => loadTracking());
    $("#btnItsmSlaTrkFilter")?.addEventListener("click", () => loadTracking());
  }

  global.SVRMON24ItsmSla = {
    initItsmSla,
    applyWriteGates,
    loadPolicies,
    loadTracking,
    setView,
    renderTicketBadges,
  };
})(window);
