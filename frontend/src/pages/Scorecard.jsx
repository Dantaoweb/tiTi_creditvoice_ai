import { useEffect, useState } from "react";
import { ShieldCheck, TrendingUp, Info, CheckCircle2, XCircle, ExternalLink } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateStr, parseAmt } from "../lib/format";
import MetricCard from "../components/MetricCard";

// The business's own evidence file: what CreditVoice can show a finance partner
// about its trading record. CreditVoice lends nothing and approves nothing —
// partners underwrite — so the wording here never promises anyone anything.

// Plain-language meaning for a component, from the advice endpoint.
function meaningFor(advice, key) {
  const found = (advice?.explanations || []).find(e => e.key === key);
  return found?.meaning || "";
}

function Bar({ value, tone = "brand" }) {
  return (
    <div style={{ height: 6, background: "rgba(127,127,127,0.15)", borderRadius: 3, overflow: "hidden" }}>
      <div style={{
        height: "100%", width: `${Math.max(0, Math.min(100, value))}%`,
        background: tone === "amber" ? "var(--amber)" : "var(--brand)", borderRadius: 3,
        transition: "width .3s",
      }} />
    </div>
  );
}

function TierBadge({ tier, score }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <ShieldCheck size={22} color="var(--brand)" />
      <div>
        <div style={{ fontSize: 20, fontWeight: 800 }}>{tier}</div>
        <div className="text-subtle text-sm">
          {score === null ? "Not enough records yet" : `Score ${score} of 100`}
        </div>
      </div>
    </div>
  );
}

