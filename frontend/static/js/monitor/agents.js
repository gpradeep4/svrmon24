/* global SVRMON24 */
(function (global) {
  "use strict";

  let api = null;
  let toast = null;
  let canFn = () => false;

  function notify(msg, isError) {
    if (typeof toast === "function") toast(msg, isError);
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setMeta(text) {
    const el = document.getElementById("magMeta");
    if (el) el.textContent = text;
  }

  function setBanner(liveAgent) {
    const banner = document.getElementById("magBanner");
    if (!banner) return;
    if (liveAgent) {
      banner.textContent =
        "Live agent gates are ON — enroll agents with one-time codes. Tokens are hashed at rest; mTLS sketch is optional (MONITOR_AGENT_MTLS_ENABLED).";
      banner.removeAttribute("data-monitor-simulated");
    } else {
      banner.textContent =
        "Agent registration is fail-closed — enable platform MONITOR_LIVE_* and tenant monitor_live_agent_opt_in to enroll agents. Tokens are hashed at rest; mTLS is an optional sketch.";
      banner.setAttribute("data-monitor-simulated", "1");
    }
  }

  function bindApi(apiClient, opts) {
    api = apiClient;
    toast = opts && opts.toast;
    if (opts && typeof opts.can === "function") canFn = opts.can;
  }

  function initAgentsUi() {
    document.getElementById("magRefresh")?.addEventListener("click", () => {
      loadAgents();
    });
    document.getElementById("magEnroll")?.addEventListener("click", () => {
      createEnrollment();
    });
  }

  async function loadAgents() {
    if (!api) return;
    if (!canFn("monitor:admin") && !canFn("monitor:targets:read")) {
      setMeta("Missing permission to view agents.");
      return;
    }
    try {
      const meta = await api("/api/monitor/meta");
      const gates = (meta && meta.live_gates) || {};
      setBanner(!!gates.agent);

      const listed = await api("/api/monitor/agents");
      const items = (listed && listed.items) || [];
      const body = document.getElementById("magAgentsBody");
      if (body) {
        if (!items.length) {
          body.innerHTML =
            '<tr><td colspan="6">No agents registered yet.</td></tr>';
        } else {
          body.innerHTML = items
            .map((a) => {
              const id = esc(a.agent_id);
              const revokeBtn =
                canFn("monitor:admin") && a.status !== "revoked"
                  ? `<button type="button" class="secondary mag-revoke" data-agent-id="${id}">Revoke</button>`
                  : "";
              return `<tr>
                <td><code>${id}</code><div class="hint">${esc(a.name)}</div></td>
                <td>${esc(a.hostname || "—")}</td>
                <td>${esc(a.os_family || "—")}${a.os_name ? " / " + esc(a.os_name) : ""}</td>
                <td><span class="status-pill ${a.status === "active" ? "ok" : a.status === "revoked" ? "danger" : "muted"}">${esc(a.status)}</span></td>
                <td>${esc(a.last_seen_at || "—")}</td>
                <td>${revokeBtn}</td>
              </tr>`;
            })
            .join("");
          body.querySelectorAll(".mag-revoke").forEach((btn) => {
            btn.addEventListener("click", () => {
              revokeAgent(btn.getAttribute("data-agent-id"));
            });
          });
        }
      }
      setMeta(
        `Agents: ${listed.total || items.length}` +
          (gates.agent ? " · live agent gate ON" : " · live agent gate OFF")
      );

      if (canFn("monitor:admin")) {
        await loadEnrollments();
      }
    } catch (err) {
      setMeta(err && err.message ? err.message : "Failed to load agents");
      notify("Failed to load agents", true);
    }
  }

  async function loadEnrollments() {
    const body = document.getElementById("magEnrollBody");
    if (!body || !api) return;
    try {
      const listed = await api("/api/monitor/agents/enrollments");
      const items = (listed && listed.items) || [];
      if (!items.length) {
        body.innerHTML =
          '<tr><td colspan="4">No enrollments yet.</td></tr>';
        return;
      }
      body.innerHTML = items
        .map(
          (e) => `<tr>
            <td><code>${esc(e.enrollment_id)}</code></td>
            <td>${esc(e.label || "—")}</td>
            <td>${esc(e.status)}</td>
            <td>${esc(e.expires_at || "—")}</td>
          </tr>`
        )
        .join("");
    } catch (err) {
      body.innerHTML = `<tr><td colspan="4">${esc(err.message || "Failed")}</td></tr>`;
    }
  }

  async function createEnrollment() {
    if (!api) return;
    if (!canFn("monitor:admin")) {
      notify("Missing permission monitor:admin", true);
      return;
    }
    const label = (document.getElementById("magEnrollLabel")?.value || "").trim();
    const resultEl = document.getElementById("magEnrollResult");
    try {
      const created = await api("/api/monitor/agents/enrollments", {
        method: "POST",
        body: JSON.stringify({ label: label || null }),
      });
      if (resultEl) {
        resultEl.hidden = false;
        resultEl.innerHTML = `Enrollment <code>${esc(created.enrollment_id)}</code> created. Code (shown once): <code>${esc(created.code)}</code>`;
      }
      notify("Enrollment created — copy the code now");
      await loadAgents();
    } catch (err) {
      notify(err && err.message ? err.message : "Enrollment failed", true);
    }
  }

  async function revokeAgent(agentId) {
    if (!api || !agentId) return;
    if (!canFn("monitor:admin")) {
      notify("Missing permission monitor:admin", true);
      return;
    }
    try {
      await api(`/api/monitor/agents/${encodeURIComponent(agentId)}/revoke`, {
        method: "POST",
        body: "{}",
      });
      notify(`Revoked ${agentId}`);
      await loadAgents();
    } catch (err) {
      notify(err && err.message ? err.message : "Revoke failed", true);
    }
  }

  function onShowTab(name) {
    if (name !== "monitor-agents") return;
    loadAgents();
  }

  global.SVRMON24MonitorAgents = {
    bindApi,
    initAgentsUi,
    loadAgents,
    onShowTab,
  };
})(window);
