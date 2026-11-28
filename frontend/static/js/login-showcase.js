/**
 * Login gate — premium interactive central intelligence hub (vanilla).
 * Sticky selected-module state; temporary edge-clipped SVG connection only.
 * Positions from enabled MODULES. No auth/API changes.
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
      short_description: "Unified view of servers, networks and applications.",
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
  /**
   * Visible empty air between hexagon outer edges on desktop (~25–35px).
   * Stroke + soft glow sit inside the edge-to-edge span, so the fit target is
   * air + stroke (+ glow pad) — not centre distance alone.
   */
  const TARGET_AIR_GAP_PX = 30;
  /** @deprecated alias — tests / exports; equals TARGET_AIR_GAP_PX */
  const TARGET_GAP_PX = TARGET_AIR_GAP_PX;
  const GLOW_PAD_PX = 4;
  const BASE_RING_5 = 42;
  const BASE_RING_6 = 38;
  const MAX_RING = 48;
  const MIN_RING = 34;
  /** Desktop selected stroke target in CSS pixels. */
  const STROKE_PX_DESKTOP = 8.5;
  const STROKE_PX_COMPACT = 6.5;
  /** Matches .login-hub-node.is-active scale — edges grow when selected. */
  const SELECTED_NODE_SCALE = 1.07;

  let activeId = DEFAULT_MODULE;
  let swapTimer = null;
  let illuminateTimer = null;
  let renderedNodes = [];
  let hubResizeObserver = null;
  let connectionAnimToken = 0;
  let fittedRing = BASE_RING_5;

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
   * Coordinates are percentages of the hub box (0–100).
   * Optional ringOverride (5/6) lets fitRingClearance re-place after measure.
   */
  function computePositions(count, ringOverride) {
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
      // CMDB top → ITSM UR → Monitoring LR → Service Portal LL → SecureOps UL
      // Base radius; fitRingClearance expands after measure for 25–35px gap.
      const base =
        typeof ringOverride === "number"
          ? ringOverride
          : count === 5
            ? BASE_RING_5
            : BASE_RING_6;
      placeRing(count, base, -90, pts);
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

  /** Flat-top hexagon vertices relative to centre (half-width hw, half-height hh). */
  function hexVertices(cx, cy, hw, hh) {
    return [
      [cx + hw / 2, cy - hh],
      [cx + hw, cy],
      [cx + hw / 2, cy + hh],
      [cx - hw / 2, cy + hh],
      [cx - hw, cy],
      [cx - hw / 2, cy - hh],
    ];
  }

  /** Ray–segment intersection. Ray: origin + t*dir (t ≥ 0). Segment s ∈ [0,1]. */
  function raySegmentIntersection(ox, oy, dx, dy, x1, y1, x2, y2) {
    const ex = x2 - x1;
    const ey = y2 - y1;
    const det = dx * ey - dy * ex;
    if (Math.abs(det) < 1e-9) return null;
    const tx = x1 - ox;
    const ty = y1 - oy;
    const t = (tx * ey - ty * ex) / det;
    const s = (tx * dy - ty * dx) / det;
    if (t >= -1e-6 && s >= -1e-6 && s <= 1 + 1e-6) {
      return { t: Math.max(0, t), x: ox + Math.max(0, t) * dx, y: oy + Math.max(0, t) * dy };
    }
    return null;
  }

  /**
   * Intersection of a ray from hex centre along (dx,dy) with the flat-top hex boundary.
   * Returns {x,y,t} in the same coordinate space as the centre / half-extents.
   */
  function hexBoundaryIntersection(cx, cy, hw, hh, dx, dy) {
    const len = Math.hypot(dx, dy);
    if (len < 1e-9 || hw <= 0 || hh <= 0) return { x: cx, y: cy, t: 0 };
    const ux = dx / len;
    const uy = dy / len;
    const verts = hexVertices(cx, cy, hw, hh);
    let best = null;
    for (let i = 0; i < 6; i++) {
      const a = verts[i];
      const b = verts[(i + 1) % 6];
      const hit = raySegmentIntersection(cx, cy, ux, uy, a[0], a[1], b[0], b[1]);
      if (hit && (best === null || hit.t < best.t)) best = hit;
    }
    return best || { x: cx + ux * Math.min(hw, hh), y: cy + uy * Math.min(hw, hh), t: Math.min(hw, hh) };
  }

  /**
   * Slight cubic between two hex-edge points (not centres). Bend is perpendicular
   * to the chord; magnitude scales with chord length — no CSS offset hacks.
   */
  function edgeCurvePath(x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.hypot(dx, dy) || 1;
    const bend = Math.min(len * 0.16, 8);
    const ox = (-dy / len) * bend;
    const oy = (dx / len) * bend;
    const c1x = x1 + dx / 3 + ox;
    const c1y = y1 + dy / 3 + oy;
    const c2x = x1 + (2 * dx) / 3 + ox;
    const c2y = y1 + (2 * dy) / 3 + oy;
    return `M ${x1} ${y1} C ${c1x} ${c1y} ${c2x} ${c2y} ${x2} ${y2}`;
  }

  /**
   * Edge-clipped connection from selected module boundary → hub boundary.
   * Reuses hex-boundary geometry from 0.99.12 (direction → intersections → cubic).
   */
  function connectionPath(hub, node) {
    const dx = node.cx - hub.cx;
    const dy = node.cy - hub.cy;
    const hubEdge = hexBoundaryIntersection(hub.cx, hub.cy, hub.hw, hub.hh, dx, dy);
    const nodeEdge = hexBoundaryIntersection(node.cx, node.cy, node.hw, node.hh, -dx, -dy);
    // Draw module → hub so stroke animation travels toward the central S
    return edgeCurvePath(nodeEdge.x, nodeEdge.y, hubEdge.x, hubEdge.y);
  }

  /**
   * Measure an element’s centre + half-size in hub-local % (0–100).
   * Uses offsetWidth/Height so hover/active CSS scale does not move endpoints.
   * visual:true applies --hub-hex-scale; assumeSelected grows nodes by the
   * active 1.07 scale so clearance accounts for the selected plate.
   */
  function measureHexInView(el, hubRect, { visual = false, assumeSelected = false } = {}) {
    if (!el || !hubRect || hubRect.width < 1 || hubRect.height < 1) {
      return { cx: CX, cy: CY, hw: 8, hh: 7 };
    }
    const r = el.getBoundingClientRect();
    const cx = (((r.left + r.right) / 2 - hubRect.left) / hubRect.width) * VIEW;
    const cy = (((r.top + r.bottom) / 2 - hubRect.top) / hubRect.height) * VIEW;
    let scale = 1;
    if (visual) {
      const hubEl = document.getElementById("loginHubHotspots");
      const raw = hubEl ? getComputedStyle(hubEl).getPropertyValue("--hub-hex-scale") : "1";
      scale = parseFloat(raw) || 1;
      if (assumeSelected || el.classList.contains("is-active")) {
        scale *= SELECTED_NODE_SCALE;
      }
    }
    const w = (el.offsetWidth || r.width) * scale;
    const h = (el.offsetHeight || r.height) * scale;
    const hw = (w / hubRect.width) * (VIEW / 2);
    const hh = (h / hubRect.height) * (VIEW / 2);
    return { cx, cy, hw, hh };
  }

  /**
   * Signed edge-to-edge clearance (px) along hub→node, using hex-boundary clip.
   * Positive = separated; negative = overlap. No CSS endpoint offsets.
   */
  function radialGapPx(hubGeom, nodeGeom, hubRect) {
    const dx = nodeGeom.cx - hubGeom.cx;
    const dy = nodeGeom.cy - hubGeom.cy;
    const hubEdge = hexBoundaryIntersection(hubGeom.cx, hubGeom.cy, hubGeom.hw, hubGeom.hh, dx, dy);
    const nodeEdge = hexBoundaryIntersection(nodeGeom.cx, nodeGeom.cy, nodeGeom.hw, nodeGeom.hh, -dx, -dy);
    const ex = ((nodeEdge.x - hubEdge.x) / VIEW) * hubRect.width;
    const ey = ((nodeEdge.y - hubEdge.y) / VIEW) * hubRect.height;
    const dirx = (dx / VIEW) * hubRect.width;
    const diry = (dy / VIEW) * hubRect.height;
    const len = Math.hypot(dirx, diry) || 1;
    return (ex * dirx + ey * diry) / len;
  }

  /** Map hub size → CSS-pixel stroke so desktop lands ~7–9px. */
  function strokePxForHub(hubRect) {
    return hubRect.width >= 720 ? STROKE_PX_DESKTOP : STROKE_PX_COMPACT;
  }

  /**
   * Edge-to-edge fit target: visible air after the stroke still reads ~25–35px.
   * required = air + stroke + glow pad (stroke occupies the corridor between edges).
   */
  function requiredEdgeGapPx(hubRect) {
    const air = hubRect.height >= 360 ? TARGET_AIR_GAP_PX : Math.min(TARGET_AIR_GAP_PX, 18);
    return air + strokePxForHub(hubRect) + GLOW_PAD_PX;
  }

  /** Keep module centres inside the hub pad so cards aren’t clipped. */
  function maxRingForInset(nodeGeomApproxHw, nodeGeomApproxHh) {
    const insetX = VIEW / 2 - nodeGeomApproxHw - 2;
    const insetY = VIEW / 2 - nodeGeomApproxHh - 2;
    return Math.max(MIN_RING, Math.min(MAX_RING, Math.min(insetX, insetY)));
  }

  function measureMinGap(core, nodes, hubRect) {
    // assumeSelected: clearance must hold when a node is popped to 1.07
    const hg = measureHexInView(core, hubRect, { visual: true });
    let minGap = Infinity;
    nodes.forEach((btn) => {
      minGap = Math.min(
        minGap,
        radialGapPx(hg, measureHexInView(btn, hubRect, { visual: true, assumeSelected: true }), hubRect)
      );
    });
    return minGap;
  }

  /** Clear air remaining after stroke sits between hex edges. */
  function airGapAfterStroke(edgeGapPx, hubRect) {
    return edgeGapPx - strokePxForHub(hubRect);
  }

  /**
   * Expand ring (and if needed shrink --hub-hex-scale) so outer-edge air after
   * the selected stroke is ~TARGET_AIR_GAP_PX. Repositions via computePositions.
   */
  function fitRingClearance() {
    const hub = document.getElementById("loginHubHotspots");
    const core = hub?.querySelector(".login-hub-core");
    const mods = enabledModules();
    if (!hub || !core || mods.length === 0 || mods.length > 6) return fittedRing;

    const hubRect = hub.getBoundingClientRect();
    if (hubRect.width < 1 || hubRect.height < 1) return fittedRing;

    const nodes = mods.map((m) => hub.querySelector(`.login-hub-node[data-module="${m.id}"]`)).filter(Boolean);
    if (!nodes.length) return fittedRing;

    const base = mods.length === 5 ? BASE_RING_5 : BASE_RING_6;
    const targetGap = requiredEdgeGapPx(hubRect);
    const targetAir = hubRect.height >= 360 ? TARGET_AIR_GAP_PX : Math.min(TARGET_AIR_GAP_PX, 18);

    const applyRing = (r) => {
      const positions = computePositions(mods.length, r);
      nodes.forEach((btn, i) => {
        const pos = positions[i];
        if (!pos) return;
        btn.style.setProperty("--hx", `${pos.x}%`);
        btn.style.setProperty("--hy", `${pos.y}%`);
      });
    };

    let scale = 1;
    hub.style.setProperty("--hub-hex-scale", "1");

    const fitAtScale = () => {
      const sample = measureHexInView(nodes[0], hubRect, { visual: true, assumeSelected: true });
      const cap = maxRingForInset(sample.hw, sample.hh);
      let ring = Math.min(Math.max(base, fittedRing > MIN_RING ? fittedRing : base), cap);
      applyRing(ring);
      for (let iter = 0; iter < 14; iter++) {
        const minGap = measureMinGap(core, nodes, hubRect);
        if (minGap >= targetGap || ring >= cap - 0.05) return { ring, minGap, cap };
        const deficit = targetGap - minGap;
        const pctPerPx = VIEW / Math.min(hubRect.width, hubRect.height);
        ring = Math.min(cap, ring + Math.max(0.55, deficit * pctPerPx * 0.55));
        applyRing(ring);
      }
      return { ring, minGap: measureMinGap(core, nodes, hubRect), cap };
    };

    let result = fitAtScale();
    // Short / tight hubs: shrink hexes so air + stroke still fit.
    const scaleFloor = hubRect.height < 340 ? 0.6 : 0.68;
    while (result.minGap < targetGap && scale > scaleFloor) {
      scale = Math.round((scale - 0.04) * 100) / 100;
      hub.style.setProperty("--hub-hex-scale", String(scale));
      void nodes[0].offsetWidth;
      result = fitAtScale();
      if (result.minGap >= targetGap) break;
    }

    // Only trim when air after stroke overshoots the 35px band by a lot.
    const air = airGapAfterStroke(result.minGap, hubRect);
    if (hubRect.height >= 400 && air > 48 && result.ring > base) {
      const pctPerPx = VIEW / Math.min(hubRect.width, hubRect.height);
      const trim = Math.min(result.ring - base, (air - targetAir) * pctPerPx * 0.35);
      result.ring = Math.max(base, result.ring - trim);
      applyRing(result.ring);
      result.minGap = measureMinGap(core, nodes, hubRect);
    }

    fittedRing = result.ring;
    const finalAir = airGapAfterStroke(result.minGap, hubRect);
    hub.dataset.ring = String(Math.round(result.ring * 100) / 100);
    hub.dataset.hexScale = String(scale);
    hub.dataset.minGap = String(Math.round(result.minGap * 10) / 10);
    hub.dataset.airGap = String(Math.round(finalAir * 10) / 10);
    return result.ring;
  }

  /** Map hub size → SVG user-unit stroke so desktop lands ~7–9px. */
  function strokeWidthForHub(hubRect, { selected = true } = {}) {
    const mean = (hubRect.width + hubRect.height) / 2 || 1;
    const targetPx = strokePxForHub(hubRect);
    const base = (targetPx / mean) * VIEW;
    return selected ? base : base * 0.72;
  }

  function tempConnectionEl() {
    return document.getElementById("loginHubTempConnection");
  }

  function tempTravelEl() {
    return document.getElementById("loginHubTempTravel");
  }

  function clearConnectionAnimation(path) {
    if (!path) return;
    path.style.removeProperty("stroke-dasharray");
    path.style.removeProperty("stroke-dashoffset");
    path.classList.remove("is-drawing");
  }

  function syncTravelPath(path, travel, { reduce = false } = {}) {
    if (!travel) return;
    const d = path?.getAttribute("d") || "";
    travel.setAttribute("d", d);
    if (!d || !path?.classList.contains("is-visible")) {
      travel.classList.remove("is-visible", "is-travelling");
      travel.style.removeProperty("stroke-dasharray");
      travel.style.removeProperty("stroke-dashoffset");
      return;
    }
    travel.classList.add("is-visible");
    if (reduce) {
      travel.classList.remove("is-travelling");
      return;
    }
    let length = 120;
    try {
      length = travel.getTotalLength() || length;
    } catch {
      /* length unavailable */
    }
    const head = Math.max(3.2, length * 0.12);
    const gap = Math.max(length * 0.88, 24);
    travel.style.strokeDasharray = `${head} ${gap}`;
    travel.style.strokeDashoffset = "0";
    travel.classList.add("is-travelling");
    travel.style.setProperty("--travel-period", `${Math.max(1.6, length * 0.028)}s`);
    travel.style.setProperty("--travel-distance", String(-(head + gap)));
  }

  /**
   * Animate the temporary connection draw-in (module → hub).
   * Uses inline dash metrics so CSS stays free of permanent spoke chrome.
   */
  function animateTempConnection(path, { animate = true } = {}) {
    if (!path) return;
    const reduce = prefersReducedMotion();
    clearConnectionAnimation(path);
    if (!path.getAttribute("d")) {
      path.classList.remove("is-visible");
      syncTravelPath(path, tempTravelEl(), { reduce });
      return;
    }
    path.classList.add("is-visible");
    if (!animate || reduce) {
      syncTravelPath(path, tempTravelEl(), { reduce });
      return;
    }

    let length = 120;
    try {
      length = path.getTotalLength() || length;
    } catch {
      /* SVG length unavailable — fall back */
    }
    const token = ++connectionAnimToken;
    path.classList.add("is-drawing");
    path.style.strokeDasharray = String(length);
    path.style.strokeDashoffset = String(length);
    // Force layout so the transition from full offset → 0 runs
    void path.getBoundingClientRect();
    requestAnimationFrame(() => {
      if (token !== connectionAnimToken) return;
      path.style.strokeDashoffset = "0";
    });
    window.setTimeout(() => {
      if (token !== connectionAnimToken) return;
      clearConnectionAnimation(path);
      syncTravelPath(path, tempTravelEl(), { reduce });
    }, 520);
  }

  /**
   * Recalculate the single temporary connection from live hub/node geometry.
   * SVG uses the same 0–100 percentage space as node --hx/--hy (preserveAspectRatio none).
   * Fit ring clearance first so CMDB sits above the hub with a real pixel gap.
   */
  function updateConnections({ animate = false, fitRing = true } = {}) {
    const hub = document.getElementById("loginHubHotspots");
    const spokes = document.getElementById("loginHubSpokes");
    const core = hub?.querySelector(".login-hub-core");
    const path = tempConnectionEl();
    const travel = tempTravelEl();
    if (!hub || !spokes || !core || !path) return;

    const hubRect = hub.getBoundingClientRect();
    if (hubRect.width < 1 || hubRect.height < 1) return;

    spokes.setAttribute("viewBox", `0 0 ${VIEW} ${VIEW}`);
    spokes.setAttribute("preserveAspectRatio", "none");

    if (fitRing) fitRingClearance();

    const mod = findModule(activeId);
    const node = mod ? hub.querySelector(`.login-hub-node[data-module="${mod.id}"]`) : null;
    if (!mod || !node) {
      path.setAttribute("d", "");
      path.removeAttribute("data-module");
      path.classList.remove("is-visible");
      clearConnectionAnimation(path);
      syncTravelPath(path, travel, { reduce: prefersReducedMotion() });
      return;
    }

    const hubGeom = measureHexInView(core, hubRect);
    const nodeGeom = measureHexInView(node, hubRect);
    const d = connectionPath(hubGeom, nodeGeom);
    const sw = strokeWidthForHub(hubRect, { selected: true });
    path.setAttribute("data-module", mod.id);
    path.setAttribute("d", d);
    path.setAttribute("stroke-width", String(Math.round(sw * 100) / 100));
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    if (travel) {
      travel.setAttribute("stroke-width", String(Math.round(sw * 0.55 * 100) / 100));
      travel.setAttribute("stroke-linecap", "round");
      travel.setAttribute("stroke-linejoin", "round");
    }
    animateTempConnection(path, { animate });
  }

  function illuminateHub() {
    const core = document.querySelector(".login-hub-core");
    if (!core) return;
    if (illuminateTimer) clearTimeout(illuminateTimer);
    core.classList.remove("is-illuminated");
    // Retrigger CSS animation
    void core.offsetWidth;
    core.classList.add("is-illuminated");
    illuminateTimer = setTimeout(() => {
      core.classList.remove("is-illuminated");
      illuminateTimer = null;
    }, 700);
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
    spokes.setAttribute("preserveAspectRatio", "none");
    spokes.innerHTML = "";
    nodesLayer.innerHTML = "";

    fittedRing = mods.length === 5 ? BASE_RING_5 : mods.length === 6 ? BASE_RING_6 : fittedRing;

    // One temporary connection — never five permanent strings
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("id", "loginHubTempConnection");
    path.setAttribute("class", "login-hub-temp-connection");
    path.setAttribute("d", "");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "url(#loginHubSpokeActive)");
    path.setAttribute("stroke-width", "2.1");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    spokes.appendChild(path);

    // Subtle travelling highlight along the selected spoke (module → hub)
    const travel = document.createElementNS("http://www.w3.org/2000/svg", "path");
    travel.setAttribute("id", "loginHubTempTravel");
    travel.setAttribute("class", "login-hub-temp-travel");
    travel.setAttribute("d", "");
    travel.setAttribute("fill", "none");
    travel.setAttribute("stroke", "url(#loginHubSpokeTravel)");
    travel.setAttribute("stroke-width", "1.15");
    travel.setAttribute("stroke-linecap", "round");
    travel.setAttribute("stroke-linejoin", "round");
    spokes.appendChild(travel);

    const nodes = [];
    mods.forEach((mod, i) => {
      const pos = positions[i] || { x: CX, y: CY };
      const hx = pos.x;
      const hy = pos.y;

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
        `<use href="#loginHubHex" filter="url(#loginHubNodeNeo)" fill="url(#loginHubNodeFill)" stroke="rgba(117,69,232,0.34)" stroke-width="1.55"/></svg>` +
        `<span class="login-hub-node-content">` +
        `<span class="login-hub-node-ico" aria-hidden="true">${iconSvg(mod)}</span>` +
        `<span class="login-hub-node-label">${labelHtml(mod.name)}</span>` +
        `</span>`;
      nodesLayer.appendChild(btn);
      nodes.push(btn);
    });

    renderedNodes = nodes;
    // Layout pass — measure real hex boxes then clip the temporary connection
    requestAnimationFrame(() => updateConnections({ animate: false }));
    return nodes;
  }

  function observeHubResize() {
    const hub = document.getElementById("loginHubHotspots");
    if (!hub || typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateConnections);
      return;
    }
    if (hubResizeObserver) hubResizeObserver.disconnect();
    hubResizeObserver = new ResizeObserver(() => updateConnections());
    hubResizeObserver.observe(hub);
  }

  function setActiveModule(moduleId, { focusNode = false, force = false, animateConnection = true } = {}) {
    const mod = findModule(moduleId);
    if (!mod) return;
    const switching = activeId !== mod.id;
    if (!switching && !force && !focusNode) return;
    activeId = mod.id;

    const visual = document.getElementById("loginModulesVisual");
    const panel = document.getElementById("loginModuleDetail");
    const titleEl = document.getElementById("loginModuleDetailTitle");
    const bodyEl = document.getElementById("loginModuleDetailBody");
    const listEl = document.getElementById("loginModuleDetailBullets");
    const iconEl = document.getElementById("loginModuleDetailIcon");
    const nodes = document.querySelectorAll(".login-hub-node");
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
      if (switching) illuminateHub();
      updateConnections({ animate: Boolean(animateConnection && switching && !reduce) });
      if (focusNode) {
        document.querySelector(`.login-hub-node[data-module="${mod.id}"]`)?.focus({ preventScroll: true });
      }
    };

    if (swapTimer) clearTimeout(swapTimer);
    if (reduce || !switching) {
      apply();
      return;
    }
    if (panel) panel.classList.add("is-swapping");
    if (visual) visual.classList.add("is-swapping");
    swapTimer = setTimeout(apply, 180);
  }

  function resetToDefault() {
    setActiveModule(DEFAULT_MODULE, { force: true, animateConnection: false });
  }

  function wireHotspots(nodes) {
    const showcase = document.getElementById("loginModulesVisual");
    if (!nodes.length || !showcase) return;

    nodes.forEach((btn, index) => {
      btn.setAttribute("aria-pressed", btn.dataset.module === DEFAULT_MODULE ? "true" : "false");
      btn.tabIndex = btn.dataset.module === DEFAULT_MODULE ? 0 : -1;

      // Hover is CSS-only (scale/glow). Selection is sticky via click / focus / touch.
      btn.addEventListener("focus", () => setActiveModule(btn.dataset.module));
      btn.addEventListener("pointerdown", (e) => {
        // Touch + mouse press select immediately so the connection is visible before click
        if (e.pointerType === "touch" || e.pointerType === "pen" || e.button === 0) {
          setActiveModule(btn.dataset.module);
        }
      });

      btn.addEventListener("click", (e) => {
        e.preventDefault();
        setActiveModule(btn.dataset.module, { focusNode: true });
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
    observeHubResize();
    setActiveModule(DEFAULT_MODULE, { force: true, animateConnection: false });
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
    updateConnections,
    fitRingClearance,
    radialGapPx,
    strokeWidthForHub,
    hexBoundaryIntersection,
    connectionPath,
    edgeCurvePath,
    measureHexInView,
    illuminateHub,
    resetToDefault,
    MODULES,
    DEFAULT_MODULE,
    TARGET_GAP_PX,
    TARGET_AIR_GAP_PX,
    BASE_RING_5,
    requiredEdgeGapPx,
    airGapAfterStroke,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLoginShowcase);
  } else {
    initLoginShowcase();
  }
})();
