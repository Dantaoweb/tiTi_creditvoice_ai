import { lazy } from "react";

// Each page is its own download, fetched the first time it's opened, so the
// app starts small and an update only re-downloads the pages that changed.
//
// If a new version went live while the app was open, the old page piece no
// longer exists on the server — reload once to pick up the new app instead of
// showing an error. (Offline, the ErrorBoundary says the page needs internet.)
const RELOADED = "cv-chunk-reload";

export default function lazyPage(load) {
  return lazy(() =>
    load()
      .then(mod => { try { sessionStorage.removeItem(RELOADED); } catch { /* private mode */ } return mod; })
      .catch(err => {
        let tried = false;
        try { tried = !!sessionStorage.getItem(RELOADED); } catch { /* private mode */ }
        if (navigator.onLine && !tried) {
          try { sessionStorage.setItem(RELOADED, "1"); } catch { /* private mode */ }
          window.location.reload();
          return new Promise(() => {});        // the page is reloading
        }
        throw err;
      })
  );
}
