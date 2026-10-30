import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { apiPut } from "../lib/api";
import MyReview from "../components/MyReview";
import LogoUploader from "../components/LogoUploader";

export default function Profile() {
  const { user, refreshUser } = useAuth();
  const isOwner = !user?.parent_id;

  const [name, setName] = useState(user?.name || "");
  const [label, setLabel] = useState(user?.business_type_label || "");
  const [address, setAddress] = useState(user?.address || "");
  // Printed on invoices and quotations (and receipts, if switched on in Settings)
  const [bizEmail, setBizEmail] = useState(user?.business_email || "");
  const [receiptPhones, setReceiptPhones] = useState(user?.receipt_phones || "");
  const blankAcct = { bank: "", number: "", name: "" };
  const [accounts, setAccounts] = useState(() => {
    const a = (user?.bank_accounts || []).map(x => ({ ...blankAcct, ...x, name: x.name || "" }));
    return a.length ? a : [{ ...blankAcct }];
  });
  const setAcct = (i, k, v) => setAccounts(list => list.map((a, j) => (j === i ? { ...a, [k]: v } : a)));
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
        business_email: isOwner ? bizEmail.trim() : undefined,
        receipt_phones: isOwner ? receiptPhones.trim() : undefined,
        bank_accounts: isOwner ? accounts : undefined,
      });
      if (refreshUser) await refreshUser();
      setMsg("Profile saved.");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
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
            <div className="form-group">
              <label className="form-label">Phone on receipts <span className="text-subtle">(optional)</span></label>
              <input value={receiptPhones} maxLength={80} inputMode="tel" onChange={e => setReceiptPhones(e.target.value)}
                placeholder={`e.g. 0803 111 2222 / 0905 333 4444 — empty shows ${user?.phone || "your login phone"}`} disabled={busy} />
              <span className="form-hint">Up to two numbers, separated by /. Shown on receipts, invoices, quotations and waybills. Your login phone doesn't change.</span>
            </div>
            <div className="form-group">
              <label className="form-label">Business email <span className="text-subtle">(optional)</span></label>
              <input type="email" value={bizEmail} onChange={e => setBizEmail(e.target.value)}
                placeholder="e.g. sales@adastores.com" disabled={busy} />
              <span className="form-hint">Printed on receipts, invoices and quotations. Not your login.</span>
            </div>
            <div className="form-group">
              <label className="form-label">Bank account for payments <span className="text-subtle">(optional)</span></label>
              {accounts.map((a, i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
                  <input value={a.bank} onChange={e => setAcct(i, "bank", e.target.value)} placeholder="Bank, e.g. GTBank" disabled={busy} />
                  <input value={a.number} inputMode="numeric" onChange={e => setAcct(i, "number", e.target.value.replace(/\D/g, ""))}
                    placeholder="Account number" maxLength={20} disabled={busy} />
                  <input value={a.name} onChange={e => setAcct(i, "name", e.target.value)} placeholder="Account name"
                    disabled={busy} style={{ gridColumn: "1 / -1" }} />
                </div>
              ))}
              {accounts.length < 2 && (
                <button type="button" className="btn btn-ghost btn-sm" style={{ justifySelf: "start" }}
                  onClick={() => setAccounts(list => [...list, { ...blankAcct }])}>+ Add another account</button>
              )}
              <span className="form-hint">
                Shown on invoices and quotations so customers know where to pay. Choose where else in Settings → Receipts &amp; printables.
                Leave empty for none.
              </span>
            </div>
            <LogoUploader />
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

    {/* Only the owner speaks for the business publicly. */}
    {isOwner && <MyReview />}
    </div>
  );
}
