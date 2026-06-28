import { useCallback, useEffect, useState } from "react";
import { getQueue, getFailedQueue, dequeue, markFailed, clearFailed } from "./offlineQueue";
import { apiPost } from "./api";
import { useToast } from "../components/Toast";

export function useOfflineSync() {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);
  const [pending,  setPending]  = useState(() => getQueue().length);
  const [failed,   setFailed]   = useState(() => getFailedQueue().length);
  const [syncing,  setSyncing]  = useState(false);
  const toast = useToast();

  const refresh = useCallback(() => {
    setPending(getQueue().length);
    setFailed(getFailedQueue().length);
  }, []);

  const sync = useCallback(async () => {
    const q = getQueue();
    if (q.length === 0 || !navigator.onLine) return;
    setSyncing(true);
    let synced = 0;
    for (const item of q) {
      try {
        await apiPost(item.endpoint, item.body);
        dequeue(item.id);
        synced++;
      } catch (e) {
        if (e.message?.includes("Session expired")) {
          dequeue(item.id);
          continue;
        }
        // Network still down — stop and retry later
        if (e instanceof TypeError) break;
        // Server error (4xx/5xx) — move to failed queue so it doesn't block others
        markFailed(item, e.message || "Server error");
      }
    }
    setSyncing(false);
    refresh();
    if (synced > 0) {
      toast(
        `${synced} offline record${synced !== 1 ? "s" : ""} synced successfully.`,
        "success",
      );
    }
    const nowFailed = getFailedQueue().length;
    if (nowFailed > 0) {
      toast(
        `${nowFailed} record${nowFailed !== 1 ? "s" : ""} failed to sync — check Offline Queue.`,
        "error",
      );
    }
  }, [toast, refresh]);

  const dismissFailed = useCallback(() => {
    clearFailed();
    refresh();
  }, [refresh]);

  useEffect(() => {
    const onOnline  = () => { setIsOnline(true);  sync(); };
    const onOffline = () => setIsOnline(false);
    const onQueued  = () => refresh();
    window.addEventListener("online",           onOnline);
    window.addEventListener("offline",          onOffline);
    window.addEventListener("cv:queue-updated", onQueued);
    return () => {
      window.removeEventListener("online",           onOnline);
      window.removeEventListener("offline",          onOffline);
      window.removeEventListener("cv:queue-updated", onQueued);
    };
  }, [sync, refresh]);

  // Sync any leftover queue on first mount
  useEffect(() => {
    if (navigator.onLine && getQueue().length > 0) sync();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { isOnline, pending, failed, syncing, refresh, dismissFailed };
}
