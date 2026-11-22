/* Monitoring Logs — SIMULATED + LIVE ingest (HTTP/syslog when gates on). */
(function (global) {
  "use strict";

  let apiFn = null;
  let toastFn = null;
  let canFn = () => false;
  let streamNameById = {};
  let liveProbes = false;

  function bindApi(api, { toast, can } = {}) {
    if (typeof api === "function") apiFn = api;
    if (typeof toast === "function") toastFn = toast;
    if (typeof can === "function") canFn = can;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function severityPill(severity) {
    const s = String(severity || "info").toLowerCase();
    let cls = "status-pill";
    if (s === "critical" || s === "error") cls += " danger";
    else if (s === "warning") cls += " warning";
    else if (s === "info") cls += " ok";
    else cls += " muted";
    return `<span class="${cls}">${esc(s)}</span>`;
  }

  function modeBadge(mode) {
    const m = String(mode || "SIMULATED").toUpperCase();
    const cls =
      m === "LIVE" ? "status-pill ok monitor-mode-live" : "status-pill muted";
    return `<span class="${cls}" title="execution_mode">${esc(m)}</span>`;
  }

  function formatWhen(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return esc(iso);
      return esc(d.toLocaleString());
    } catch (_err) {
      return esc(iso);
    }
  }

  function readFilters() {
    return {
      q: document.getElementById("mlSearch")?.value?.trim() || "",
      severity: document.getElementById("mlSeverity")?.value?.trim() || "",
      component_id: document.getElementById("mlComponentId")?.value?.trim() || "",
      stream_id: document.getElementById("mlStream")?.value?.trim() || "",
      source: document.getElementById("mlSource")?.value?.trim() || "",
    };
  }

  function applyAdminGate() {
    const btn = document.getElementById("mlSimulate");
    if (!btn) return;
    btn.hidden = !canFn("monitor:admin");
  }

  async function loadStreams() {
    if (!apiFn) return;
    const select = document.getElementById("mlStream");
    if (!select) return;
    const current = select.value;
    try {
      const data = await apiFn("/api/monitor/logs/streams?page_size=100");
      const items = data.items || [];
      streamNameById = {};
      items.forEach((s) => {
        streamNameById[s.stream_id] = s.name || s.stream_id;
      });
      const opts = ['<option value="">All streams</option>'].concat(
        items.map(
          (s) =>
            `<option value="${esc(s.stream_id)}">${esc(s.name || s.stream_id)}</option>`
        )
      );
      select.innerHTML = opts.join("");
      if (current && streamNameById[current]) select.value = current;
    } catch (_err) {
      /* keep existing options */
    }
  }

  async function loadEvents({ toast } = {}) {
    const notify = toast || toastFn;
    const body = document.getElementById("mlEventsBody");
    const meta = document.getElementById("mlMeta");
    if (!apiFn || !body) return;
    applyAdminGate();
    const filters = readFilters();
    const params = new URLSearchParams();
    params.set("page_size", "50");
    Object.entries(filters).forEach(([k, v]) => {
      if (v) params.set(k, v);
    });
    try {
      const data = await apiFn(`/api/monitor/logs/events?${params.toString()}`);
      const items = data.items || [];
      const retained = data.retained_total != null ? data.retained_total : items.length;
      const limit =
        data.retention_limit == null ? "unlimited" : String(data.retention_limit);
      const hasLive = items.some(
        (row) => String(row.execution_mode || "").toUpperCase() === "LIVE"
      );
      const modeLabel = hasLive
        ? "SIMULATED+LIVE"
        : liveProbes
          ? "gates on (awaiting LIVE ingest)"
          : "SIMULATED";
      if (meta) {
        meta.textContent =
          `${data.total || 0} match(es) · retained ${retained}/${limit} · ` +
          `${modeLabel} · live_probes=${liveProbes ? "true" : "false"}`;
      }
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="7" class="hint">No log events yet. Admins can use ` +
          `<strong>Simulate tick</strong> for SIMULATED demo events, or POST ` +
          `<code>/api/monitor/ingest/logs</code> when live gates are on.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const streamLabel =
            streamNameById[row.stream_id] || row.stream_id || "—";
          return `<tr data-event-id="${esc(row.event_id)}" data-execution-mode="${esc(row.execution_mode || "SIMULATED")}">
            <td class="mono">${formatWhen(row.observed_at)}</td>
            <td>${modeBadge(row.execution_mode)}</td>
            <td>${severityPill(row.severity)}</td>
            <td>${esc(row.source || "—")}</td>
            <td title="${esc(row.stream_id)}">${esc(streamLabel)}</td>
            <td class="mono">${esc(row.component_id || "—")}</td>
            <td>${esc(row.message || "")}</td>
          </tr>`;
        })
        .join("");
    } catch (err) {
      body.innerHTML = `<tr><td colspan="7" class="hint">${esc(
        err.message || "Failed to load log events"
      )}</td></tr>`;
      if (typeof notify === "function") {
        notify(err.message || "Log events load failed", true);
      }
    }
  }

  async function simulateTick({ toast } = {}) {
    const notify = toast || toastFn;
    if (!apiFn) return;
    if (!canFn("monitor:admin")) {
      if (typeof notify === "function") {
        notify("Missing permission monitor:admin", true);
      }
      return;
    }
    try {
      const result = await apiFn("/api/monitor/logs/simulate-tick", {
        method: "POST",
      });
      const msg =
        `Simulated ${result.events_created || 0} event(s)` +
        (result.events_trimmed
          ? ` · trimmed ${result.events_trimmed} for retention`
          : "");
      if (typeof notify === "function") notify(msg, false);
      await loadStreams();
      await loadEvents({ toast: notify });
    } catch (err) {
      if (typeof notify === "function") {
        notify(err.message || "Simulate tick failed", true);
      }
    }
  }

  function initLogsUi() {
    applyAdminGate();
    document.getElementById("mlRefresh")?.addEventListener("click", () => {
      loadStreams().then(() => loadEvents());
    });
    document.getElementById("mlSimulate")?.addEventListener("click", () => {
      simulateTick();
    });
    const onEnter = (ev) => {
      if (ev.key === "Enter") loadEvents();
    };
    document.getElementById("mlSearch")?.addEventListener("keydown", onEnter);
    document
      .getElementById("mlComponentId")
      ?.addEventListener("keydown", onEnter);
    ["mlSeverity", "mlStream", "mlSource"].forEach((id) => {
      document.getElementById(id)?.addEventListener("change", () => loadEvents());
    });
  }

  async function refreshLiveMeta() {
    if (!apiFn) return;
    try {
      const meta = await apiFn("/api/monitor/meta");
      liveProbes = Boolean(meta.live_probes);
      const banner = document.querySelector(
        '#tab-monitor-logs [data-monitor-simulated="1"]'
      );
      if (banner && liveProbes) {
        banner.textContent =
          "Live gates ON — Logs may mix SIMULATED and LIVE events. HTTP ingest " +
          "and optional syslog write LIVE rows when capability gates allow.";
      }
    } catch (_err) {
      liveProbes = false;
    }
  }

  function onShowTab(name) {
    if (name !== "monitor-logs") return;
    applyAdminGate();
    refreshLiveMeta().then(() => loadStreams().then(() => loadEvents()));
  }

  global.SVRMON24MonitorLogs = {
    bindApi,
    initLogsUi,
    loadEvents,
    loadStreams,
    simulateTick,
    onShowTab,
  };
})(window);
