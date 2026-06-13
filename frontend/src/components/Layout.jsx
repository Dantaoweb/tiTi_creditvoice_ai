import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  MessageSquare, LayoutDashboard, Users, ArrowLeftRight,
  Package, Bell, Truck, UserCheck, ShoppingCart, LogOut, Wallet,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { getBizLabels } from "../lib/bizLabels";

function buildNav(L) {
  return [
    { to: "/home",         label: "Chat with tiTi",  icon: MessageSquare   },
    { to: "/pos",          label: "Select product",   icon: ShoppingCart    },
    { to: "/inventory",    label: L.stock,            icon: Package         },
    { to: "/customers",    label: L.navCustomers,     icon: Users           },
    { to: "/reminders",    label: L.reminders,        icon: Bell            },
    { to: "/dashboard",    label: "Dashboard",        icon: LayoutDashboard },
    { to: "/wallet",       label: "Wallet ✦",         icon: Wallet, badge: "soon" },
    { section: "More" },
    { to: "/transactions", label: "Transactions",     icon: ArrowLeftRight  },
    { to: "/suppliers",    label: "Suppliers",        icon: Truck           },
    { to: "/staff",        label: "Staff",            icon: UserCheck       },
  ];
}

export default function Layout() {
  const { ownerPhone, setOwnerPhone, period, setPeriod } = useApp();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const L = getBizLabels(user?.menu_group);
  const NAV = buildNav(L);
  const TITLES = {
    "/home":         "Chat with tiTi",
    "/capture":      "Record",
    "/pos":          "Select product",
    "/inventory":    L.stock,
    "/customers":    L.navCustomers,
    "/reminders":    L.reminders,
    "/dashboard":    "Dashboard",
    "/transactions": "Transactions",
    "/suppliers":    "Suppliers",
    "/staff":        "Staff",
    "/wallet":       "Wallet",
  };

  const path = window.location.pathname.replace("/app", "") || "/home";
  const title = TITLES[path] || "CreditVoice";

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-mark">CV</div>
          <div>
            <div className="sidebar-name">CreditVoice</div>
            <div className="sidebar-sub">Business Desk</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {NAV.map((item, i) =>
            item.section !== undefined ? (
              <div key={i} className="nav-section">{item.section}</div>
            ) : item.disabled ? (
              <div key={item.label} className="nav-link nav-link-disabled">
                <item.icon size={16} />
                {item.label}
                {item.badge && <span className="nav-badge">{item.badge}</span>}
              </div>
            ) : (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
              >
                <item.icon size={16} />
                {item.label}
              </NavLink>
            )
          )}
        </nav>

        {user && (
          <div className="sidebar-user">
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">{user.name}</div>
              <div className="sidebar-user-phone">{user.phone}</div>
            </div>
            <button
              className="sidebar-logout"
              onClick={handleLogout}
              title="Sign out"
            >
              <LogOut size={15} />
            </button>
          </div>
        )}
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <div className="topbar-eyebrow">CreditVoice</div>
            <h1>{title}</h1>
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
    </div>
  );
}
