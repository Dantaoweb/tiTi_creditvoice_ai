import { createContext, useCallback, useContext, useState } from "react";
import { CheckCircle, XCircle, Info, X } from "lucide-react";

const ToastContext = createContext(null);

let _id = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  // push(message, type, opts?) — opts.persist keeps it up until the user closes it.
  const push = useCallback((message, type = "info", opts = {}) => {
    const id = ++_id;
    setToasts((t) => [...t, { id, message, type }]);
    if (!opts.persist) {
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), opts.duration || 3500);
    }
    return id;
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-stack">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.type}`}>
            {t.type === "success" && <CheckCircle size={16} />}
            {t.type === "error"   && <XCircle     size={16} />}
            {t.type === "info"    && <Info         size={16} />}
            <span style={{ flex: 1 }}>{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss"
              style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, marginLeft: 8, opacity: 0.75, display: "flex" }}
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
