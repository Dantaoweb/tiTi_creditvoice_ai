import { createContext, useContext, useState } from "react";

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [ownerPhone, setOwnerPhoneState] = useState(() => {
    // Admin "view-as" override stored explicitly; otherwise derive from logged-in user
    const override = localStorage.getItem("cv_owner_phone");
    if (override) return override;
    try {
      const user = JSON.parse(localStorage.getItem("cv_user") || "null");
      return user?.phone || "";
    } catch { return ""; }
  });
  const [period, setPeriod] = useState("MONTH");

  function setOwnerPhone(v) {
    setOwnerPhoneState(v);
    localStorage.setItem("cv_owner_phone", v);
  }

  return (
    <AppContext.Provider value={{ ownerPhone, setOwnerPhone, period, setPeriod }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  return useContext(AppContext);
}
