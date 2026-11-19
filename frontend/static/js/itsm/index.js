/* global SVRMON24ItsmDashboard, SVRMON24ItsmIncidents, SVRMON24ItsmChanges, SVRMON24ItsmProblems, SVRMON24ItsmApprovals, SVRMON24ItsmWorkflows, SVRMON24ItsmSla, SVRMON24ItsmKnowledge */
(function (global) {
  "use strict";

  function anyItsmPermission(can) {
    const keys = [
      "itsm:incident:read",
      "itsm:incident:write",
      "itsm:dashboard:read",
      "itsm:change:read",
      "itsm:change:write",
      "itsm:problem:read",
      "itsm:problem:write",
      "itsm:workflow:read",
      "itsm:workflow:admin",
      "itsm:approval:read",
      "itsm:approval:decide",
      "itsm:sla:read",
      "itsm:knowledge:read",
      "itsm:notification:read",
    ];
    return keys.some((k) => can(k));
  }

  function applyItsmNavGates(can) {
    const section = document.getElementById("navItsmSection");
    const showSection = anyItsmPermission(can);
    if (section) section.hidden = !showSection;
    document.querySelectorAll("[data-itsm-nav='1']").forEach((btn) => {
      const perm = btn.getAttribute("data-itsm-perm");
      const allowed = !perm || can(perm);
      btn.hidden = !showSection || !allowed;
    });
  }

  function registerItsmHooks(hooks) {
    const {
      can,
      toast,
      escapeHtml,
      pageMeta,
      api,
      onShowTab,
      onPermissionGates,
    } = hooks || {};

    if (api && global.SVRMON24ItsmApi?.bindApi) {
      global.SVRMON24ItsmApi.bindApi(api);
    }

    if (pageMeta) {
      pageMeta["itsm-dashboard"] = {
        title: "ITSM Dashboard",
        subtitle: "Open incidents, changes, and problems for the current tenant",
      };
      pageMeta["itsm-incidents"] = {
        title: "Incidents",
        subtitle: "Create and manage incident tickets · activities · CMDB CI links",
      };
      pageMeta["itsm-changes"] = {
        title: "Changes",
        subtitle: "Change Management · status transitions · related tickets · CI links",
      };
      pageMeta["itsm-problems"] = {
        title: "Problems",
        subtitle: "Problem Management · known errors · related incidents · CI links",
      };
      pageMeta["itsm-approvals"] = {
        title: "Approvals",
        subtitle: "Manual and workflow approvals · approve / reject · ticket audit",
      };
      pageMeta["itsm-workflows"] = {
        title: "Workflow Designer",
        subtitle: "Define graphs · activate · start executions · approval gates",
      };
      pageMeta["itsm-sla"] = {
        title: "SLA",
        subtitle: "Policies · tracking · response / resolution clocks · breach view",
      };
      pageMeta["itsm-knowledge"] = {
        title: "Knowledge Base",
        subtitle: "Articles · publish / retire · related ticket and CI refs · search",
      };
    }

    SVRMON24ItsmIncidents.initItsmIncidents({ can, toast, escapeHtml });
    SVRMON24ItsmChanges.initItsmChanges({ can, toast, escapeHtml });
    SVRMON24ItsmProblems.initItsmProblems({ can, toast, escapeHtml });
    SVRMON24ItsmApprovals.initItsmApprovals({ can, toast, escapeHtml });
    SVRMON24ItsmWorkflows.initItsmWorkflows({ can, toast, escapeHtml });
    SVRMON24ItsmSla.initItsmSla({ can, toast, escapeHtml });
    SVRMON24ItsmKnowledge.initItsmKnowledge({ can, toast, escapeHtml });

    document.getElementById("btnRefreshItsmDash")?.addEventListener("click", () => {
      SVRMON24ItsmDashboard.loadItsmDashboard({ toast });
    });

    if (typeof onShowTab === "function") {
      onShowTab((name, ctx) => {
        if (!ctx?.authenticated) return;
        if (name === "itsm-dashboard") {
          SVRMON24ItsmDashboard.loadItsmDashboard({ toast });
        }
        if (name === "itsm-incidents") {
          SVRMON24ItsmIncidents.applyWriteGates();
          SVRMON24ItsmIncidents.loadIncidents();
        }
        if (name === "itsm-changes") {
          SVRMON24ItsmChanges.applyWriteGates();
          SVRMON24ItsmChanges.loadChanges();
        }
        if (name === "itsm-problems") {
          SVRMON24ItsmProblems.applyWriteGates();
          SVRMON24ItsmProblems.loadProblems();
        }
        if (name === "itsm-approvals") {
          SVRMON24ItsmApprovals.applyWriteGates();
          SVRMON24ItsmApprovals.loadApprovals();
        }
        if (name === "itsm-workflows") {
          SVRMON24ItsmWorkflows.applyWriteGates();
          SVRMON24ItsmWorkflows.loadWorkflows();
        }
        if (name === "itsm-sla") {
          SVRMON24ItsmSla.applyWriteGates();
          SVRMON24ItsmSla.setView("policies");
        }
        if (name === "itsm-knowledge") {
          SVRMON24ItsmKnowledge.applyWriteGates();
          SVRMON24ItsmKnowledge.loadArticles();
        }
      });
    }

    if (typeof onPermissionGates === "function") {
      onPermissionGates(() => {
        applyItsmNavGates(can);
        SVRMON24ItsmIncidents.applyWriteGates();
        SVRMON24ItsmChanges.applyWriteGates();
        SVRMON24ItsmProblems.applyWriteGates();
        SVRMON24ItsmApprovals.applyWriteGates();
        SVRMON24ItsmWorkflows.applyWriteGates();
        SVRMON24ItsmSla.applyWriteGates();
        SVRMON24ItsmKnowledge.applyWriteGates();
      });
    } else {
      applyItsmNavGates(can);
    }
  }

  global.SVRMON24Itsm = {
    registerItsmHooks,
    applyItsmNavGates,
    anyItsmPermission,
  };
})(window);
