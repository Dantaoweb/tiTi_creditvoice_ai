import { useEffect, useState } from "react";
import { apiFetch, apiPost } from "../lib/api";
import { parseAmt } from "../lib/format";

// The finance application flow, shared by the noticeboard and the Business
// Score page: consent, the identity details a financier needs, and the status
// of an application already sent.

export const APPLICATION_STATUS = {
  SUBMITTED: ["Sent to CreditVoice", "#92400e", "rgba(180,83,9,0.10)"],
  SHARED:    ["Shared with financier", "#1d4ed8", "rgba(29,78,216,0.10)"],
  IN_REVIEW: ["Financier reviewing", "#1d4ed8", "rgba(29,78,216,0.10)"],
  APPROVED:  ["Approved", "#166534", "rgba(22,101,52,0.10)"],
  DELIVERED: ["Asset delivered", "#166534", "rgba(22,101,52,0.12)"],
  DECLINED:  ["Declined", "#b91c1c", "rgba(185,28,28,0.10)"],
  WITHDRAWN: ["Withdrawn", "#6b7280", "rgba(107,114,128,0.12)"],
};

export function StatusPill({ status }) {
  const [label, color, bg] = APPLICATION_STATUS[status] || [status, "#6b7280", "rgba(107,114,128,0.12)"];
  return <span className="badge" style={{ color, background: bg, fontWeight: 700 }}>{label}</span>;
}

// Identity details, asked at the point a financier needs them — never at sign-up.
export function KycModal({ onClose, onSaved }) {
  const [meta, setMeta] = useState(null);
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    Promise.all([apiFetch("finance-meta"), apiFetch("kyc")])
      .then(([m, k]) => { setMeta(m); setForm(k.kyc || {}); })
      .catch(e => setErr(e.message));
  }, []);

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  async function save() {
    setBusy(true); setErr("");
    try {
      const r = await apiPost("kyc", form);
      if (!r.complete) {
        setErr(`Still needed: ${(r.missing || []).map(x => x.label).join(", ")}`);
        return;
      }
      onSaved();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Your business &amp; identity details</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {err && <div className="modal-error">{err}</div>}
          <p className="text-subtle text-sm">
            Financiers must know who they are dealing with. You enter this once, and it is
            shared only with the financier you apply to.
          </p>
          {!meta ? <p className="td-muted">Loading…</p> : (
            <>
              <div className="form-group">
                <label className="form-label">Full name, as on your ID *</label>
                <input value={form.legal_name || ""} onChange={e => set("legal_name", e.target.value)} />
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <div className="form-group" style={{ flex: "1 1 150px" }}>
                  <label className="form-label">State *</label>
                  <select value={form.state || ""} onChange={e => set("state", e.target.value)}>
                    <option value="">Select…</option>
                    {meta.states.map(st => <option key={st} value={st}>{st}</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ flex: "1 1 150px" }}>
                  <label className="form-label">Town / city *</label>
                  <input value={form.city || ""} onChange={e => set("city", e.target.value)} />
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Business address *</label>
                <input value={form.address || ""} onChange={e => set("address", e.target.value)} />
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <div className="form-group" style={{ flex: "1 1 170px" }}>
                  <label className="form-label">ID type *</label>
                  <select value={form.id_type || ""} onChange={e => set("id_type", e.target.value)}>
                    <option value="">Select…</option>
                    {meta.id_types.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ flex: "1 1 170px" }}>
                  <label className="form-label">ID number *</label>
                  <input value={form.id_number || ""} onChange={e => set("id_number", e.target.value)} />
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Is the business registered with CAC? *</label>
                <select
                  value={form.is_registered === true ? "yes" : form.is_registered === false ? "no" : ""}
                  onChange={e => set("is_registered", e.target.value === "" ? null : e.target.value === "yes")}>
                  <option value="">Select…</option>
                  <option value="no">No, not registered</option>
                  <option value="yes">Yes, registered</option>
                </select>
                <span className="form-hint">
                  Being unregistered is fine — most financiers accept it.
                </span>
              </div>
              {form.is_registered === true && (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <div className="form-group" style={{ flex: "1 1 170px" }}>
                    <label className="form-label">Registered name</label>
                    <input value={form.registered_name || ""}
                      onChange={e => set("registered_name", e.target.value)} />
                  </div>
                  <div className="form-group" style={{ flex: "1 1 150px" }}>
                    <label className="form-label">RC / BN number *</label>
                    <input value={form.registration_number || ""}
                      onChange={e => set("registration_number", e.target.value)} />
                  </div>
                </div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <div className="form-group" style={{ flex: "1 1 150px" }}>
                  <label className="form-label">Guarantor name</label>
                  <input value={form.guarantor_name || ""}
                    onChange={e => set("guarantor_name", e.target.value)} />
                </div>
                <div className="form-group" style={{ flex: "1 1 150px" }}>
                  <label className="form-label">Guarantor phone</label>
                  <input inputMode="tel" value={form.guarantor_phone || ""}
                    onChange={e => set("guarantor_phone", e.target.value)} />
                </div>
              </div>
              <p className="text-subtle text-sm">
                Fields marked * are required. We never ask for your BVN.
              </p>
            </>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !meta}>
            {busy ? "Saving…" : "Save details"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Applying shares this business's record with ONE financier. Consent is
// explicit, and the scorecard is frozen at this moment.
export function FinanceApplyModal({ offer, onClose, onDone }) {
  const name = offer.partner_name || offer.name;
  const [asset, setAsset] = useState((offer.asset_types || [])[0] || "");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit() {
    setBusy(true); setErr("");
    try {
      await apiPost(`finance-offers/${offer.financier_id || offer.id}/apply`, {
        consent: true,
        asset_requested: asset.trim() || null,
        asset_value: value ? parseAmt(value) : null,
        note: note.trim() || null,
      });
      onDone();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Apply — {name}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {err && <div className="modal-error">{err}</div>}
          <div className="form-group">
            <label className="form-label">What do you need?</label>
            <input value={asset} onChange={e => setAsset(e.target.value)}
              placeholder={(offer.asset_types || []).join(", ") || "e.g. motorcycle"} />
          </div>
          <div className="form-group">
            <label className="form-label">Roughly what does it cost? (optional)</label>
            <input inputMode="numeric" value={value} onChange={e => setValue(e.target.value)}
              placeholder="e.g. 1,200,000" />
          </div>
          <div className="form-group">
            <label className="form-label">Anything they should know? (optional)</label>
            <textarea rows={3} value={note} onChange={e => setNote(e.target.value)} />
          </div>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
            <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}
              style={{ marginTop: 3 }} />
            <span>
              I agree to share my business record with <strong>{name}</strong> — sales totals,
              how steadily I record, margin, how my customers pay and how I pay suppliers.
              My customers&apos; names and phone numbers are never shared. I can withdraw this
              application while it is still under review.
            </span>
          </label>
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={busy || !consent}>
            {busy ? "Sending…" : "Send application"}
          </button>
        </div>
      </div>
    </div>
  );
}
