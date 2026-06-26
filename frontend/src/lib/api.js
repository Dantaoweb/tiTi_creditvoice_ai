export async function apiFetch(path, params = {}, options = {}) {
  const url = new URL(`/app/api/${path}`, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, v);
  });

  const res = await fetch(url.toString(), {
    credentials: "include",
    ...options,
    headers: { ...(options.headers || {}) },
  });

  const isAuthEndpoint = path.includes("/auth/login") || path.includes("/auth/register") ||
    path.includes("/auth/request-otp") || path.includes("/auth/set-pin") || path.includes("/auth/accept-invite");

  if (res.status === 401 && !isAuthEndpoint) {
    localStorage.removeItem("cv_user");
    window.location.href = "/app/login";
    throw new Error("Session expired.");
  }

  if (!res.ok) {
    let msg = `Request failed: ${res.status}`;
    try {
      const body = await res.json();
      msg = body.detail || body.message || msg;
    } catch {
      msg = (await res.text().catch(() => "")) || msg;
    }
    throw new Error(msg);
  }
  return res.json();
}

export async function apiPost(path, body) {
  return apiFetch(path, {}, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiPut(path, body) {
  return apiFetch(path, {}, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiDelete(path) {
  return apiFetch(path, {}, { method: "DELETE" });
}

export async function apiDownload(path, params = {}) {
  const url = new URL(`/app/api/${path}`, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, v);
  });
  const res = await fetch(url.toString(), { credentials: "include" });
  if (res.status === 401) {
    localStorage.removeItem("cv_user");
    window.location.href = "/app/login";
    throw new Error("Session expired.");
  }
  if (!res.ok) {
    throw new Error(`Export failed (${res.status})`);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "export.csv";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}
