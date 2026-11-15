import { apiFetch } from "./api";
import { isNetworkError } from "./offlineQueue";

/* Customers kept on the phone so a sale can still go to a named customer with
   no internet. Refreshed while online (Layout); searched only when the server
   can't be reached. Cleared on logout (AuthContext). */
const KEY = "cv_offline_customers";
const REFRESH_MS = 30 * 60 * 1000;
const MAX = 3000;

function read() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
}

export async function refreshOfflineCustomers(ownerPhone, force = false) {
  if (!ownerPhone || !navigator.onLine) return;
  const kept = read();
  if (!force && kept?.owner === ownerPhone && Date.now() - (kept.saved_at || 0) < REFRESH_MS) return;
  const items = [];
  try {
    for (let offset = 0; offset < MAX; offset += 500) {
      const d = await apiFetch("customers", { owner_phone: ownerPhone, sort: "name", limit: 500, offset });
      const page = d.customers || [];
      page.forEach(c => items.push({ id: c.id, name: c.name, phone: c.phone || "", balance: c.balance || 0 }));
      if (page.length < 500) break;
    }
    localStorage.setItem(KEY, JSON.stringify({ owner: ownerPhone, saved_at: Date.now(), items }));
  } catch { /* keep what we had */ }
}

function searchKept(ownerPhone, q, { debtors = false, limit = 8 } = {}) {
  const kept = read();
  if (!kept || kept.owner !== ownerPhone) return [];
  const t = (q || "").trim().toLowerCase();
  return kept.items
    .filter(c => (!debtors || c.balance > 0) && (!t || c.name.toLowerCase().includes(t) || (c.phone || "").includes(t)))
    .slice(0, limit);
}

/* The server's search when online; the phone's copy when not. */
export async function searchCustomers(ownerPhone, params = {}) {
  const { q = "", debtors = false, limit = 8 } = params;
  try {
    const d = await apiFetch("customers", { owner_phone: ownerPhone, q, debtors: debtors ? "true" : "", limit });
    return d.customers || [];
  } catch (e) {
    if (isNetworkError(e)) return searchKept(ownerPhone, q, { debtors, limit });
    throw e;
  }
}
