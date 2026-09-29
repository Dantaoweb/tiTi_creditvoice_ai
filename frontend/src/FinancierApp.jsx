import { useEffect, useState } from "react";
import { Routes, Route, Navigate, useNavigate, useParams } from "react-router-dom";
import { ShieldCheck, LogOut, ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import { apiFetch, apiPost } from "./lib/api";
import { nairaFull, dateStr } from "./lib/format";

// The financier portal, served at /financier — deliberately its own small app.
// A financier is not a CreditVoice business and not a user's business partner,
// so this shares no layout, no sidebar and no cookie with the business app.

function Shell({ who, children, onSignOut }) {
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg, #f6f7f9)" }}>
      <header style={{
        display: "flex", alignItems: "center", gap: 10, padding: "12px 16px",
        background: "var(--surface, #fff)", borderBottom: "1px solid var(--border, #e5e7eb)",
      }}>
        <ShieldCheck size={20} color="var(--brand)" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 15 }}>
            {who?.financier_name || "Financier portal"}
          </div>
          <div className="text-subtle text-sm">
            {who ? `${who.name} · CreditVoice applications` : "CreditVoice"}
          </div>
        </div>
        {who && (
          <button className="btn btn-ghost btn-sm" onClick={onSignOut}>
            <LogOut size={14} /> Sign out
          </button>
        )}
      </header>
      <main style={{ maxWidth: 900, margin: "0 auto", padding: 16 }}>{children}</main>
    </div>
  );
}

function Login({ onSignedIn }) {
  const [mode, setMode] = useState("login");       // login | invite
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit() {
    setBusy(true); setErr("");
    try {
      if (mode === "invite") {
        await apiPost("financier/accept-invite", { code: code.trim(), pin: pin.trim() });
      } else {
        await apiPost("financier/login", { phone: phone.trim(), pin: pin.trim() });
      }
      onSignedIn();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ maxWidth: 420, margin: "40px auto" }}>
      <div className="card-header">
        <span className="card-title">
          {mode === "invite" ? "Set up your access" : "Financier sign in"}
        </span>
      </div>
      <div className="card-body">
        {err && <div className="modal-error">{err}</div>}
        {mode === "invite" ? (
          <>
            <div className="form-group">
              <label className="form-label">Invite code</label>
              <input value={code} onChange={e => setCode(e.target.value.toUpperCase())}
                placeholder="FIN-XXXXXX" autoFocus />
            </div>
            <div className="form-group">
              <label className="form-label">Choose a PIN (4+ digits)</label>
              <input inputMode="numeric" type="password" value={pin}
                onChange={e => setPin(e.target.value)} />
            </div>
          </>
        ) : (
          <>
            <div className="form-group">
              <label className="form-label">Phone number</label>
              <input inputMode="tel" value={phone} onChange={e => setPhone(e.target.value)} autoFocus />
            </div>
            <div className="form-group">
              <label className="form-label">PIN</label>
              <input inputMode="numeric" type="password" value={pin}
                onChange={e => setPin(e.target.value)} />
            </div>
          </>
        )}
        <button className="btn btn-primary" style={{ width: "100%" }} disabled={busy} onClick={submit}>
          {busy ? "Please wait…" : mode === "invite" ? "Set PIN and continue" : "Sign in"}
        </button>
        <button className="btn btn-ghost btn-sm" style={{ width: "100%", marginTop: 8 }}
          onClick={() => { setMode(mode === "invite" ? "login" : "invite"); setErr(""); }}>
          {mode === "invite" ? "I already have a PIN" : "I have an invite code"}
        </button>
      </div>
    </div>
  );
}

const STAGES = {
  SHARED:    ["New", "#92400e", "rgba(180,83,9,0.10)"],
  IN_REVIEW: ["Reviewing", "#1d4ed8", "rgba(29,78,216,0.10)"],
  APPROVED:  ["Approved", "#166534", "rgba(22,101,52,0.10)"],
  DELIVERED: ["Delivered", "#166534", "rgba(22,101,52,0.16)"],
  DECLINED:  ["Declined", "#b91c1c", "rgba(185,28,28,0.10)"],
  WITHDRAWN: ["Withdrawn", "#6b7280", "rgba(107,114,128,0.12)"],
};

function Stage({ status }) {
  const [label, color, background] = STAGES[status] || [status, "#6b7280", "rgba(107,114,128,0.12)"];
  return <span className="badge" style={{ color, background, fontWeight: 700 }}>{label}</span>;
}

