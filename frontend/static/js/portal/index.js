/* Service Portal FE — sidebar gates + stub meta (SP1); catalog+ in SP2+. */
(function (global) {
  "use strict";

  function anyPortalPermission(can) {
    const keys = [
      "sp:catalog:read",
      "sp:catalog:admin",
      "sp:request:create",
      "sp:request:read",
      "sp:request:cancel",
      "sp:approval:read",
      "sp:approval:decide",
      "sp:approval:high-risk",
      "sp:execution:read",
      "sp:execution:run",
      "sp:admin",
    ];
    return keys.some((k) => can(k));
  }

  function applyPortalNavGates(can) {
    const section = document.getElementById("navPortalSection");
    const group = document.getElementById("navPortalGroup");
    const showSection = anyPortalPermission(can);
    if (section) section.hidden = !showSection;
    if (group) group.hidden = !showSection;
    document.querySelectorAll("[data-portal-nav='1']").forEach((btn) => {
      const perm = btn.getAttribute("data-portal-perm");
      const allowed = !perm || can(perm);
      btn.hidden = !showSection || !allowed;
    });
  }

  async function loadPortalMeta(api, toast) {
    if (!api) return null;
    try {
      const meta = await api("/api/portal/meta");
      const banner = document.getElementById("spCatalogBanner");
      if (banner && meta?.banner) banner.textContent = meta.banner;
      const stub = document.getElementById("spCatalogStub");
      if (stub && meta?.domains) {
        stub.textContent =
          `Domains: ${meta.domains.join(", ")}. Collect modes: ${(meta.collect_modes || []).join(", ")}. ` +
          `DB: ${meta.itsm_database || meta.database || "—"}. Live exec: ${meta.live_exec ? "on" : "off"}.`;
      }
      return meta;
    } catch (err) {
      if (toast) toast(err.message || "Portal meta failed", true);
      return null;
    }
  }

  function registerPortalHooks(hooks) {
    const { can, toast, pageMeta, api, onShowTab, onPermissionGates, showTab } =
      hooks || {};

    if (api && global.SVRMON24PortalCatalog?.bindApi) {
      global.SVRMON24PortalCatalog.bindApi(api, { toast, showTab });
      global.SVRMON24PortalCatalog.initCatalogUi();
    }
    if (api && global.SVRMON24PortalRequests?.bindApi) {
      global.SVRMON24PortalRequests.bindApi(api, { toast, showTab });
    }

    if (pageMeta) {
      pageMeta["sp-catalog"] = {
        title: "Service Portal Catalog",
        subtitle: "Allowlisted ops tasks · SIMULATED execution default",
      };
      pageMeta["sp-request-new"] = {
        title: "New request",
        subtitle: "Typed form · CI / cloud target · collect mode",
      };
      pageMeta["sp-my-requests"] = {
        title: "My requests",
        subtitle: "Status · approvals · CMDB sync",
      };
      pageMeta["sp-approvals"] = {
        title: "Change status",
        subtitle: "ITSM Change SoT · mirror status · open in ITSM",
      };
      pageMeta["sp-executions"] = {
        title: "Execution history",
        subtitle: "AGENT / AGENTLESS · SIMULATED until live unlock",
      };
      pageMeta["sp-catalog-admin"] = {
        title: "Catalog admin",
        subtitle: "Items · schemas · policies · CMDB field maps",
      };
    }

    document
      .querySelector('[data-tab="sp-catalog"]')
      ?.addEventListener("click", () => {
        loadPortalMeta(api, toast);
        global.SVRMON24PortalCatalog?.onShowTab?.("sp-catalog");
      });
    document
      .querySelector('[data-tab="sp-catalog-admin"]')
      ?.addEventListener("click", () => {
        global.SVRMON24PortalCatalog?.onShowTab?.("sp-catalog-admin");
      });
    document
      .querySelector('[data-tab="sp-my-requests"]')
      ?.addEventListener("click", () => {
        global.SVRMON24PortalRequests?.onShowTab?.("sp-my-requests");
      });
    if (typeof onShowTab === "function") {
      onShowTab((name, ctx) => {
        if (!ctx?.authenticated) return;
        if (name === "sp-catalog") {
          loadPortalMeta(api, toast);
        }
        global.SVRMON24PortalCatalog?.onShowTab?.(name);
        global.SVRMON24PortalRequests?.onShowTab?.(name);
      });
    }

    if (typeof onPermissionGates === "function") {
      onPermissionGates(() => applyPortalNavGates(can));
    } else if (typeof can === "function") {
      applyPortalNavGates(can);
    }

    // Deep-link helper for later slices (Catalog → Request form).
    if (typeof showTab === "function") {
      global.SvrmonPortalShowTab = showTab;
    }
  }

  global.SVRMON24Portal = {
    registerPortalHooks,
    applyPortalNavGates,
    anyPortalPermission,
    loadPortalMeta,
  };
  global.SvrmonPortal = global.SVRMON24Portal;
})(typeof window !== "undefined" ? window : globalThis);
