(function (global) {
  "use strict";

  let request = null;

  function bindApi(apiFn) {
    request = apiFn;
  }

  async function itsmGet(path) {
    if (!request) throw new Error("ITSM API not bound");
    return request(`/api/itsm${path}`);
  }

  async function itsmSend(path, method, body) {
    if (!request) throw new Error("ITSM API not bound");
    return request(`/api/itsm${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  global.SVRMON24ItsmApi = {
    bindApi,
    dashboardSummary: () => itsmGet("/dashboard/summary"),
    listIncidents: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/incidents?${q.toString()}`);
    },
    getIncident: (id) => itsmGet(`/incidents/${encodeURIComponent(id)}`),
    createIncident: (payload) => itsmSend("/incidents", "POST", payload),
    updateIncident: (id, payload) =>
      itsmSend(`/incidents/${encodeURIComponent(id)}`, "PATCH", payload),
    transitionIncident: (id, payload) =>
      itsmSend(`/incidents/${encodeURIComponent(id)}/transition`, "POST", payload),
    addCiLink: (id, componentId) =>
      itsmSend(`/incidents/${encodeURIComponent(id)}/ci-links`, "POST", {
        component_id: componentId,
      }),
    removeCiLink: (id, componentId) =>
      itsmSend(
        `/incidents/${encodeURIComponent(id)}/ci-links/${encodeURIComponent(componentId)}`,
        "DELETE"
      ),
    listChanges: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/changes?${q.toString()}`);
    },
    getChange: (id) => itsmGet(`/changes/${encodeURIComponent(id)}`),
    createChange: (payload) => itsmSend("/changes", "POST", payload),
    updateChange: (id, payload) =>
      itsmSend(`/changes/${encodeURIComponent(id)}`, "PATCH", payload),
    transitionChange: (id, payload) =>
      itsmSend(`/changes/${encodeURIComponent(id)}/transition`, "POST", payload),
    addChangeCiLink: (id, componentId) =>
      itsmSend(`/changes/${encodeURIComponent(id)}/ci-links`, "POST", {
        component_id: componentId,
      }),
    removeChangeCiLink: (id, componentId) =>
      itsmSend(
        `/changes/${encodeURIComponent(id)}/ci-links/${encodeURIComponent(componentId)}`,
        "DELETE"
      ),
    listProblems: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/problems?${q.toString()}`);
    },
    getProblem: (id) => itsmGet(`/problems/${encodeURIComponent(id)}`),
    createProblem: (payload) => itsmSend("/problems", "POST", payload),
    updateProblem: (id, payload) =>
      itsmSend(`/problems/${encodeURIComponent(id)}`, "PATCH", payload),
    transitionProblem: (id, payload) =>
      itsmSend(`/problems/${encodeURIComponent(id)}/transition`, "POST", payload),
    addProblemCiLink: (id, componentId) =>
      itsmSend(`/problems/${encodeURIComponent(id)}/ci-links`, "POST", {
        component_id: componentId,
      }),
    removeProblemCiLink: (id, componentId) =>
      itsmSend(
        `/problems/${encodeURIComponent(id)}/ci-links/${encodeURIComponent(componentId)}`,
        "DELETE"
      ),
    listActivities: (ticketType, ticketId) =>
      itsmGet(
        `/${encodeURIComponent(ticketType)}/${encodeURIComponent(ticketId)}/activities?page=1&page_size=50`
      ),
    postComment: (ticketType, ticketId, message) =>
      itsmSend(
        `/${encodeURIComponent(ticketType)}/${encodeURIComponent(ticketId)}/activities`,
        "POST",
        { message, activity_type: "comment", visibility: "public" }
      ),
    listApprovals: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/approvals?${q.toString()}`);
    },
    getApproval: (id) => itsmGet(`/approvals/${encodeURIComponent(id)}`),
    createApproval: (payload) => itsmSend("/approvals", "POST", payload),
    updateApproval: (id, payload) =>
      itsmSend(`/approvals/${encodeURIComponent(id)}`, "PATCH", payload),
    decideApproval: (id, payload) =>
      itsmSend(`/approvals/${encodeURIComponent(id)}/decide`, "POST", payload),
    cancelApproval: (id, payload) =>
      itsmSend(`/approvals/${encodeURIComponent(id)}/cancel`, "POST", payload || {}),
    listWorkflows: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/workflows?${q.toString()}`);
    },
    getWorkflow: (id) => itsmGet(`/workflows/${encodeURIComponent(id)}`),
    createWorkflow: (payload) => itsmSend("/workflows", "POST", payload),
    updateWorkflow: (id, payload) =>
      itsmSend(`/workflows/${encodeURIComponent(id)}`, "PATCH", payload),
    activateWorkflow: (id, payload) =>
      itsmSend(`/workflows/${encodeURIComponent(id)}/activate`, "POST", payload),
    publishWorkflow: (id) =>
      itsmSend(`/workflows/${encodeURIComponent(id)}/publish`, "POST", {}),
    startWorkflow: (id, payload) =>
      itsmSend(`/workflows/${encodeURIComponent(id)}/start`, "POST", payload),
    listWorkflowExecutions: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/workflow-executions?${q.toString()}`);
    },
    getWorkflowExecution: (id) =>
      itsmGet(`/workflow-executions/${encodeURIComponent(id)}`),
    advanceWorkflowExecution: (id, payload) =>
      itsmSend(
        `/workflow-executions/${encodeURIComponent(id)}/advance`,
        "POST",
        payload || {}
      ),
    cancelWorkflowExecution: (id, payload) =>
      itsmSend(
        `/workflow-executions/${encodeURIComponent(id)}/cancel`,
        "POST",
        payload || {}
      ),
    listSlaPolicies: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/sla/policies?${q.toString()}`);
    },
    getSlaPolicy: (id) => itsmGet(`/sla/policies/${encodeURIComponent(id)}`),
    createSlaPolicy: (payload) => itsmSend("/sla/policies", "POST", payload),
    updateSlaPolicy: (id, payload) =>
      itsmSend(`/sla/policies/${encodeURIComponent(id)}`, "PATCH", payload),
    listSlaTracking: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/sla/tracking?${q.toString()}`);
    },
    getSlaTracking: (id) => itsmGet(`/sla/tracking/${encodeURIComponent(id)}`),
    slaSummary: (ticketType, ticketId) =>
      itsmGet(
        `/sla/summary/${encodeURIComponent(ticketType)}/${encodeURIComponent(ticketId)}`
      ),
    listKnowledgeArticles: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/knowledge/articles?${q.toString()}`);
    },
    getKnowledgeArticle: (id) =>
      itsmGet(`/knowledge/articles/${encodeURIComponent(id)}`),
    createKnowledgeArticle: (payload) =>
      itsmSend("/knowledge/articles", "POST", payload),
    updateKnowledgeArticle: (id, payload) =>
      itsmSend(`/knowledge/articles/${encodeURIComponent(id)}`, "PATCH", payload),
    transitionKnowledgeArticle: (id, payload) =>
      itsmSend(
        `/knowledge/articles/${encodeURIComponent(id)}/transition`,
        "POST",
        payload
      ),
    listKnowledgeActivities: (id) =>
      itsmGet(
        `/knowledge/articles/${encodeURIComponent(id)}/activities?page=1&page_size=50`
      ),
    suggestKnowledgeArticles: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/knowledge/articles/suggest?${q.toString()}`);
    },
  };
})(window);
