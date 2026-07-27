import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { apiPut } from "../lib/api";

export default function Profile() {
  const { user, refreshUser } = useAuth();
  const isOwner = !user?.parent_id;

  const [name, setName] = useState(user?.name || "");
  const [label, setLabel] = useState(user?.business_type_label || "");
  const [address, setAddress] = useState(user?.address || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function save(e) {
    e.preventDefault();
    setErr(""); setMsg("");
    if (!name.trim()) { setErr("Enter your name / business name."); return; }
    setBusy(true);
    try {
      await apiPut("auth/profile", {
        name: name.trim(),
        business_type_label: isOwner ? label.trim() : undefined,
        address: isOwner ? address.trim() : undefined,
      });
      if (refreshUser) await refreshUser();
      setMsg("Profile saved.");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <div className="card-header">
        <span className="card-title">My Profile</span>
      </div>
      <form onSubmit={save} style={{ display: "grid", gap: 14, marginTop: 12 }}>
        <div className="form-group">
          <label className="form-label">{isOwner ? "Business / your name" : "Your name"}</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Ada Stores" disabled={busy} />
          {isOwner && <span className="form-hint">This is the name shown on your receipts and invoices.</span>}
        </div>

        {isOwner && (
          <>
            <div className="form-group">
              <label className="form-label">Business type</label>
              <input value={label} onChange={e => setLabel(e.target.value)} placeholder="e.g. Pharmacy, Boutique" disabled={busy} />
            </div>
            <div className="form-group">
              <label className="form-label">Business address</label>
              <textarea value={address} onChange={e => setAddress(e.target.value)} rows={2}
                placeholder="e.g. 12 Market Rd, Ikeja, Lagos" disabled={busy} style={{ resize: "vertical" }} />
              <span className="form-hint">Shown on receipts and invoices.</span>
            </div>
          </>
        )}

        <div className="form-group">
          <label className="form-label">Phone</label>
          <input value={user?.phone || ""} disabled readOnly />
          <span className="form-hint">Your phone is your login and can't be changed here.</span>
        </div>

        {msg && <div style={{ color: "#16a34a", fontSize: 13 }}>{msg}</div>}
        {err && <div className="login-error">{err}</div>}

        <div>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </div>
  );
}
