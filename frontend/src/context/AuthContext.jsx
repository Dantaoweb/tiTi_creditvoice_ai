import { createContext, useContext, useState, useCallback } from "react";
import { apiPost } from "../lib/api";

const AuthContext = createContext(null);

const TOKEN_KEY = "cv_token";
const USER_KEY = "cv_user";

export function AuthProvider({ children }) {
  const [token, setTokenState] = useState(() => localStorage.getItem(TOKEN_KEY) || null);
  const [user, setUserState] = useState(() => {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); }
    catch { return null; }
  });
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");

  function _persist(tok, usr) {
    localStorage.setItem(TOKEN_KEY, tok);
    localStorage.setItem(USER_KEY, JSON.stringify(usr));
    setTokenState(tok);
    setUserState(usr);
    // Seed ownerPhone so existing pages work right after login
    if (usr?.phone) localStorage.setItem("cv_owner_phone", usr.phone);
  }

  async function login(phone, pin) {
    setAuthLoading(true);
    setAuthError("");
    try {
      const data = await apiPost("auth/login", { phone, pin });
      _persist(data.token, data.user);
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
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setTokenState(null);
    setUserState(null);
  }, []);

  function persistSession(tok, usr) {
    _persist(tok, usr);
  }

  return (
    <AuthContext.Provider value={{
      token, user, authLoading, authError,
      login, logout, persistSession,
      isAuthed: !!token,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
