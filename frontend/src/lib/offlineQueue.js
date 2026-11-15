const KEY      = "cv_offline_queue";
const FAIL_KEY = "cv_offline_failed";

function read()      { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); }      catch { return []; } }
function readFailed(){ try { return JSON.parse(localStorage.getItem(FAIL_KEY) || "[]"); } catch { return []; } }

function write(q) {
  localStorage.setItem(KEY, JSON.stringify(q));
  window.dispatchEvent(new Event("cv:queue-updated"));
}

function writeFailed(q) {
  localStorage.setItem(FAIL_KEY, JSON.stringify(q));
  window.dispatchEvent(new Event("cv:queue-updated"));
}

export function getQueue()      { return read(); }
export function getFailedQueue(){ return readFailed(); }

// The logged-in person: waiting records are only ever sent by the one who made them
export function currentUserId() {
  try { return JSON.parse(localStorage.getItem("cv_user") || "null")?.id || null; } catch { return null; }
}
export function myQueue() {
  const me = currentUserId();
  return read().filter(item => !item.user_id || item.user_id === me);
}

// A new ID for one record — made before the first try, so a retry of the same
// record (online or from the queue) is never recorded twice
export function newRef() {
  const rnd = (crypto?.randomUUID?.() || `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`);
  return `cv-${rnd}`.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64);
}

export function enqueue(endpoint, body, label, ref) {
  const q = read();
  q.push({
    id:        Date.now().toString(36) + Math.random().toString(36).slice(2),
    ref:       ref || newRef(),
    user_id:   currentUserId(),
    endpoint,
    body,
    label,
    queued_at: new Date().toISOString(),
  });
  write(q);
}

export function dequeue(id) {
  write(read().filter(item => item.id !== id));
}

export function markFailed(item, reason) {
  dequeue(item.id);
  const failed = readFailed();
  failed.push({ ...item, failed_at: new Date().toISOString(), error: reason });
  writeFailed(failed);
}

export function clearFailed() {
  writeFailed([]);
}

export function isNetworkError(err) {
  return err instanceof TypeError || !navigator.onLine;
}
