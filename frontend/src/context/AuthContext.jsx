import { createContext, useContext, useState, useCallback, useEffect } from "react";
import { apiPost, apiFetch } from "../lib/api";

const AuthContext = createContext(null);

const USER_KEY = "cv_user";

function _isSessionExpired(usr) {
  if (!usr?.session_expires_at) return false;
  return new Date(usr.session_expires_at) < new Date();
}

// The data the app keeps on the phone to work offline (public/sw.js) belongs to
// whoever is logged in — cleared when they log out or someone else logs in.
// (Records waiting to be sent are kept: they're only ever sent by their owner.)
function clearOfflineData() {
  try { navigator.serviceWorker?.controller?.postMessage("cv-clear-api"); } catch { /* no worker */ }
  try { localStorage.removeItem("cv_offline_customers"); } catch { /* ignore */ }
}

export function AuthProvider({ children }) {
  const [user, setUserState] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(USER_KEY) || "null");
      if (stored && _isSessionExpired(stored)) {
        localStorage.removeItem(USER_KEY);
        return null;
      }
      return stored;
    } catch { return null; }
  });
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");

  function _persist(usr) {
    // Someone else on this phone: forget the last person's data kept for offline
    let before = null;
    try { before = JSON.parse(localStorage.getItem(USER_KEY) || "null")?.id || null; } catch { /* none */ }
    if (before !== usr?.id) clearOfflineData();
    localStorage.setItem(USER_KEY, JSON.stringify(usr));
    setUserState(usr);
  }

  async function login(phone, pin) {
    setAuthLoading(true);
    setAuthError("");
    try {
      const data = await apiPost("auth/login", { phone, pin });
      _persist(data.user);
      return data.user;
    } catch (err) {
      const msg = err.message || "Login failed.";
      setAuthError(msg);
      throw new Error(msg);
    } finally {
      setAuthLoading(false);
    }
  }

  const logout = useCallback(() => {
    fetch("/app/api/auth/logout", { method: "POST", credentials: "include" }).catch(() => {});
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem("cv_owner_phone");
    clearOfflineData();
    setUserState(null);
  }, []);

  function persistSession(usr) {
    _persist(usr);
  }

  async function refreshUser() {
    try {
      const data = await apiFetch("auth/me");
      _persist({ ...user, ...data });
    } catch { /* silent — stale data is fine */ }
  }

  // On app load, refresh from the server so plan changes made elsewhere
  // (WhatsApp upgrade, admin / bank-transfer approval) are reflected without
  // requiring a manual logout/login.
  useEffect(() => {
    if (user && !_isSessionExpired(user)) refreshUser();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isAuthed = !!user && !_isSessionExpired(user);

  return (
    <AuthContext.Provider value={{
      user, authLoading, authError,
      login, logout, persistSession, refreshUser,
      isAuthed,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
