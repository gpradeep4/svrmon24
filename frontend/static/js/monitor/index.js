/* global SVRMON24MonitorDashboard */
(function (global) {
  "use strict";

  function anyMonitorPermission(can) {
    const keys = [
      "monitor:dashboard:read",
      "monitor:targets:read",
      "monitor:targets:write",
      "monitor:logs:read",
      "monitor:logs:write",
      "monitor:files:read",
      "monitor:alerts:read",
      "monitor:alerts:write",
      "monitor:admin",
      "file_monitoring:read",
      "diagnostics:read",
      "diagnostics:run",
    ];
    return keys.some((k) => can(k));
  }

  function permAllowed(can, btn) {
    const tab = btn.getAttribute("data-tab") || "";
    if (tab === "file-monitoring") {
      return can("file_monitoring:read") || can("monitor:files:read");
    }
    if (tab === "diagnostics") {
      return can("diagnostics:read") || can("diagnostics:run");
    }
    const perm = btn.getAttribute("data-monitor-perm");
    if (!perm) return true;
    return can(perm);
  }

  function applyMonitorNavGates(can) {
    const section = document.getElementById("navMonitoringSection");
    const group = document.getElementById("navMonitoringGroup");
    const showSection = anyMonitorPermission(can);
    if (section) section.hidden = !showSection;
    if (group) group.hidden = !showSection;
    document.querySelectorAll("[data-monitor-nav='1']").forEach((btn) => {
      const allowed = permAllowed(can, btn);
      btn.hidden = !showSection || !allowed;
    });
    // CMDB transition stubs stay visible when the target module is reachable.
    document.querySelectorAll("[data-cmdb-monitor-redirect]").forEach((btn) => {
      const target = btn.getAttribute("data-cmdb-monitor-redirect");
      let allowed = true;
      if (target === "file-monitoring") {
        allowed = can("file_monitoring:read") || can("monitor:files:read");
      } else if (target === "diagnostics") {
        allowed = can("diagnostics:read") || can("diagnostics:run");
      }
      btn.hidden = !allowed;
    });
  }

  function registerMonitorHooks(hooks) {
    const { can, toast, pageMeta, api, onShowTab, onPermissionGates } = hooks || {};

    if (api && global.SVRMON24MonitorDashboard?.bindApi) {
      global.SVRMON24MonitorDashboard.bindApi(api, { toast });
    }

    if (pageMeta) {
      pageMeta["monitor-dashboard"] = {
        title: "Monitoring Dashboard",
        subtitle: "SIMULATED health overview — live probes off",
      };
      pageMeta["monitor-servers"] = {
        title: "Servers (Monitoring)",
        subtitle: "Placeholder — SIMULATED server health (later slice)",
      };
      pageMeta["monitor-network"] = {
        title: "Network (Monitoring)",
        subtitle: "Placeholder — SIMULATED network health (later slice)",
      };
      pageMeta["monitor-applications"] = {
        title: "Applications (Monitoring)",
        subtitle: "Placeholder — SIMULATED application health (later slice)",
      };
      pageMeta["monitor-databases"] = {
        title: "Databases (Monitoring)",
        subtitle: "Placeholder — SIMULATED database health (later slice)",
      };
      pageMeta["monitor-logs"] = {
        title: "Logs",
        subtitle: "Placeholder — SIMULATED log streams (later slice)",
      };
      pageMeta["monitor-alerts"] = {
        title: "Alerts",
        subtitle: "Placeholder — SIMULATED alert rules / instances (later slice)",
      };
      pageMeta["cmdb-redirect-file-monitoring"] = {
        title: "File Monitoring moved",
        subtitle: "Rehomed under Monitoring — use the Open button below",
      };
      pageMeta["cmdb-redirect-diagnostics"] = {
        title: "Diagnostics moved",
        subtitle: "Rehomed under Monitoring — use the Open button below",
      };
    }

    document.getElementById("btnRefreshMonitorDash")?.addEventListener("click", () => {
      SVRMON24MonitorDashboard.loadMonitorDashboard({ toast });
    });

    document.querySelectorAll("[data-open-monitor-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.getAttribute("data-open-monitor-tab");
        if (tab && typeof hooks.showTab === "function") {
          hooks.showTab(tab);
        } else if (tab && global.SVRMON24ItsmRouting?.navigateTo) {
          global.SVRMON24ItsmRouting.navigateTo({ tab });
        } else if (tab) {
          const nav = document.querySelector(`.nav-item[data-tab="${tab}"]`);
          nav?.click();
        }
      });
    });

    if (typeof onShowTab === "function") {
      onShowTab((name, ctx) => {
        if (!ctx?.authenticated) return;
        if (name === "monitor-dashboard") {
          SVRMON24MonitorDashboard.loadMonitorDashboard({ toast });
        }
      });
    }

    if (typeof onPermissionGates === "function") {
      onPermissionGates(() => applyMonitorNavGates(can));
    } else if (typeof can === "function") {
      applyMonitorNavGates(can);
    }
  }

  global.SVRMON24Monitor = {
    registerMonitorHooks,
    applyMonitorNavGates,
    anyMonitorPermission,
  };
})(window);
