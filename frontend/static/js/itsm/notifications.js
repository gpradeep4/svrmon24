/* global SVRMON24ItsmApi */
(function (global) {
  "use strict";

  let deps = { can: () => false, toast: () => {}, escapeHtml: (s) => s };
  let badgeTimer = null;

  function $(sel) {
    return document.querySelector(sel);
  }

  function esc(s) {
    return deps.escapeHtml(s == null ? "" : String(s));
  }

  function fmtWhen(value) {
    if (!value) return "—";
    try {
      return new Date(value).toLocaleString();
    } catch (_) {
      return String(value);
    }
  }

  function setBadge(count) {
    const badge = $("#itsmNotifBadge");
    const navBadge = $("#itsmNotifNavBadge");
    const n = Math.max(0, Number(count) || 0);
    const label = n > 99 ? "99+" : String(n);
    [badge, navBadge].forEach((el) => {
      if (!el) return;
      el.textContent = label;
      el.hidden = n <= 0;
      el.setAttribute("aria-label", `${n} unread notifications`);
    });
  }

  async function refreshBadge() {
    if (!deps.can("itsm:notification:read")) {
      setBadge(0);
      return;
    }
    try {
      const data = await SVRMON24ItsmApi.notificationUnreadCount();
      setBadge(data.unread_count || 0);
    } catch (_) {
      /* badge is best-effort */
    }
  }

  function startBadgePolling() {
    stopBadgePolling();
    refreshBadge();
    badgeTimer = window.setInterval(refreshBadge, 60000);
  }

  function stopBadgePolling() {
    if (badgeTimer) {
      window.clearInterval(badgeTimer);
      badgeTimer = null;
    }
  }

  async function loadNotifications() {
    const body = $("#itsmNotifBody");
    const meta = $("#itsmNotifListMeta");
    if (!body) return;
    const params = {
      page: "1",
      page_size: "50",
      sort_by: "created_at",
      sort_dir: "desc",
    };
    const status = $("#itsmNotifStatus")?.value;
    const eventType = $("#itsmNotifEvent")?.value;
    const includeArchived = $("#itsmNotifIncludeArchived")?.checked;
    if (status) params.status = status;
    if (eventType) params.event_type = eventType;
    if (includeArchived) params.include_archived = "true";
    try {
      const data = await SVRMON24ItsmApi.listNotifications(params);
      const items = data.items || [];
      setBadge(data.unread_count || 0);
      if (meta) {
        meta.textContent = `${data.total || 0} notification(s) · ${data.unread_count || 0} unread · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="6" class="hint">No notifications in this view.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map((row) => {
          const ticket =
            row.ticket_type && row.ticket_id
              ? `${esc(row.ticket_type)} ${esc(row.ticket_id)}`
              : "—";
          const unreadClass = row.status === "unread" ? " itsm-notif-unread" : "";
          return `<tr class="itsm-notif-row${unreadClass}" data-notification-id="${esc(row.notification_id)}">
            <td><span class="itsm-status is-${esc(row.status)}">${esc(row.status)}</span></td>
            <td><span class="itsm-notif-event">${esc(row.event_type)}</span></td>
            <td>
              <button type="button" class="ghost itsm-notif-open" data-id="${esc(row.notification_id)}">${esc(row.subject)}</button>
              <div class="hint itsm-notif-body">${esc(row.body)}</div>
            </td>
            <td>${ticket}</td>
            <td>${esc(fmtWhen(row.created_at))}</td>
            <td class="itsm-notif-actions">
              ${
                row.status !== "read"
                  ? `<button type="button" class="ghost itsm-notif-read" data-id="${esc(row.notification_id)}">Read</button>`
                  : `<button type="button" class="ghost itsm-notif-unread" data-id="${esc(row.notification_id)}">Unread</button>`
              }
              ${
                row.status !== "archived"
                  ? `<button type="button" class="ghost itsm-notif-archive" data-id="${esc(row.notification_id)}">Archive</button>`
                  : ""
              }
            </td>
          </tr>`;
        })
        .join("");
      body.querySelectorAll(".itsm-notif-open").forEach((btn) => {
        btn.addEventListener("click", () => openNotification(btn.getAttribute("data-id")));
      });
      body.querySelectorAll(".itsm-notif-read").forEach((btn) => {
        btn.addEventListener("click", () => markStatus(btn.getAttribute("data-id"), "read"));
      });
      body.querySelectorAll(".itsm-notif-unread").forEach((btn) => {
        btn.addEventListener("click", () => markStatus(btn.getAttribute("data-id"), "unread"));
      });
      body.querySelectorAll(".itsm-notif-archive").forEach((btn) => {
        btn.addEventListener("click", () => markStatus(btn.getAttribute("data-id"), "archive"));
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="6" class="hint">${esc(err.message || "Failed")}</td></tr>`;
      deps.toast(err.message || "Notifications failed", true);
    }
  }

  function showTab(name) {
    const nav = document.querySelector(`[data-tab="${name}"]`);
    if (nav) nav.click();
  }

  async function openLinkedTicket(doc) {
    const ticketType = doc.ticket_type;
    const ticketId = doc.ticket_id;
    const approvalId = doc.approval_id;
    const portalRequestId = doc.portal_request_id;
    // Portal ↔ Change deep-link: prefer Service Portal Change-status / My requests.
    if (portalRequestId) {
      const portalTab =
        (doc.event_type || "").startsWith("approval") || ticketType === "change"
          ? "sp-approvals"
          : "sp-my-requests";
      showTab(portalTab);
      window.setTimeout(() => {
        if (portalTab === "sp-approvals") {
          global.SVRMON24PortalApprovals?.onShowTab?.("sp-approvals");
        } else {
          global.SVRMON24PortalRequests?.onShowTab?.("sp-my-requests");
        }
      }, 120);
      return;
    }
    if (approvalId && (doc.event_type || "").startsWith("approval")) {
      showTab("itsm-approvals");
      window.setTimeout(() => {
        global.SVRMON24ItsmApprovals?.openApproval?.(approvalId);
      }, 120);
      return;
    }
    if (ticketType === "incident" && ticketId) {
      showTab("itsm-incidents");
      window.setTimeout(() => {
        global.SVRMON24ItsmIncidents?.openIncident?.(ticketId);
      }, 120);
      return;
    }
    if (ticketType === "change" && ticketId) {
      showTab("itsm-changes");
      window.setTimeout(() => {
        global.SVRMON24ItsmChanges?.openChange?.(ticketId);
      }, 120);
      return;
    }
    if (ticketType === "problem" && ticketId) {
      showTab("itsm-problems");
      window.setTimeout(() => {
        global.SVRMON24ItsmProblems?.openProblem?.(ticketId);
      }, 120);
      return;
    }
    if (doc.event_type === "sla_breach") {
      showTab("itsm-sla");
    }
  }

  async function openNotification(notificationId) {
    try {
      const doc = await SVRMON24ItsmApi.getNotification(notificationId);
      if (doc.status === "unread") {
        await SVRMON24ItsmApi.markNotificationRead(notificationId);
      }
      await openLinkedTicket(doc);
      await loadNotifications();
      await refreshBadge();
    } catch (err) {
      deps.toast(err.message || "Open notification failed", true);
    }
  }

  async function markStatus(notificationId, action) {
    try {
      if (action === "read") await SVRMON24ItsmApi.markNotificationRead(notificationId);
      else if (action === "unread")
        await SVRMON24ItsmApi.markNotificationUnread(notificationId);
      else if (action === "archive")
        await SVRMON24ItsmApi.markNotificationArchive(notificationId);
      await loadNotifications();
      await refreshBadge();
    } catch (err) {
      deps.toast(err.message || "Update failed", true);
    }
  }

  function fillEmailForm(cfg) {
    if (!cfg) return;
    const en = $("#itsmNotifEmailEnabled");
    if (en) en.checked = !!cfg.enabled;
    const host = $("#itsmNotifSmtpHost");
    if (host) host.value = cfg.smtp_host || "";
    const port = $("#itsmNotifSmtpPort");
    if (port) port.value = cfg.smtp_port != null ? String(cfg.smtp_port) : "587";
    const tls = $("#itsmNotifSmtpTls");
    if (tls) tls.checked = cfg.smtp_use_tls !== false;
    const user = $("#itsmNotifSmtpUser");
    if (user) user.value = cfg.smtp_username || "";
    const pref = $("#itsmNotifSmtpPassRef");
    if (pref) pref.value = cfg.smtp_password_env_ref || "";
    const from = $("#itsmNotifFromAddr");
    if (from) from.value = cfg.from_address || "";
    const meta = $("#itsmNotifEmailMeta");
    if (meta) {
      meta.textContent = cfg.enabled
        ? `Email channel enabled · host ${cfg.smtp_host || "(unset)"}`
        : "Email channel disabled — emits stay in-app only until enabled.";
    }
  }

  function fillSmsForm(cfg) {
    if (!cfg) return;
    const en = $("#itsmNotifSmsEnabled");
    if (en) en.checked = !!cfg.enabled;
    const sid = $("#itsmNotifSmsSidRef");
    if (sid) sid.value = cfg.twilio_account_sid_env_ref || "";
    const tok = $("#itsmNotifSmsTokenRef");
    if (tok) tok.value = cfg.twilio_auth_token_env_ref || "";
    const from = $("#itsmNotifSmsFrom");
    if (from) from.value = cfg.twilio_from_number || "";
  }

  function fillSlackForm(cfg) {
    if (!cfg) return;
    const en = $("#itsmNotifSlackEnabled");
    if (en) en.checked = !!cfg.enabled;
    const wh = $("#itsmNotifSlackWebhookRef");
    if (wh) wh.value = cfg.webhook_url_env_ref || "";
    const tok = $("#itsmNotifSlackTokenRef");
    if (tok) tok.value = cfg.bot_token_env_ref || "";
    const ch = $("#itsmNotifSlackDefault");
    if (ch) ch.value = cfg.default_channel || "";
  }

  async function loadChannelSettings() {
    const panel = $("#itsmNotifChannelsPanel");
    if (!panel) return;
    if (!deps.can("itsm:notification:admin")) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    try {
      const data = await SVRMON24ItsmApi.listNotificationChannels();
      const byChannel = {};
      (data.items || []).forEach((row) => {
        byChannel[row.channel] = row;
      });
      fillEmailForm(byChannel.email);
      fillSmsForm(byChannel.sms);
      fillSlackForm(byChannel.slack);
      await loadDeliveries();
    } catch (err) {
      deps.toast(err.message || "Channel settings failed", true);
    }
  }

  async function loadDeliveries() {
    const body = $("#itsmNotifDeliveryBody");
    const meta = $("#itsmNotifDeliveryMeta");
    if (!body || !deps.can("itsm:notification:admin")) return;
    try {
      const data = await SVRMON24ItsmApi.listNotificationDeliveries({
        page: "1",
        page_size: "25",
      });
      const items = data.items || [];
      if (meta) {
        meta.textContent = `${data.total || 0} delivery attempt(s) · tenant ${data.tenant_id || ""}`;
      }
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="6" class="hint">No delivery attempts yet.</td></tr>`;
        return;
      }
      body.innerHTML = items
        .map(
          (row) => `<tr>
            <td><span class="itsm-status is-${esc(row.status)}">${esc(row.status)}</span></td>
            <td>${esc(row.channel)}</td>
            <td>${esc(row.recipient_address || row.recipient_user_id || "—")}</td>
            <td>${esc(row.provider || "—")}</td>
            <td>${esc(row.error || "—")}</td>
            <td>${esc(fmtWhen(row.created_at))}</td>
          </tr>`
        )
        .join("");
    } catch (err) {
      body.innerHTML = `<tr><td colspan="6" class="hint">${esc(err.message || "Failed")}</td></tr>`;
    }
  }

  async function saveEmailChannel() {
    try {
      const payload = {
        enabled: !!$("#itsmNotifEmailEnabled")?.checked,
        smtp_host: $("#itsmNotifSmtpHost")?.value || null,
        smtp_port: Number($("#itsmNotifSmtpPort")?.value || 587),
        smtp_use_tls: !!$("#itsmNotifSmtpTls")?.checked,
        smtp_username: $("#itsmNotifSmtpUser")?.value || null,
        smtp_password_env_ref: $("#itsmNotifSmtpPassRef")?.value || null,
        from_address: $("#itsmNotifFromAddr")?.value || null,
      };
      const saved = await SVRMON24ItsmApi.putNotificationChannelEmail(payload);
      fillEmailForm(saved);
      deps.toast("Email channel saved");
    } catch (err) {
      deps.toast(err.message || "Save failed", true);
    }
  }

  async function saveSmsChannel() {
    try {
      const payload = {
        enabled: !!$("#itsmNotifSmsEnabled")?.checked,
        twilio_account_sid_env_ref: $("#itsmNotifSmsSidRef")?.value || null,
        twilio_auth_token_env_ref: $("#itsmNotifSmsTokenRef")?.value || null,
        twilio_from_number: $("#itsmNotifSmsFrom")?.value || null,
      };
      const saved = await SVRMON24ItsmApi.putNotificationChannelSms(payload);
      fillSmsForm(saved);
      deps.toast("SMS channel saved");
    } catch (err) {
      deps.toast(err.message || "Save failed", true);
    }
  }

  async function saveSlackChannel() {
    try {
      const payload = {
        enabled: !!$("#itsmNotifSlackEnabled")?.checked,
        webhook_url_env_ref: $("#itsmNotifSlackWebhookRef")?.value || null,
        bot_token_env_ref: $("#itsmNotifSlackTokenRef")?.value || null,
        default_channel: $("#itsmNotifSlackDefault")?.value || null,
      };
      const saved = await SVRMON24ItsmApi.putNotificationChannelSlack(payload);
      fillSlackForm(saved);
      deps.toast("Slack channel saved");
    } catch (err) {
      deps.toast(err.message || "Save failed", true);
    }
  }

  function bindEvents() {
    $("#btnRefreshItsmNotif")?.addEventListener("click", () => loadNotifications());
    $("#itsmNotifStatus")?.addEventListener("change", () => loadNotifications());
    $("#itsmNotifEvent")?.addEventListener("change", () => loadNotifications());
    $("#itsmNotifIncludeArchived")?.addEventListener("change", () => loadNotifications());
    $("#btnSaveItsmNotifEmail")?.addEventListener("click", () => saveEmailChannel());
    $("#btnSaveItsmNotifSms")?.addEventListener("click", () => saveSmsChannel());
    $("#btnSaveItsmNotifSlack")?.addEventListener("click", () => saveSlackChannel());
    $("#btnRefreshItsmDeliveries")?.addEventListener("click", () => loadDeliveries());
  }

  function initItsmNotifications(options) {
    deps = { ...deps, ...(options || {}) };
    bindEvents();
    if (deps.can("itsm:notification:read")) {
      startBadgePolling();
    }
    loadChannelSettings();
  }

  global.SVRMON24ItsmNotifications = {
    initItsmNotifications,
    loadNotifications,
    loadChannelSettings,
    loadDeliveries,
    refreshBadge,
    startBadgePolling,
    stopBadgePolling,
  };
})(window);
