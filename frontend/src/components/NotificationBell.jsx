import { useEffect, useRef, useState } from "react";
import { Bell, X, Trash2 } from "lucide-react";
import { apiFetch, apiPost, apiDelete } from "../lib/api";

const TYPE_ICONS = {
  low_stock:    "⚠️",
  overdue_debt: "💰",
  inactivity:   "👋",
};

export default function NotificationBell() {
  const [notifications, setNotifications] = useState([]);
  const [open, setOpen] = useState(false);
  const [expandedId, setExpandedId] = useState(null);   // tap a notification to read it in full
  const panelRef = useRef(null);

  function load() {
    apiFetch("notifications").then(d => setNotifications(d.notifications || [])).catch(() => {});
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5 * 60 * 1000); // refresh every 5 min
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!open) return;
    function handleClick(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const unread = notifications.filter(n => !n.is_read).length;

  async function markRead(id) {
    await apiPost(`notifications/${id}/read`, {}).catch(() => {});
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
  }

  async function markAllRead() {
    await apiPost("notifications/read-all", {}).catch(() => {});
    setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
  }

  async function deleteOne(id, e) {
    e.stopPropagation();
    setNotifications(prev => prev.filter(n => n.id !== id));  // optimistic
    await apiDelete(`notifications/${id}`).catch(() => {});
  }

  async function clearAll() {
    setNotifications([]);  // optimistic
    await apiFetch("notifications/clear", {}, { method: "POST" }).catch(() => {});
  }

  function timeAgo(iso) {
    if (!iso) return "";
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return `${Math.round(diff / 86400)}d ago`;
  }

  return (
    <div style={{ position: "relative" }} ref={panelRef}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: "none", border: "none", cursor: "pointer",
          position: "relative", padding: 6, color: "var(--ink)",
          display: "flex", alignItems: "center",
        }}
        title="Notifications"
      >
        <Bell size={20} />
        {unread > 0 && (
          <span style={{
            position: "absolute", top: 2, right: 2,
            background: "var(--rose)", color: "#fff",
            borderRadius: "50%", width: 16, height: 16,
            fontSize: 10, fontWeight: 700,
            display: "grid", placeItems: "center",
          }}>
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 8px)", right: 0,
          width: 320, maxHeight: 420,
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 12, boxShadow: "0 8px 32px rgba(0,0,0,0.15)",
          zIndex: 500, display: "flex", flexDirection: "column",
          overflow: "hidden",
        }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "12px 14px", borderBottom: "1px solid var(--border)",
          }}>
            <span style={{ fontWeight: 700, fontSize: 14 }}>Notifications</span>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              {unread > 0 && (
                <button
                  onClick={markAllRead}
                  style={{ fontSize: 11, color: "var(--brand)", background: "none", border: "none", cursor: "pointer" }}
                >
                  Mark all read
                </button>
              )}
              {notifications.length > 0 && (
                <button
                  onClick={clearAll}
                  style={{ fontSize: 11, color: "var(--rose)", background: "none", border: "none", cursor: "pointer" }}
                >
                  Clear all
                </button>
              )}
              <button onClick={() => setOpen(false)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)" }}>
                <X size={14} />
              </button>
            </div>
          </div>

          <div style={{ overflowY: "auto", flex: 1 }}>
            {notifications.length === 0 ? (
              <div style={{ padding: 20, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
                No notifications yet
              </div>
            ) : (
              notifications.map(n => {
                const isOpen = expandedId === n.id;
                return (
                <div
                  key={n.id}
                  onClick={() => { setExpandedId(isOpen ? null : n.id); if (!n.is_read) markRead(n.id); }}
                  style={{
                    padding: "10px 14px",
                    borderBottom: "1px solid var(--border)",
                    background: n.is_read ? "transparent" : "rgba(var(--brand-rgb, 37,99,235),0.04)",
                    cursor: "pointer",
                    transition: "background 0.15s",
                  }}
                >
                  <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                    <span style={{ fontSize: 16, flexShrink: 0 }}>{TYPE_ICONS[n.event_type] || "🔔"}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: n.is_read ? 500 : 700, fontSize: 13, marginBottom: 2 }}>
                        {n.title}
                      </div>
                      <div style={{
                        fontSize: 12, color: "var(--text-muted)", whiteSpace: "pre-line",
                        ...(isOpen ? {} : {
                          overflow: "hidden", textOverflow: "ellipsis",
                          display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                        }),
                      }}>
                        {n.body}
                      </div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
                      <span style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                        {timeAgo(n.created_at)}
                      </span>
                      <button
                        onClick={(e) => deleteOne(n.id, e)}
                        title="Delete"
                        style={{ background: "none", border: "none", cursor: "pointer",
                                 color: "var(--text-muted)", padding: 2, lineHeight: 0 }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
