import { useCallback, useEffect, useState } from "react";
import { getQueue, dequeue } from "./offlineQueue";
import { apiPost } from "./api";
import { useToast } from "../components/Toast";

export function useOfflineSync() {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);
  const [pending,  setPending]  = useState(() => getQueue().length);
  const [syncing,  setSyncing]  = useState(false);
  const toast = useToast();

  const refresh = useCallback(() => setPending(getQueue().length), []);

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
        }
        // network still down or server error — leave in queue
        if (e instanceof TypeError) break;
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
  }, [toast, refresh]);

  useEffect(() => {
    const onOnline  = () => { setIsOnline(true);  sync(); };
    const onOffline = () => setIsOnline(false);
    const onQueued  = () => refresh();
    window.addEventListener("online",             onOnline);
    window.addEventListener("offline",            onOffline);
    window.addEventListener("cv:queue-updated",   onQueued);
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

  return { isOnline, pending, syncing, refresh };
}
