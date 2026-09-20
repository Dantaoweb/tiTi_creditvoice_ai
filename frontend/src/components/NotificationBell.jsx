import { useEffect, useRef, useState } from "react";
import { Bell, X, Trash2, BellRing, BellOff, Volume2, VolumeX } from "lucide-react";
import { apiFetch, apiPost, apiDelete } from "../lib/api";
import { getPushState, enablePush, disablePush } from "../lib/webpush";

// Chime for a notification that arrives while the app is open. Synthesised, so
// there's no audio file to download. On by default so users learn that alerts
// come through; the toggle is remembered per device.
const SOUND_KEY = "cv_notif_sound";

function soundPref() {
  try { return localStorage.getItem(SOUND_KEY) !== "off"; } catch { return true; }
}

function playChime() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    // Two short notes, quiet enough not to startle.
    [[880, 0], [1175, 0.12]].forEach(([freq, at]) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.28);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + at);
      osc.stop(ctx.currentTime + at + 0.3);
    });
    setTimeout(() => ctx.close().catch(() => {}), 1200);
  } catch { /* audio blocked or unsupported — stay silent */ }
}

const TYPE_ICONS = {
  low_stock:    "⚠️",
  overdue_debt: "💰",
  inactivity:   "👋",
};

export default function NotificationBell() {
  const [notifications, setNotifications] = useState([]);
  const [open, setOpen] = useState(false);
  const [expandedId, setExpandedId] = useState(null);   // tap a notification to read it in full
  const [push, setPush] = useState(null);               // { available, subscribed, key, ... }
  const [pushBusy, setPushBusy] = useState(false);
  const [pushErr, setPushErr] = useState("");
  const [soundOn, setSoundOn] = useState(soundPref);
  const panelRef = useRef(null);
  const seenIds = useRef(null);   // null until the first load, so it never chimes on open

  useEffect(() => {
    if (open && push === null) getPushState().then(setPush).catch(() => setPush({ available: false }));
  }, [open, push]);

  async function togglePush() {
    if (!push) return;
    setPushBusy(true); setPushErr("");
    try {
      if (push.subscribed) {
        await disablePush();
        setPush({ ...push, subscribed: false });
      } else {
        await enablePush(push.key);
        setPush({ ...push, subscribed: true });
      }
    } catch (e) {
      setPushErr(e.message || "Could not change notifications.");
    } finally {
      setPushBusy(false);
    }
  }

  function toggleSound() {
    const next = !soundOn;
    setSoundOn(next);
    try { localStorage.setItem(SOUND_KEY, next ? "on" : "off"); } catch { /* private mode */ }
    if (next) playChime();   // let them hear what they just switched on
  }

  function load() {
    apiFetch("notifications")
      .then(d => {
        const list = d.notifications || [];
        const ids = new Set(list.map(n => n.id));
        const first = seenIds.current === null;
        const fresh = first ? [] : list.filter(n => !n.is_read && !seenIds.current.has(n.id));
        seenIds.current = ids;
        setNotifications(list);
        if (fresh.length && soundPref()) playChime();
      })
      .catch(() => {});
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

          {/* Phone notifications (Web Push) toggle — the silence control */}
          {push && push.available && (
            <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
              {push.subscribed ? <BellRing size={15} color="var(--brand)" /> : <BellOff size={15} color="var(--text-muted)" />}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>Phone notifications</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  {push.subscribed ? "On — alerts reach this device" : "Off — get alerts even when the app is closed"}
                </div>
                {pushErr && <div style={{ fontSize: 11, color: "var(--rose)", marginTop: 2 }}>{pushErr}</div>}
              </div>
              <button
                onClick={togglePush}
                disabled={pushBusy}
                style={{
                  flexShrink: 0, border: "none", borderRadius: 999, cursor: "pointer",
                  padding: "5px 12px", fontSize: 12, fontWeight: 700,
                  background: push.subscribed ? "var(--surface, #eef2f7)" : "var(--brand)",
                  color: push.subscribed ? "var(--text-muted)" : "#fff",
                }}
              >
                {pushBusy ? "…" : push.subscribed ? "Turn off" : "Turn on"}
              </button>
            </div>
          )}

          {/* Chime for alerts that arrive while the app is open */}
          <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
            {soundOn ? <Volume2 size={15} color="var(--brand)" /> : <VolumeX size={15} color="var(--text-muted)" />}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>Notification sound</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                {soundOn ? "On — a chime plays when an alert arrives" : "Off — alerts arrive silently"}
              </div>
            </div>
            <button
              onClick={toggleSound}
              style={{
                flexShrink: 0, border: "none", borderRadius: 999, cursor: "pointer",
                padding: "5px 12px", fontSize: 12, fontWeight: 700,
                background: soundOn ? "var(--surface, #eef2f7)" : "var(--brand)",
                color: soundOn ? "var(--text-muted)" : "#fff",
              }}
            >
              {soundOn ? "Turn off" : "Turn on"}
            </button>
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
