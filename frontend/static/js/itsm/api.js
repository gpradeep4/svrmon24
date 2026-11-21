(function (global) {
  "use strict";

  let request = null;
  let downloadFn = null;

  function bindApi(apiFn, helpers) {
    request = apiFn;
    if (helpers && typeof helpers.downloadBinary === "function") {
      downloadFn = helpers.downloadBinary;
    }
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

  async function downloadBinary(path, fallbackFilename) {
    if (!downloadFn) throw new Error("ITSM download helper not bound");
    return downloadFn(`/api/itsm${path}`, fallbackFilename);
  }

  global.SVRMON24ItsmApi = {
    bindApi,
    downloadBinary,
    dashboardSummary: (params) => {
      const q = new URLSearchParams(params || {});
      const suffix = q.toString() ? `?${q.toString()}` : "";
      return itsmGet(`/dashboard/summary${suffix}`);
    },
    dashboardReports: (params) => {
      const q = new URLSearchParams(params || {});
      const suffix = q.toString() ? `?${q.toString()}` : "";
      return itsmGet(`/dashboard/reports${suffix}`);
    },
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
    previewKnowledgeBody: (payload) =>
      itsmSend("/knowledge/articles/preview", "POST", payload),
    listNotifications: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/notifications?${q.toString()}`);
    },
    getNotification: (id) =>
      itsmGet(`/notifications/${encodeURIComponent(id)}`),
    notificationUnreadCount: () => itsmGet("/notifications/unread-count"),
    markNotificationRead: (id) =>
      itsmSend(`/notifications/${encodeURIComponent(id)}/read`, "POST"),
    markNotificationUnread: (id) =>
      itsmSend(`/notifications/${encodeURIComponent(id)}/unread`, "POST"),
    markNotificationArchive: (id) =>
      itsmSend(`/notifications/${encodeURIComponent(id)}/archive`, "POST"),
    listNotificationChannels: () => itsmGet("/notifications/channels"),
    getNotificationChannel: (channel) =>
      itsmGet(`/notifications/channels/${encodeURIComponent(channel)}`),
    putNotificationChannelEmail: (payload) =>
      itsmSend("/notifications/channels/email", "PUT", payload),
    putNotificationChannelSms: (payload) =>
      itsmSend("/notifications/channels/sms", "PUT", payload),
    putNotificationChannelSlack: (payload) =>
      itsmSend("/notifications/channels/slack", "PUT", payload),
    listNotificationDeliveries: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/notifications/deliveries?${q.toString()}`);
    },
    listReportDefinitions: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/reports/definitions?${q.toString()}`);
    },
    getReportDefinition: (id) =>
      itsmGet(`/reports/definitions/${encodeURIComponent(id)}`),
    createReportDefinition: (payload) =>
      itsmSend("/reports/definitions", "POST", payload),
    updateReportDefinition: (id, payload) =>
      itsmSend(`/reports/definitions/${encodeURIComponent(id)}`, "PATCH", payload),
    deleteReportDefinition: (id) =>
      itsmSend(`/reports/definitions/${encodeURIComponent(id)}`, "DELETE"),
    runReportDefinition: (id) =>
      itsmSend(`/reports/definitions/${encodeURIComponent(id)}/run`, "POST"),
    listReportSchedules: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/reports/schedules?${q.toString()}`);
    },
    getReportSchedule: (id) =>
      itsmGet(`/reports/schedules/${encodeURIComponent(id)}`),
    createReportSchedule: (payload) =>
      itsmSend("/reports/schedules", "POST", payload),
    updateReportSchedule: (id, payload) =>
      itsmSend(`/reports/schedules/${encodeURIComponent(id)}`, "PATCH", payload),
    deleteReportSchedule: (id) =>
      itsmSend(`/reports/schedules/${encodeURIComponent(id)}`, "DELETE"),
    runReportSchedule: (id) =>
      itsmSend(`/reports/schedules/${encodeURIComponent(id)}/run`, "POST"),
    listReportScheduleRuns: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/reports/schedules/runs?${q.toString()}`);
    },
    listAssignmentGroups: (params) => {
      const q = new URLSearchParams(params || {});
      return itsmGet(`/assignment-groups?${q.toString()}`);
    },
    assignmentGroupPicker: () => itsmGet("/assignment-groups/picker"),
    getAssignmentGroup: (id) =>
      itsmGet(`/assignment-groups/${encodeURIComponent(id)}`),
    createAssignmentGroup: (payload) =>
      itsmSend("/assignment-groups", "POST", payload),
    updateAssignmentGroup: (id, payload) =>
      itsmSend(`/assignment-groups/${encodeURIComponent(id)}`, "PATCH", payload),
    deleteAssignmentGroup: (id) =>
      itsmSend(`/assignment-groups/${encodeURIComponent(id)}`, "DELETE"),
    listAttachments: (ticketType, ticketId) =>
      itsmGet(
        `/${encodeURIComponent(ticketType)}/${encodeURIComponent(ticketId)}/attachments`
      ),
    uploadAttachment: async (ticketType, ticketId, file) => {
      if (!request) throw new Error("ITSM API not bound");
      const form = new FormData();
      form.append("file", file, file.name || "attachment.bin");
      return request(
        `/api/itsm/${encodeURIComponent(ticketType)}/${encodeURIComponent(ticketId)}/attachments`,
        { method: "POST", body: form }
      );
    },
    deleteAttachment: (attachmentId) =>
      itsmSend(`/attachments/${encodeURIComponent(attachmentId)}`, "DELETE"),
    attachmentContentUrl: (attachmentId) =>
      `/api/itsm/attachments/${encodeURIComponent(attachmentId)}/content`,
  };
})(window);
