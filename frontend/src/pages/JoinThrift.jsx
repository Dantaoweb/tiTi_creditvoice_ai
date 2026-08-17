import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Users, Check, AlertCircle, Loader2 } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";

const cap = s => (s || "—").replace(/\b\w/g, c => c.toUpperCase());

export default function JoinThrift() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [joined, setJoined] = useState(null);

  useEffect(() => {
    apiFetch(`thrift/join/${token}`).then(setInfo).catch(e => setError(e.message));
  }, [token]);

  async function join() {
    setBusy(true); setError("");
    try {
      const r = await apiPost(`thrift/join/${token}`, {});
      setJoined(r.status);
      setTimeout(() => navigate("/thrift"), 1600);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  if (error && !info) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
        <AlertCircle size={32} color="var(--rose)" style={{ margin: "0 auto 12px" }} />
        <div style={{ fontWeight: 700, marginBottom: 6 }}>Group unavailable</div>
        <p className="text-subtle">{error}</p>
        <button className="btn btn-secondary" style={{ marginTop: 16 }} onClick={() => navigate("/thrift")}>Go to Thrift</button>
      </div>
    );
  }
  if (!info) {
    return <div className="card card-body" style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <Loader2 size={16} className="spin" /> Loading group…
    </div>;
  }
  if (joined) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "40px 24px" }}>
        <Check size={32} color="var(--brand)" style={{ margin: "0 auto 12px" }} />
        <div style={{ fontWeight: 700 }}>
          {joined === "pending" ? "Request sent 🎉" : "You've joined 🎉"}
        </div>
        <p className="text-subtle" style={{ marginTop: 6 }}>
          {joined === "pending" ? "The group admin will approve you shortly." : "Taking you to your groups…"}
        </p>
      </div>
    );
  }

  const alreadyIn = info.my_status && info.my_status !== "declined";

  return (
    <div style={{ maxWidth: 480, margin: "0 auto" }}>
      <div className="card" style={{ textAlign: "center" }}>
        <Users size={34} color="var(--brand)" style={{ margin: "4px auto 10px" }} />
        <div style={{ fontSize: 20, fontWeight: 800 }}>{info.name}</div>
        <p className="text-subtle" style={{ marginTop: 4 }}>
          {cap(info.admin_name)} invited you to join this ajo / thrift group
        </p>
        {info.spilled && (
          <p className="text-sm" style={{ marginTop: 6, color: "var(--brand)" }}>
            ♻ The earlier group filled up — you'll join <strong>{info.name}</strong>.
          </p>
        )}

        <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", marginTop: 16 }}>
          {info.group_type === "target" ? (
            <>
              <div className="parsed-cell"><span>Goal</span><strong>{nairaFull(info.goal_amount)}</strong></div>
              <div className="parsed-cell"><span>Save</span><strong>any amount, anytime</strong></div>
            </>
          ) : (
            <>
              <div className="parsed-cell"><span>Contribution</span><strong>{nairaFull(info.contribution_amount)}</strong></div>
              <div className="parsed-cell"><span>How often</span><strong>{cap(info.frequency)}</strong></div>
            </>
          )}
          <div className="parsed-cell"><span>Members</span><strong>{info.member_count}{info.max_members ? `/${info.max_members}` : ""}</strong></div>
        </div>

        {error && (
          <div className="card-body" style={{ color: "var(--rose)", display: "flex", gap: 8, justifyContent: "center", marginTop: 12 }}>
            <AlertCircle size={16} /> {error}
          </div>
        )}

        {alreadyIn ? (
          <p className="text-subtle" style={{ marginTop: 18 }}>
            You're {info.my_status === "pending" ? "awaiting approval" : "already a member"} of this group.
            <br /><button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => navigate("/thrift")}>View my groups</button>
          </p>
        ) : !info.accepting ? (
          <p className="text-subtle" style={{ marginTop: 18 }}>
            {info.closed_reason || "This group is not accepting new members."}
          </p>
        ) : (
          <div style={{ marginTop: 20 }}>
            {info.require_approval && (
              <p className="text-subtle text-sm" style={{ marginBottom: 10 }}>Joining sends a request the admin approves.</p>
            )}
            <button className="btn btn-primary" disabled={busy} onClick={join}>
              {busy ? "Joining…" : "Join this group"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
