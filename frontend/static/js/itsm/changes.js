/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  const TRANSITIONS = {
    draft: ["submitted", "cancelled"],
    submitted: ["approved", "rejected", "cancelled"],
    approved: ["scheduled", "cancelled"],
    scheduled: ["implementing", "cancelled"],
    implementing: ["review", "cancelled"],
    review: ["closed", "implementing"],
    closed: [],
    rejected: [],
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
    const modal = $("#itsmChangeModal");
    if (!modal) return;
    modal.classList.add("open");
    const title = $("#itsmChgFieldTitle");
    if (title) title.focus();
  }

  function closeModal() {
    const modal = $("#itsmChangeModal");
    if (!modal) return;
    modal.classList.remove("open");
    const form = $("#itsmChangeForm");
    if (form) form.reset();
  }

  function openDrawer() {
    const drawer = $("#itsmChgDrawer");
    if (!drawer) return;
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    const drawer = $("#itsmChgDrawer");
    if (!drawer) return;
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    selectedId = null;
  }

  async function loadChanges() {
    const body = $("#itsmChgBody");
    const meta = $("#itsmChgListMeta");
    if (!body) return;
    const params = {
      page: "1",
      page_size: "50",
      sort_by: "updated_at",
      sort_dir: "desc",
    };
    const q = $("#itsmChgSearch")?.value?.trim();
    const status = $("#itsmChgStatus")?.value;
    const changeType = $("#itsmChgType")?.value;
    const componentId = $("#itsmChgCiFilter")?.value?.trim();
    if (q) params.q = q;
    if (status) params.status = status;
    if (changeType) params.change_type = changeType;
    if (componentId) params.component_id = componentId;
    try {
      const data = await SVRMON24ItsmApi.listChanges(params);
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} change(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="8" class="hint">No changes yet. Create one to get started.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const cis = (row.ci_links || []).length;
          return `<tr data-change-id="${esc(row.change_id)}">
            <td><code>${esc(row.number_display || row.change_id)}</code></td>
            <td>${esc(row.title)}</td>
            <td><span class="itsm-status is-${esc(row.status)}">${esc(row.status)}</span></td>
            <td>${esc(row.change_type)}</td>
            <td><span class="itsm-priority is-${esc(row.priority)}">${esc(row.priority)}</span></td>
            <td>${cis}</td>
            <td>${esc(fmtWhen(row.updated_at))}</td>
            <td><button type="button" class="ghost itsm-open-chg" data-id="${esc(row.change_id)}">Open</button></td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".itsm-open-chg").forEach((btn) => {
        btn.addEventListener("click", () => openChange(btn.getAttribute("data-id")));
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="8" class="hint">${esc(err.message || "Failed")}</td></tr>`;
      deps.toast(err.message || "Changes failed", true);
    }
  }

  function renderAiAssist(html) {
    const box = $("#itsmChgAiAssist");
    if (box) box.innerHTML = html || "";
  }

  async function refreshAiStatus() {
    const box = $("#itsmChgAiStatus");
    if (!box) return;
    try {
      const st = await SVRMON24ItsmApi.aiStatus();
      const ollama = st.providers?.ollama ? "enabled" : "off";
      const cloud = st.providers?.cloud_suggestions ? "enabled" : "off";
      box.innerHTML = `AI providers: Ollama <code>${esc(
        ollama
      )}</code> · cloud <code>${esc(cloud)}</code> · assist only`;
    } catch (_) {
      box.innerHTML = "";
    }
  }

  async function runNextStepsAssist() {
    if (!selectedId) return deps.toast("Open a change first", true);
    try {
      const result = await SVRMON24ItsmApi.nextStepsChange(selectedId, {
        force_fallback: false,
      });
      const legal = (result.legal_next_statuses || []).map(esc).join(", ") || "—";
      const wfs = (result.suggested_workflows || [])
        .slice(0, 3)
        .map(
          (w) =>
            `<li><code>${esc(w.workflow_id)}</code> ${esc(w.name || "")} ` +
            `<span class="hint">${esc(w.match_reason || "")}</span></li>`
        )
        .join("");
      renderAiAssist(
        `<strong>Next steps (${esc(result.source)}):</strong> ${esc(
          result.summary || ""
        )}<br/><span class="hint">Legal: ${legal}</span>` +
          (wfs ? `<ul class="itsm-ci-list">${wfs}</ul>` : "") +
          `<br/><span class="hint">No auto-transition / auto-approve.</span>`
      );
      deps.toast(`Next steps ready (${result.source})`);
    } catch (err) {
      renderAiAssist("");
      deps.toast(err.message || "Next steps failed", true);
    }
  }

  async function runChangeRiskAssist() {
    if (!selectedId) return deps.toast("Open a change first", true);
    try {
      const result = await SVRMON24ItsmApi.changeRiskAssist(selectedId, {
        force_fallback: false,
      });
      const apps = (result.affected_applications || [])
        .slice(0, 5)
        .map((a) => esc(a.component_id || a.name || ""))
        .filter(Boolean)
        .join(", ");
      const checks = (result.checklist || [])
        .slice(0, 4)
        .map((c) => `<li>${esc(c)}</li>`)
        .join("");
      renderAiAssist(
        `<strong>Risk (${esc(result.source)}):</strong> band <code>${esc(
          result.risk_band
        )}</code>. ${esc(result.narrative || "")}` +
          (apps ? `<br/><span class="hint">Apps: ${apps}</span>` : "") +
          (checks ? `<ul class="itsm-ci-list">${checks}</ul>` : "") +
          `<br/><span class="hint">${esc(
            result.disclaimer || "Assist only — no auto CAB."
          )}</span>`
      );
      deps.toast(`Change risk ready (${result.source})`);
    } catch (err) {
      renderAiAssist("");
      deps.toast(err.message || "Change risk failed", true);
    }
  }

  async function runSlaAtRiskAssist() {
    if (!selectedId) return deps.toast("Open a change first", true);
    try {
      const result = await SVRMON24ItsmApi.slaAtRiskAssist({
        ticket_type: "change",
        ticket_id: selectedId,
        force_fallback: false,
      });
      const items = (result.items || [])
        .slice(0, 4)
        .map(
          (row) =>
            `<li><code>${esc(row.metric)}</code> · ${esc(row.status)} · ` +
            `at_risk=${esc(row.at_risk)} · ${esc(row.reason || "")}</li>`
        )
        .join("");
      renderAiAssist(
        `<strong>SLA (${esc(result.source)}):</strong> ${esc(
          result.summary || ""
        )}` +
          (items ? `<ul class="itsm-ci-list">${items}</ul>` : "") +
          `<span class="hint">Assist only — clocks not mutated.</span>`
      );
      deps.toast(`SLA assist ready (${result.source})`);
    } catch (err) {
      renderAiAssist("");
      deps.toast(err.message || "SLA assist failed", true);
    }
  }

  async function openChange(changeId) {
    selectedId = changeId;
    renderAiAssist("");
    openDrawer();
    refreshAiStatus();
    const detail = $("#itsmChgDrawerDetail");
    const title = $("#itsmChgDrawerTitle");
    const sub = $("#itsmChgDrawerSub");
    try {
      const doc = await SVRMON24ItsmApi.getChange(changeId);
      if (title) title.textContent = doc.number_display || doc.change_id;
      if (sub) sub.textContent = `${doc.status} · ${doc.change_type} · ${doc.priority}`;
      if (detail) {
        const relatedInc = (doc.related_incident_ids || []).join(", ") || "—";
        const relatedPrb = (doc.related_problem_ids || []).join(", ") || "—";
        detail.innerHTML = `
          <p><strong>${esc(doc.title)}</strong></p>
          <p class="hint">${esc(doc.description || "No description")}</p>
          <p class="hint">Justification: ${esc(doc.justification || "—")}</p>
          <p class="hint">Risk: ${esc(doc.risk || "—")} · Impact: ${esc(doc.impact || "—")} · CAB: ${doc.cab_required ? "yes" : "no"}</p>
          <p class="hint">Assignee: ${esc(doc.assignee_user_id || "—")}</p>
          <p class="hint">Related incidents: ${esc(relatedInc)}</p>
          <p class="hint">Related problems: ${esc(relatedPrb)}</p>
          <p class="hint">Created ${esc(fmtWhen(doc.created_at))} · Updated ${esc(fmtWhen(doc.updated_at))}</p>
        `;
      }
      renderTransitions(doc.status);
      renderCiLinks(doc.ci_links || []);
      if (global.SVRMON24ItsmDeeplinks?.renderImpactPanel) {
        await global.SVRMON24ItsmDeeplinks.renderImpactPanel(
          $("#itsmChgImpactPanel"),
          doc.ci_links || []
        );
      }
      if (global.SVRMON24ItsmSla?.renderTicketBadges) {
        await global.SVRMON24ItsmSla.renderTicketBadges(
          $("#itsmChgSlaBadges"),
          "change",
          changeId
        );
      }
      await loadActivities(changeId);
    } catch (err) {
      if (detail) detail.textContent = err.message || "Failed to load change";
      deps.toast(err.message || "Change detail failed", true);
    }
  }

  function renderTransitions(status) {
    const bar = $("#itsmChgTransitionBar");
    if (!bar) return;
    const write = deps.can("itsm:change:write");
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
          await SVRMON24ItsmApi.transitionChange(selectedId, {
            status: btn.getAttribute("data-status"),
          });
          deps.toast(`Transitioned to ${btn.getAttribute("data-status")}`);
          await openChange(selectedId);
          await loadChanges();
        } catch (err) {
          deps.toast(err.message || "Transition failed", true);
        }
      });
    });
  }

  function renderCiLinks(links) {
    const list = $("#itsmChgCiList");
    if (!list) return;
    const write = deps.can("itsm:change:write");
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
          await SVRMON24ItsmApi.removeChangeCiLink(selectedId, btn.getAttribute("data-id"));
          deps.toast("CI unlinked");
          await openChange(selectedId);
          await loadChanges();
        } catch (err) {
          deps.toast(err.message || "Unlink failed", true);
        }
      });
    });
  }

  async function loadActivities(changeId) {
    const list = $("#itsmChgActivityList");
    if (!list) return;
    try {
      const data = await SVRMON24ItsmApi.listActivities("change", changeId);
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

  async function createChange(event) {
    event.preventDefault();
    const title = $("#itsmChgFieldTitle")?.value?.trim();
    if (!title) {
      deps.toast("Title is required", true);
      return;
    }
    const payload = {
      title,
      description: $("#itsmChgFieldDescription")?.value?.trim() || null,
      justification: $("#itsmChgFieldJustification")?.value?.trim() || null,
      change_type: $("#itsmChgFieldType")?.value || "normal",
      priority: $("#itsmChgFieldPriority")?.value || "p3",
      risk: $("#itsmChgFieldRisk")?.value?.trim() || null,
      impact: $("#itsmChgFieldImpact")?.value?.trim() || null,
      assignee_user_id: $("#itsmChgFieldAssignee")?.value?.trim() || null,
      cab_required: Boolean($("#itsmChgFieldCab")?.checked),
      implementation_plan: $("#itsmChgFieldImpl")?.value?.trim() || null,
      backout_plan: $("#itsmChgFieldBackout")?.value?.trim() || null,
      related_incident_ids: splitIds($("#itsmChgFieldRelatedInc")?.value || ""),
      related_problem_ids: splitIds($("#itsmChgFieldRelatedPrb")?.value || ""),
      ci_links: [],
    };
    const ci = $("#itsmChgFieldCi")?.value?.trim();
    if (ci) payload.ci_links = [{ component_id: ci }];
    const btn = $("#btnSaveItsmChange");
    if (btn) btn.disabled = true;
    try {
      const doc = await SVRMON24ItsmApi.createChange(payload);
      deps.toast(`Created ${doc.number_display || doc.change_id}`);
      closeModal();
      await loadChanges();
      await openChange(doc.change_id);
    } catch (err) {
      deps.toast(err.message || "Create failed", true);
    } finally {
      if (btn) btn.disabled = !deps.can("itsm:change:write");
    }
  }

  function applyWriteGates() {
    const write = deps.can("itsm:change:write");
    ["btnNewItsmChg", "btnItsmChgAddCi", "btnItsmChgComment", "btnSaveItsmChange"].forEach(
      (id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !write;
      }
    );
  }

  function bindEvents() {
    $("#btnRefreshItsmChg")?.addEventListener("click", () => loadChanges());
    $("#btnNewItsmChg")?.addEventListener("click", () => openModal());
    $("#btnCloseItsmChangeModal")?.addEventListener("click", () => closeModal());
    $("#btnCancelItsmChange")?.addEventListener("click", () => closeModal());
    $("#itsmChangeForm")?.addEventListener("submit", createChange);
    $("#btnCloseItsmChgDrawer")?.addEventListener("click", () => closeDrawer());
    $("#itsmChgSearch")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") loadChanges();
    });
    $("#itsmChgStatus")?.addEventListener("change", () => loadChanges());
    $("#itsmChgType")?.addEventListener("change", () => loadChanges());
    $("#itsmChgCiFilter")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") loadChanges();
    });
    $("#itsmChgCiFilter")?.addEventListener("change", () => loadChanges());
    $("#btnItsmChgAddCi")?.addEventListener("click", async () => {
      if (!selectedId) return;
      const cid = $("#itsmChgCiComponentId")?.value?.trim();
      if (!cid) return deps.toast("Enter a component_id", true);
      try {
        await SVRMON24ItsmApi.addChangeCiLink(selectedId, cid);
        $("#itsmChgCiComponentId").value = "";
        deps.toast("CI linked");
        await openChange(selectedId);
        await loadChanges();
      } catch (err) {
        deps.toast(err.message || "CI link failed", true);
      }
    });
    $("#btnItsmChgComment")?.addEventListener("click", async () => {
      if (!selectedId) return;
      const message = $("#itsmChgCommentInput")?.value?.trim();
      if (!message) return deps.toast("Enter a comment", true);
      try {
        await SVRMON24ItsmApi.postComment("change", selectedId, message);
        $("#itsmChgCommentInput").value = "";
        await loadActivities(selectedId);
      } catch (err) {
        deps.toast(err.message || "Comment failed", true);
      }
    });
    $("#btnItsmChgRisk")?.addEventListener("click", () => {
      runChangeRiskAssist();
    });
    $("#btnItsmChgSlaRisk")?.addEventListener("click", () => {
      runSlaAtRiskAssist();
    });
    $("#btnItsmChgNextSteps")?.addEventListener("click", () => {
      runNextStepsAssist();
    });
  }

  function initItsmChanges(options) {
    deps = { ...deps, ...(options || {}) };
    bindEvents();
    applyWriteGates();
  }

  function filterByComponent(componentId) {
    const el = $("#itsmChgCiFilter");
    if (el) el.value = (componentId || "").trim();
    return loadChanges();
  }

  global.SVRMON24ItsmChanges = {
    initItsmChanges,
    loadChanges,
    openChange,
    filterByComponent,
    applyWriteGates,
    closeDrawer,
  };
})(window);
