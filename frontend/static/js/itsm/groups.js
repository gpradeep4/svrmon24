/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  let deps = { can: () => false, toast: () => {}, escapeHtml: (s) => s };

  function $(sel) {
    return document.querySelector(sel);
  }

  function esc(s) {
    return deps.escapeHtml(s == null ? "" : String(s));
  }

  async function refreshGroupPicker() {
    const list = $("#itsmGroupPickerList");
    if (!list || !deps.can("itsm:groups:read")) return;
    try {
      const data = await SVRMON24ItsmApi.assignmentGroupPicker();
      const items = data.items || [];
      list.innerHTML = items.map((n) => `<option value="${esc(n)}"></option>`).join("");
    } catch (_) {
      /* picker is best-effort */
    }
  }

  async function loadGroups() {
    const body = $("#itsmGrpBody");
    const meta = $("#itsmGrpListMeta");
    if (!body) return;
    try {
      const data = await SVRMON24ItsmApi.listAssignmentGroups({
        page: "1",
        page_size: "100",
      });
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} group(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="5" class="hint">No assignment groups yet.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map(
          (row) => `<tr data-group-id="${esc(row.group_id)}">
            <td><code>${esc(row.group_id)}</code></td>
            <td>${esc(row.name)}</td>
            <td>${row.active ? "active" : "inactive"}</td>
            <td>${esc((row.member_user_ids || []).length)}</td>
            <td>${esc(row.email || "—")}</td>
          </tr>`
        )
        .join("");
    } catch (err) {
      if (meta) meta.textContent = err.message || "Failed to load groups";
      body.innerHTML = `<tr><td colspan="5" class="hint">${esc(err.message || "Failed")}</td></tr>`;
    }
  }

  async function createGroup(event) {
    event.preventDefault();
    const name = $("#itsmGrpFieldName")?.value?.trim();
    if (!name) {
      deps.toast("Name is required", true);
      return;
    }
    const membersRaw = $("#itsmGrpFieldMembers")?.value?.trim() || "";
    const payload = {
      name,
      description: $("#itsmGrpFieldDesc")?.value?.trim() || null,
      email: $("#itsmGrpFieldEmail")?.value?.trim() || null,
      member_user_ids: membersRaw
        ? membersRaw.split(",").map((s) => s.trim()).filter(Boolean)
        : [],
      active: $("#itsmGrpFieldActive")?.checked !== false,
    };
    try {
      const doc = await SVRMON24ItsmApi.createAssignmentGroup(payload);
      deps.toast(`Created ${doc.name || doc.group_id}`);
      $("#itsmGrpForm")?.reset();
      const active = $("#itsmGrpFieldActive");
      if (active) active.checked = true;
      await loadGroups();
      await refreshGroupPicker();
    } catch (err) {
      deps.toast(err.message || "Create failed", true);
    }
  }

  function applyWriteGates() {
    const admin = deps.can("itsm:groups:admin");
    const btn = $("#btnSaveItsmGroup");
    if (btn) btn.disabled = !admin;
    const form = $("#itsmGrpForm");
    if (form) form.hidden = !admin;
  }

  function initItsmGroups(options) {
    deps = { ...deps, ...(options || {}) };
    $("#itsmGrpForm")?.addEventListener("submit", createGroup);
    $("#btnRefreshItsmGrp")?.addEventListener("click", () => loadGroups());
    applyWriteGates();
  }

  global.SVRMON24ItsmGroups = {
    initItsmGroups,
    loadGroups,
    refreshGroupPicker,
    applyWriteGates,
  };
})(window);
