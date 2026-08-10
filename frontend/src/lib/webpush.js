// Web Push subscribe / unsubscribe from the browser. Pairs with the backend
// /app/api/push/* endpoints and the service worker's push handler.
import { apiFetch, apiPost } from "./api";

function urlB64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

export function pushSupported() {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

// { supported, available, key, permission, subscribed }
export async function getPushState() {
  const supported = pushSupported();
  let available = false;
  let key = "";
  try {
    const cfg = await apiFetch("auth/config");
    available = !!cfg.push_enabled;
    key = cfg.vapid_public_key || "";
  } catch { /* ignore */ }

  let subscribed = false;
  if (supported) {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      subscribed = !!sub;
    } catch { /* ignore */ }
  }
  return {
    supported,
    available,
    key,
    permission: supported ? Notification.permission : "denied",
    subscribed,
  };
}

export async function enablePush(vapidKey) {
  if (!pushSupported()) throw new Error("Notifications aren't supported on this device.");
  if (!vapidKey) throw new Error("Push isn't configured yet.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("You blocked notifications for this site.");

  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(vapidKey),
    });
  }
  const json = sub.toJSON();
  await apiPost("push/subscribe", {
    endpoint: sub.endpoint,
    p256dh: json.keys.p256dh,
    auth: json.keys.auth,
  });
  return true;
}

export async function disablePush() {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  const endpoint = sub ? sub.endpoint : null;
  if (sub) {
    try { await sub.unsubscribe(); } catch { /* ignore */ }
  }
  await apiPost("push/unsubscribe", { endpoint });
  return true;
}
