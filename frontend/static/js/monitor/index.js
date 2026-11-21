/* global SVRMON24MonitorDashboard, SVRMON24MonitorTargets, SVRMON24MonitorLogs, SVRMON24MonitorAlerts */
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

  function applyMonitorActionGates(can) {
    document.querySelectorAll("[data-monitor-perm-write]").forEach((btn) => {
      const perm = btn.getAttribute("data-monitor-perm-write");
      if (perm) btn.hidden = !can(perm);
    });
    document.querySelectorAll("[data-monitor-perm-admin]").forEach((btn) => {
      const perm = btn.getAttribute("data-monitor-perm-admin");
      if (perm) btn.hidden = !can(perm);
    });
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
    applyMonitorActionGates(can);
  }

  function registerMonitorHooks(hooks) {
    const { can, toast, pageMeta, api, onShowTab, onPermissionGates } = hooks || {};

    if (api && global.SVRMON24MonitorDashboard?.bindApi) {
      global.SVRMON24MonitorDashboard.bindApi(api, { toast });
    }
    if (api && global.SVRMON24MonitorTargets?.bindApi) {
      global.SVRMON24MonitorTargets.bindApi(api, { toast, can });
      global.SVRMON24MonitorTargets.initTargetsUi();
    }
    if (api && global.SVRMON24MonitorLogs?.bindApi) {
      global.SVRMON24MonitorLogs.bindApi(api, { toast, can });
      global.SVRMON24MonitorLogs.initLogsUi();
    }
    if (api && global.SVRMON24MonitorAlerts?.bindApi) {
      global.SVRMON24MonitorAlerts.bindApi(api, { toast, can });
      global.SVRMON24MonitorAlerts.initAlertsUi();
    }

    if (pageMeta) {
      pageMeta["monitor-dashboard"] = {
        title: "Monitoring Dashboard",
        subtitle: "SIMULATED aggregates · targets · alerts · logs/files",
      };
      pageMeta["monitor-servers"] = {
        title: "Servers (Monitoring)",
        subtitle: "SIMULATED server health · sync from CMDB",
      };
      pageMeta["monitor-network"] = {
        title: "Network (Monitoring)",
        subtitle: "SIMULATED network kinds · sync from CMDB",
      };
      pageMeta["monitor-applications"] = {
        title: "Applications (Monitoring)",
        subtitle: "SIMULATED application health · sync from CMDB",
      };
      pageMeta["monitor-databases"] = {
        title: "Databases (Monitoring)",
        subtitle: "SIMULATED database health · sync from CMDB",
      };
      pageMeta["monitor-logs"] = {
        title: "Logs",
        subtitle: "SIMULATED log streams · search · no live ingest",
      };
      pageMeta["monitor-alerts"] = {
        title: "Alerts",
        subtitle: "SIMULATED rules · ack/resolve · draft incident Apply via ITSM",
      };
    }

    document.getElementById("btnRefreshMonitorDash")?.addEventListener("click", () => {
      SVRMON24MonitorDashboard.loadMonitorDashboard({ toast });
    });

    if (typeof onShowTab === "function") {
      onShowTab((name, ctx) => {
        if (!ctx?.authenticated) return;
        if (name === "monitor-dashboard") {
          SVRMON24MonitorDashboard.loadMonitorDashboard({ toast });
        }
        if (global.SVRMON24MonitorTargets?.onShowTab) {
          global.SVRMON24MonitorTargets.onShowTab(name);
        }
        if (global.SVRMON24MonitorLogs?.onShowTab) {
          global.SVRMON24MonitorLogs.onShowTab(name);
        }
        if (global.SVRMON24MonitorAlerts?.onShowTab) {
          global.SVRMON24MonitorAlerts.onShowTab(name);
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
    applyMonitorActionGates,
    anyMonitorPermission,
  };
})(window);
