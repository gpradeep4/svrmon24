/**
 * Login gate — hub graphic carries all modules; hover/focus nodes for details;
 * Option B Watch overview modal (no page-load autoplay). Vanilla only.
 */
(function () {
  const MODULES = [
    {
      id: "cmdb",
      title: "CMDB & Inventory",
      caption: "Unified view of servers, network and applications",
      seek: 0,
    },
    {
      id: "monitoring",
      title: "Monitoring",
      caption: "Health, alerts, logs and diagnostics across infrastructure",
      seek: 2,
    },
    {
      id: "itsm",
      title: "ITSM",
      caption: "Track, collaborate and resolve incidents end-to-end",
      seek: 4,
    },
    {
      id: "portal",
      title: "Service Portal",
      caption: "Request catalog services and track fulfilment",
      seek: 6,
    },
    {
      id: "secureops",
      title: "SecureOps",
      caption: "RBAC, audit trail and enterprise-grade access",
      seek: 10,
    },
    {
      id: "config",
      title: "Configuration",
      caption: "Tenant settings, live gates and platform controls",
      seek: 8,
    },
  ];

  const DEFAULT_DETAIL = {
    title: "Explore the platform",
    caption: "Hover or focus a module on the hub to see what it covers.",
  };

  function prefersReducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
      return false;
    }
  }

  function setActiveModule(moduleId, { focusNode = false } = {}) {
    const mod = MODULES.find((m) => m.id === moduleId);
    const visual = document.getElementById("loginModulesVisual");
    const titleEl = document.getElementById("loginModuleDetailTitle");
    const bodyEl = document.getElementById("loginModuleDetailBody");
    const nodes = document.querySelectorAll(".login-hub-node");
    if (!titleEl || !bodyEl) return;

    const reduce = prefersReducedMotion();
    if (!reduce && visual) visual.classList.add("is-swapping");

    const apply = () => {
      if (visual) visual.setAttribute("data-active", mod ? mod.id : "");
      nodes.forEach((el) => {
        const on = !!mod && el.dataset.module === mod.id;
        el.classList.toggle("is-active", on);
        el.setAttribute("aria-pressed", on ? "true" : "false");
      });
      titleEl.textContent = mod ? mod.title : DEFAULT_DETAIL.title;
      bodyEl.textContent = mod ? mod.caption : DEFAULT_DETAIL.caption;
      if (visual) visual.classList.remove("is-swapping");
      if (focusNode && mod) {
        document.querySelector(`.login-hub-node[data-module="${mod.id}"]`)?.focus({ preventScroll: true });
      }
    };

    if (reduce) apply();
    else setTimeout(apply, 90);
  }

  function clearActiveModule() {
    const active = document.activeElement;
    if (active && active.classList && active.classList.contains("login-hub-node")) return;
    setActiveModule(null);
  }

  function wireHotspots() {
    const nodes = Array.from(document.querySelectorAll(".login-hub-node"));
    if (!nodes.length) return;

    nodes.forEach((btn, index) => {
      btn.setAttribute("aria-pressed", "false");
      btn.addEventListener("mouseenter", () => setActiveModule(btn.dataset.module));
      btn.addEventListener("focus", () => setActiveModule(btn.dataset.module));
      btn.addEventListener("mouseleave", clearActiveModule);
      btn.addEventListener("blur", () => {
        setTimeout(clearActiveModule, 0);
      });
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        setActiveModule(btn.dataset.module, { focusNode: true });
      });
      btn.addEventListener("keydown", (e) => {
        let next = index;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (index + 1) % nodes.length;
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (index - 1 + nodes.length) % nodes.length;
        else if (e.key === "Home") next = 0;
        else if (e.key === "End") next = nodes.length - 1;
        else return;
        e.preventDefault();
        setActiveModule(nodes[next].dataset.module, { focusNode: true });
      });
    });

    document.getElementById("loginModulesVisual")?.addEventListener("mouseleave", clearActiveModule);
  }

  let lastFocus = null;

  function openOverviewModal(seekSeconds) {
    const modal = document.getElementById("loginOverviewModal");
    const video = document.getElementById("loginOverviewVideo");
    if (!modal || !video) return;
    lastFocus = document.activeElement;
    modal.hidden = false;
    modal.classList.add("is-open");
    document.getElementById("btnLoginOverviewClose")?.focus();
    try {
      video.currentTime = typeof seekSeconds === "number" ? seekSeconds : 0;
    } catch {
      /* ignore seek errors before metadata */
    }
    video.play?.().catch(() => {});
  }

  function closeOverviewModal() {
    const modal = document.getElementById("loginOverviewModal");
    const video = document.getElementById("loginOverviewVideo");
    if (!modal) return;
    modal.classList.remove("is-open");
    modal.hidden = true;
    try {
      video?.pause();
    } catch {
      /* ignore */
    }
    lastFocus?.focus?.();
  }

  function wireModal() {
    const modal = document.getElementById("loginOverviewModal");
    if (!modal) return;
    document.getElementById("btnLoginWatchOverview")?.addEventListener("click", () => openOverviewModal(0));
    document.getElementById("btnLoginOverviewClose")?.addEventListener("click", closeOverviewModal);
    modal.querySelectorAll("[data-close-overview]").forEach((el) => {
      el.addEventListener("click", closeOverviewModal);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal.classList.contains("is-open")) {
        e.preventDefault();
        closeOverviewModal();
      }
    });
  }

  function initLoginShowcase() {
    if (!document.getElementById("loginGate")) return;
    wireHotspots();
    wireModal();
    setActiveModule(null);
  }

  window.svrmonLoginShowcase = {
    setActiveModule,
    openOverviewModal,
    closeOverviewModal,
    MODULES,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLoginShowcase);
  } else {
    initLoginShowcase();
  }
})();
