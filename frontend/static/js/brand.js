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
    assets: {
      markSvg: "/static/img/svrmon-brand-mark.svg",
      faviconSvg: "/static/img/svrmon-favicon.svg",
    },
  };
  global.SVRMON24_BRAND = Object.freeze(brand);
})(typeof window !== "undefined" ? window : globalThis);