/**
 * Login gate — interactive module showcase (hover + keyboard focus).
 * Vanilla only; keeps auth form untouched.
 */
(function () {
  const MODULES = [
    {
      id: "dashboard",
      title: "Dashboard overview",
      caption: "Cross-module KPIs and tenant posture at a glance",
    },
    {
      id: "cmdb",
      title: "CMDB",
      caption: "Authoritative CI inventory, relationships, and dependency mapping",
    },
    {
      id: "monitoring",
      title: "Monitoring",
      caption: "Agentless and agent health checks, logs, alerts, and diagnostics",
    },
    {
      id: "itsm",
      title: "ITSM",
      caption: "Incidents, changes, SLAs, and knowledge-driven workflows",
    },
    {
      id: "portal",
      title: "Service Portal",
      caption: "Self-service catalog with approval-driven change fulfillment",
    },
    {
      id: "admin",
      title: "Configuration & Administration",
      caption: "RBAC, entitlements, OIDC/Basic coexistence, and audit",
    },
  ];

  const DEFAULT_ID = "dashboard";

  function prefersReducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
      return false;
    }
  }

  function setActiveModule(id, { focusChip = false } = {}) {
    const mod = MODULES.find((m) => m.id === id) || MODULES[0];
    const rail = document.getElementById("loginModuleRail");
    const captionEl = document.getElementById("loginModuleCaption");
    const viewport = document.getElementById("loginPreviewViewport");
    if (!rail || !captionEl || !viewport) return;

    rail.setAttribute("data-active", mod.id);
    viewport.setAttribute("data-active", mod.id);

    rail.querySelectorAll(".login-module-chip").forEach((chip) => {
      const on = chip.dataset.module === mod.id;
      chip.classList.toggle("is-active", on);
      chip.setAttribute("aria-selected", on ? "true" : "false");
      chip.tabIndex = on ? 0 : -1;
    });

    viewport.querySelectorAll(".login-module-preview").forEach((panel) => {
      const on = panel.dataset.module === mod.id;
      panel.classList.toggle("is-active", on);
      panel.hidden = !on;
    });

    captionEl.textContent = mod.caption;

    if (focusChip) {
      const chip = rail.querySelector(`[data-module="${mod.id}"]`);
      chip?.focus({ preventScroll: true });
    }
  }

  function initRail() {
    const rail = document.getElementById("loginModuleRail");
    if (!rail) return;

    MODULES.forEach((mod, index) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "login-module-chip";
      btn.dataset.module = mod.id;
      btn.id = `loginModuleTab-${mod.id}`;
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-controls", `loginModulePanel-${mod.id}`);
      btn.setAttribute("aria-selected", mod.id === DEFAULT_ID ? "true" : "false");
      btn.tabIndex = mod.id === DEFAULT_ID ? 0 : -1;
      btn.textContent = mod.id === "admin" ? "Config / Admin" : mod.title;
      if (mod.id === "dashboard") btn.textContent = "Dashboard";
      rail.appendChild(btn);

      btn.addEventListener("mouseenter", () => setActiveModule(mod.id));
      btn.addEventListener("focus", () => setActiveModule(mod.id));
      btn.addEventListener("click", () => setActiveModule(mod.id, { focusChip: true }));

      btn.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowDown") {
          e.preventDefault();
          const next = MODULES[(index + 1) % MODULES.length];
          setActiveModule(next.id, { focusChip: true });
        } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
          e.preventDefault();
          const prev = MODULES[(index - 1 + MODULES.length) % MODULES.length];
          setActiveModule(prev.id, { focusChip: true });
        } else if (e.key === "Home") {
          e.preventDefault();
          setActiveModule(MODULES[0].id, { focusChip: true });
        } else if (e.key === "End") {
          e.preventDefault();
          setActiveModule(MODULES[MODULES.length - 1].id, { focusChip: true });
        }
      });
    });

    if (!prefersReducedMotion()) {
      rail.classList.add("login-module-rail--motion");
    }
  }

  function wirePreviewPanels() {
    const viewport = document.getElementById("loginPreviewViewport");
    if (!viewport) return;
    viewport.querySelectorAll(".login-module-preview").forEach((panel) => {
      panel.id = `loginModulePanel-${panel.dataset.module}`;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", `loginModuleTab-${panel.dataset.module}`);
    });
  }

  function initLoginShowcase() {
    if (!document.getElementById("loginGate")) return;
    wirePreviewPanels();
    initRail();
    setActiveModule(DEFAULT_ID);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLoginShowcase);
  } else {
    initLoginShowcase();
  }
})();