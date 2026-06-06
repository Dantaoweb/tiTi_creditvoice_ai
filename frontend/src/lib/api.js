function _getToken() {
  return localStorage.getItem("cv_token") || "";
}

export async function apiFetch(path, params = {}, options = {}) {
  const url = new URL(`/app/api/${path}`, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, v);
  });

  const headers = { ...(options.headers || {}) };
  const tok = _getToken();
  if (tok) headers["Authorization"] = `Bearer ${tok}`;

  const res = await fetch(url.toString(), { ...options, headers });

  if (res.status === 401) {
    // Clear stale session and force login
    localStorage.removeItem("cv_token");
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
