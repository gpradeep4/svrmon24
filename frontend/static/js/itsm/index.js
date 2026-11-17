/* global SVRMON24ItsmDashboard, SVRMON24ItsmIncidents */
(function (global) {
  "use strict";

  function anyItsmPermission(can) {
    const keys = [
      "itsm:incident:read",
      "itsm:incident:write",
      "itsm:dashboard:read",
      "itsm:change:read",
      "itsm:problem:read",
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
        subtitle: "Open incidents and ITSM stub KPIs for the current tenant",
      };
      pageMeta["itsm-incidents"] = {
        title: "Incidents",
        subtitle: "Incident Management · activities · CMDB CI links",
      };
      pageMeta["itsm-changes"] = {
        title: "Changes",
        subtitle: "Change Management — coming in a later slice",
      };
      pageMeta["itsm-problems"] = {
        title: "Problems",
        subtitle: "Problem Management — coming in a later slice",
      };
    }

    SVRMON24ItsmIncidents.initItsmIncidents({ can, toast, escapeHtml });

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
      });
    }

    if (typeof onPermissionGates === "function") {
      onPermissionGates(() => {
        applyItsmNavGates(can);
        SVRMON24ItsmIncidents.applyWriteGates();
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
