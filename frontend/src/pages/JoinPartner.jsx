import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Handshake, Check, AlertCircle, Loader2 } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";

export default function JoinPartner() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [invite, setInvite] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");

  useEffect(() => {
    apiFetch(`partners/join/${token}`).then(setInvite).catch(e => setError(e.message));
  }, [token]);

  async function accept() {
    setBusy(true); setError("");
    try {
      await apiPost(`partners/join/${token}/accept`, {});
      setDone("accepted");
      setTimeout(() => navigate("/partners"), 1400);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  async function decline() {
    if (!window.confirm("Decline this invitation?")) return;
    setBusy(true); setError("");
    try {
      await apiPost(`partners/join/${token}/decline`, {});
      setDone("declined");
      setTimeout(() => navigate("/partners"), 1400);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  if (error && !invite) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
        <AlertCircle size={32} color="var(--rose)" style={{ margin: "0 auto 12px" }} />
        <div style={{ fontWeight: 700, marginBottom: 6 }}>Invitation unavailable</div>
        <p className="text-subtle">{error}</p>
        <button className="btn btn-secondary" style={{ marginTop: 16 }} onClick={() => navigate("/partners")}>
          Go to Partners
        </button>
      </div>
    );
  }

  if (!invite) {
    return <div className="card card-body" style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <Loader2 size={16} className="spin" /> Loading invitation…
    </div>;
  }

  if (done) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
        <Check size={32} color="var(--brand)" style={{ margin: "0 auto 12px" }} />
        <div style={{ fontWeight: 700 }}>
          {done === "accepted" ? "Invitation accepted 🎉" : "Invitation declined"}
        </div>
        <p className="text-subtle" style={{ marginTop: 6 }}>Taking you to Partners…</p>
      </div>
    );
  }

  const alreadyActive = invite.status === "active";

  return (
    <div style={{ maxWidth: 520, margin: "0 auto" }}>
      <div className="card" style={{ textAlign: "center" }}>
        <Handshake size={34} color="var(--brand)" style={{ margin: "4px auto 10px" }} />
        <div style={{ fontSize: 20, fontWeight: 800 }}>{invite.business_name}</div>
        <p className="text-subtle" style={{ marginTop: 4 }}>
          {invite.owner_name} invited you to join as
        </p>
        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--brand)", margin: "6px 0 2px" }}>
          {invite.role_label}
        </div>
        <p className="text-subtle text-sm">{invite.access_label}</p>

        {(invite.equity_percent != null || invite.investment_amount != null) && (
          <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", marginTop: 16 }}>
            {invite.equity_percent != null && (
              <div className="parsed-cell"><span>Equity</span><strong>{invite.equity_percent}%</strong></div>
            )}
            {invite.investment_amount != null && (
              <div className="parsed-cell"><span>Investment</span><strong>{nairaFull(invite.investment_amount)}</strong></div>
            )}
          </div>
        )}

        {error && (
          <div className="card-body" style={{ color: "var(--rose)", display: "flex", gap: 8, justifyContent: "center", marginTop: 12 }}>
            <AlertCircle size={16} /> {error}
          </div>
        )}

        {invite.is_own_invite ? (
          <p className="text-subtle" style={{ marginTop: 18 }}>
            This is your own business invite — share this link with the person you invited.
          </p>
        ) : alreadyActive ? (
          <p className="text-subtle" style={{ marginTop: 18 }}>
            You've already accepted this invitation.
            <br /><button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => navigate("/partners")}>View businesses I'm in</button>
          </p>
        ) : (
          <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 20 }}>
            <button className="btn btn-primary" disabled={busy} onClick={accept}>
              {busy ? "Working…" : "Accept invitation"}
            </button>
            <button className="btn btn-secondary" disabled={busy} onClick={decline} style={{ color: "var(--rose)" }}>
              Decline
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
