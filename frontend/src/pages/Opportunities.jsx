import { useEffect, useState } from "react";
import { apiFetch, apiPost } from "../lib/api";
import { ExternalLink, CheckCircle, Clock, XCircle, ChevronRight } from "lucide-react";

const CATEGORY_COLORS = {
  finance:   { bg: "#eff6ff", border: "#bfdbfe", text: "#1d4ed8" },
  equipment: { bg: "#f0fdf4", border: "#bbf7d0", text: "#15803d" },
  trade:     { bg: "#fef3c7", border: "#fcd34d", text: "#b45309" },
  products:  { bg: "#fdf2f8", border: "#f0abfc", text: "#7e22ce" },
  general:   { bg: "#f9fafb", border: "#e5e7eb", text: "#374151" },
};
const CATEGORY_LABELS = {
  finance: "Finance", equipment: "Equipment", trade: "Trade",
  products: "Products", general: "General",
};
const STATUS_CONFIG = {
  submitted:  { label: "Submitted",    color: "#d97706", bg: "#fef3c7", icon: <Clock size={11} /> },
  reviewing:  { label: "Under Review", color: "#2563eb", bg: "#eff6ff", icon: <Clock size={11} /> },
  approved:   { label: "Approved",     color: "#059669", bg: "#d1fae5", icon: <CheckCircle size={11} /> },
  declined:   { label: "Declined",     color: "#dc2626", bg: "#fee2e2", icon: <XCircle size={11} /> },
};

function StatusBadge({ status }) {
  const s = STATUS_CONFIG[status] || STATUS_CONFIG.submitted;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12,
      fontWeight: 600, color: s.color, background: s.bg, borderRadius: 99, padding: "3px 10px" }}>
      {s.icon} {s.label}
    </span>
  );
}

