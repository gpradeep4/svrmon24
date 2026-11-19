/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  const TRANSITIONS = {
    new: ["under_investigation", "cancelled"],
    under_investigation: ["known_error", "resolved", "cancelled"],
    known_error: ["resolved", "cancelled"],
    resolved: ["closed", "under_investigation"],
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
    const modal = $("#itsmProblemModal");
    if (!modal) return;
    modal.classList.add("open");
    const title = $("#itsmPrbFieldTitle");
    if (title) title.focus();
  }

  function closeModal() {
    const modal = $("#itsmProblemModal");
    if (!modal) return;
    modal.classList.remove("open");
    const form = $("#itsmProblemForm");
    if (form) form.reset();
  }

  function openDrawer() {
    const drawer = $("#itsmPrbDrawer");
    if (!drawer) return;
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    const drawer = $("#itsmPrbDrawer");
    if (!drawer) return;
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    selectedId = null;
  }

  async function loadProblems() {
    const body = $("#itsmPrbBody");
    const meta = $("#itsmPrbListMeta");
    if (!body) return;
    const params = {
      page: "1",
      page_size: "50",
      sort_by: "updated_at",
      sort_dir: "desc",
    };
    const q = $("#itsmPrbSearch")?.value?.trim();
    const status = $("#itsmPrbStatus")?.value;
    const priority = $("#itsmPrbPriority")?.value;
    if (q) params.q = q;
    if (status) params.status = status;
    if (priority) params.priority = priority;
    try {
      const data = await SVRMON24ItsmApi.listProblems(params);
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} problem(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="8" class="hint">No problems yet. Create one to get started.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const cis = (row.ci_links || []).length;
          return `<tr data-problem-id="${esc(row.problem_id)}">
            <td><code>${esc(row.number_display || row.problem_id)}</code></td>
            <td>${esc(row.title)}</td>
            <td><span class="itsm-status is-${esc(row.status)}">${esc(row.status)}</span></td>
            <td><span class="itsm-priority is-${esc(row.priority)}">${esc(row.priority)}</span></td>
            <td>${row.known_error ? "yes" : "—"}</td>
            <td>${cis}</td>
            <td>${esc(fmtWhen(row.updated_at))}</td>
            <td><button type="button" class="ghost itsm-open-prb" data-id="${esc(row.problem_id)}">Open</button></td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".itsm-open-prb").forEach((btn) => {
        btn.addEventListener("click", () => openProblem(btn.getAttribute("data-id")));
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="8" class="hint">${esc(err.message || "Failed")}</td></tr>`;
      deps.toast(err.message || "Problems failed", true);
    }
  }

  async function openProblem(problemId) {
    selectedId = problemId;
    openDrawer();
    const detail = $("#itsmPrbDrawerDetail");
    const title = $("#itsmPrbDrawerTitle");
    const sub = $("#itsmPrbDrawerSub");
    try {
      const doc = await SVRMON24ItsmApi.getProblem(problemId);
      if (title) title.textContent = doc.number_display || doc.problem_id;
      if (sub) sub.textContent = `${doc.status} · ${doc.priority}`;
      if (detail) {
        const relatedInc = (doc.related_incident_ids || []).join(", ") || "—";
        detail.innerHTML = `
          <p><strong>${esc(doc.title)}</strong></p>
          <p class="hint">${esc(doc.description || "No description")}</p>
          <p class="hint">Category: ${esc(doc.category || "—")} · Known error: ${doc.known_error ? "yes" : "no"}</p>
          <p class="hint">Root cause: ${esc(doc.root_cause || "—")}</p>
          <p class="hint">Workaround: ${esc(doc.workaround || "—")}</p>
          <p class="hint">Assignee: ${esc(doc.assignee_user_id || "—")}</p>
          <p class="hint">Related incidents: ${esc(relatedInc)}</p>
          <p class="hint">Linked change: ${esc(doc.change_id || "—")}</p>
          <p class="hint">Created ${esc(fmtWhen(doc.created_at))} · Updated ${esc(fmtWhen(doc.updated_at))}</p>
        `;
      }
      renderTransitions(doc.status);
      renderCiLinks(doc.ci_links || []);
      await loadActivities(problemId);
    } catch (err) {
      if (detail) detail.textContent = err.message || "Failed to load problem";
      deps.toast(err.message || "Problem detail failed", true);
    }
  }

  function renderTransitions(status) {
    const bar = $("#itsmPrbTransitionBar");
    if (!bar) return;
    const write = deps.can("itsm:problem:write");
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
          await SVRMON24ItsmApi.transitionProblem(selectedId, {
            status: btn.getAttribute("data-status"),
          });
          deps.toast(`Transitioned to ${btn.getAttribute("data-status")}`);
          await openProblem(selectedId);
          await loadProblems();
        } catch (err) {
          deps.toast(err.message || "Transition failed", true);
        }
      });
    });
  }

  function renderCiLinks(links) {
    const list = $("#itsmPrbCiList");
    if (!list) return;
    const write = deps.can("itsm:problem:write");
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
          await SVRMON24ItsmApi.removeProblemCiLink(selectedId, btn.getAttribute("data-id"));
          deps.toast("CI unlinked");
          await openProblem(selectedId);
          await loadProblems();
        } catch (err) {
          deps.toast(err.message || "Unlink failed", true);
        }
      });
    });
  }

  async function loadActivities(problemId) {
    const list = $("#itsmPrbActivityList");
    if (!list) return;
    try {
      const data = await SVRMON24ItsmApi.listActivities("problem", problemId);
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

  function splitIds(raw) {
    if (!raw || !raw.trim()) return [];
    return raw
      .split(/[,;\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  async function createProblem(event) {
    event.preventDefault();
    const title = $("#itsmPrbFieldTitle")?.value?.trim();
    if (!title) {
      deps.toast("Title is required", true);
      return;
    }
    const payload = {
      title,
      description: $("#itsmPrbFieldDescription")?.value?.trim() || null,
      priority: $("#itsmPrbFieldPriority")?.value || "p3",
      category: $("#itsmPrbFieldCategory")?.value?.trim() || null,
      assignee_user_id: $("#itsmPrbFieldAssignee")?.value?.trim() || null,
      root_cause: $("#itsmPrbFieldRootCause")?.value?.trim() || null,
      workaround: $("#itsmPrbFieldWorkaround")?.value?.trim() || null,
      known_error: Boolean($("#itsmPrbFieldKnownError")?.checked),
      related_incident_ids: splitIds($("#itsmPrbFieldRelatedInc")?.value || ""),
      change_id: $("#itsmPrbFieldChangeId")?.value?.trim() || null,
      ci_links: [],
    };
    const ci = $("#itsmPrbFieldCi")?.value?.trim();
    if (ci) payload.ci_links = [{ component_id: ci }];
    const btn = $("#btnSaveItsmProblem");
    if (btn) btn.disabled = true;
    try {
      const doc = await SVRMON24ItsmApi.createProblem(payload);
      deps.toast(`Created ${doc.number_display || doc.problem_id}`);
      closeModal();
      await loadProblems();
      await openProblem(doc.problem_id);
    } catch (err) {
      deps.toast(err.message || "Create failed", true);
    } finally {
      if (btn) btn.disabled = !deps.can("itsm:problem:write");
    }
  }

  function applyWriteGates() {
    const write = deps.can("itsm:problem:write");
    ["btnNewItsmPrb", "btnItsmPrbAddCi", "btnItsmPrbComment", "btnSaveItsmProblem"].forEach(
      (id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !write;
      }
    );
  }

  function bindEvents() {
    $("#btnRefreshItsmPrb")?.addEventListener("click", () => loadProblems());
    $("#btnNewItsmPrb")?.addEventListener("click", () => openModal());
    $("#btnCloseItsmProblemModal")?.addEventListener("click", () => closeModal());
    $("#btnCancelItsmProblem")?.addEventListener("click", () => closeModal());
    $("#itsmProblemForm")?.addEventListener("submit", createProblem);
    $("#btnCloseItsmPrbDrawer")?.addEventListener("click", () => closeDrawer());
    $("#itsmPrbSearch")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") loadProblems();
    });
    $("#itsmPrbStatus")?.addEventListener("change", () => loadProblems());
    $("#itsmPrbPriority")?.addEventListener("change", () => loadProblems());
    $("#btnItsmPrbAddCi")?.addEventListener("click", async () => {
      if (!selectedId) return;
      const cid = $("#itsmPrbCiComponentId")?.value?.trim();
      if (!cid) return deps.toast("Enter a component_id", true);
      try {
        await SVRMON24ItsmApi.addProblemCiLink(selectedId, cid);
        $("#itsmPrbCiComponentId").value = "";
        deps.toast("CI linked");
        await openProblem(selectedId);
        await loadProblems();
      } catch (err) {
        deps.toast(err.message || "CI link failed", true);
      }
    });
    $("#btnItsmPrbComment")?.addEventListener("click", async () => {
      if (!selectedId) return;
      const message = $("#itsmPrbCommentInput")?.value?.trim();
      if (!message) return deps.toast("Enter a comment", true);
      try {
        await SVRMON24ItsmApi.postComment("problem", selectedId, message);
        $("#itsmPrbCommentInput").value = "";
        await loadActivities(selectedId);
      } catch (err) {
        deps.toast(err.message || "Comment failed", true);
      }
    });
  }

  function initItsmProblems(options) {
    deps = { ...deps, ...(options || {}) };
    bindEvents();
    applyWriteGates();
  }

  global.SVRMON24ItsmProblems = {
    initItsmProblems,
    loadProblems,
    applyWriteGates,
    closeDrawer,
  };
})(window);
