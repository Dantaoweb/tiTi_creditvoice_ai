import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { AppProvider } from "./context/AppContext";
import ErrorBoundary from "./components/ErrorBoundary";
import App from "./App.jsx";
import FinancierApp from "./FinancierApp.jsx";
import "./lib/pwaInstall";   // capture the install event as early as possible
import "./index.css";

// The financier portal lives at /financier — outside /app, with its own cookie,
// its own layout and none of the business app's providers, so it can never be
// mistaken for a user's own app (or for their business partners).
const IS_FINANCIER = window.location.pathname.startsWith("/financier");

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ErrorBoundary>
      {IS_FINANCIER ? (
        <BrowserRouter basename="/financier">
          <FinancierApp />
        </BrowserRouter>
      ) : (
        <BrowserRouter basename="/app">
          <AuthProvider>
            <AppProvider>
              <App />
            </AppProvider>
          </AuthProvider>
        </BrowserRouter>
      )}
    </ErrorBoundary>
  </StrictMode>
);

// Register the service worker (enables Add-to-Home-Screen install + offline page).
// Only for the business app: the portal is a plain web page for partner staff.
if ("serviceWorker" in navigator && !IS_FINANCIER) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/app/sw.js").catch(() => {});
  });
}
