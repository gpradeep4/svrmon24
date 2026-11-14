/**
 * Frontend runtime config for split deploy.
 * Default: same-origin (empty apiBase). Set window.SVRMON24.apiBase before this script
 * or edit below for cross-origin API (requires CORS_ORIGINS on the API).
 */
(function initSvrmon24FrontendConfig(global) {
  const existing = global.SVRMON24 || {};
  global.SVRMON24 = Object.freeze({
    ...existing,
    apiBase: typeof existing.apiBase === "string" ? existing.apiBase : "",
  });
})(typeof window !== "undefined" ? window : globalThis);