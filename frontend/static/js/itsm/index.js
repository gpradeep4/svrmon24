/* global SVRMON24ItsmDashboard, SVRMON24ItsmIncidents, SVRMON24ItsmChanges, SVRMON24ItsmProblems */
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
      "itsm:approval:read",
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
    }

    SVRMON24ItsmIncidents.initItsmIncidents({ can, toast, escapeHtml });
    SVRMON24ItsmChanges.initItsmChanges({ can, toast, escapeHtml });
    SVRMON24ItsmProblems.initItsmProblems({ can, toast, escapeHtml });

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
      });
    }

    if (typeof onPermissionGates === "function") {
      onPermissionGates(() => {
        applyItsmNavGates(can);
        SVRMON24ItsmIncidents.applyWriteGates();
        SVRMON24ItsmChanges.applyWriteGates();
        SVRMON24ItsmProblems.applyWriteGates();
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
