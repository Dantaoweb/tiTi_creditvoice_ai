import { useEffect, useRef, useState } from "react";
import { apiDelete, apiFetch, apiPost } from "../lib/api";

/* The business logo, printed on receipts, invoices and quotations. Shrunk in
   the browser to a small picture before it's sent, so receipts stay quick. */

const MAX_SIDE = 320;

function shrink(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(img.src);
      // PNG keeps a transparent background; a photo-like logo is smaller as JPEG
      const png = canvas.toDataURL("image/png");
      const jpg = canvas.toDataURL("image/jpeg", 0.88);
      resolve(file.type === "image/png" && png.length < 280_000 ? png : jpg);
    };
    img.onerror = () => reject(new Error("That file isn't a picture we can read."));
    img.src = URL.createObjectURL(file);
  });
}

export default function LogoUploader() {
  const [logo, setLogo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const input = useRef(null);

  useEffect(() => { apiFetch("auth/profile/logo").then(d => setLogo(d.logo)).catch(() => {}); }, []);

  async function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setErr(""); setMsg(""); setBusy(true);
    try {
      const data = await shrink(file);
      const r = await apiPost("auth/profile/logo", { data_url: data });
      setLogo(r.logo);
      setMsg("Logo saved — it now prints on your receipts and invoices.");
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!window.confirm("Remove your logo from receipts and invoices?")) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      await apiDelete("auth/profile/logo");
      setLogo(null);
      setMsg("Logo removed.");
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="form-group">
      <label className="form-label">Business logo</label>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ width: 88, height: 88, border: "1px dashed var(--line)", borderRadius: 10,
                      display: "grid", placeItems: "center", background: "#fff", overflow: "hidden" }}>
          {logo
            ? <img src={logo} alt="Your logo" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
            : <span className="td-muted" style={{ fontSize: 11, textAlign: "center", padding: 6 }}>No logo yet</span>}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" onChange={onFile} style={{ display: "none" }} />
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => input.current?.click()}>
            {busy ? "Saving…" : logo ? "Change logo" : "Upload logo"}
          </button>
          {logo && <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={remove}>Remove</button>}
        </div>
      </div>
      <span className="form-hint">Printed at the top of your receipts, invoices and quotations. A square PNG or JPG works best.</span>
      {msg && <div style={{ color: "#16a34a", fontSize: 13 }}>{msg}</div>}
      {err && <div className="login-error">{err}</div>}
    </div>
  );
}
