/**
 * SVRMON24 central brand tokens — keep in sync with :root brand variables in cmdb.css.
 */
(function initSvrmon24Brand(global) {
  const brand = {
    name: "SVRMON",
    suffix: "24",
    fullName: "SVRMON24",
    tagline: "AI Infrastructure Diagnostic & Automation Platform",
    colors: {
      navy: "#10264A",
      blue: "#1769D2",
      blueBright: "#2563EB",
      sky: "#38BDF8",
      bg: "#EEF6FF",
      border: "#DCE7F5",
      muted: "#64748B",
    },
    markStyle: "user-png-exact",
    assets: {
      logoPng: "/static/img/svrmon-logo.png",
      logoCompactPng: "/static/img/svrmon-logo-compact.png",
      markPng: "/static/img/svrmon-logo-mark.png",
      faviconPng: "/static/img/svrmon-favicon.png",
      appleTouchPng: "/static/img/svrmon-apple-touch.png",
      logoSvg: "/static/assets/brand/svrmon24-logo.svg",
      symbolSvg: "/static/assets/brand/svrmon24-symbol.svg",
      icons: {
        cmdb: "/static/assets/icons/cmdb.svg",
        aiInvestigation: "/static/assets/icons/ai-investigation.svg",
        diagnostics: "/static/assets/icons/diagnostics.svg",
        logIntelligence: "/static/assets/icons/log-intelligence.svg",
        workflows: "/static/assets/icons/workflows.svg",
        security: "/static/assets/icons/security.svg",
      },
    },
  };
  global.SVRMON24_BRAND = Object.freeze(brand);
})(typeof window !== "undefined" ? window : globalThis);