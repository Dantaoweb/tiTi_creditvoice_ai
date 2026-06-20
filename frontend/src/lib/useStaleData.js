import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "./api";

/**
 * Like apiFetch but also tracks whether the response came from the
 * Workbox cache (stale) or the network (fresh).
 *
 * Returns { data, loading, error, isStale, reload }
 *
 * "isStale" is true when:
 *  - the browser is offline, OR
 *  - the fetch succeeded but the response Age header > 0 (served from cache)
 */
export function useStaleData(path, params = {}, deps = []) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const [isStale, setIsStale] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    if (!navigator.onLine) {
      // Attempt cache-only fetch via workbox
      try {
        const url  = new URL(`/app/api/${path}`, window.location.origin);
        Object.entries(params).forEach(([k, v]) => {
          if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, v);
        });
        const tok  = localStorage.getItem("cv_token") || "";
        const res  = await fetch(url.toString(), {
          headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        });
        if (res.ok) {
          setData(await res.json());
          setIsStale(true);   // definitely from cache — we're offline
        }
      } catch {
        setError("You're offline. Showing last saved data.");
        setIsStale(true);
      } finally {
        setLoading(false);
      }
      return;
    }

    try {
      const result = await apiFetch(path, params);
      setData(result);
      setIsStale(false);
    } catch (e) {
      // network fetch failed mid-request — fall back to whatever cache returned
      setError(e.message);
      setIsStale(true);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, JSON.stringify(params), ...deps]);

  useEffect(() => { load(); }, [load]);

  // Re-fetch when coming back online
  useEffect(() => {
    const onOnline = () => load();
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [load]);

  return { data, loading, error, isStale, reload: load };
}
