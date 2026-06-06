import { createContext, useContext, useState } from "react";

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [ownerPhone, setOwnerPhoneState] = useState(
    () => localStorage.getItem("cv_owner_phone") || ""
  );
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
