/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

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
    const modal = $("#itsmApprovalModal");
    if (!modal) return;
    modal.classList.add("open");
    $("#itsmAprFieldTitle")?.focus();
  }

  function closeModal() {
    const modal = $("#itsmApprovalModal");
    if (!modal) return;
    modal.classList.remove("open");
    $("#itsmApprovalForm")?.reset();
  }

  function openDrawer() {
    const drawer = $("#itsmAprDrawer");
    if (!drawer) return;
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    const drawer = $("#itsmAprDrawer");
    if (!drawer) return;
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    selectedId = null;
  }

  function applyWriteGates() {
    const canDecide = deps.can("itsm:approval:decide");
    const btn = $("#btnNewItsmApr");
    if (btn) btn.hidden = !canDecide;
  }

  async function loadApprovals() {
    const body = $("#itsmAprBody");
    const meta = $("#itsmAprListMeta");
    if (!body) return;
    const params = {
      page: "1",
      page_size: "50",
      sort_by: "updated_at",
      sort_dir: "desc",
    };
    const q = $("#itsmAprSearch")?.value?.trim();
    const status = $("#itsmAprStatus")?.value;
    const ticketType = $("#itsmAprTicketType")?.value;
    if (q) params.q = q;
    if (status) params.status = status;
    if (ticketType) params.ticket_type = ticketType;
    try {
      const data = await SVRMON24ItsmApi.listApprovals(params);
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} approval(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="7" class="hint">No approvals yet. Create one or start a workflow with an approval node.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const approvers = (row.approver_user_ids || []).join(", ") || row.approver_group || "—";
          return `<tr data-approval-id="${esc(row.approval_id)}">
            <td><code>${esc(row.approval_id)}</code></td>
            <td>${esc(row.title)}</td>
            <td><span class="itsm-status is-${esc(row.status)}">${esc(row.status)}</span></td>
            <td>${esc(row.ticket_type)} / <code>${esc(row.ticket_id)}</code></td>
            <td>${esc(approvers)}</td>
            <td>${esc(fmtWhen(row.updated_at))}</td>
            <td><button type="button" class="ghost itsm-open-apr" data-id="${esc(row.approval_id)}">Open</button></td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".itsm-open-apr").forEach((btn) => {
        btn.addEventListener("click", () => openApproval(btn.getAttribute("data-id")));
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="7" class="hint">${esc(err.message || "Failed")}</td></tr>`;
      deps.toast(err.message || "Approvals failed", true);
    }
  }

  function renderDecideBar(doc) {
    const bar = $("#itsmAprDecideBar");
    if (!bar) return;
    bar.innerHTML = "";
    if (!deps.can("itsm:approval:decide") || doc.status !== "pending") return;
    const approve = document.createElement("button");
    approve.type = "button";
    approve.textContent = "Approve";
    approve.addEventListener("click", () => decide("approved"));
    const reject = document.createElement("button");
    reject.type = "button";
    reject.className = "secondary";
    reject.textContent = "Reject";
    reject.addEventListener("click", () => decide("rejected"));
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "ghost";
    cancel.textContent = "Cancel request";
    cancel.addEventListener("click", () => cancelApproval());
    bar.append(approve, reject, cancel);
  }

  async function loadTicketActivities(ticketType, ticketId) {
    const list = $("#itsmAprActivityList");
    if (!list) return;
    try {
      const data = await SVRMON24ItsmApi.listActivities(ticketType, ticketId);
      const items = data.items || [];
      if (!items.length) {
        list.innerHTML = `<li class="hint">No activity.</li>`;
        return;
      }
      list.innerHTML = items
        .slice(0, 20)
        .map(
          (a) => `<li>
            <strong>${esc(a.activity_type)}</strong> — ${esc(a.message)}
            <span class="meta">${esc(a.actor_username || "—")} · ${esc(fmtWhen(a.created_at))}</span>
          </li>`
        )
        .join("");
    } catch (_) {
      list.innerHTML = `<li class="hint">Activity unavailable.</li>`;
    }
  }

  async function openApproval(approvalId) {
    selectedId = approvalId;
    openDrawer();
    const detail = $("#itsmAprDrawerDetail");
    const title = $("#itsmAprDrawerTitle");
    const sub = $("#itsmAprDrawerSub");
    try {
      const doc = await SVRMON24ItsmApi.getApproval(approvalId);
      if (title) title.textContent = doc.approval_id;
      if (sub) sub.textContent = `${doc.status} · ${doc.ticket_type}/${doc.ticket_id}`;
      if (detail) {
        const approvers = (doc.approver_user_ids || []).join(", ") || "—";
        detail.innerHTML = `
          <p><strong>${esc(doc.title)}</strong></p>
          <p class="hint">${esc(doc.description || "No description")}</p>
          <p class="hint">Ticket: ${esc(doc.ticket_type)} / <code>${esc(doc.ticket_id)}</code></p>
          <p class="hint">Approvers: ${esc(approvers)}</p>
          <p class="hint">Group: ${esc(doc.approver_group || "—")} · Policy: ${esc(doc.policy || "—")}</p>
          <p class="hint">Workflow execution: ${esc(doc.workflow_execution_id || "—")} · Node: ${esc(doc.node_id || "—")}</p>
          <p class="hint">Decided by: ${esc(doc.decided_by || "—")} · ${esc(fmtWhen(doc.decided_at))}</p>
          <p class="hint">Decision comment: ${esc(doc.comment || "—")}</p>
          <p class="hint">Created ${esc(fmtWhen(doc.created_at))} · Updated ${esc(fmtWhen(doc.updated_at))}</p>
        `;
      }
      renderDecideBar(doc);
      await loadTicketActivities(doc.ticket_type, doc.ticket_id);
    } catch (err) {
      if (detail) detail.textContent = err.message || "Failed to load approval";
      deps.toast(err.message || "Approval detail failed", true);
    }
  }

  async function decide(decision) {
    if (!selectedId) return;
    const comment = $("#itsmAprCommentInput")?.value?.trim() || null;
    try {
      await SVRMON24ItsmApi.decideApproval(selectedId, { decision, comment });
      deps.toast(`Approval ${decision}`);
      await loadApprovals();
      await openApproval(selectedId);
    } catch (err) {
      deps.toast(err.message || "Decide failed", true);
    }
  }

  async function cancelApproval() {
    if (!selectedId) return;
    const comment = $("#itsmAprCommentInput")?.value?.trim() || null;
    try {
      await SVRMON24ItsmApi.cancelApproval(selectedId, { comment });
      deps.toast("Approval cancelled");
      await loadApprovals();
      await openApproval(selectedId);
    } catch (err) {
      deps.toast(err.message || "Cancel failed", true);
    }
  }

  async function createApproval(ev) {
    ev.preventDefault();
    const title = $("#itsmAprFieldTitle")?.value?.trim();
    const ticket_type = $("#itsmAprFieldTicketType")?.value;
    const ticket_id = $("#itsmAprFieldTicketId")?.value?.trim();
    if (!title || !ticket_id) {
      deps.toast("Title and ticket id are required", true);
      return;
    }
    const approversRaw = $("#itsmAprFieldApprovers")?.value || "";
    const approver_user_ids = approversRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const payload = {
      title,
      ticket_type,
      ticket_id,
      description: $("#itsmAprFieldDescription")?.value?.trim() || null,
      approver_user_ids,
      approver_group: $("#itsmAprFieldGroup")?.value?.trim() || null,
      policy: $("#itsmAprFieldPolicy")?.value?.trim() || null,
    };
    try {
      const doc = await SVRMON24ItsmApi.createApproval(payload);
      closeModal();
      deps.toast(`Created ${doc.approval_id}`);
      await loadApprovals();
      await openApproval(doc.approval_id);
    } catch (err) {
      deps.toast(err.message || "Create failed", true);
    }
  }

  function initItsmApprovals(options) {
    deps = { ...deps, ...(options || {}) };
    applyWriteGates();

    $("#btnRefreshItsmApr")?.addEventListener("click", () => loadApprovals());
    $("#btnNewItsmApr")?.addEventListener("click", () => openModal());
    $("#btnCloseItsmApprovalModal")?.addEventListener("click", closeModal);
    $("#btnCancelItsmApproval")?.addEventListener("click", closeModal);
    $("#itsmApprovalForm")?.addEventListener("submit", createApproval);
    $("#btnCloseItsmAprDrawer")?.addEventListener("click", closeDrawer);
    $("#itsmAprSearch")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") loadApprovals();
    });
    $("#itsmAprStatus")?.addEventListener("change", () => loadApprovals());
    $("#itsmAprTicketType")?.addEventListener("change", () => loadApprovals());
  }

  global.SVRMON24ItsmApprovals = {
    initItsmApprovals,
    loadApprovals,
    openApproval,
    applyWriteGates,
  };
})(window);