function MonthlySales({ months }) {
  const entries = Object.entries(months || {});
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="card">
      <div className="card-header"><span className="card-title">Sales by month</span></div>
      <div className="card-body" style={{ display: "grid", gap: 8 }}>
        {entries.map(([month, value]) => (
          <div key={month} style={{ display: "grid", gridTemplateColumns: "72px 1fr auto", gap: 10, alignItems: "center" }}>
            <span className="text-subtle text-sm">{month}</span>
            <Bar value={(value / max) * 100} />
            <strong style={{ fontSize: 13 }}>{nairaFull(value)}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

const APPLICATION_STATUS = {
  SUBMITTED: ["Sent to CreditVoice", "#92400e", "rgba(180,83,9,0.10)"],
  SHARED:    ["Shared with partner", "#1d4ed8", "rgba(29,78,216,0.10)"],
  IN_REVIEW: ["Partner reviewing", "#1d4ed8", "rgba(29,78,216,0.10)"],
  APPROVED:  ["Approved", "#166534", "rgba(22,101,52,0.10)"],
  DELIVERED: ["Asset delivered", "#166534", "rgba(22,101,52,0.12)"],
  DECLINED:  ["Declined", "#b91c1c", "rgba(185,28,28,0.10)"],
  WITHDRAWN: ["Withdrawn", "#6b7280", "rgba(107,114,128,0.12)"],
};

function StatusPill({ status }) {
  const [label, color, bg] = APPLICATION_STATUS[status] || [status, "#6b7280", "rgba(107,114,128,0.12)"];
  return <span className="badge" style={{ color, background: bg, fontWeight: 700 }}>{label}</span>;
}

// Identity details, asked at the point a financier needs them — never at
// sign-up. The owner fills this once and it is reused for every application.
function KycModal({ onClose, onSaved }) {
  const [meta, setMeta] = useState(null);
  const [form, setForm] = useState({});
  const [missing, setMissing] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    Promise.all([apiFetch("finance-meta"), apiFetch("kyc")])
      .then(([m, k]) => {
        setMeta(m);
        setForm(k.kyc || {});
        setMissing((k.missing || []).map(x => x.key));
      })
      .catch(e => setErr(e.message));
  }, []);

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  async function save() {
    setBusy(true); setErr("");
    try {
      const r = await apiPost("kyc", form);
      if (!r.complete) {
        setMissing((r.missing || []).map(x => x.key));
        setErr(`Still needed: ${(r.missing || []).map(x => x.label).join(", ")}`);
        return;
      }
      onSaved();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const need = k => missing.includes(k);

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
            Financiers must know who they are dealing with. You enter this once, and it
            is shared only with the partner you apply to.
          </p>
          {!meta ? <p className="td-muted">Loading…</p> : (
            <>
              <div className="form-group">
                <label className="form-label">Full name, as on your ID *</label>
                <input value={form.legal_name || ""} onChange={e => set("legal_name", e.target.value)}
                  style={need("legal_name") ? { borderColor: "var(--amber)" } : undefined} />
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
                  Being unregistered is fine — most partners accept it. A few only finance
                  registered businesses.
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
                  <input value={form.guarantor_name || ""} onChange={e => set("guarantor_name", e.target.value)} />
                </div>
                <div className="form-group" style={{ flex: "1 1 150px" }}>
                  <label className="form-label">Guarantor phone</label>
                  <input inputMode="tel" value={form.guarantor_phone || ""}
                    onChange={e => set("guarantor_phone", e.target.value)} />
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <div className="form-group" style={{ flex: "1 1 130px" }}>
                  <label className="form-label">Years in business</label>
                  <input inputMode="numeric" value={form.years_in_business ?? ""}
                    onChange={e => set("years_in_business", e.target.value)} />
                </div>
                <div className="form-group" style={{ flex: "1 1 130px" }}>
                  <label className="form-label">People working with you</label>
                  <input inputMode="numeric" value={form.employees ?? ""}
                    onChange={e => set("employees", e.target.value)} />
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

// Applying shares this business's trading record with one partner. Consent is
// explicit, and the scorecard is frozen at this moment so what the partner sees
// can't drift afterwards.
function ApplyModal({ offer, onClose, onDone }) {
  const [asset, setAsset] = useState((offer.asset_types || [])[0] || "");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit() {
    setBusy(true); setErr("");
    try {
      await apiPost(`finance-offers/${offer.id}/apply`, {
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
          <span className="modal-title">Apply — {offer.name}</span>
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
            <input inputMode="numeric" value={value} onChange={e => setValue(e.target.value)} placeholder="e.g. 1,200,000" />
          </div>
          <div className="form-group">
            <label className="form-label">Anything they should know? (optional)</label>
            <textarea rows={3} value={note} onChange={e => setNote(e.target.value)} />
          </div>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
            <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}
              style={{ marginTop: 3 }} />
            <span>
              I agree to share my business record with <strong>{offer.name}</strong> — sales totals,
              how steadily I record, margin, how my customers pay and how I pay suppliers.
              My customers' names and phone numbers are never shared. I can withdraw this
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

// A financed asset's repayment plan. It also lives on the Suppliers page (each
// installment is a supplier bill), but the plan reads clearer in one place.
function RepaymentPlan({ application, onPaid }) {
  const [schedule, setSchedule] = useState(null);
  const [busy, setBusy] = useState(null);      // installment number being paid
  const [err, setErr] = useState("");

  function load() {
    apiFetch(`my-applications/${application.id}/schedule`)
      .then(d => setSchedule(d.schedule))
      .catch(e => setErr(e.message));
  }
  useEffect(load, [application.id]);

  async function pay(inst) {
    const typed = window.prompt(
      `How much did you pay towards installment ${inst.installment_no}?`,
      String(inst.outstanding));
    if (typed === null) return;
    const amount = parseAmt(typed);
    if (!amount || amount <= 0) return;
    setBusy(inst.installment_no); setErr("");
    try {
      const r = await apiPost(`my-applications/${application.id}/repayments`,
        { installment_no: inst.installment_no, amount });
      setSchedule(r.schedule);
      onPaid && onPaid();
    } catch (e) { setErr(e.message); }
    finally { setBusy(null); }
  }

  if (err) return <div style={{ color: "var(--rose)", fontSize: 12 }}>{err}</div>;
  if (!schedule) return null;

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="card-title">
          Repayments — {application.partner_name} · {application.asset_requested || "asset"}
        </span>
        <span className="text-subtle text-sm">
          {schedule.settled_count} of {schedule.count} paid · {nairaFull(schedule.outstanding)} left
          {schedule.overdue_count > 0 && <span style={{ color: "var(--rose)" }}> · {schedule.overdue_count} overdue</span>}
        </span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>#</th><th>Due</th><th>Amount</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {schedule.installments.map(i => (
              <tr key={i.installment_no} className={i.overdue ? "low-stock" : ""}>
                <td>{i.installment_no}</td>
                <td className="td-muted">{i.due_date ? dateStr(i.due_date) : "—"}</td>
                <td>{nairaFull(i.amount)}{i.paid > 0 && !i.settled ? ` · paid ${nairaFull(i.paid)}` : ""}</td>
                <td>
                  {i.settled ? (
                    i.confirmed >= i.amount
                      ? <span className="badge badge-green">Paid ✓ confirmed</span>
                      : <span className="badge" style={{ color: "#92400e", background: "rgba(180,83,9,0.10)" }}>
                          Paid · awaiting confirmation
                        </span>
                  ) : i.overdue ? (
                    <span className="badge" style={{ color: "#b91c1c", background: "rgba(185,28,28,0.10)" }}>Overdue</span>
                  ) : <span className="td-muted">Due</span>}
                </td>
                <td>
                  {!i.settled && (
                    <button className="btn btn-primary btn-xs" disabled={busy === i.installment_no}
                      onClick={() => pay(i)}>
                      {busy === i.installment_no ? "Saving…" : "I have paid"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-body text-subtle text-sm">
        Each installment also appears under Suppliers, where you pay everyone else.
        A repayment counts towards your record once {application.partner_name} confirms it.
      </div>
    </div>
  );
}

function MyApplications({ applications, onWithdraw }) {
  if (!applications || applications.length === 0) return null;
  return (
    <div className="card">
      <div className="card-header"><span className="card-title">My financing applications</span></div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Partner</th><th>Item</th><th>Ref</th><th>Sent</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {applications.map(r => (
              <tr key={r.id}>
                <td><strong>{r.partner_name || "—"}</strong></td>
                <td>{r.asset_requested || "—"}{r.asset_value ? ` · ${nairaFull(r.asset_value)}` : ""}</td>
                <td className="td-mono td-muted">{r.application_code}</td>
                <td className="td-muted">{r.created_at ? dateStr(r.created_at) : "—"}</td>
                <td>
                  <StatusPill status={r.status} />
                  {r.decline_reason && (
                    <div className="td-muted" style={{ fontSize: 11 }}>{r.decline_reason}</div>
                  )}
                </td>
                <td>
                  {["SUBMITTED", "SHARED", "IN_REVIEW"].includes(r.status) && (
                    <button className="btn btn-ghost btn-xs text-rose" onClick={() => onWithdraw(r)}>
                      Withdraw
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Offer({ offer, onApply }) {
  const assets = (offer.asset_types || []).join(", ");
  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="card-title">{offer.name}</span>
        <span className="badge" style={{
          background: offer.eligible ? "rgba(22,101,52,0.10)" : "rgba(180,83,9,0.10)",
          color: offer.eligible ? "#166534" : "#92400e", fontWeight: 700,
        }}>
          {offer.eligible ? "You meet their requirements" : "Not there yet"}
        </span>
      </div>
      <div className="card-body">
        {assets && <div className="text-subtle text-sm" style={{ marginBottom: 6 }}>Finances: {assets}</div>}
        {offer.coverage && (
          <div className="text-subtle text-sm" style={{ marginBottom: 6 }}>
            Covers: {offer.coverage}
            {offer.covered === false && (
              <strong style={{ color: "var(--amber)" }}> — not available where you are</strong>
            )}
          </div>
        )}
        {(offer.asset_value_min || offer.asset_value_max) && (
          <div className="text-subtle text-sm" style={{ marginBottom: 10 }}>
            Value range: {nairaFull(offer.asset_value_min || 0)} – {nairaFull(offer.asset_value_max || 0)}
          </div>
        )}
        {offer.partner_rules && (
          <div className="text-subtle text-sm" style={{ marginBottom: 8 }}>
            {offer.name} weighs things their own way — with them your score is{" "}
            <strong>{offer.score ?? "not rated"}</strong>
            {offer.tier ? ` (${offer.tier})` : ""}.
          </div>
        )}
        {(offer.checks || []).length === 0 ? (
          <div className="text-subtle text-sm">No published requirements — apply and they will review.</div>
        ) : (
          <div style={{ display: "grid", gap: 6 }}>
            {offer.checks.map((c, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                {c.passed
                  ? <CheckCircle2 size={14} color="#166534" />
                  : <XCircle size={14} color="#b45309" />}
                <span style={{ flex: 1 }}>{c.requirement}</span>
                <span className="text-subtle">
                  needs {c.required.toLocaleString()} · you have {Number(c.actual).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        )}
        <div style={{ marginTop: 12 }}>
          {offer.applied_status && !["DECLINED", "WITHDRAWN"].includes(offer.applied_status) ? (
            <StatusPill status={offer.applied_status} />
          ) : offer.covered === false ? (
            <span className="text-subtle text-sm">They do not operate in your state yet.</span>
          ) : (
            <button className="btn btn-primary btn-sm" onClick={() => onApply(offer)}>
              Apply
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// The score is useless if a trader can't see what moved it. Each action is the
// concrete next thing, with the business's own figures in it.
function HowToImprove({ advice }) {
  if (!advice || (advice.actions || []).length === 0) return null;
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">How to improve your score</span>
      </div>
      <div className="card-body" style={{ display: "grid", gap: 12 }}>
        {advice.actions.map((a, i) => (
          <div key={a.key} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{
              flexShrink: 0, width: 22, height: 22, borderRadius: 999, fontSize: 12,
              display: "grid", placeItems: "center", fontWeight: 800,
              background: "rgba(37,99,235,0.12)", color: "var(--brand)",
            }}>{i + 1}</span>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                {a.label}
                {a.possible_gain > 0 && (
                  <span className="text-subtle text-sm"> · up to +{a.possible_gain} points</span>
                )}
              </div>
              <div className="text-subtle text-sm">{a.action}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Scorecard() {
  const [card, setCard] = useState(null);
  const [offers, setOffers] = useState(null);
  const [applications, setApplications] = useState([]);
  const [advice, setAdvice] = useState(null);
  const [applying, setApplying] = useState(null);   // the offer being applied to
  const [kycOpen, setKycOpen] = useState(false);
  const [pendingOffer, setPendingOffer] = useState(null);   // resume after details
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function loadOffers() {
    return Promise.all([apiFetch("finance-offers"), apiFetch("my-applications")])
      .then(([o, r]) => { setOffers(o); setApplications(r.applications || []); });
  }

  useEffect(() => {
    Promise.all([
      apiFetch("scorecard").then(setCard),
      apiFetch("scorecard/advice").then(setAdvice).catch(() => {}),
      loadOffers(),
    ])
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Financiers need identity details; collect them at this point rather than
  // at sign-up, then carry on into the application the owner wanted.
  function startApply(offer) {
    if (offers && offers.kyc_complete === false) {
      setPendingOffer(offer);
      setKycOpen(true);
      return;
    }
    setApplying(offer);
  }

  async function withdraw(r) {
    if (!window.confirm(`Withdraw your application to ${r.partner_name}? Your record will no longer be shared with them.`)) return;
    try { await apiPost(`my-applications/${r.id}/withdraw`, {}); await loadOffers(); }
    catch (e) { setError(e.message); }
  }

  if (loading) return <div className="page-loading">Loading your scorecard…</div>;
  if (error) return <div style={{ color: "var(--rose)" }}>{error}</div>;

  const m = card.metrics;

  return (
    <>
      <div className="card">
        <div className="card-header" style={{ flexWrap: "wrap", gap: 12 }}>
          <TierBadge tier={card.tier} score={card.score} />
          <div style={{ textAlign: "right" }}>
            <div className="text-subtle text-sm">Evidence strength</div>
            <div style={{ fontWeight: 700 }}>{card.confidence}%</div>
          </div>
        </div>
        <div className="card-body">
          {!card.scored && (
            <div className="card card-body" style={{ color: "var(--amber)", fontSize: 13.5, marginBottom: 12 }}>
              {card.not_scored_reason} Keep recording your sales and it will appear here.
            </div>
          )}
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, color: "var(--text-muted)" }}>
            <Info size={15} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>
              This is a record of what you have entered in CreditVoice. You choose when to share it
              with a finance partner. CreditVoice does not lend and does not approve anything — each
              partner decides for itself.
            </span>
          </div>
        </div>
      </div>

      {offers && offers.kyc_complete === false && (offers.offers || []).length > 0 && (
        <div className="card card-body" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 13.5 }}>
            Financing partners need your business and identity details before you can apply.
          </span>
          <button className="btn btn-primary btn-sm" onClick={() => setKycOpen(true)}>
            Add my details
          </button>
        </div>
      )}

      <div className="metrics-grid">
        <MetricCard label="Average monthly sales" value={nairaFull(m.avg_monthly_sales)} color="brand" />
        <MetricCard label="Lowest month" value={nairaFull(m.min_monthly_sales)} />
        <MetricCard label="Months of records" value={m.months_recorded} />
        <MetricCard label="Due in next 30 days" value={nairaFull(m.expected_next_30_days)} color="blue" />
        <MetricCard label="Owed to you" value={nairaFull(m.receivables)} color={m.receivables > 0 ? "rose" : undefined} />
        <MetricCard label="Customers who return" value={`${m.repeat_customer_pct}%`} />
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">What builds your score</span>
          <span className="text-subtle text-sm">{card.scored ? `Score ${card.score}` : "Unrated"}</span>
        </div>
        <div className="card-body" style={{ display: "grid", gap: 12 }}>
          {card.components.map(c => (
            <div key={c.key}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                <span>{c.label}</span>
                <span className="text-subtle">
                  {typeof c.value === "number" && c.value > 1000 ? nairaFull(c.value) : c.value} · {c.score}/100
                </span>
              </div>
              <Bar value={c.score} tone={c.score < 40 ? "amber" : "brand"} />
              {meaningFor(advice, c.key) && (
                <div className="text-subtle text-sm" style={{ marginTop: 3 }}>
                  {meaningFor(advice, c.key)}
                </div>
              )}
            </div>
          ))}
          {(card.not_applicable || []).length > 0 && (
            <div className="text-subtle text-sm" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
              Not counted for your business:{" "}
              {card.not_applicable.map(s => s.label).join(", ")}. These need records
              you haven't kept, so they don't count against your score.
            </div>
          )}
        </div>
      </div>

      <HowToImprove advice={advice} />

      <MonthlySales months={m.monthly_sales} />

      <div className="card">
        <div className="card-header"><span className="card-title">Your record in detail</span></div>
        <div className="card-body">
          <table className="history-table">
            <tbody>
              <tr><td>Recording days per month</td><td className="receipt-right">{m.avg_active_days_per_month}</td></tr>
              <tr><td>First record</td><td className="receipt-right">{m.first_record_at ? dateStr(m.first_record_at) : "—"}</td></tr>
              <tr><td>On CreditVoice</td><td className="receipt-right">{m.months_on_platform} month(s)</td></tr>
              <tr>
                <td>Gross margin</td>
                <td className="receipt-right">
                  {m.gross_margin_pct}%
                  <span className="text-subtle text-sm"> (based on {m.margin_coverage_pct}% of sales)</span>
                </td>
              </tr>
              <tr><td>Credit given to customers</td><td className="receipt-right">{nairaFull(m.credit_sales)}</td></tr>
              <tr><td>Credit collected back</td><td className="receipt-right">{m.collection_rate_pct}%</td></tr>
              <tr><td>Average days to collect</td><td className="receipt-right">{m.avg_days_to_collect}</td></tr>
              <tr><td>Suppliers paid</td><td className="receipt-right">{m.supplier_paid_pct}%</td></tr>
              <tr><td>Overdue to suppliers</td><td className="receipt-right">{nairaFull(m.overdue_payables)}</td></tr>
              <tr><td>Sales tied to a named customer</td><td className="receipt-right">{m.corroborated_revenue_pct}%</td></tr>
              <tr><td>Customers · staff · products</td><td className="receipt-right">{m.total_customers} · {m.staff_count} · {m.stock_items}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title"><TrendingUp size={15} /> Financing partners</span>
        </div>
        <div className="card-body">
          {(offers?.offers || []).length === 0 ? (
            <p className="td-muted">No partners listed yet. They will appear here as they join.</p>
          ) : (
            offers.offers.map(o => (
              <Offer key={o.id} offer={o} onApply={startApply} />
            ))
          )}
          <div className="text-subtle text-sm" style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
            <ExternalLink size={13} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>
              Partners finance tools and vehicles and let you spread the cost. They run their own
              checks; meeting the requirements here does not guarantee approval.
            </span>
          </div>
        </div>
      </div>

      <MyApplications applications={applications} onWithdraw={withdraw} />

      {applications.filter(a => a.status === "DELIVERED").map(a => (
        <RepaymentPlan key={a.id} application={a} onPaid={loadOffers} />
      ))}

      {kycOpen && (
        <KycModal
          onClose={() => { setKycOpen(false); setPendingOffer(null); }}
          onSaved={async () => {
            setKycOpen(false);
            await loadOffers();
            if (pendingOffer) { setApplying(pendingOffer); setPendingOffer(null); }
          }}
        />
      )}

      {applying && (
        <ApplyModal
          offer={applying}
          onClose={() => setApplying(null)}
          onDone={async () => { setApplying(null); await loadOffers(); }}
        />
      )}
    </>
  );
}
