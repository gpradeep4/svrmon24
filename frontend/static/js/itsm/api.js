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
  };
})(window);