function Queue() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("");
  const [err, setErr] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    apiFetch("financier/applications", status ? { status } : {})
      .then(setData).catch(e => setErr(e.message));
  }, [status]);

  if (err) return <div style={{ color: "var(--rose)" }}>{err}</div>;
  if (!data) return <p className="td-muted">Loading applications…</p>;

  return (
    <>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {["", "SHARED", "IN_REVIEW", "APPROVED", "DELIVERED", "DECLINED"].map(s => (
          <button key={s || "all"} className={`btn btn-sm btn-pill ${status === s ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setStatus(s)}>
            {s ? `${(STAGES[s] || [s])[0]} (${data.counts?.[s] ?? 0})` : "All"}
          </button>
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">
            Applications <span className="text-subtle text-sm">({data.applications.length})</span>
          </span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Business</th><th>Wants</th><th>Evidence</th><th>Sent</th><th>Stage</th></tr>
            </thead>
            <tbody>
              {data.applications.length === 0 ? (
                <tr><td colSpan={5} className="td-muted">Nothing here yet.</td></tr>
              ) : data.applications.map(a => (
                <tr key={a.id} style={{ cursor: "pointer" }}
                  onClick={() => navigate(`/applications/${a.id}`)}>
                  <td>
                    <strong>{a.business_name || "—"}</strong>
                    <div className="td-mono td-muted" style={{ fontSize: 11 }}>{a.application_code}</div>
                  </td>
                  <td>
                    {a.asset_requested || "—"}
                    {a.asset_value ? <div className="td-muted" style={{ fontSize: 11 }}>{nairaFull(a.asset_value)}</div> : null}
                  </td>
                  <td>
                    {a.tier} · {a.score ?? "—"}
                    <div className="td-muted" style={{ fontSize: 11 }}>records {a.confidence}%</div>
                  </td>
                  <td className="td-muted">{a.created_at ? dateStr(a.created_at) : "—"}</td>
                  <td><Stage status={a.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function Application() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [a, setA] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function load() {
    apiFetch(`financier/applications/${id}`).then(setA).catch(e => setErr(e.message));
  }
  useEffect(load, [id]);

  async function move(status) {
    let decline_reason;
    if (status === "DECLINED") {
      decline_reason = window.prompt("Why are you declining? The business will see this.");
      if (!decline_reason) return;
    }
    setBusy(true); setErr("");
    try {
      const body = { status };
      if (decline_reason) body.decline_reason = decline_reason;
      if (status === "APPROVED") {
        const value = window.prompt("Asset value you are financing (₦)", String(a.asset_value || ""));
        if (value) body.asset_value = Number(String(value).replace(/[^0-9]/g, ""));
        const ref = window.prompt("Your own reference for this deal (optional)", a.partner_ref || "");
        if (ref) body.partner_ref = ref;
      }
      setA(await apiFetch(`financier/applications/${id}`, {}, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }));
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function confirmRepayment(installment_no) {
    setBusy(true); setErr("");
    try {
      await apiPost(`financier/applications/${id}/confirm-repayment`, { installment_no });
      load();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  if (err) return <div style={{ color: "var(--rose)" }}>{err}</div>;
  if (!a) return <p className="td-muted">Loading…</p>;

  const m = a.snapshot?.metrics || {};
  const k = a.kyc || {};

  return (
    <>
      <button className="btn btn-ghost btn-sm" onClick={() => navigate("/")}>
        <ArrowLeft size={14} /> All applications
      </button>

      <div className="card" style={{ marginTop: 10 }}>
        <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
          <span className="card-title">{a.business_name} · {a.application_code}</span>
          <Stage status={a.status} />
        </div>
        <div className="card-body">
          <p className="text-subtle text-sm">
            Wants {a.asset_requested || "—"}
            {a.asset_value ? ` · about ${nairaFull(a.asset_value)}` : ""}.
            {a.note ? ` They said: "${a.note}"` : ""}
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            {(a.next_statuses || []).map(s => (
              <button key={s} className={`btn btn-sm ${s === "DECLINED" ? "btn-ghost text-rose" : "btn-primary"}`}
                disabled={busy} onClick={() => move(s)}>
                {s === "IN_REVIEW" ? "Start reviewing"
                  : s === "APPROVED" ? "Approve"
                  : s === "DELIVERED" ? "Mark asset delivered"
                  : "Decline"}
              </button>
            ))}
          </div>
          {a.decline_reason && (
            <div className="text-subtle text-sm" style={{ marginTop: 8 }}>
              Declined: {a.decline_reason}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">Trading record (as at application)</span></div>
        <div className="table-scroll">
          <table className="history-table">
            <tbody>
              <tr><td>Score / tier / records complete</td>
                  <td className="receipt-right">{a.score ?? "—"} · {a.tier} · {a.confidence}%</td></tr>
              <tr><td>Average monthly sales</td><td className="receipt-right">{nairaFull(m.avg_monthly_sales)}</td></tr>
              <tr><td>Lowest month</td><td className="receipt-right">{nairaFull(m.min_monthly_sales)}</td></tr>
              <tr><td>Months recorded · days per month</td>
                  <td className="receipt-right">{m.months_recorded} · {m.avg_active_days_per_month}</td></tr>
              <tr><td>Gross margin (based on)</td>
                  <td className="receipt-right">{m.gross_margin_pct}% ({m.margin_coverage_pct}% of sales)</td></tr>
              <tr><td>Customers · returning</td>
                  <td className="receipt-right">{m.total_customers} · {m.repeat_customer_pct}%</td></tr>
              <tr><td>Credit given · collected back</td>
                  <td className="receipt-right">{nairaFull(m.credit_sales)} · {m.collection_rate_pct}%</td></tr>
              <tr><td>Owed to them · due in 30 days</td>
                  <td className="receipt-right">{nairaFull(m.receivables)} · {nairaFull(m.expected_next_30_days)}</td></tr>
              <tr><td>Suppliers paid · overdue</td>
                  <td className="receipt-right">{m.supplier_paid_pct}% · {nairaFull(m.overdue_payables)}</td></tr>
              <tr><td>Sales tied to a named customer</td>
                  <td className="receipt-right">{m.corroborated_revenue_pct}%</td></tr>
              {m.has_financing && (
                <tr><td>Past financing repaid on time</td>
                    <td className="receipt-right">{m.repayment_on_time_pct}% of {m.repayment_settled}</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="card-body text-subtle text-sm">
          CreditVoice reports what this business recorded. It does not lend, approve or
          recommend — the decision is yours.
        </div>
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">Who they are</span></div>
        <div className="table-scroll">
          <table className="history-table">
            <tbody>
              <tr><td>Name on ID</td><td className="receipt-right">{k.legal_name || "—"}</td></tr>
              <tr><td>Where</td><td className="receipt-right">{k.city}{k.city && k.state ? ", " : ""}{k.state}</td></tr>
              <tr><td>Address</td><td className="receipt-right">{k.address || "—"}</td></tr>
              <tr><td>ID</td><td className="receipt-right">{k.id_type || "—"} {k.id_number || ""}</td></tr>
              <tr><td>Registered business</td>
                  <td className="receipt-right">
                    {k.is_registered ? `Yes · ${k.registration_number || ""}` : "No"}
                  </td></tr>
              <tr><td>Guarantor</td>
                  <td className="receipt-right">{k.guarantor_name || "—"} {k.guarantor_phone || ""}</td></tr>
              <tr><td>Contact</td>
                  <td className="receipt-right">{a.contact_phone || "shown once approved"}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      {a.schedule && (
        <div className="card">
          <div className="card-header" style={{ flexWrap: "wrap", gap: 8 }}>
            <span className="card-title">Repayments</span>
            <span className="text-subtle text-sm">
              {a.schedule.settled_count} of {a.schedule.count} paid ·
              {" "}{nairaFull(a.schedule.outstanding)} outstanding
            </span>
          </div>
          <div className="table-scroll">
            <table>
              <thead><tr><th>#</th><th>Due</th><th>Amount</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {a.schedule.installments.map(i => (
                  <tr key={i.installment_no}>
                    <td>{i.installment_no}</td>
                    <td className="td-muted">{i.due_date ? dateStr(i.due_date) : "—"}</td>
                    <td>{nairaFull(i.amount)}</td>
                    <td>
                      {i.confirmed >= i.amount
                        ? <span className="badge badge-green"><CheckCircle2 size={11} /> confirmed</span>
                        : i.settled
                          ? <span className="badge" style={{ color: "#92400e", background: "rgba(180,83,9,0.10)" }}>
                              they say paid
                            </span>
                          : i.overdue
                            ? <span className="badge" style={{ color: "#b91c1c", background: "rgba(185,28,28,0.10)" }}>
                                <XCircle size={11} /> overdue
                              </span>
                            : <span className="td-muted">due</span>}
                    </td>
                    <td>
                      {i.settled && i.confirmed < i.amount && (
                        <button className="btn btn-ghost btn-xs" disabled={busy}
                          onClick={() => confirmRepayment(i.installment_no)}>
                          confirm received
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

export default function FinancierApp() {
  const [who, setWho] = useState(null);
  const [checked, setChecked] = useState(false);

  function loadMe() {
    return apiFetch("financier/me")
      .then(setWho)
      .catch(() => setWho(null))
      .finally(() => setChecked(true));
  }
  useEffect(() => { loadMe(); }, []);

  async function signOut() {
    await apiPost("financier/logout", {}).catch(() => {});
    setWho(null);
  }

  if (!checked) return <Shell><p className="td-muted">Loading…</p></Shell>;
  if (!who) return <Shell><Login onSignedIn={loadMe} /></Shell>;

  return (
    <Shell who={who} onSignOut={signOut}>
      <Routes>
        <Route index element={<Queue />} />
        <Route path="applications/:id" element={<Application />} />
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
