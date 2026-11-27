/**
 * Login gate — interactive hub showcase (vanilla).
 * Config-driven modules; hover/focus details; Option B Watch overview.
 * No auth/API changes.
 */
(function () {
  /** Central module config — source of truth for hub interactions. */
  const MODULES = [
    {
      id: "cmdb",
      label: "CMDB",
      title: "CMDB & Inventory",
      blurb: "Unified view of servers, networks and applications",
      tone: "indigo",
      seek: 0,
      bullets: [
        "Centralised infrastructure inventory",
        "Manage servers, operating systems, middleware, databases and applications",
        "Visualise infrastructure relationships and dependencies",
        "Maintain configuration item information",
      ],
    },
    {
      id: "monitoring",
      label: "Monitoring",
      title: "Infrastructure Monitoring",
      blurb: "Health, alerts and performance across infrastructure",
      tone: "violet",
      seek: 2,
      bullets: [
        "Monitor server and infrastructure health",
        "CPU, memory, disk and network utilisation",
        "Infrastructure availability and performance",
        "Alert and event visibility",
      ],
    },
    {
      id: "itsm",
      label: "ITSM",
      title: "IT Service Management",
      blurb: "Incidents, changes and ticket lifecycle end-to-end",
      tone: "blue",
      seek: 4,
      bullets: [
        "Incident Management",
        "Change Management",
        "Problem Management",
        "Service requests and ticket lifecycle management",
      ],
    },
    {
      id: "portal",
      label: "Service Portal",
      title: "Self-Service Portal",
      blurb: "Request catalog services and track fulfilment",
      tone: "sky",
      seek: 6,
      bullets: [
        "Centralised service request portal",
        "Submit and track service requests",
        "View incidents and request status",
        "Access service catalogue and knowledge resources",
      ],
    },
    {
      id: "secureops",
      label: "SecureOps",
      title: "Security and Compliance",
      blurb: "RBAC, audit trail and enterprise-grade access",
      tone: "purple",
      seek: 10,
      bullets: [
        "Role-based access control",
        "Audit trail and activity tracking",
        "Security visibility and compliance",
        "Secure infrastructure access",
      ],
    },
    {
      id: "config",
      label: "Configuration",
      title: "Platform Configuration",
      blurb: "Tenant settings, live gates and platform controls",
      tone: "lilac",
      seek: 8,
      bullets: [
        "Configure integrations and platform settings",
        "Manage users, groups and roles",
        "Configure diagnostic scripts and workflows",
        "Manage tenant-level settings",
      ],
    },
  ];

  const DEFAULT_MODULE = "cmdb";
  let activeId = DEFAULT_MODULE;
  let swapTimer = null;

  function prefersReducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
      return false;
    }
  }

  function findModule(id) {
    return MODULES.find((m) => m.id === id) || MODULES.find((m) => m.id === DEFAULT_MODULE);
  }

  function setActiveModule(moduleId, { focusNode = false, force = false } = {}) {
    const mod = findModule(moduleId);
    if (!mod) return;
    if (!force && mod.id === activeId && !focusNode) {
      // still refresh aria/pressed state
    }
    activeId = mod.id;

    const visual = document.getElementById("loginModulesVisual");
    const panel = document.getElementById("loginModuleDetail");
    const titleEl = document.getElementById("loginModuleDetailTitle");
    const bodyEl = document.getElementById("loginModuleDetailBody");
    const listEl = document.getElementById("loginModuleDetailBullets");
    const iconEl = document.getElementById("loginModuleDetailIcon");
    const nodes = document.querySelectorAll(".login-hub-node");
    const spokes = document.querySelectorAll(".login-hub-spokes path");
    if (!titleEl || !bodyEl || !listEl) return;

    const reduce = prefersReducedMotion();
    const apply = () => {
      if (visual) {
        visual.setAttribute("data-active", mod.id);
        visual.classList.add("has-selection");
      }
      nodes.forEach((el) => {
        const on = el.dataset.module === mod.id;
        el.classList.toggle("is-active", on);
        el.setAttribute("aria-pressed", on ? "true" : "false");
        el.tabIndex = on ? 0 : -1;
      });
      spokes.forEach((curve) => {
        const on = curve.dataset.module === mod.id;
        curve.classList.toggle("is-active", on);
      });
      titleEl.textContent = mod.title;
      bodyEl.textContent = mod.blurb;
      listEl.innerHTML = mod.bullets.map((b) => `<li>${b}</li>`).join("");
      if (iconEl) {
        const src = document.querySelector(`.login-hub-node[data-module="${mod.id}"] .login-hub-node-ico`);
        iconEl.innerHTML = src ? src.innerHTML : "";
        iconEl.dataset.tone = mod.tone;
      }
      if (panel) {
        panel.dataset.module = mod.id;
        panel.dataset.tone = mod.tone;
        panel.classList.remove("is-swapping");
      }
      if (visual) visual.classList.remove("is-swapping");
      if (focusNode) {
        document.querySelector(`.login-hub-node[data-module="${mod.id}"]`)?.focus({ preventScroll: true });
      }
    };

    if (swapTimer) clearTimeout(swapTimer);
    if (reduce) {
      apply();
      return;
    }
    if (panel) panel.classList.add("is-swapping");
    if (visual) visual.classList.add("is-swapping");
    swapTimer = setTimeout(apply, 240);
  }

  function resetToDefault() {
    setActiveModule(DEFAULT_MODULE, { force: true });
  }

  function isInsideShowcase(node) {
    const showcase = document.getElementById("loginModulesVisual");
    return !!(showcase && node && showcase.contains(node));
  }

  function wireHotspots() {
    const nodes = Array.from(document.querySelectorAll(".login-hub-node"));
    const showcase = document.getElementById("loginModulesVisual");
    if (!nodes.length || !showcase) return;

    // Map spokes to modules by data-module on lines (set in HTML)
    nodes.forEach((btn, index) => {
      btn.setAttribute("aria-pressed", btn.dataset.module === DEFAULT_MODULE ? "true" : "false");
      btn.tabIndex = btn.dataset.module === DEFAULT_MODULE ? 0 : -1;

      btn.addEventListener("mouseenter", () => setActiveModule(btn.dataset.module));
      btn.addEventListener("focus", () => setActiveModule(btn.dataset.module));
      btn.addEventListener("pointerdown", () => setActiveModule(btn.dataset.module));

      btn.addEventListener("click", (e) => {
        e.preventDefault();
        setActiveModule(btn.dataset.module, { focusNode: true });
        openModuleIntro(btn.dataset.module);
      });

      btn.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setActiveModule(btn.dataset.module, { focusNode: true });
          openModuleIntro(btn.dataset.module);
          return;
        }
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

    // Sticky into description; reset only when leaving entire showcase
    showcase.addEventListener("mouseleave", (e) => {
      if (isInsideShowcase(e.relatedTarget)) return;
      resetToDefault();
    });
    showcase.addEventListener("focusout", (e) => {
      if (isInsideShowcase(e.relatedTarget)) return;
      // Defer so click/focus within panel can settle
      setTimeout(() => {
        if (!isInsideShowcase(document.activeElement)) resetToDefault();
      }, 0);
    });
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
      /* ignore */
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

  function openModuleIntro(moduleId) {
    const mod = findModule(moduleId);
    const dialog = document.getElementById("loginModuleIntro");
    if (!dialog || !mod) {
      openOverviewModal(mod?.seek ?? 0);
      return;
    }
    lastFocus = document.activeElement;
    const title = document.getElementById("loginModuleIntroTitle");
    const blurb = document.getElementById("loginModuleIntroBlurb");
    const list = document.getElementById("loginModuleIntroBullets");
    const icon = document.getElementById("loginModuleIntroIcon");
    if (title) title.textContent = mod.title;
    if (blurb) blurb.textContent = mod.blurb;
    if (list) list.innerHTML = mod.bullets.map((b) => `<li>${b}</li>`).join("");
    if (icon) {
      const src = document.querySelector(`.login-hub-node[data-module="${mod.id}"] .login-hub-node-ico`);
      icon.innerHTML = src ? src.innerHTML : "";
    }
    dialog.hidden = false;
    dialog.classList.add("is-open");
    dialog.dataset.module = mod.id;
    document.getElementById("btnLoginModuleIntroClose")?.focus();
  }

  function closeModuleIntro() {
    const dialog = document.getElementById("loginModuleIntro");
    if (!dialog) return;
    dialog.classList.remove("is-open");
    dialog.hidden = true;
    lastFocus?.focus?.();
  }

  function wireModal() {
    const overview = document.getElementById("loginOverviewModal");
    document.getElementById("btnLoginWatchOverview")?.addEventListener("click", () => openOverviewModal(0));
    document.getElementById("btnLoginOverviewClose")?.addEventListener("click", closeOverviewModal);
    overview?.querySelectorAll("[data-close-overview]").forEach((el) => {
      el.addEventListener("click", closeOverviewModal);
    });

    const intro = document.getElementById("loginModuleIntro");
    document.getElementById("btnLoginModuleIntroClose")?.addEventListener("click", closeModuleIntro);
    document.getElementById("btnLoginModuleIntroWatch")?.addEventListener("click", () => {
      const mod = findModule(intro?.dataset.module || activeId);
      closeModuleIntro();
      openOverviewModal(mod?.seek ?? 0);
    });
    intro?.querySelectorAll("[data-close-intro]").forEach((el) => {
      el.addEventListener("click", closeModuleIntro);
    });

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (intro?.classList.contains("is-open")) {
        e.preventDefault();
        closeModuleIntro();
        return;
      }
      if (overview?.classList.contains("is-open")) {
        e.preventDefault();
        closeOverviewModal();
      }
    });
  }

  function initLoginShowcase() {
    if (!document.getElementById("loginGate")) return;
    wireHotspots();
    wireModal();
    setActiveModule(DEFAULT_MODULE, { force: true });
  }

  window.svrmonLoginShowcase = {
    setActiveModule,
    openOverviewModal,
    closeOverviewModal,
    openModuleIntro,
    closeModuleIntro,
    MODULES,
    DEFAULT_MODULE,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLoginShowcase);
  } else {
    initLoginShowcase();
  }
})();
