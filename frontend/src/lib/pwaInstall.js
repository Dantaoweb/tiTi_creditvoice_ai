// Shared PWA-install state so both the first-time cue and the sidebar menu item
// use the SAME captured install event (it can only be prompted once).

let deferredPrompt = null;
const listeners = new Set();

function notify() { listeners.forEach((fn) => { try { fn(); } catch { /* ignore */ } }); }

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    notify();
  });
}

export function isIOS() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
}

export function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true
  );
}

export function canPromptInstall() {
  return !!deferredPrompt;
}

// Fires the native Android install prompt. Returns "accepted" | "dismissed" | null.
export async function promptInstall() {
  if (!deferredPrompt) return null;
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  if (outcome === "accepted") deferredPrompt = null;
  return outcome;
}

// Subscribe to install-availability changes; returns an unsubscribe fn.
export function onInstallChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
