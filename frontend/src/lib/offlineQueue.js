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

export function enqueue(endpoint, body, label) {
  const q = read();
  q.push({
    id:        Date.now().toString(36) + Math.random().toString(36).slice(2),
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
