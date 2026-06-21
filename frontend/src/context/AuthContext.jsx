import { createContext, useContext, useState, useCallback } from "react";
import { apiPost } from "../lib/api";

const AuthContext = createContext(null);

const USER_KEY = "cv_user";

function _isSessionExpired(usr) {
  if (!usr?.session_expires_at) return false;
  return new Date(usr.session_expires_at) < new Date();
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
    setUserState(null);
  }, []);

  function persistSession(usr) {
    _persist(usr);
  }

  const isAuthed = !!user && !_isSessionExpired(user);

  return (
    <AuthContext.Provider value={{
      user, authLoading, authError,
      login, logout, persistSession,
      isAuthed,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
