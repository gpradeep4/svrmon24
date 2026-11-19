/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  let deps = { can: () => false, toast: () => {}, escapeHtml: (s) => s };
  let selectedWorkflowId = null;
  let selectedNodeId = null;
  let selectedEdgeId = null;
  let connectMode = false;
  let connectFrom = null;
  let graph = { nodes: [], edges: [] };
  let dragState = null;
  let nodeSeq = 1;

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

  function canAdmin() {
    return deps.can("itsm:workflow:admin");
  }

  function applyWriteGates() {
    const admin = canAdmin();
    [
      "btnNewItsmWf",
      "btnSaveItsmWf",
      "btnActivateItsmWf",
      "btnDeactivateItsmWf",
      "btnItsmWfStart",
      "btnItsmWfConnect",
      "btnItsmWfApplyNode",
      "btnItsmWfDeleteNode",
      "btnItsmWfDeleteEdge",
    ].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.hidden = !admin;
    });
    document.querySelectorAll(".itsm-wf-add-node").forEach((btn) => {
      btn.hidden = !admin;
    });
  }

  function defaultGraph() {
    return {
      nodes: [
        { id: "start", type: "start", label: "Start", config: {}, x: 40, y: 80 },
        { id: "end", type: "end", label: "End", config: {}, x: 360, y: 80 },
      ],
      edges: [{ id: "e-start-end", from: "start", to: "end", condition: null }],
    };
  }

  function resetDesigner(empty) {
    selectedWorkflowId = null;
    selectedNodeId = null;
    selectedEdgeId = null;
    connectMode = false;
    connectFrom = null;
    graph = empty ? { nodes: [], edges: [] } : defaultGraph();
    nodeSeq = graph.nodes.length + 1;
    $("#itsmWfName").value = "";
    $("#itsmWfAppliesTo").value = "generic";
    $("#itsmWfTrigger").value = "manual";
    $("#itsmWfMeta").textContent = "New unsaved workflow";
    renderCanvas();
    renderInspector();
  }

  function nodeById(id) {
    return graph.nodes.find((n) => n.id === id);
  }

  function renderCanvas() {
    const nodesEl = $("#itsmWfNodes");
    const svg = $("#itsmWfEdges");
    if (!nodesEl || !svg) return;
    nodesEl.innerHTML = "";
    graph.nodes.forEach((node) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `itsm-wf-node is-${node.type}${selectedNodeId === node.id ? " is-selected" : ""}${
        connectFrom === node.id ? " is-connect-from" : ""
      }`;
      el.style.left = `${node.x || 40}px`;
      el.style.top = `${node.y || 40}px`;
      el.dataset.nodeId = node.id;
      el.innerHTML = `<span class="type">${esc(node.type)}</span><strong>${esc(
        node.label || node.id
      )}</strong>`;
      el.addEventListener("mousedown", (ev) => onNodeMouseDown(ev, node.id));
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        onNodeClick(node.id);
      });
      nodesEl.appendChild(el);
    });
    drawEdges(svg);
  }

  function drawEdges(svg) {
    const canvas = $("#itsmWfCanvas");
    const w = canvas?.clientWidth || 800;
    const h = canvas?.clientHeight || 360;
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("width", String(w));
    svg.setAttribute("height", String(h));
    const lines = graph.edges
      .map((edge) => {
        const a = nodeById(edge.from);
        const b = nodeById(edge.to);
        if (!a || !b) return "";
        const x1 = (a.x || 0) + 70;
        const y1 = (a.y || 0) + 28;
        const x2 = (b.x || 0) + 10;
        const y2 = (b.y || 0) + 28;
        const midX = (x1 + x2) / 2;
        const selected = selectedEdgeId === edge.id ? " is-selected" : "";
        const label = edge.condition
          ? `<text x="${midX}" y="${(y1 + y2) / 2 - 6}" class="itsm-wf-edge-label">${esc(
              edge.condition
            )}</text>`
          : "";
        return `<g class="itsm-wf-edge${selected}" data-edge-id="${esc(edge.id)}">
          <path d="M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}" />
          ${label}
        </g>`;
      })
      .join("");
    svg.innerHTML = lines;
    svg.querySelectorAll(".itsm-wf-edge").forEach((g) => {
      g.addEventListener("click", (ev) => {
        ev.stopPropagation();
        selectedEdgeId = g.getAttribute("data-edge-id");
        selectedNodeId = null;
        renderCanvas();
        renderInspector();
      });
    });
  }

  function onNodeClick(nodeId) {
    if (connectMode) {
      if (!connectFrom) {
        connectFrom = nodeId;
        renderCanvas();
        return;
      }
      if (connectFrom !== nodeId) {
        const id = `e-${connectFrom}-${nodeId}-${graph.edges.length + 1}`;
        graph.edges.push({
          id,
          from: connectFrom,
          to: nodeId,
          condition: null,
        });
        selectedEdgeId = id;
      }
      connectFrom = null;
      connectMode = false;
      $("#btnItsmWfConnect")?.classList.remove("is-active");
      renderCanvas();
      renderInspector();
      return;
    }
    selectedNodeId = nodeId;
    selectedEdgeId = null;
    renderCanvas();
    renderInspector();
  }

  function onNodeMouseDown(ev, nodeId) {
    if (!canAdmin() || connectMode) return;
    if (ev.button !== 0) return;
    const node = nodeById(nodeId);
    if (!node) return;
    dragState = {
      id: nodeId,
      ox: ev.clientX,
      oy: ev.clientY,
      sx: node.x || 0,
      sy: node.y || 0,
    };
    ev.preventDefault();
  }

  function onMouseMove(ev) {
    if (!dragState) return;
    const node = nodeById(dragState.id);
    if (!node) return;
    node.x = Math.max(8, dragState.sx + (ev.clientX - dragState.ox));
    node.y = Math.max(8, dragState.sy + (ev.clientY - dragState.oy));
    renderCanvas();
  }

  function onMouseUp() {
    dragState = null;
  }

  function renderInspector() {
    const panel = $("#itsmWfInspector");
    const hint = $("#itsmWfInspectorHint");
    if (!panel) return;
    const node = selectedNodeId ? nodeById(selectedNodeId) : null;
    if (!node && !selectedEdgeId) {
      panel.hidden = true;
      if (hint) hint.hidden = false;
      return;
    }
    if (hint) hint.hidden = true;
    panel.hidden = false;
    if (node) {
      $("#itsmWfNodeLabel").value = node.label || "";
      const isStatus = node.type === "status_change";
      const isApproval = node.type === "approval";
      $("#itsmWfCfgStatusWrap").hidden = !isStatus;
      $("#itsmWfCfgTitleWrap").hidden = !isApproval;
      $("#itsmWfCfgApproversWrap").hidden = !isApproval;
      $("#itsmWfCfgStatus").value = (node.config && node.config.status) || "";
      $("#itsmWfCfgTitle").value = (node.config && node.config.title) || "";
      $("#itsmWfCfgApprovers").value = ((node.config && node.config.approver_user_ids) || []).join(
        ", "
      );
    }
    const edge = graph.edges.find((e) => e.id === selectedEdgeId);
    $("#itsmWfEdgeCondWrap").hidden = !edge;
    if (edge) $("#itsmWfEdgeCond").value = edge.condition || "";
  }

  function applyInspector() {
    const node = selectedNodeId ? nodeById(selectedNodeId) : null;
    if (node) {
      node.label = $("#itsmWfNodeLabel")?.value?.trim() || node.type;
      node.config = node.config || {};
      if (node.type === "status_change") {
        node.config.status = $("#itsmWfCfgStatus")?.value?.trim() || "";
      }
      if (node.type === "approval") {
        node.config.title = $("#itsmWfCfgTitle")?.value?.trim() || node.label;
        const raw = $("#itsmWfCfgApprovers")?.value || "";
        node.config.approver_user_ids = raw
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }
    }
    const edge = graph.edges.find((e) => e.id === selectedEdgeId);
    if (edge) {
      const cond = $("#itsmWfEdgeCond")?.value || "";
      edge.condition = cond || null;
    }
    renderCanvas();
    deps.toast("Node/edge updated (remember Save)");
  }

  function addNode(type) {
    if (!canAdmin()) return;
    if (type === "start" && graph.nodes.some((n) => n.type === "start")) {
      deps.toast("Only one start node allowed", true);
      return;
    }
    const id = `${type}_${nodeSeq++}`;
    const x = 40 + (graph.nodes.length % 4) * 120;
    const y = 40 + Math.floor(graph.nodes.length / 4) * 90;
    const node = {
      id,
      type,
      label: type === "approval" ? "Approval" : type,
      config:
        type === "status_change"
          ? { status: "submitted" }
          : type === "approval"
            ? { title: "Approval required", approver_user_ids: [] }
            : {},
      x,
      y,
    };
    graph.nodes.push(node);
    selectedNodeId = id;
    renderCanvas();
    renderInspector();
  }

  function deleteSelectedNode() {
    if (!selectedNodeId) return;
    const node = nodeById(selectedNodeId);
    if (!node) return;
    if (node.type === "start") {
      deps.toast("Cannot delete the start node", true);
      return;
    }
    graph.nodes = graph.nodes.filter((n) => n.id !== selectedNodeId);
    graph.edges = graph.edges.filter(
      (e) => e.from !== selectedNodeId && e.to !== selectedNodeId
    );
    selectedNodeId = null;
    renderCanvas();
    renderInspector();
  }

  function deleteLastEdge() {
    if (selectedEdgeId) {
      graph.edges = graph.edges.filter((e) => e.id !== selectedEdgeId);
      selectedEdgeId = null;
    } else if (graph.edges.length) {
      graph.edges.pop();
    }
    renderCanvas();
    renderInspector();
  }

  async function loadWorkflows() {
    const list = $("#itsmWfList");
    if (!list) return;
    const params = { page: "1", page_size: "50", sort_by: "updated_at", sort_dir: "desc" };
    const q = $("#itsmWfSearch")?.value?.trim();
    if (q) params.q = q;
    try {
      const data = await SVRMON24ItsmApi.listWorkflows(params);
      const items = data.items || [];
      if (!items.length) {
        list.innerHTML = `<li class="hint">No workflows yet.</li>`;
        return;
      }
      list.innerHTML = items
        .map((wf) => {
          const active = wf.active ? "active" : "inactive";
          const sel = wf.workflow_id === selectedWorkflowId ? " is-selected" : "";
          return `<li class="itsm-wf-list-item${sel}" data-id="${esc(wf.workflow_id)}">
            <button type="button" class="itsm-wf-pick" data-id="${esc(wf.workflow_id)}">
              <strong>${esc(wf.name)}</strong>
              <span class="meta">${esc(wf.workflow_id)} · v${esc(wf.version)} · ${esc(active)} · ${esc(
                wf.applies_to
              )}</span>
            </button>
          </li>`;
        })
        .join("");
      list.querySelectorAll(".itsm-wf-pick").forEach((btn) => {
        btn.addEventListener("click", () => openWorkflow(btn.getAttribute("data-id")));
      });
    } catch (err) {
      list.innerHTML = `<li class="hint">${esc(err.message || "Failed")}</li>`;
      deps.toast(err.message || "Workflows failed", true);
    }
  }

  async function openWorkflow(workflowId) {
    try {
      const doc = await SVRMON24ItsmApi.getWorkflow(workflowId);
      selectedWorkflowId = doc.workflow_id;
      selectedNodeId = null;
      selectedEdgeId = null;
      graph = {
        nodes: (doc.graph?.nodes || []).map((n) => ({ ...n, config: n.config || {} })),
        edges: (doc.graph?.edges || []).map((e) => ({
          id: e.id || `e-${e.from}-${e.to}`,
          from: e.from,
          to: e.to,
          condition: e.condition || null,
        })),
      };
      nodeSeq = graph.nodes.length + 1;
      $("#itsmWfName").value = doc.name || "";
      $("#itsmWfAppliesTo").value = doc.applies_to || "generic";
      $("#itsmWfTrigger").value = doc.trigger || "manual";
      $("#itsmWfMeta").textContent = `${doc.workflow_id} · v${doc.version} · ${
        doc.active ? "active" : "inactive"
      }`;
      renderCanvas();
      renderInspector();
      await loadWorkflows();
      await loadExecutions();
    } catch (err) {
      deps.toast(err.message || "Load workflow failed", true);
    }
  }

  function graphPayload() {
    return {
      nodes: graph.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        label: n.label || n.type,
        config: n.config || {},
        x: n.x,
        y: n.y,
      })),
      edges: graph.edges.map((e) => ({
        id: e.id,
        from: e.from,
        to: e.to,
        condition: e.condition || null,
      })),
    };
  }

  async function saveWorkflow() {
    if (!canAdmin()) return;
    const name = $("#itsmWfName")?.value?.trim();
    if (!name) {
      deps.toast("Name is required", true);
      return;
    }
    const payload = {
      name,
      applies_to: $("#itsmWfAppliesTo")?.value || "generic",
      trigger: $("#itsmWfTrigger")?.value || "manual",
      graph: graphPayload(),
      description: null,
    };
    try {
      let doc;
      if (selectedWorkflowId) {
        doc = await SVRMON24ItsmApi.updateWorkflow(selectedWorkflowId, payload);
      } else {
        doc = await SVRMON24ItsmApi.createWorkflow({ ...payload, active: false });
        selectedWorkflowId = doc.workflow_id;
      }
      deps.toast(`Saved ${doc.workflow_id} v${doc.version}`);
      await openWorkflow(doc.workflow_id);
    } catch (err) {
      deps.toast(err.message || "Save failed", true);
    }
  }

  async function setActive(active) {
    if (!selectedWorkflowId) {
      deps.toast("Save the workflow first", true);
      return;
    }
    try {
      if (active) {
        await SVRMON24ItsmApi.publishWorkflow(selectedWorkflowId);
      } else {
        await SVRMON24ItsmApi.activateWorkflow(selectedWorkflowId, { active: false });
      }
      deps.toast(active ? "Workflow activated" : "Workflow deactivated");
      await openWorkflow(selectedWorkflowId);
    } catch (err) {
      deps.toast(err.message || "Activate failed", true);
    }
  }

  async function startExecution() {
    if (!selectedWorkflowId) {
      deps.toast("Select an active workflow", true);
      return;
    }
    const ticket_type = $("#itsmWfRunTicketType")?.value;
    const ticket_id = $("#itsmWfRunTicketId")?.value?.trim();
    if (!ticket_id) {
      deps.toast("ticket_id is required", true);
      return;
    }
    try {
      const doc = await SVRMON24ItsmApi.startWorkflow(selectedWorkflowId, {
        ticket_type,
        ticket_id,
      });
      deps.toast(`Execution ${doc.execution_id} · ${doc.status}`);
      await loadExecutions();
      await openExecution(doc.execution_id);
    } catch (err) {
      deps.toast(err.message || "Start failed", true);
    }
  }

  async function loadExecutions() {
    const list = $("#itsmWxList");
    if (!list) return;
    const params = { page: "1", page_size: "30", sort_by: "updated_at", sort_dir: "desc" };
    if (selectedWorkflowId) params.workflow_id = selectedWorkflowId;
    const ticketId = $("#itsmWxTicketId")?.value?.trim();
    if (ticketId) params.ticket_id = ticketId;
    try {
      const data = await SVRMON24ItsmApi.listWorkflowExecutions(params);
      const items = data.items || [];
      if (!items.length) {
        list.innerHTML = `<li class="hint">No executions yet.</li>`;
        return;
      }
      list.innerHTML = items
        .map(
          (ex) => `<li class="itsm-wf-list-item">
            <button type="button" class="itsm-wx-pick" data-id="${esc(ex.execution_id)}">
              <strong>${esc(ex.execution_id)}</strong>
              <span class="meta">${esc(ex.status)} · ${esc(ex.ticket_type)}/${esc(
                ex.ticket_id
              )} · ${esc(fmtWhen(ex.updated_at))}</span>
            </button>
          </li>`
        )
        .join("");
      list.querySelectorAll(".itsm-wx-pick").forEach((btn) => {
        btn.addEventListener("click", () => openExecution(btn.getAttribute("data-id")));
      });
    } catch (err) {
      list.innerHTML = `<li class="hint">${esc(err.message || "Failed")}</li>`;
    }
  }

  async function openExecution(executionId) {
    const detail = $("#itsmWxDetail");
    if (!detail) return;
    try {
      const doc = await SVRMON24ItsmApi.getWorkflowExecution(executionId);
      const history = (doc.history || [])
        .map(
          (h) =>
            `<li><strong>${esc(h.action)}</strong> @ ${esc(h.node_id)} (${esc(
              h.node_type
            )}) — ${esc(h.detail || "")}<span class="meta">${esc(h.at)}</span></li>`
        )
        .join("");
      detail.innerHTML = `
        <p><strong>${esc(doc.execution_id)}</strong> · <span class="itsm-status is-${esc(
          doc.status
        )}">${esc(doc.status)}</span></p>
        <p class="hint">${esc(doc.workflow_name || doc.workflow_id)} v${esc(
          doc.workflow_version
        )} · ticket ${esc(doc.ticket_type)}/<code>${esc(doc.ticket_id)}</code></p>
        <p class="hint">Current node: ${esc(doc.current_node_id || "—")} · Pending approval: ${esc(
          doc.pending_approval_id || "—"
        )}</p>
        ${doc.error ? `<p class="hint">Error: ${esc(doc.error)}</p>` : ""}
        <h4 class="itsm-drawer-section">History</h4>
        <ul class="itsm-activity-list">${history || "<li class='hint'>Empty</li>"}</ul>
        <div class="itsm-drawer-actions" id="itsmWxActions"></div>
      `;
      const actions = $("#itsmWxActions");
      if (actions && canAdmin() && doc.status === "running") {
        const adv = document.createElement("button");
        adv.type = "button";
        adv.className = "secondary";
        adv.textContent = "Advance";
        adv.addEventListener("click", async () => {
          try {
            const next = await SVRMON24ItsmApi.advanceWorkflowExecution(executionId, {});
            deps.toast(`Advanced → ${next.status}`);
            await openExecution(executionId);
            await loadExecutions();
          } catch (err) {
            deps.toast(err.message || "Advance failed", true);
          }
        });
        actions.appendChild(adv);
      }
      if (actions && canAdmin() && !["completed", "cancelled"].includes(doc.status)) {
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "ghost";
        cancel.textContent = "Cancel execution";
        cancel.addEventListener("click", async () => {
          try {
            await SVRMON24ItsmApi.cancelWorkflowExecution(executionId, {
              comment: "Cancelled from UI",
            });
            deps.toast("Execution cancelled");
            await openExecution(executionId);
            await loadExecutions();
          } catch (err) {
            deps.toast(err.message || "Cancel failed", true);
          }
        });
        actions.appendChild(cancel);
      }
    } catch (err) {
      detail.textContent = err.message || "Failed to load execution";
    }
  }

  function initItsmWorkflows(options) {
    deps = { ...deps, ...(options || {}) };
    applyWriteGates();
    if (!graph.nodes.length) graph = defaultGraph();
    renderCanvas();

    $("#btnNewItsmWf")?.addEventListener("click", () => resetDesigner(false));
    $("#btnSaveItsmWf")?.addEventListener("click", () => saveWorkflow());
    $("#btnActivateItsmWf")?.addEventListener("click", () => setActive(true));
    $("#btnDeactivateItsmWf")?.addEventListener("click", () => setActive(false));
    $("#btnItsmWfStart")?.addEventListener("click", () => startExecution());
    $("#btnRefreshItsmWx")?.addEventListener("click", () => loadExecutions());
    $("#itsmWfSearch")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") loadWorkflows();
    });
    document.querySelectorAll(".itsm-wf-add-node").forEach((btn) => {
      btn.addEventListener("click", () => addNode(btn.getAttribute("data-node-type")));
    });
    $("#btnItsmWfConnect")?.addEventListener("click", () => {
      connectMode = !connectMode;
      connectFrom = null;
      $("#btnItsmWfConnect")?.classList.toggle("is-active", connectMode);
      deps.toast(connectMode ? "Connect mode: click source then target" : "Connect mode off");
    });
    $("#btnItsmWfClearSel")?.addEventListener("click", () => {
      selectedNodeId = null;
      selectedEdgeId = null;
      connectFrom = null;
      renderCanvas();
      renderInspector();
    });
    $("#btnItsmWfApplyNode")?.addEventListener("click", () => applyInspector());
    $("#btnItsmWfDeleteNode")?.addEventListener("click", () => deleteSelectedNode());
    $("#btnItsmWfDeleteEdge")?.addEventListener("click", () => deleteLastEdge());
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    window.addEventListener("resize", () => renderCanvas());
  }

  function loadAll() {
    loadWorkflows();
    loadExecutions();
    renderCanvas();
  }

  global.SVRMON24ItsmWorkflows = {
    initItsmWorkflows,
    loadWorkflows: loadAll,
    applyWriteGates,
  };
})(window);
