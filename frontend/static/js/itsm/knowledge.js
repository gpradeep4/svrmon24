/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  const TRANSITIONS = {
    draft: ["published", "retired"],
    published: ["retired", "draft"],
    retired: ["draft"],
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

  function splitCsv(value) {
    return String(value || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function applyWriteGates() {
    const canWrite = deps.can("itsm:knowledge:write");
    const btn = $("#btnNewItsmKb");
    if (btn) btn.hidden = !canWrite;
  }

  function openModal(editDoc) {
    const modal = $("#itsmKnowledgeModal");
    if (!modal) return;
    modal.classList.add("open");
    $("#itsmKnowledgeModalTitle").textContent = editDoc
      ? "Edit knowledge article"
      : "New knowledge article";
    $("#itsmKbEditId").value = editDoc?.article_id || "";
    $("#itsmKbFieldTitle").value = editDoc?.title || "";
    $("#itsmKbFieldBody").value = editDoc?.body || "";
    $("#itsmKbFieldCategory").value = editDoc?.category || "";
    $("#itsmKbFieldTags").value = (editDoc?.tags || []).join(", ");
    $("#itsmKbFieldIncidents").value = (editDoc?.related_incident_ids || []).join(", ");
    $("#itsmKbFieldProblems").value = (editDoc?.related_problem_ids || []).join(", ");
    $("#itsmKbFieldComponents").value = (editDoc?.related_component_ids || []).join(
      ", "
    );
    $("#itsmKbFieldTitle")?.focus();
  }

  function closeModal() {
    const modal = $("#itsmKnowledgeModal");
    if (!modal) return;
    modal.classList.remove("open");
    const form = $("#itsmKnowledgeForm");
    if (form) form.reset();
    const editId = $("#itsmKbEditId");
    if (editId) editId.value = "";
  }

  function openDrawer() {
    const drawer = $("#itsmKbDrawer");
    if (!drawer) return;
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    const drawer = $("#itsmKbDrawer");
    if (!drawer) return;
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    selectedId = null;
  }

  async function loadArticles() {
    const body = $("#itsmKbBody");
    const meta = $("#itsmKbListMeta");
    if (!body) return;
    const params = {
      page: "1",
      page_size: "50",
      sort_by: "updated_at",
      sort_dir: "desc",
    };
    const q = $("#itsmKbSearch")?.value?.trim();
    const status = $("#itsmKbStatus")?.value;
    const category = $("#itsmKbCategory")?.value?.trim();
    const tag = $("#itsmKbTag")?.value?.trim();
    if (q) params.q = q;
    if (status) params.status = status;
    if (category) params.category = category;
    if (tag) params.tag = tag;
    try {
      const data = await SVRMON24ItsmApi.listKnowledgeArticles(params);
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} article(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="7" class="hint">No knowledge articles yet. Create one to get started.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const tags = (row.tags || []).join(", ") || "—";
          return `<tr data-article-id="${esc(row.article_id)}">
            <td><code>${esc(row.number_display || row.article_id)}</code></td>
            <td>${esc(row.title)}</td>
            <td><span class="itsm-status is-${esc(row.status)}">${esc(row.status)}</span></td>
            <td>${esc(row.category || "—")}</td>
            <td>${esc(tags)}</td>
            <td>${esc(fmtWhen(row.updated_at))}</td>
            <td><button type="button" class="ghost itsm-open-kb" data-id="${esc(row.article_id)}">Open</button></td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".itsm-open-kb").forEach((btn) => {
        btn.addEventListener("click", () => openArticle(btn.getAttribute("data-id")));
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="7" class="hint">${esc(err.message || "Failed")}</td></tr>`;
      deps.toast(err.message || "Knowledge failed", true);
    }
  }

  async function openArticle(articleId) {
    selectedId = articleId;
    openDrawer();
    const detail = $("#itsmKbDrawerDetail");
    const title = $("#itsmKbDrawerTitle");
    const sub = $("#itsmKbDrawerSub");
    const related = $("#itsmKbRelated");
    try {
      const doc = await SVRMON24ItsmApi.getKnowledgeArticle(articleId);
      if (title) title.textContent = doc.number_display || doc.article_id;
      if (sub) sub.textContent = `${doc.status} · ${doc.category || "uncategorized"}`;
      if (detail) {
        const bodyPreview = esc(String(doc.body || "").slice(0, 4000)).replace(
          /\n/g,
          "<br/>"
        );
        detail.innerHTML = `
          <p><strong>${esc(doc.title)}</strong></p>
          <p class="hint">Tags: ${esc((doc.tags || []).join(", ") || "—")}</p>
          <div class="itsm-kb-body">${bodyPreview || "<span class='hint'>No body</span>"}</div>
          <p class="hint">Created ${esc(fmtWhen(doc.created_at))} · Updated ${esc(fmtWhen(doc.updated_at))}</p>
          <p class="hint">Published ${esc(fmtWhen(doc.published_at))} · Retired ${esc(fmtWhen(doc.retired_at))}</p>
        `;
      }
      if (related) {
        related.innerHTML = `
          <p>Incidents: ${esc((doc.related_incident_ids || []).join(", ") || "—")}</p>
          <p>Problems: ${esc((doc.related_problem_ids || []).join(", ") || "—")}</p>
          <p>Components: ${esc((doc.related_component_ids || []).join(", ") || "—")}</p>
        `;
      }
      renderTransitions(doc.status);
      renderEditBar(doc);
      await loadActivities(articleId);
    } catch (err) {
      if (detail) detail.textContent = err.message || "Failed to load article";
      deps.toast(err.message || "Article detail failed", true);
    }
  }

  function renderEditBar(doc) {
    const bar = $("#itsmKbEditBar");
    if (!bar) return;
    const write = deps.can("itsm:knowledge:write");
    if (!write) {
      bar.innerHTML = "";
      return;
    }
    bar.innerHTML = `<button type="button" class="secondary" id="btnItsmKbEdit">Edit article</button>`;
    $("#btnItsmKbEdit")?.addEventListener("click", () => openModal(doc));
  }

  function renderTransitions(status) {
    const bar = $("#itsmKbTransitionBar");
    if (!bar) return;
    const write = deps.can("itsm:knowledge:write");
    const next = TRANSITIONS[status] || [];
    if (!next.length) {
      bar.innerHTML = `<span class="hint">No further transitions from <code>${esc(status)}</code>.</span>`;
      return;
    }
    bar.innerHTML = next
      .map(
        (st) =>
          `<button type="button" class="secondary itsm-kb-transition" data-status="${esc(st)}" ${
            write ? "" : "disabled"
          }>→ ${esc(st)}</button>`
      )
      .join("");
    bar.querySelectorAll(".itsm-kb-transition").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!selectedId) return;
        try {
          await SVRMON24ItsmApi.transitionKnowledgeArticle(selectedId, {
            status: btn.getAttribute("data-status"),
          });
          deps.toast(`Transitioned to ${btn.getAttribute("data-status")}`);
          await openArticle(selectedId);
          await loadArticles();
        } catch (err) {
          deps.toast(err.message || "Transition failed", true);
        }
      });
    });
  }

  async function loadActivities(articleId) {
    const list = $("#itsmKbActivityList");
    if (!list) return;
    try {
      const data = await SVRMON24ItsmApi.listKnowledgeActivities(articleId);
      const items = data.items || [];
      if (!items.length) {
        list.innerHTML = `<li class="hint">No activity yet.</li>`;
        return;
      }
      list.innerHTML = items
        .map(
          (row) =>
            `<li><span class="itsm-activity-type">${esc(row.activity_type)}</span> ${esc(
              row.message
            )} <span class="hint">${esc(fmtWhen(row.created_at))}</span></li>`
        )
        .join("");
    } catch (err) {
      list.innerHTML = `<li class="hint">${esc(err.message || "Activity failed")}</li>`;
    }
  }

  async function renderSuggestedArticles(container, opts) {
    if (!container) return;
    if (!deps.can("itsm:knowledge:read")) {
      container.innerHTML = "";
      return;
    }
    const category = opts?.category || "";
    const tags = opts?.tags || [];
    if (!category && !(tags && tags.length)) {
      container.innerHTML = `<li class="hint">No category/tags on this incident for suggestions.</li>`;
      return;
    }
    try {
      const data = await SVRMON24ItsmApi.suggestKnowledgeArticles({
        category: category || undefined,
        tags: (tags || []).join(","),
        limit: "5",
      });
      const items = data.items || [];
      if (!items.length) {
        container.innerHTML = `<li class="hint">No matching published articles.</li>`;
        return;
      }
      container.innerHTML = items
        .map(
          (row) =>
            `<li><button type="button" class="ghost itsm-kb-jump" data-id="${esc(
              row.article_id
            )}">${esc(row.number_display || row.article_id)} · ${esc(
              row.title
            )}</button> <span class="hint">score ${esc(row.match_score)}</span></li>`
        )
        .join("");
      container.querySelectorAll(".itsm-kb-jump").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-id");
          const nav = document.querySelector('[data-tab="itsm-knowledge"]');
          nav?.click();
          setTimeout(() => openArticle(id), 50);
        });
      });
    } catch (err) {
      container.innerHTML = `<li class="hint">${esc(err.message || "Suggest failed")}</li>`;
    }
  }

  function collectPayload() {
    return {
      title: $("#itsmKbFieldTitle")?.value?.trim() || "",
      body: $("#itsmKbFieldBody")?.value?.trim() || "",
      category: $("#itsmKbFieldCategory")?.value?.trim() || null,
      tags: splitCsv($("#itsmKbFieldTags")?.value),
      related_incident_ids: splitCsv($("#itsmKbFieldIncidents")?.value),
      related_problem_ids: splitCsv($("#itsmKbFieldProblems")?.value),
      related_component_ids: splitCsv($("#itsmKbFieldComponents")?.value),
    };
  }

  function initItsmKnowledge(options) {
    deps = { ...deps, ...(options || {}) };
    applyWriteGates();

    $("#btnRefreshItsmKb")?.addEventListener("click", () => loadArticles());
    $("#btnNewItsmKb")?.addEventListener("click", () => openModal(null));
    $("#btnCloseItsmKbDrawer")?.addEventListener("click", () => closeDrawer());
    $("#btnCloseItsmKnowledgeModal")?.addEventListener("click", () => closeModal());
    $("#btnCancelItsmKnowledge")?.addEventListener("click", () => closeModal());

    ["itsmKbSearch", "itsmKbStatus", "itsmKbCategory", "itsmKbTag"].forEach((id) => {
      $(`#${id}`)?.addEventListener("change", () => loadArticles());
    });
    $("#itsmKbSearch")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        loadArticles();
      }
    });

    $("#itsmKnowledgeForm")?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const payload = collectPayload();
      if (!payload.title || !payload.body) {
        deps.toast("Title and body are required", true);
        return;
      }
      const editId = $("#itsmKbEditId")?.value?.trim();
      try {
        if (editId) {
          await SVRMON24ItsmApi.updateKnowledgeArticle(editId, payload);
          deps.toast("Article updated");
          closeModal();
          await openArticle(editId);
        } else {
          const created = await SVRMON24ItsmApi.createKnowledgeArticle({
            ...payload,
            status: "draft",
          });
          deps.toast(`Created ${created.number_display || created.article_id}`);
          closeModal();
          await loadArticles();
          if (created.article_id) await openArticle(created.article_id);
        }
        await loadArticles();
      } catch (err) {
        deps.toast(err.message || "Save failed", true);
      }
    });
  }

  global.SVRMON24ItsmKnowledge = {
    initItsmKnowledge,
    applyWriteGates,
    loadArticles,
    openArticle,
    renderSuggestedArticles,
  };
})(window);
