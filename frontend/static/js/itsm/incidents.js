/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  const TRANSITIONS = {
    new: ["in_progress", "on_hold", "cancelled"],
    in_progress: ["on_hold", "resolved", "cancelled"],
    on_hold: ["in_progress", "cancelled"],
    resolved: ["closed", "in_progress"],
    closed: [],
    cancelled: [],
  };

  let selectedId = null;
  let deps = { can: () => false, toast: () => {}, escapeHtml: (s) => s };

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

  function openModal() {
    const modal = $("#itsmIncidentModal");
    if (!modal) return;
    modal.classList.add("open");
    const title = $("#itsmFieldTitle");
    if (title) title.focus();
  }

  function closeModal() {
    const modal = $("#itsmIncidentModal");
    if (!modal) return;
    modal.classList.remove("open");
    const form = $("#itsmIncidentForm");
    if (form) form.reset();
  }

  function openDrawer() {
    const drawer = $("#itsmIncDrawer");
    if (!drawer) return;
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    const drawer = $("#itsmIncDrawer");
    if (!drawer) return;
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    selectedId = null;
  }

  async function loadIncidents() {
    const body = $("#itsmIncBody");
    const meta = $("#itsmIncListMeta");
    if (!body) return;
    const params = {
      page: "1",
      page_size: "50",
      sort_by: "updated_at",
      sort_dir: "desc",
    };
    const q = $("#itsmIncSearch")?.value?.trim();
    const status = $("#itsmIncStatus")?.value;
    const priority = $("#itsmIncPriority")?.value;
    if (q) params.q = q;
    if (status) params.status = status;
    if (priority) params.priority = priority;
    try {
      const data = await SVRMON24ItsmApi.listIncidents(params);
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} incident(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="8" class="hint">No incidents yet. Create one to get started.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const cis = (row.ci_links || []).length;
          return `<tr data-incident-id="${esc(row.incident_id)}">
            <td><code>${esc(row.number_display || row.incident_id)}</code></td>
            <td>${esc(row.title)}</td>
            <td><span class="itsm-status is-${esc(row.status)}">${esc(row.status)}</span></td>
            <td><span class="itsm-priority is-${esc(row.priority)}">${esc(row.priority)}</span></td>
            <td>${esc(row.assignee_user_id || "—")}</td>
            <td>${cis}</td>
            <td>${esc(fmtWhen(row.updated_at))}</td>
            <td><button type="button" class="ghost itsm-open-inc" data-id="${esc(row.incident_id)}">Open</button></td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".itsm-open-inc").forEach((btn) => {
        btn.addEventListener("click", () => openIncident(btn.getAttribute("data-id")));
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="8" class="hint">${esc(err.message || "Failed")}</td></tr>`;
      deps.toast(err.message || "Incidents failed", true);
    }
  }

  async function openIncident(incidentId) {
    selectedId = incidentId;
    openDrawer();
    const detail = $("#itsmIncDrawerDetail");
    const title = $("#itsmIncDrawerTitle");
    const sub = $("#itsmIncDrawerSub");
    try {
      const doc = await SVRMON24ItsmApi.getIncident(incidentId);
      if (title) title.textContent = doc.number_display || doc.incident_id;
      if (sub) sub.textContent = `${doc.status} · ${doc.priority}`;
      if (detail) {
        detail.innerHTML = `
          <p><strong>${esc(doc.title)}</strong></p>
          <p class="hint">${esc(doc.description || "No description")}</p>
          <p class="hint">Assignee: ${esc(doc.assignee_user_id || "—")} · Category: ${esc(doc.category || "—")}</p>
          <p class="hint">Urgency: ${esc(doc.urgency || "—")} · Impact: ${esc(doc.impact || "—")}</p>
          <p class="hint">Related problem: ${esc(doc.problem_id || "—")} · Related change: ${esc(doc.change_id || "—")}</p>
          <p class="hint">Created ${esc(fmtWhen(doc.created_at))} · Updated ${esc(fmtWhen(doc.updated_at))}</p>
        `;
      }
      renderTransitions(doc.status);
      renderCiLinks(doc.ci_links || []);
      await loadActivities(incidentId);
    } catch (err) {
      if (detail) detail.textContent = err.message || "Failed to load incident";
      deps.toast(err.message || "Incident detail failed", true);
    }
  }

  function renderTransitions(status) {
    const bar = $("#itsmIncTransitionBar");
    if (!bar) return;
    const write = deps.can("itsm:incident:write");
    const next = TRANSITIONS[status] || [];
    if (!next.length) {
      bar.innerHTML = `<span class="hint">No further transitions from <code>${esc(status)}</code>.</span>`;
      return;
    }
    bar.innerHTML = next
      .map(
        (st) =>
          `<button type="button" class="secondary itsm-transition" data-status="${esc(st)}" ${
            write ? "" : "disabled"
          }>→ ${esc(st)}</button>`
      )
      .join("");
    bar.querySelectorAll(".itsm-transition").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!selectedId) return;
        try {
          await SVRMON24ItsmApi.transitionIncident(selectedId, {
            status: btn.getAttribute("data-status"),
          });
          deps.toast(`Transitioned to ${btn.getAttribute("data-status")}`);
          await openIncident(selectedId);
          await loadIncidents();
        } catch (err) {
          deps.toast(err.message || "Transition failed", true);
        }
      });
    });
  }

  function renderCiLinks(links) {
    const list = $("#itsmCiList");
    if (!list) return;
    const write = deps.can("itsm:incident:write");
    if (!links.length) {
      list.innerHTML = `<li class="hint">No CIs linked.</li>`;
      return;
    }
    list.innerHTML = links
      .map((link) => {
        const cid = link.component_id;
        return `<li>
          <code>${esc(cid)}</code>
          <span class="hint"> · ${esc(link.component_type || "")} · ${esc(link.name_snapshot || "")}</span>
          ${
            write
              ? `<button type="button" class="ghost itsm-unlink-ci" data-id="${esc(cid)}">Unlink</button>`
              : ""
          }
        </li>`;
      })
      .join("");
    list.querySelectorAll(".itsm-unlink-ci").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!selectedId) return;
        try {
          await SVRMON24ItsmApi.removeCiLink(selectedId, btn.getAttribute("data-id"));
          deps.toast("CI unlinked");
          await openIncident(selectedId);
          await loadIncidents();
        } catch (err) {
          deps.toast(err.message || "Unlink failed", true);
        }
      });
    });
  }

  async function loadActivities(incidentId) {
    const list = $("#itsmActivityList");
    if (!list) return;
    try {
      const data = await SVRMON24ItsmApi.listActivities("incident", incidentId);
      const items = data.items || [];
      if (!items.length) {
        list.innerHTML = `<li class="hint">No activity yet.</li>`;
        return;
      }
      list.innerHTML = items
        .map(
          (a) => `<li>
            <strong>${esc(a.activity_type)}</strong> — ${esc(a.message)}
            <span class="meta">${esc(a.actor_username || "system")} · ${esc(fmtWhen(a.created_at))}</span>
          </li>`
        )
        .join("");
    } catch (err) {
      list.innerHTML = `<li class="hint">${esc(err.message || "Failed")}</li>`;
    }
  }

  async function createIncident(event) {
    event.preventDefault();
    const title = $("#itsmFieldTitle")?.value?.trim();
    if (!title) {
      deps.toast("Title is required", true);
      return;
    }
    const payload = {
      title,
      description: $("#itsmFieldDescription")?.value?.trim() || null,
      priority: $("#itsmFieldPriority")?.value || "p3",
      urgency: $("#itsmFieldUrgency")?.value?.trim() || null,
      impact: $("#itsmFieldImpact")?.value?.trim() || null,
      category: $("#itsmFieldCategory")?.value?.trim() || null,
      assignee_user_id: $("#itsmFieldAssignee")?.value?.trim() || null,
      caller_email: $("#itsmFieldCallerEmail")?.value?.trim() || null,
      problem_id: $("#itsmFieldProblemId")?.value?.trim() || null,
      change_id: $("#itsmFieldChangeId")?.value?.trim() || null,
      ci_links: [],
    };
    const ci = $("#itsmFieldCi")?.value?.trim();
    if (ci) payload.ci_links = [{ component_id: ci }];
    const btn = $("#btnSaveItsmIncident");
    if (btn) btn.disabled = true;
    try {
      const doc = await SVRMON24ItsmApi.createIncident(payload);
      deps.toast(`Created ${doc.number_display || doc.incident_id}`);
      closeModal();
      await loadIncidents();
      await openIncident(doc.incident_id);
    } catch (err) {
      deps.toast(err.message || "Create failed", true);
    } finally {
      if (btn) btn.disabled = !deps.can("itsm:incident:write");
    }
  }

  function applyWriteGates() {
    const write = deps.can("itsm:incident:write");
    ["btnNewItsmInc", "btnItsmAddCi", "btnItsmComment", "btnSaveItsmIncident"].forEach(
      (id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !write;
      }
    );
  }

  function bindEvents() {
    $("#btnRefreshItsmInc")?.addEventListener("click", () => loadIncidents());
    $("#btnNewItsmInc")?.addEventListener("click", () => openModal());
    $("#btnCloseItsmIncidentModal")?.addEventListener("click", () => closeModal());
    $("#btnCancelItsmIncident")?.addEventListener("click", () => closeModal());
    $("#itsmIncidentForm")?.addEventListener("submit", createIncident);
    $("#btnCloseItsmIncDrawer")?.addEventListener("click", () => closeDrawer());
    $("#itsmIncSearch")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") loadIncidents();
    });
    $("#itsmIncStatus")?.addEventListener("change", () => loadIncidents());
    $("#itsmIncPriority")?.addEventListener("change", () => loadIncidents());
    $("#btnItsmAddCi")?.addEventListener("click", async () => {
      if (!selectedId) return;
      const cid = $("#itsmCiComponentId")?.value?.trim();
      if (!cid) return deps.toast("Enter a component_id", true);
      try {
        await SVRMON24ItsmApi.addCiLink(selectedId, cid);
        $("#itsmCiComponentId").value = "";
        deps.toast("CI linked");
        await openIncident(selectedId);
        await loadIncidents();
      } catch (err) {
        deps.toast(err.message || "CI link failed", true);
      }
    });
    $("#btnItsmComment")?.addEventListener("click", async () => {
      if (!selectedId) return;
      const message = $("#itsmCommentInput")?.value?.trim();
      if (!message) return deps.toast("Enter a comment", true);
      try {
        await SVRMON24ItsmApi.postComment("incident", selectedId, message);
        $("#itsmCommentInput").value = "";
        await loadActivities(selectedId);
      } catch (err) {
        deps.toast(err.message || "Comment failed", true);
      }
    });
  }

  function initItsmIncidents(options) {
    deps = { ...deps, ...(options || {}) };
    bindEvents();
    applyWriteGates();
  }

  global.SVRMON24ItsmIncidents = {
    initItsmIncidents,
    loadIncidents,
    applyWriteGates,
    closeDrawer,
  };
})(window);
