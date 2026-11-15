import { useCallback, useEffect, useState } from "react";
import { myQueue, myFailed, getFailedQueue, dequeue, markFailed, clearFailed, newRef } from "./offlineQueue";
import { apiPostOnce } from "./api";
import { useToast } from "../components/Toast";

export function useOfflineSync() {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);
  const [pending,  setPending]  = useState(() => myQueue().length);
  const [failed,   setFailed]   = useState(() => myFailed().length);
  const [syncing,  setSyncing]  = useState(false);
  const toast = useToast();

  const refresh = useCallback(() => {
    setPending(myQueue().length);
    setFailed(myFailed().length);
  }, []);

  const sync = useCallback(async () => {
    const q = myQueue();
    if (q.length === 0 || !navigator.onLine) return;
    setSyncing(true);
    let synced = 0;
    for (const item of q) {
      try {
        // The record's own ID: if an earlier try got through, the server
        // gives that answer back instead of recording it again
        await apiPostOnce(item.endpoint, item.body, item.ref || (item.ref = newRef()));
        dequeue(item.id);
        synced++;
      } catch (e) {
        // Logged out: keep everything — it's sent after logging in again
        if (e.message?.includes("Session expired")) break;
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
    if (navigator.onLine && myQueue().length > 0) sync();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { isOnline, pending, failed, syncing, refresh, dismissFailed, sync };
}
