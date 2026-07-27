import { useState, useEffect } from "react";
import { NavLink, Outlet, useNavigate, useLocation } from "react-router-dom";
import {
  MessageSquare, LayoutDashboard, Users, ArrowLeftRight,
  Package, Bell, Truck, UserCheck, ShoppingCart, LogOut, Wallet, PlusCircle, MapPin, Zap,
  Handshake, FileText, Menu, X, ShieldCheck, Activity, Sparkles, ArrowUpCircle, Receipt, PackageCheck, ScrollText,
  MoreHorizontal, ChevronDown, UserCircle,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { getBizLabels } from "../lib/bizLabels";
import { apiFetch, apiPost } from "../lib/api";
import { useOfflineSync } from "../lib/useOfflineSync";
import TitiPanel from "./TitiPanel";
import NotificationBell from "./NotificationBell";

function buildNav(L, group) {
  // Businesses that don't sell products (savings/ajo, dues collection) get the
  // product-centric items deprioritized off the primary tab bar — mirroring the
  // WhatsApp home menu, which omits stock/POS for these groups.
  const noProducts = group === "thrift" || group === "fee";
  const isThrift = group === "thrift";
  return [
    { to: "/home",         label: "Chat with tiTi",  icon: MessageSquare,   tab: true  },
    { to: "/capture",      label: L.record,           icon: PlusCircle,      tab: true  },
    { to: "/pos",          label: L.pos,              icon: ShoppingCart,    tab: !noProducts },
    { to: "/inventory",    label: L.stock,            icon: Package,         tab: !noProducts },
    { to: "/customers",    label: L.navCustomers,     icon: Users,           tab: true  },
    { to: "/thrift",       label: "Thrift / Ajo",     icon: Activity,        tab: isThrift },
    { to: "/reminders",    label: L.reminders,        icon: Bell            },
    { to: "/dashboard",    label: "Dashboard",        icon: LayoutDashboard },
    { to: "/receipts",     label: "Receipts",         icon: Receipt },
    { to: "/invoices",     label: "Invoices",         icon: ScrollText },
    { to: "/deliveries",   label: "Deliveries",       icon: PackageCheck },
    { to: "/wallet",       label: "Wallet ✦",         icon: Wallet, badge: "soon" },
    { section: "More" },
    { to: "/transactions", label: "Transactions",     icon: ArrowLeftRight  },
    { to: "/suppliers",    label: "Suppliers",        icon: Truck           },
    { to: "/staff",        label: "Staff",            icon: UserCheck       },
    { to: "/partners",     label: "Partners",         icon: Handshake       },
    { to: "/notes",        label: "Notes",            icon: FileText        },
    { to: "/branches",     label: "Branches",         icon: MapPin          },
    { to: "/automation",    label: "Automation",       icon: Zap               },
    { to: "/opportunities", label: "Opportunities",   icon: Sparkles          },
    { to: "/admin",         label: "Admin",           icon: ShieldCheck, adminOnly: true },
    { to: "/profile",       label: "My Profile",      icon: UserCircle },
    { to: "/upgrade",       label: "Upgrade Plan ✦",  icon: ArrowUpCircle },
  ];
}

export default function Layout() {
  const { ownerPhone, setOwnerPhone, period, setPeriod } = useApp();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [titiNumber, setTitiNumber] = useState("");
  const [oppsUnread, setOppsUnread] = useState(0);
  // Remember whether "More" was expanded, per device.
  const [moreOpen, setMoreOpen] = useState(() => localStorage.getItem("cv_more_open") === "1");
  function toggleMore() {
    setMoreOpen(o => { const n = !o; localStorage.setItem("cv_more_open", n ? "1" : "0"); return n; });
  }
  // Dashboard joins the always-visible primary set (checked daily), on top of
  // the mobile tab-bar items — without adding it to the bottom bar itself.
  const isPrimary = (item) => item.tab || item.to === "/dashboard";

  useEffect(() => {
    apiFetch("auth/config").then(d => setTitiNumber(d.titi_whatsapp || "")).catch(() => {});
  }, []);

  // Persistent "new opportunities" badge: count opportunities created after the
  // last time this user opened the Opportunities page. Stays until they check
  // it (the marker is only advanced by visiting /opportunities), and re-checks
  // whenever they navigate so a freshly-posted opportunity lights up.
  useEffect(() => {
    apiFetch("opportunities").then(d => {
      const opps = d.opportunities || [];
      const seenAt = localStorage.getItem("cv_opps_seen_at") || "";
      const unseen = opps.filter(o => (o.created_at || "") > seenAt).length;
      setOppsUnread(unseen);
    }).catch(() => {});
  }, [location.pathname]);

  // Clear the badge the moment they're on the Opportunities page.
  useEffect(() => {
    if (location.pathname === "/opportunities") {
      localStorage.setItem("cv_opps_seen_at", new Date().toISOString());
      setOppsUnread(0);
    }
  }, [location.pathname]);

  const L = getBizLabels(user?.menu_group);
  const isAdmin = user?.role === "app_admin" || user?.is_app_admin;
  const NAV = buildNav(L, user?.menu_group).filter(item => !item.adminOnly || isAdmin);
  const { isOnline, pending, failed, syncing, dismissFailed } = useOfflineSync();

  const TITLES = {
    "/home":         "Chat with tiTi",
    "/capture":      "Quick Record",
    "/pos":          "Select product",
    "/receipts":     "Receipts",
    "/invoices":     "Invoices",
    "/deliveries":   "Deliveries",
    "/inventory":    L.stock,
    "/customers":    L.navCustomers,
    "/reminders":    L.reminders,
    "/dashboard":    "Dashboard",
    "/transactions": "Transactions",
    "/suppliers":    "Suppliers",
    "/staff":        "Staff",
    "/partners":     "Partners & Investors",
    "/notes":        "Business Notes",
    "/wallet":       "Wallet",
    "/thrift":       "Thrift / Ajo Savings",
    "/branches":     "Branches",
    "/automation":    "Automation",
    "/opportunities": "Opportunities",
    "/admin":         "Admin Dashboard",
    "/profile":       "My Profile",
    "/upgrade":       "Upgrade Plan",
  };

  const path = location.pathname.replace("/app", "") || "/home";
  const title = TITLES[path] || "CreditVoice";

  const tabItems = NAV.filter(item => item.tab);

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  async function handleLogoutAll() {
    if (!window.confirm("Sign out of ALL devices? You'll need to log in again everywhere.")) return;
    try { await apiPost("auth/logout-all", {}); } catch { /* proceed regardless */ }
    logout();
    navigate("/login", { replace: true });
  }

  function closeDrawer() { setDrawerOpen(false); }

  function renderNavItem(item) {
    if (item.disabled) {
      return (
        <div key={item.label} className="nav-link nav-link-disabled">
          <item.icon size={16} />
          <span className="nav-label">{item.label}</span>
          {item.badge && <span className="nav-badge">{item.badge}</span>}
        </div>
      );
    }
    return (
      <NavLink
        key={item.to}
        to={item.to}
        className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
        onClick={closeDrawer}
      >
        <item.icon size={16} />
        <span className="nav-label">{item.label}</span>
        {item.badge && <span className="nav-badge">{item.badge}</span>}
        {item.to === "/opportunities" && oppsUnread > 0 && (
          <span className="nav-badge nav-badge-alert">{oppsUnread}</span>
        )}
      </NavLink>
    );
  }

  return (
    <div className="shell">
      {/* Drawer overlay (mobile) */}
      <div
        className={`sidebar-overlay${drawerOpen ? " visible" : ""}`}
        onClick={closeDrawer}
      />

      <aside className={`sidebar${drawerOpen ? " sidebar-open" : ""}`}>
        <div className="sidebar-brand">
          <img src="/app/logo.png" alt="CreditVoice" style={{ width: 44, height: 44, borderRadius: 8, objectFit: "cover" }} />
          {/* Close button inside drawer on mobile */}
          <button
            onClick={closeDrawer}
            style={{
              marginLeft: "auto", background: "none", border: "none",
              color: "rgba(255,255,255,0.6)", cursor: "pointer", padding: 4,
            }}
            className="topbar-menu-btn"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="sidebar-nav">
          {/* Primary items first (the same set pinned to the mobile tab bar).
              Secondary features live behind "More" — two taps to reach, so the
              sidebar stays short and the essentials are always in view. */}
          {NAV.filter(i => i.to && isPrimary(i)).map(renderNavItem)}

          {NAV.some(i => i.to && !isPrimary(i)) && (
            <button
              type="button"
              className={`nav-link nav-more-btn${moreOpen ? " active" : ""}`}
              onClick={toggleMore}
            >
              <MoreHorizontal size={16} />
              <span className="nav-label">{moreOpen ? "Less" : "More"}</span>
              {/* When collapsed, surface the opportunities alert on More itself */}
              {!moreOpen && oppsUnread > 0 && (
                <span className="nav-badge nav-badge-alert">{oppsUnread}</span>
              )}
              <ChevronDown
                size={15}
                style={{ marginLeft: !moreOpen && oppsUnread > 0 ? 6 : "auto",
                         transform: moreOpen ? "rotate(180deg)" : "none", transition: "transform 0.15s" }}
              />
            </button>
          )}

          {moreOpen && NAV.filter(i => i.to && !isPrimary(i)).map(renderNavItem)}
        </nav>

        {titiNumber && (
          <a
            href={`https://wa.me/${titiNumber}?text=${encodeURIComponent("Hello")}`}
            target="_blank"
            rel="noopener noreferrer"
            className="nav-link"
            style={{ margin: "6px 8px 2px", background: "rgba(37,211,102,0.14)", color: "#25D366", fontWeight: 600 }}
            onClick={closeDrawer}
            title="Open tiTi on WhatsApp"
          >
            <MessageSquare size={16} />
            <span className="nav-label">
              {user?.whatsapp_linked ? "Chat on WhatsApp" : "Connect WhatsApp"}
            </span>
          </a>
        )}

        {user && (
          <div className="sidebar-user">
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">{user.name}</div>
              <div className="sidebar-user-phone">{user.phone}</div>
            </div>
            <button className="sidebar-logout" onClick={handleLogout} title="Sign out">
              <LogOut size={15} />
            </button>
            <button onClick={handleLogoutAll} title="Sign out of all devices"
              style={{ background: "none", border: "none", color: "var(--text-muted)",
                       fontSize: 10, cursor: "pointer", textDecoration: "underline", padding: 0 }}>
              All devices
            </button>
          </div>
        )}
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {/* Hamburger + logo — visible only on mobile via CSS */}
            <button
              className="topbar-menu-btn"
              onClick={() => setDrawerOpen(true)}
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink)", padding: 4 }}
            >
              <Menu size={22} />
            </button>
            <img
              src="/app/logo.png"
              alt="logo"
              className="topbar-logo"
              style={{ width: 30, height: 30, borderRadius: 6, objectFit: "cover" }}
            />
            <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--ink)", letterSpacing: "-0.3px", lineHeight: 1 }}>
              {title}
            </h1>
          </div>

          <div className="topbar-sync" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {!isOnline && <span className="sync-chip sync-chip--offline">Offline</span>}
            {isOnline && pending > 0 && (
              <span className="sync-chip sync-chip--syncing">
                {syncing ? `Syncing ${pending}…` : `${pending} pending`}
              </span>
            )}
            {failed > 0 && (
              <button
                className="sync-chip sync-chip--failed"
                onClick={dismissFailed}
                title={`${failed} record${failed !== 1 ? "s" : ""} failed to sync. Click to dismiss.`}
              >
                {failed} failed ×
              </button>
            )}
            <NotificationBell />
          </div>

          <div className="topbar-controls">
            <div className="form-group" style={{ gap: 4 }}>
              <label className="form-label">Owner phone</label>
              <input
                value={ownerPhone}
                onChange={(e) => setOwnerPhone(e.target.value)}
                placeholder="234..."
                style={{ width: 160 }}
              />
            </div>
            <div className="form-group" style={{ gap: 4 }}>
              <label className="form-label">Period</label>
              <select value={period} onChange={(e) => setPeriod(e.target.value)} style={{ width: 110 }}>
                <option value="TODAY">Today</option>
                <option value="WEEK">This Week</option>
                <option value="MONTH">This Month</option>
                <option value="YEAR">This Year</option>
                <option value="">All Time</option>
              </select>
            </div>
          </div>
        </header>

        <main className="page-content">
          <Outlet />
        </main>
      </div>

      {/* tiTi floating panel — hidden on /home (Chat page) */}
      {path !== "/home" && <TitiPanel />}

      {/* Bottom tab bar — mobile only (hidden via CSS on desktop) */}
      <nav className="bottom-tab-bar">
        {tabItems.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => isActive ? "tab-active" : ""}
          >
            <item.icon size={20} />
            <span>{item.label === "Chat with tiTi" ? "tiTi" : item.label}</span>
          </NavLink>
        ))}
        <button onClick={() => setDrawerOpen(true)}>
          <Menu size={20} />
          <span>More</span>
        </button>
      </nav>
    </div>
  );
}
