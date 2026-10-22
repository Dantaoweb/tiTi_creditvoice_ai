import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateTimeStr } from "../lib/format";

/* The page a customer opens from a WhatsApp link — no app, no account.
   It shows who they're paying, what for, how much, and the bank account to
   transfer to. "I've paid" tells the business, who confirms once the money
   shows in their bank. The money never passes through the app. */

// Shrink a phone photo so it uploads quickly (and stays under the size limit)
function shrink(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const scale = Math.min(1, 1200 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.75));
    };
    img.onerror = reject;
    img.src = url;
  });
}

export default function PayPage() {
  const { token } = useParams();
  const [p, setP] = useState(null);
  const [err, setErr] = useState("");
  const [amount, setAmount] = useState("");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [proof, setProof] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    apiFetch(`public/pay/${token}`)
      .then(d => { setP(d); setAmount(String(d.amount || "")); setName(d.customer_name || ""); })
      .catch(e => setErr(e.message));
  }, [token]);

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); setCopied(text); setTimeout(() => setCopied(""), 1500); }
    catch { /* old phone — they can read it */ }
  }

  async function pickPhoto(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    try { setProof(await shrink(f)); } catch { setErr("Couldn't read that photo — try another."); }
  }

  async function paid() {
    setBusy(true); setErr("");
    try {
      const d = await apiPost(`public/pay/${token}/claim`, {
        amount: amount ? Number(String(amount).replace(/,/g, "")) : null,
        name: name.trim() || null, note: note.trim() || null, proof,
      });
      setP(d); setDone(true);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const wrap = children => (
    <div style={{ minHeight: "100vh", background: "var(--bg, #f4f6fb)", padding: "24px 16px" }}>
      <div className="card" style={{ maxWidth: 440, margin: "0 auto", padding: 20 }}>{children}</div>
    </div>
  );
  if (err && !p) return wrap(<div className="pos-error">{err}</div>);
  if (!p) return wrap(<div className="td-muted">Loading…</div>);

  return wrap(
    <>
      <div style={{ textAlign: "center", marginBottom: 14 }}>
        {p.biz_logo && <img src={p.biz_logo} alt="" style={{ maxHeight: 56, maxWidth: 140, objectFit: "contain" }} />}
        <div style={{ fontSize: 19, fontWeight: 800 }}>{p.biz_name}</div>
        {p.customer_name && <div className="td-muted" style={{ fontSize: 13 }}>For {p.customer_name}</div>}
      </div>

      {p.cancelled ? (
        <div style={{ textAlign: "center", fontWeight: 700 }}>This invoice was cancelled. Nothing to pay.</div>
      ) : p.settled ? (
        <div style={{ textAlign: "center", fontWeight: 700, color: "#166534" }}>All paid ✓ Thank you!</div>
      ) : (
        <>
          <div style={{ textAlign: "center", margin: "6px 0 16px" }}>
            <div className="td-muted" style={{ fontSize: 13 }}>{p.label}</div>
            <div style={{ fontSize: 30, fontWeight: 800 }}>{nairaFull(p.amount)}</div>
          </div>

          {p.bank_accounts.length > 0 ? (
            <div style={{ display: "grid", gap: 8, marginBottom: 16 }}>
              <div className="receipt-label">Transfer to</div>
              {p.bank_accounts.map(a => (
                <div key={a.number} style={{ border: "1px solid var(--line, #e5e7eb)", borderRadius: 10, padding: 12 }}>
                  <div style={{ fontWeight: 700 }}>{a.bank}</div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontSize: 20, letterSpacing: 1, fontFamily: "monospace" }}>{a.number}</span>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => copy(a.number)}>
                      {copied === a.number ? "Copied ✓" : "Copy"}
                    </button>
                  </div>
                  {a.name && <div className="td-muted" style={{ fontSize: 13 }}>{a.name}</div>}
                </div>
              ))}
            </div>
          ) : (
            <div className="td-muted" style={{ marginBottom: 16 }}>Ask {p.biz_name} for their account details{p.biz_phone ? ` (${p.biz_phone})` : ""}.</div>
          )}

          {p.claim_pending || done ? (
            <div style={{ background: "#ecfdf5", color: "#166534", borderRadius: 10, padding: 12, fontSize: 14 }}>
              ✓ We've told {p.biz_name} you paid{p.claimed_at ? ` (${dateTimeStr(p.claimed_at)})` : ""}.
              They'll confirm once they see it in their bank, and you'll get a receipt on WhatsApp.
            </div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              <div className="receipt-label">Already paid? Tell them</div>
              <label className="form-label" style={{ margin: 0 }}>Amount you sent (₦)</label>
              <input inputMode="numeric" value={amount} onChange={e => setAmount(e.target.value.replace(/[^\d,]/g, ""))} />
              <label className="form-label" style={{ margin: 0 }}>Your name</label>
              <input value={name} maxLength={100} onChange={e => setName(e.target.value)} />
              <label className="form-label" style={{ margin: 0 }}>Note <span style={{ opacity: 0.6 }}>(optional — e.g. "sent from Opay")</span></label>
              <input value={note} maxLength={300} onChange={e => setNote(e.target.value)} />
              <label className="form-label" style={{ margin: 0 }}>Photo of the transfer receipt <span style={{ opacity: 0.6 }}>(optional)</span></label>
              <input type="file" accept="image/*" onChange={pickPhoto} />
              {proof && <img src={proof} alt="" style={{ maxHeight: 140, objectFit: "contain", borderRadius: 8 }} />}
              <button className="btn btn-primary" onClick={paid} disabled={busy} style={{ justifyContent: "center" }}>
                {busy ? "Sending…" : "I've paid"}
              </button>
            </div>
          )}
        </>
      )}
      {err && <div className="modal-error">{err}</div>}
      <div className="td-muted" style={{ fontSize: 11, textAlign: "center", marginTop: 16 }}>
        You pay {p.biz_name} directly by bank transfer. Powered by CreditVoice.
      </div>
    </>
  );
}
