/* Monitoring Alerts — SIMULATED rules + instances (ack/resolve; no auto-incident). */
(function (global) {
  "use strict";

  let apiFn = null;
  let toastFn = null;
  let canFn = () => false;

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

  function statusPill(status) {
    const s = String(status || "firing").toLowerCase();
    let cls = "status-pill";
    if (s === "firing") cls += " danger";
    else if (s === "acked") cls += " warning";
    else if (s === "resolved") cls += " ok";
    else cls += " muted";
    return `<span class="${cls}">${esc(s)}</span>`;
  }

  function severityPill(severity) {
    const s = String(severity || "warning").toLowerCase();
    let cls = "status-pill";
    if (s === "critical" || s === "error") cls += " danger";
    else if (s === "warning") cls += " warning";
    else if (s === "info") cls += " ok";
    else cls += " muted";
    return `<span class="${cls}">${esc(s)}</span>`;
  }

  function conditionLabel(condition) {
    if (!condition || !condition.type) return "—";
    const t = condition.type;
    if (t === "threshold") {
      return `${condition.metric_name || "?"} ${condition.operator || "?"} ${condition.value}`;
    }
    if (t === "log_match") {
      const parts = [];
      if (condition.severity) parts.push(`sev=${condition.severity}`);
      if (condition.message_contains) parts.push(`q=${condition.message_contains}`);
      return `log_match(${parts.join(", ") || "any"})`;
    }
    if (t === "file_change") {
      return condition.path_contains
        ? `file_change(path~${condition.path_contains})`
        : "file_change";
    }
    return esc(t);
  }

  function applyWriteGates() {
    const canWrite = canFn("monitor:alerts:write");
    document.querySelectorAll("[data-monitor-perm-write='monitor:alerts:write']").forEach((el) => {
      el.hidden = !canWrite;
    });
  }

  function readInstanceFilters() {
    return {
      q: document.getElementById("maSearch")?.value?.trim() || "",
      status: document.getElementById("maStatus")?.value?.trim() || "",
      component_id: document.getElementById("maComponentId")?.value?.trim() || "",
    };
  }

  async function loadRules({ toast } = {}) {
    const notify = toast || toastFn;
    const body = document.getElementById("maRulesBody");
    const meta = document.getElementById("maRulesMeta");
    if (!apiFn || !body) return;
    applyWriteGates();
    try {
      const data = await apiFn("/api/monitor/alerts/rules?page_size=100");
      const items = data.items || [];
      const limit = data.rules_limit == null ? "unlimited" : String(data.rules_limit);
      if (meta) {
        meta.textContent =
          `${data.total || 0} rule(s) · limit ${limit} · SIMULATED · live_probes=false`;
      }
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="6" class="hint">No alert rules yet.</td></tr>`;
        return;
      }
      const canWrite = canFn("monitor:alerts:write");
      body.innerHTML = items
        .map((row) => {
          const enabled = row.enabled ? "yes" : "no";
          const actions = canWrite
            ? `<button type="button" class="secondary ma-toggle" data-rule-id="${esc(
                row.rule_id
              )}" data-enabled="${row.enabled ? "1" : "0"}">${
                row.enabled ? "Disable" : "Enable"
              }</button>`
            : "—";
          return `<tr data-rule-id="${esc(row.rule_id)}">
            <td>${esc(row.name || row.rule_id)}</td>
            <td>${severityPill(row.severity)}</td>
            <td class="mono">${esc(conditionLabel(row.condition))}</td>
            <td>${esc(enabled)}</td>
            <td class="mono">${esc(row.rule_id)}</td>
            <td>${actions}</td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".ma-toggle").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-rule-id");
          const currently = btn.getAttribute("data-enabled") === "1";
          toggleRule(id, !currently, { toast: notify });
        });
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="6" class="hint">${esc(
        err.message || "Failed to load rules"
      )}</td></tr>`;
      if (typeof notify === "function") {
        notify(err.message || "Rules load failed", true);
      }
    }
  }

  async function loadInstances({ toast } = {}) {
    const notify = toast || toastFn;
    const body = document.getElementById("maInstancesBody");
    const meta = document.getElementById("maInstancesMeta");
    if (!apiFn || !body) return;
    applyWriteGates();
    const filters = readInstanceFilters();
    const params = new URLSearchParams();
    params.set("page_size", "50");
    Object.entries(filters).forEach(([k, v]) => {
      if (v) params.set(k, v);
    });
    try {
      const data = await apiFn(
        `/api/monitor/alerts/instances?${params.toString()}`
      );
      const items = data.items || [];
      if (meta) {
        meta.textContent =
          `${data.total || 0} match(es) · open ${data.open_count || 0} · ` +
          `SIMULATED · no auto-incident`;
      }
      if (!items.length) {
        body.innerHTML =
          `<tr><td colspan="7" class="hint">No alert instances. Use ` +
          `<strong>Evaluate rules</strong> or Logs → Simulate tick.</td></tr>`;
        return;
      }
      const canWrite = canFn("monitor:alerts:write");
      body.innerHTML = items
        .map((row) => {
          const open = row.status === "firing" || row.status === "acked";
          let actions = "—";
          if (canWrite && open) {
            const bits = [];
            if (row.status === "firing") {
              bits.push(
                `<button type="button" class="secondary ma-ack" data-alert-id="${esc(
                  row.alert_id
                )}">Ack</button>`
              );
            }
            bits.push(
              `<button type="button" class="primary ma-resolve" data-alert-id="${esc(
                row.alert_id
              )}">Resolve</button>`
            );
            actions = bits.join(" ");
          }
          return `<tr data-alert-id="${esc(row.alert_id)}">
            <td class="mono">${formatWhen(row.fired_at)}</td>
            <td>${statusPill(row.status)}</td>
            <td>${severityPill(row.severity)}</td>
            <td>${esc(row.rule_name || row.rule_id || "—")}</td>
            <td class="mono">${esc(row.component_id || "—")}</td>
            <td>${esc(row.summary || "")}</td>
            <td>${actions}</td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".ma-ack").forEach((btn) => {
        btn.addEventListener("click", () =>
          ackAlert(btn.getAttribute("data-alert-id"), { toast: notify })
        );
      });
      body.querySelectorAll(".ma-resolve").forEach((btn) => {
        btn.addEventListener("click", () =>
          resolveAlert(btn.getAttribute("data-alert-id"), { toast: notify })
        );
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="7" class="hint">${esc(
        err.message || "Failed to load instances"
      )}</td></tr>`;
      if (typeof notify === "function") {
        notify(err.message || "Instances load failed", true);
      }
    }
  }

  async function toggleRule(ruleId, enabled, { toast } = {}) {
    const notify = toast || toastFn;
    if (!apiFn || !ruleId) return;
    try {
      await apiFn(`/api/monitor/alerts/rules/${encodeURIComponent(ruleId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (typeof notify === "function") {
        notify(enabled ? "Rule enabled" : "Rule disabled", false);
      }
      await loadRules({ toast: notify });
    } catch (err) {
      if (typeof notify === "function") {
        notify(err.message || "Rule update failed", true);
      }
    }
  }

  async function createRuleFromForm({ toast } = {}) {
    const notify = toast || toastFn;
    if (!apiFn) return;
    if (!canFn("monitor:alerts:write")) {
      if (typeof notify === "function") {
        notify("Missing permission monitor:alerts:write", true);
      }
      return;
    }
    const name = document.getElementById("maRuleName")?.value?.trim() || "";
    const severity =
      document.getElementById("maRuleSeverity")?.value?.trim() || "warning";
    const ctype =
      document.getElementById("maRuleType")?.value?.trim() || "log_match";
    if (!name) {
      if (typeof notify === "function") notify("Rule name is required", true);
      return;
    }
    let condition = { type: ctype };
    if (ctype === "threshold") {
      const metric =
        document.getElementById("maRuleMetric")?.value?.trim() || "cpu_pct";
      const op = document.getElementById("maRuleOp")?.value?.trim() || "gt";
      const value = Number(
        document.getElementById("maRuleValue")?.value ?? "80"
      );
      condition = {
        type: "threshold",
        metric_name: metric,
        operator: op,
        value,
      };
    } else if (ctype === "log_match") {
      const sev =
        document.getElementById("maRuleLogSev")?.value?.trim() || "error,critical";
      const msg =
        document.getElementById("maRuleLogMsg")?.value?.trim() || "";
      condition = { type: "log_match", severity: sev };
      if (msg) condition.message_contains = msg;
    } else {
      const path =
        document.getElementById("maRulePath")?.value?.trim() || "";
      condition = { type: "file_change" };
      if (path) condition.path_contains = path;
    }
    try {
      const doc = await apiFn("/api/monitor/alerts/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          severity,
          enabled: true,
          condition,
          scope: {},
        }),
      });
      if (typeof notify === "function") {
        notify(`Created rule ${doc.rule_id}`, false);
      }
      const nameEl = document.getElementById("maRuleName");
      if (nameEl) nameEl.value = "";
      await loadRules({ toast: notify });
    } catch (err) {
      if (typeof notify === "function") {
        notify(err.message || "Create rule failed", true);
      }
    }
  }

  async function evaluateRules({ toast } = {}) {
    const notify = toast || toastFn;
    if (!apiFn) return;
    if (!canFn("monitor:alerts:write")) {
      if (typeof notify === "function") {
        notify("Missing permission monitor:alerts:write", true);
      }
      return;
    }
    try {
      const result = await apiFn("/api/monitor/alerts/evaluate", {
        method: "POST",
      });
      const msg =
        `Evaluated ${result.rules_evaluated || 0} rule(s) · ` +
        `created ${result.created || 0} · open ${result.open_count || 0}`;
      if (typeof notify === "function") notify(msg, false);
      await loadRules({ toast: notify });
      await loadInstances({ toast: notify });
    } catch (err) {
      if (typeof notify === "function") {
        notify(err.message || "Evaluate failed", true);
      }
    }
  }

  async function ackAlert(alertId, { toast } = {}) {
    const notify = toast || toastFn;
    if (!apiFn || !alertId) return;
    try {
      await apiFn(
        `/api/monitor/alerts/instances/${encodeURIComponent(alertId)}/ack`,
        { method: "POST" }
      );
      if (typeof notify === "function") notify("Alert acknowledged", false);
      await loadInstances({ toast: notify });
    } catch (err) {
      if (typeof notify === "function") {
        notify(err.message || "Ack failed", true);
      }
    }
  }

  async function resolveAlert(alertId, { toast } = {}) {
    const notify = toast || toastFn;
    if (!apiFn || !alertId) return;
    try {
      await apiFn(
        `/api/monitor/alerts/instances/${encodeURIComponent(alertId)}/resolve`,
        { method: "POST" }
      );
      if (typeof notify === "function") notify("Alert resolved", false);
      await loadInstances({ toast: notify });
    } catch (err) {
      if (typeof notify === "function") {
        notify(err.message || "Resolve failed", true);
      }
    }
  }

  function syncConditionFields() {
    const ctype = document.getElementById("maRuleType")?.value || "log_match";
    document.querySelectorAll("[data-ma-cond]").forEach((el) => {
      el.hidden = el.getAttribute("data-ma-cond") !== ctype;
    });
  }

  function initAlertsUi() {
    applyWriteGates();
    syncConditionFields();
    document.getElementById("maRefresh")?.addEventListener("click", () => {
      loadRules().then(() => loadInstances());
    });
    document.getElementById("maEvaluate")?.addEventListener("click", () => {
      evaluateRules();
    });
    document.getElementById("maCreateRule")?.addEventListener("click", () => {
      createRuleFromForm();
    });
    document.getElementById("maRuleType")?.addEventListener("change", () => {
      syncConditionFields();
    });
    const onEnter = (ev) => {
      if (ev.key === "Enter") loadInstances();
    };
    document.getElementById("maSearch")?.addEventListener("keydown", onEnter);
    document
      .getElementById("maComponentId")
      ?.addEventListener("keydown", onEnter);
    document.getElementById("maStatus")?.addEventListener("change", () => {
      loadInstances();
    });
  }

  function onShowTab(name) {
    if (name !== "monitor-alerts") return;
    applyWriteGates();
    loadRules().then(() => loadInstances());
  }

  global.SVRMON24MonitorAlerts = {
    bindApi,
    initAlertsUi,
    loadRules,
    loadInstances,
    evaluateRules,
    ackAlert,
    resolveAlert,
    onShowTab,
  };
})(window);
