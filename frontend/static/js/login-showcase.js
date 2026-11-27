/**
 * Login gate — capability cards drive caption; Option B overview modal;
 * play icon on each card seeks into the overview. Vanilla only.
 * Hero uses one composed all-modules illustration (not app screenshots).
 */
(function () {
  const CARDS = [
    {
      id: "cmdb",
      module: "cmdb",
      title: "CMDB & Inventory",
      caption: "Unified view of servers, network and applications",
      icon: "/static/assets/icons/cmdb.svg",
      tone: "blue",
      seek: 0,
    },
    {
      id: "ai",
      module: "dashboard",
      title: "AI Investigation",
      caption: "Analyse incidents, logs and health data to find root cause",
      icon: "/static/assets/icons/ai-investigation.svg",
      tone: "violet",
      seek: 0,
    },
    {
      id: "diagnostics",
      module: "monitoring",
      title: "Automated Diagnostics",
      caption: "Run secure, read-only diagnostic scripts on demand",
      icon: "/static/assets/icons/diagnostics.svg",
      tone: "green",
      seek: 8,
    },
    {
      id: "logs",
      module: "monitoring",
      title: "Log Intelligence",
      caption: "Understand middleware and system logs with AI",
      icon: "/static/assets/icons/log-intelligence.svg",
      tone: "orange",
      seek: 2,
    },
    {
      id: "workflows",
      module: "itsm",
      title: "Investigation Workflows",
      caption: "Track, collaborate and resolve incidents end-to-end",
      icon: "/static/assets/icons/workflows.svg",
      tone: "indigo",
      seek: 4,
    },
    {
      id: "secure",
      module: "admin",
      title: "Secure & Compliant",
      caption: "RBAC, audit trail and enterprise-grade access",
      icon: "/static/assets/icons/security.svg",
      tone: "teal",
      seek: 10,
    },
  ];

  const DEFAULT_CARD = "ai";
  const COLS = 3;

  function prefersReducedMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
      return false;
    }
  }

  function setActiveCard(cardId, { focusCard = false } = {}) {
    const card = CARDS.find((c) => c.id === cardId) || CARDS.find((c) => c.id === DEFAULT_CARD);
    const grid = document.getElementById("loginCapabilityGrid");
    const captionEl = document.getElementById("loginModuleCaption");
    const visual = document.getElementById("loginModulesVisual");
    if (!grid || !captionEl) return;

    const reduce = prefersReducedMotion();
    if (!reduce && visual) visual.classList.add("is-swapping");

    const apply = () => {
      if (visual) visual.setAttribute("data-active", card.module);
      grid.querySelectorAll(".login-cap-card").forEach((el) => {
        const on = el.dataset.card === card.id;
        el.classList.toggle("is-active", on);
        el.setAttribute("aria-selected", on ? "true" : "false");
        el.tabIndex = on ? 0 : -1;
      });
      captionEl.textContent = card.caption;
      if (visual) visual.classList.remove("is-swapping");
      if (focusCard) {
        grid.querySelector(`[data-card="${card.id}"]`)?.focus({ preventScroll: true });
      }
    };

    if (reduce) apply();
    else setTimeout(apply, 120);
  }

  function buildCards() {
    const grid = document.getElementById("loginCapabilityGrid");
    if (!grid) return;
    grid.innerHTML = "";

    CARDS.forEach((card, index) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "login-cap-card" + (card.id === DEFAULT_CARD ? " is-active" : "");
      btn.dataset.card = card.id;
      btn.dataset.module = card.module;
      btn.id = `loginCapTab-${card.id}`;
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-controls", "loginModulesVisual");
      btn.setAttribute("aria-selected", card.id === DEFAULT_CARD ? "true" : "false");
      btn.tabIndex = card.id === DEFAULT_CARD ? 0 : -1;

      btn.innerHTML =
        `<span class="login-cap-ico login-cap-ico--${card.tone}" aria-hidden="true">` +
        `<img src="${card.icon}" alt="" width="20" height="20" decoding="async" />` +
        `</span>` +
        `<span class="login-cap-copy"><strong>${card.title}</strong><span>${card.caption}</span></span>` +
        `<span class="login-cap-play" data-play-card="${card.id}" role="button" tabindex="0" ` +
        `aria-label="Watch overview for ${card.title}">` +
        `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.6"/>` +
        `<path d="M10 8.5v7l6-3.5z" fill="currentColor" stroke="none"/></svg></span>`;

      btn.addEventListener("mouseenter", () => setActiveCard(card.id));
      btn.addEventListener("focus", () => setActiveCard(card.id));
      btn.addEventListener("click", (e) => {
        if (e.target.closest("[data-play-card]")) return;
        setActiveCard(card.id, { focusCard: true });
      });
      btn.addEventListener("keydown", (e) => {
        if (e.target.closest("[data-play-card]") && (e.key === "Enter" || e.key === " ")) {
          return;
        }
        let next = index;
        if (e.key === "ArrowRight") next = (index + 1) % CARDS.length;
        else if (e.key === "ArrowLeft") next = (index - 1 + CARDS.length) % CARDS.length;
        else if (e.key === "ArrowDown") next = (index + COLS) % CARDS.length;
        else if (e.key === "ArrowUp") next = (index - COLS + CARDS.length) % CARDS.length;
        else if (e.key === "Home") next = 0;
        else if (e.key === "End") next = CARDS.length - 1;
        else return;
        e.preventDefault();
        setActiveCard(CARDS[next].id, { focusCard: true });
      });

      const play = btn.querySelector("[data-play-card]");
      play?.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        openOverviewModal(card.seek);
      });
      play?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.stopPropagation();
          openOverviewModal(card.seek);
        }
      });

      grid.appendChild(btn);
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
    buildCards();
    wireModal();
    setActiveCard(DEFAULT_CARD);
  }

  window.svrmonLoginShowcase = {
    setActiveCard,
    openOverviewModal,
    closeOverviewModal,
    CARDS,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLoginShowcase);
  } else {
    initLoginShowcase();
  }
})();
