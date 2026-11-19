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

  function bindEvents() {
    $("#btnRefreshItsmNotif")?.addEventListener("click", () => loadNotifications());
    $("#itsmNotifStatus")?.addEventListener("change", () => loadNotifications());
    $("#itsmNotifEvent")?.addEventListener("change", () => loadNotifications());
    $("#itsmNotifIncludeArchived")?.addEventListener("change", () => loadNotifications());
  }

  function initItsmNotifications(options) {
    deps = { ...deps, ...(options || {}) };
    bindEvents();
    if (deps.can("itsm:notification:read")) {
      startBadgePolling();
    }
  }

  global.SVRMON24ItsmNotifications = {
    initItsmNotifications,
    loadNotifications,
    refreshBadge,
    startBadgePolling,
    stopBadgePolling,
  };
})(window);
