/**
 * Login gate — data-driven hexagonal module showcase (vanilla).
 * Positions computed from enabled MODULES count. No auth/API changes.
 */
(function () {
  const ICONS = {
    cmdb:
      '<svg viewBox="0 0 24 24"><rect x="3" y="2.5" width="18" height="5.2" rx="1.4"/><rect x="3" y="9.4" width="18" height="5.2" rx="1.4"/><rect x="3" y="16.3" width="18" height="5.2" rx="1.4"/><circle cx="6.4" cy="5.1" r="0.85" fill="currentColor" stroke="none"/><circle cx="6.4" cy="12" r="0.85" fill="currentColor" stroke="none"/><circle cx="6.4" cy="18.9" r="0.85" fill="currentColor" stroke="none"/></svg>',
    monitoring:
      '<svg viewBox="0 0 24 24"><path d="M3.5 12h3l2-5 3 10 2.5-5H20.5"/></svg>',
    itsm:
      '<svg viewBox="0 0 24 24"><path d="M7 4.5h10a2 2 0 0 1 2 2v13l-3-1.6-3 1.6-3-1.6-3 1.6v-13a2 2 0 0 1 2-2z"/><path d="m11.2 11.2 1.3 1.3 2.8-2.8"/></svg>',
    portal:
      '<svg viewBox="0 0 24 24"><path d="M4 4h9v16H4z"/><path d="M13 7h7v13h-7"/><rect x="15.2" y="10" width="2.2" height="2.2" rx="0.3"/><rect x="18" y="10" width="2.2" height="2.2" rx="0.3"/><rect x="15.2" y="13.2" width="2.2" height="2.2" rx="0.3"/><rect x="18" y="13.2" width="2.2" height="2.2" rx="0.3"/></svg>',
    secureops:
      '<svg viewBox="0 0 24 24"><path d="M12 3l8 4v5c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V7l8-4z"/><rect x="9.2" y="10.2" width="5.6" height="4.8" rx="1"/><path d="M10.4 10.2V8.8a1.6 1.6 0 0 1 3.2 0v1.4"/></svg>',
    config:
      '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/><path d="M12 3.2v2.2M12 18.6v2.2M4.8 4.8l1.6 1.6M17.6 17.6l1.6 1.6M3.2 12h2.2M18.6 12h2.2M4.8 19.2l1.6-1.6M17.6 6.4l1.6-1.6"/><path d="M7.5 9.2h4.2M12.5 14.8h4"/></svg>',
  };

  /** Central module config — source of truth for hub interactions. */
  const MODULES = [
    {
      id: "cmdb",
      name: "CMDB",
      icon: "cmdb",
      short_description: "Unified view of servers, networks and applications",
      capabilities: [
        "Centralised infrastructure inventory",
        "Manage servers, operating systems, middleware, databases and applications",
        "Visualise infrastructure relationships and dependencies",
        "Maintain configuration item information",
      ],
      route: "#cmdb",
      display_order: 1,
      enabled: true,
      ariaLabel: "CMDB — Configuration Management Database",
      seek: 0,
    },
    {
      id: "itsm",
      name: "ITSM",
      icon: "itsm",
      short_description: "Incidents, changes and ticket lifecycle end-to-end",
      capabilities: [
        "Incident Management",
        "Change Management",
        "Problem Management",
        "Service requests and ticket lifecycle management",
      ],
      route: "#itsm",
      display_order: 2,
      enabled: true,
      ariaLabel: "ITSM — IT Service Management",
      seek: 4,
    },
    {
      id: "monitoring",
      name: "Monitoring",
      icon: "monitoring",
      short_description: "Health, alerts and performance across infrastructure",
      capabilities: [
        "Monitor server and infrastructure health",
        "CPU, memory, disk and network utilisation",
        "Infrastructure availability and performance",
        "Alert and event visibility",
      ],
      route: "#monitoring",
      display_order: 3,
      enabled: true,
      ariaLabel: "Monitoring — Infrastructure Monitoring",
      seek: 2,
    },
    {
      id: "portal",
      name: "Service Portal",
      icon: "portal",
      short_description: "Request catalog services and track fulfilment",
      capabilities: [
        "Centralised service request portal",
        "Submit and track service requests",
        "View incidents and request status",
        "Access service catalogue and knowledge resources",
      ],
      route: "#portal",
      display_order: 4,
      enabled: true,
      ariaLabel: "Service Portal — Self-Service Portal",
      seek: 6,
    },
    {
      id: "secureops",
      name: "SecureOps",
      icon: "secureops",
      short_description: "RBAC, audit trail and enterprise-grade access",
      capabilities: [
        "Role-based access control",
        "Audit trail and activity tracking",
        "Security visibility and compliance",
        "Secure infrastructure access",
      ],
      route: "#secureops",
      display_order: 5,
      enabled: true,
      ariaLabel: "SecureOps — Security and Compliance",
      seek: 10,
    },
    // Kept disabled — Configuration remains in the real app nav, not the login showcase.
    {
      id: "config",
      name: "Configuration",
      icon: "config",
      short_description: "Tenant settings, live gates and platform controls",
      capabilities: [
        "Configure integrations and platform settings",
        "Manage users, groups and roles",
        "Configure diagnostic scripts and workflows",
        "Manage tenant-level settings",
      ],
      route: "#configuration",
      display_order: 6,
      enabled: false,
      ariaLabel: "Configuration — Platform Configuration",
      seek: 8,
    },
  ];

  const DEFAULT_MODULE = "cmdb";
  const VIEW = 100;
  const CX = 50;
  const CY = 50;

  let activeId = DEFAULT_MODULE;
  let swapTimer = null;
  let renderedNodes = [];

  function prefersReducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
      return false;
    }
  }

  function enabledModules() {
    return MODULES.filter((m) => m.enabled)
      .slice()
      .sort((a, b) => a.display_order - b.display_order);
  }

  function findModule(id) {
    const enabled = enabledModules();
    return enabled.find((m) => m.id === id) || enabled.find((m) => m.id === DEFAULT_MODULE) || enabled[0];
  }

  function iconSvg(mod) {
    return ICONS[mod.icon] || ICONS.cmdb;
  }

  function labelHtml(name) {
    if (name === "Service Portal") return "Service<br>Portal";
    return name;
  }

  /**
   * Compute polar placements for N enabled modules.
   * 5 → one ring; 6 → even ring; 7–10 → inner+outer; >10 → adaptive rings.
   */
  function computePositions(count) {
    const pts = [];
    if (count <= 0) return pts;

    const placeRing = (n, radius, startDeg, out) => {
      const step = 360 / n;
      for (let i = 0; i < n; i++) {
        const deg = startDeg + i * step;
        const rad = (deg * Math.PI) / 180;
        out.push({
          x: CX + radius * Math.cos(rad),
          y: CY + radius * Math.sin(rad),
          angle: deg,
          ring: radius,
        });
      }
    };

    if (count <= 6) {
      // Single symmetric ring (5 or 6); start at top (−90°)
      placeRing(count, count === 5 ? 34 : 33, -90, pts);
      return pts;
    }

    if (count <= 10) {
      // Inner ring of 5 + outer ring of remainder
      const inner = 5;
      const outer = count - inner;
      placeRing(inner, 28, -90, pts);
      placeRing(outer, 40, -90 + 180 / outer, pts);
      return pts;
    }

    // Adaptive multi-ring for >10
    let remaining = count;
    let ringIdx = 0;
    while (remaining > 0) {
      const capacity = ringIdx === 0 ? 6 : Math.min(8, remaining);
      const take = Math.min(capacity, remaining);
      const radius = 22 + ringIdx * 12;
      placeRing(take, radius, -90, pts);
      remaining -= take;
      ringIdx += 1;
    }
    return pts;
  }

  function curvePath(x, y) {
    const mx = (CX + x) / 2;
    const my = (CY + y) / 2;
    const dx = x - CX;
    const dy = y - CY;
    const len = Math.hypot(dx, dy) || 1;
    const ox = (-dy / len) * 6;
    const oy = (dx / len) * 6;
    return `M ${CX} ${CY} Q ${mx + ox} ${my + oy} ${x} ${y}`;
  }

  function renderHub() {
    const hub = document.getElementById("loginHubHotspots");
    const spokes = document.getElementById("loginHubSpokes");
    const nodesLayer = document.getElementById("loginHubNodes");
    if (!hub || !spokes || !nodesLayer) return [];

    const mods = enabledModules();
    const positions = computePositions(mods.length);
    hub.dataset.count = String(mods.length);

    spokes.setAttribute("viewBox", `0 0 ${VIEW} ${VIEW}`);
    spokes.setAttribute("preserveAspectRatio", "xMidYMid meet");
    spokes.innerHTML = "";
    nodesLayer.innerHTML = "";

    const nodes = [];
    mods.forEach((mod, i) => {
      const pos = positions[i] || { x: CX, y: CY };
      const hx = pos.x;
      const hy = pos.y;

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("data-module", mod.id);
      path.setAttribute("d", curvePath(hx, hy));
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "url(#loginHubSpokeGrad)");
      path.setAttribute("stroke-width", "1.15");
      path.setAttribute("stroke-linecap", "round");
      spokes.appendChild(path);

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "login-hub-node";
      btn.dataset.module = mod.id;
      btn.dataset.route = mod.route;
      btn.style.setProperty("--hx", `${hx}%`);
      btn.style.setProperty("--hy", `${hy}%`);
      btn.setAttribute("aria-describedby", "loginModuleDetail");
      btn.setAttribute("aria-label", mod.ariaLabel || mod.name);
      btn.innerHTML =
        `<svg class="login-hub-node-plate" viewBox="0 0 100 86.6" aria-hidden="true">` +
        `<use href="#loginHubHex" filter="url(#loginHubNodeNeo)" fill="url(#loginHubNodeFill)" stroke="rgba(91,33,182,0.28)" stroke-width="1.5"/></svg>` +
        `<span class="login-hub-node-content">` +
        `<span class="login-hub-node-ico" aria-hidden="true">${iconSvg(mod)}</span>` +
        `<span class="login-hub-node-label">${labelHtml(mod.name)}</span>` +
        `</span>`;
      nodesLayer.appendChild(btn);
      nodes.push(btn);
    });

    renderedNodes = nodes;
    return nodes;
  }

  function setActiveModule(moduleId, { focusNode = false, force = false } = {}) {
    const mod = findModule(moduleId);
    if (!mod) return;
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
        curve.classList.toggle("is-active", curve.dataset.module === mod.id);
      });
      titleEl.textContent = mod.name;
      bodyEl.textContent = mod.short_description;
      listEl.innerHTML = (mod.capabilities || []).map((b) => `<li>${b}</li>`).join("");
      if (iconEl) {
        iconEl.innerHTML = iconSvg(mod);
      }
      if (panel) {
        panel.dataset.module = mod.id;
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

  function wireHotspots(nodes) {
    const showcase = document.getElementById("loginModulesVisual");
    if (!nodes.length || !showcase) return;

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

    showcase.addEventListener("mouseleave", (e) => {
      if (isInsideShowcase(e.relatedTarget)) return;
      resetToDefault();
    });
    showcase.addEventListener("focusout", (e) => {
      if (isInsideShowcase(e.relatedTarget)) return;
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
    if (title) title.textContent = mod.name;
    if (blurb) blurb.textContent = mod.short_description;
    if (list) list.innerHTML = (mod.capabilities || []).map((b) => `<li>${b}</li>`).join("");
    if (icon) icon.innerHTML = iconSvg(mod);
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
    const nodes = renderHub();
    wireHotspots(nodes);
    wireModal();
    setActiveModule(DEFAULT_MODULE, { force: true });
  }

  window.svrmonLoginShowcase = {
    setActiveModule,
    openOverviewModal,
    closeOverviewModal,
    openModuleIntro,
    closeModuleIntro,
    computePositions,
    enabledModules,
    renderHub,
    MODULES,
    DEFAULT_MODULE,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLoginShowcase);
  } else {
    initLoginShowcase();
  }
})();
