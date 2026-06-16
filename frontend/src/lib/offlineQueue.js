const KEY = "cv_offline_queue";

function read() {
  try { return JSON.parse(localStorage.getItem(KEY) || "[]"); }
  catch { return []; }
}

function write(q) {
  localStorage.setItem(KEY, JSON.stringify(q));
  window.dispatchEvent(new Event("cv:queue-updated"));
}

export function getQueue() { return read(); }

export function enqueue(endpoint, body, label) {
  const q = read();
  q.push({
    id:         Date.now().toString(36) + Math.random().toString(36).slice(2),
    endpoint,
    body,
    label,
    queued_at:  new Date().toISOString(),
  });
  write(q);
}

export function dequeue(id) {
  write(read().filter(item => item.id !== id));
}

export function isNetworkError(err) {
  return err instanceof TypeError || !navigator.onLine;
}