// ── Apply modal ───────────────────────────────────────────────────────────────
function ApplyModal({ opp, user, onClose, onDone }) {
  const fields = JSON.parse(opp.application_fields || "[]");
  const [answers, setAnswers] = useState({});
  const [busy, setBusy]       = useState(false);
  const [done, setDone]       = useState(false);
  const [err, setErr]         = useState("");

  function set(label, val) { setAnswers(a => ({ ...a, [label]: val })); }

  async function submit(e) {
    e.preventDefault(); setErr("");
    const missing = fields.filter(f => f.required && !answers[f.label]?.trim());
    if (missing.length) { setErr(`Please fill in: ${missing.map(f => f.label).join(", ")}`); return; }
    setBusy(true);
    try {
      await apiPost(`opportunities/${opp.id}/apply`, { answers });
      setDone(true);
      onDone();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const c = CATEGORY_COLORS[opp.category] || CATEGORY_COLORS.general;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">Apply — {opp.title}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        {done ? (
          <div style={{ padding: "32px 0", textAlign: "center" }}>
            <CheckCircle size={44} color="var(--green)" style={{ marginBottom: 12 }} />
            <p style={{ fontWeight: 700, fontSize: 16, marginBottom: 6 }}>Application submitted!</p>
            <p style={{ color: "var(--text-muted)", fontSize: 14, lineHeight: 1.7 }}>
              CreditVoice has received your application for <strong>{opp.title}</strong>.
              You can track its status under <em>My Applications</em>.
            </p>
            <button className="btn btn-primary" style={{ marginTop: 20 }} onClick={onClose}>Close</button>
          </div>
        ) : (
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Pre-filled section */}
            <div style={{ background: c.bg, border: `1px solid ${c.border}`, borderRadius: 8, padding: "12px 14px", fontSize: 13 }}>
              <strong>Your details (auto-filled from your account)</strong>
              <div style={{ marginTop: 6, color: "var(--text-secondary)", lineHeight: 1.9 }}>
                <div>Business: <strong>{user?.business_type_label || user?.name || "—"}</strong></div>
                <div>Phone: <strong>{user?.phone || "—"}</strong></div>
                {user?.email && <div>Email: <strong>{user.email}</strong></div>}
              </div>
            </div>

            {/* Custom fields */}
            {fields.map((f, i) => (
              <div key={i} className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">
                  {f.label}{f.required ? " *" : " (optional)"}
                </label>
                {f.type === "select" ? (
                  <select value={answers[f.label] || ""} onChange={e => set(f.label, e.target.value)}>
                    <option value="">Select…</option>
                    {(f.options || []).map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : f.type === "textarea" ? (
                  <textarea rows={3} value={answers[f.label] || ""}
                    onChange={e => set(f.label, e.target.value)}
                    placeholder={f.placeholder || ""} />
                ) : (
                  <input type={f.type || "text"} value={answers[f.label] || ""}
                    onChange={e => set(f.label, e.target.value)}
                    placeholder={f.placeholder || ""} />
                )}
              </div>
            ))}

            {fields.length === 0 && (
              <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
                No additional information needed. Click submit to express your interest.
              </p>
            )}

            {err && <div className="login-error">{err}</div>}

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? "Submitting…" : "Submit Application"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

// ── Opportunity card ──────────────────────────────────────────────────────────
function OpportunityCard({ opp, applied, user, onApplied }) {
  const [showApply, setShowApply] = useState(false);
  const c = CATEGORY_COLORS[opp.category] || CATEGORY_COLORS.general;

  return (
    <>
      <div style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <div style={{ background: c.bg, borderBottom: `1px solid ${c.border}`, padding: "12px 20px",
          display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: c.text, textTransform: "uppercase", letterSpacing: 0.5 }}>
            {CATEGORY_LABELS[opp.category] || opp.category}
          </span>
          {opp.partner_name && (
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{opp.partner_name}</span>
          )}
        </div>
        <div style={{ padding: "18px 20px", flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0, lineHeight: 1.4 }}>{opp.title}</h3>
          <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.7, margin: 0, flex: 1 }}>
            {opp.description}
          </p>
        </div>
        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)", display: "flex", gap: 8 }}>
          {applied ? (
            <div style={{ flex: 1 }}>
              <StatusBadge status={applied.status} />
            </div>
          ) : (
            <button className="btn btn-primary" style={{ flex: 1, justifyContent: "center", fontSize: 13 }}
              onClick={() => setShowApply(true)}>
              Apply / Express Interest
            </button>
          )}
          {opp.link_url && (
            <a href={opp.link_url} target="_blank" rel="noopener noreferrer"
              className="btn btn-secondary" style={{ fontSize: 13, textDecoration: "none" }}
              title="Learn more">
              <ExternalLink size={13} />
            </a>
          )}
        </div>
      </div>

      {showApply && (
        <ApplyModal opp={opp} user={user} onClose={() => setShowApply(false)}
          onDone={() => { setShowApply(false); onApplied(); }} />
      )}
    </>
  );
}

// ── My Applications section ───────────────────────────────────────────────────
function MyApplications({ onBack }) {
  const [apps, setApps]       = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch("opportunities/my-applications")
      .then(d => setApps(d.applications || []))
      .catch(() => setApps([]))
      .finally(() => setLoading(false));
  }, []);

  const dateStr = s => s ? new Date(s).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" }) : "—";

  return (
    <div style={{ maxWidth: 700 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <button className="btn btn-secondary" onClick={onBack}>← Back</button>
        <strong style={{ fontSize: 16 }}>My Applications</strong>
      </div>

      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading…</p>
      ) : apps.length === 0 ? (
        <div style={{ textAlign: "center", padding: "48px 0", color: "var(--text-muted)" }}>
          <p style={{ fontSize: 15, fontWeight: 600 }}>No applications yet</p>
          <p style={{ fontSize: 13 }}>Browse opportunities and click "Apply" to get started.</p>
        </div>
      ) : (
        apps.map(a => (
          <div key={a.id} className="card" style={{ marginBottom: 14, padding: 18 }}>
            <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
              <div>
                <strong style={{ fontSize: 14 }}>{a.opportunity_title}</strong>
                {a.opportunity_partner && (
                  <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: 8 }}>{a.opportunity_partner}</span>
                )}
              </div>
              <StatusBadge status={a.status} />
            </div>
            {Object.keys(a.answers).length > 0 && (
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>
                {Object.entries(a.answers).map(([k, v]) => v ? (
                  <span key={k} style={{ marginRight: 12 }}><strong>{k}:</strong> {v}</span>
                ) : null)}
              </div>
            )}
            {a.admin_notes && (
              <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 6, padding: "8px 12px", fontSize: 13, color: "#15803d", marginTop: 8 }}>
                <strong>Update from CreditVoice:</strong> {a.admin_notes}
              </div>
            )}
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
              Applied {dateStr(a.created_at)}
              {a.updated_at && a.updated_at !== a.created_at && ` · Updated ${dateStr(a.updated_at)}`}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────
export default function Opportunities() {
  const [opps, setOpps]         = useState([]);
  const [myApps, setMyApps]     = useState([]);
  const [loading, setLoading]   = useState(true);
  const [filter, setFilter]     = useState("all");
  const [showMyApps, setShowMyApps] = useState(false);
  const [user, setUser]         = useState(null);

  function loadAll() {
    apiFetch("opportunities")
      .then(d => setOpps(d.opportunities || []))
      .catch(() => setOpps([]))
      .finally(() => setLoading(false));
    apiFetch("opportunities/my-applications")
      .then(d => setMyApps(d.applications || []))
      .catch(() => {});
  }

  useEffect(() => {
    loadAll();
    // Get user info for pre-filling apply form
    const stored = localStorage.getItem("cv_user");
    if (stored) { try { setUser(JSON.parse(stored)); } catch {} }
  }, []);

  if (showMyApps) {
    return <MyApplications onBack={() => setShowMyApps(false)} />;
  }

  const categories = ["all", ...new Set(opps.map(o => o.category))];
  const visible    = filter === "all" ? opps : opps.filter(o => o.category === filter);
  const appliedMap = Object.fromEntries(myApps.map(a => [a.opportunity_id, a]));

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 800, margin: "0 0 4px" }}>Opportunities</h1>
          <p style={{ fontSize: 14, color: "var(--text-muted)", margin: 0 }}>
            Finance, equipment, partnerships and deals curated for CreditVoice businesses.
          </p>
        </div>
        {myApps.length > 0 && (
          <button className="btn btn-secondary" onClick={() => setShowMyApps(true)} style={{ fontSize: 13 }}>
            My Applications ({myApps.length}) <ChevronRight size={13} />
          </button>
        )}
      </div>

      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading opportunities…</p>
      ) : opps.length === 0 ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-muted)" }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🔮</div>
          <p style={{ fontWeight: 600, fontSize: 15 }}>No opportunities yet</p>
          <p style={{ fontSize: 13 }}>Check back soon — new partner offers will appear here.</p>
        </div>
      ) : (
        <>
          {categories.length > 2 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20 }}>
              {categories.map(c => (
                <button key={c} onClick={() => setFilter(c)} style={{
                  padding: "6px 14px", borderRadius: 99, border: "1px solid", cursor: "pointer", fontSize: 13,
                  fontWeight: filter === c ? 700 : 400,
                  borderColor: filter === c ? "var(--brand)" : "var(--border)",
                  background: filter === c ? "var(--brand)" : "transparent",
                  color: filter === c ? "#fff" : "var(--text-secondary)",
                }}>
                  {c === "all" ? "All" : (CATEGORY_LABELS[c] || c)}
                </button>
              ))}
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 20 }}>
            {visible.map(o => (
              <OpportunityCard key={o.id} opp={o} user={user}
                applied={appliedMap[o.id] || null}
                onApplied={loadAll} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
