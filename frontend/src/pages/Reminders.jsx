import { useEffect, useState, useCallback } from "react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull, dateStr, dateTimeStr } from "../lib/format";
import { StatusBadge } from "../components/Badge";
import { getBizLabels } from "../lib/bizLabels";
import { Send, Zap } from "lucide-react";

export default function Reminders() {
  const { ownerPhone } = useApp();
  const { user } = useAuth();
  const L = getBizLabels(user?.menu_group);
  const [rows, setRows]         = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [running, setRunning]   = useState(false);
  const [runResult, setRunResult] = useState(null);
  const [sending, setSending]   = useState(null); // reminder id being sent

  const load = useCallback(() => {
    setLoading(true);
    apiFetch("reminders", { owner_phone: ownerPhone })
      .then((d) => setRows(d.reminders))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ownerPhone]);

  useEffect(load, [load]);

  async function handleRunNow() {
    setRunning(true); setRunResult(null); setError(null);
    try {
      const res = await apiPost("reminders/run", {});
      setRunResult(res);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  async function handleSend(id) {
    setSending(id); setError(null);
    try {
      await apiPost(`reminders/${id}/send`, {});
      setRows(prev => prev.map(r => r.id === id ? { ...r, status: "SENT" } : r));
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(null);
    }
  }

  const counts = rows.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    return acc;
  }, {});

  const pendingCount = rows.filter(r => r.status === "PENDING_OWNER_CONFIRMATION" || r.status === "EDITING").length;

  return (
    <>
      {error && <div style={{ color: "var(--rose)", marginBottom: 10 }}>{error}</div>}

      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {Object.entries(counts).map(([status, count]) => (
            <div key={status} className="card card-body text-sm" style={{ padding: "8px 14px", display: "flex", alignItems: "center", gap: 6 }}>
              <StatusBadge status={status} /> <strong>{count}</strong>
            </div>
          ))}
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={handleRunNow}
          disabled={running}
          title="Generate today's reminder batch"
        >
          <Zap size={13} /> {running ? "Running…" : "Run reminders now"}
        </button>
      </div>

      {runResult && (
        <div className="card card-body" style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", marginBottom: 12, fontSize: 13.5 }}>
          Automation ran: <strong>{runResult.queued}</strong> queued,{" "}
          <strong>{runResult.sent}</strong> sent,{" "}
          <strong>{runResult.skipped}</strong> skipped.
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title">
            Reminder Queue
            {pendingCount > 0 && (
              <span style={{ marginLeft: 8, background: "var(--brand)", color: "#fff", borderRadius: 99, fontSize: 10, padding: "1px 7px", fontWeight: 700, verticalAlign: "middle" }}>
                {pendingCount} pending
              </span>
            )}
          </span>
        </div>

        {loading ? (
          <div style={{ padding: 20, color: "var(--text-muted)", fontSize: 14 }}>Loading…</div>
        ) : rows.length === 0 ? (
          <div style={{ padding: 20, color: "var(--text-muted)", fontSize: 14 }}>
            No reminders queued. Click <strong>Run reminders now</strong> to generate today's batch.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--text-muted)" }}>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>{L.customer}</th>
                  <th style={{ padding: "8px 12px", textAlign: "right" }}>Balance</th>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>Due</th>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>Status</th>
                  <th style={{ padding: "8px 12px", textAlign: "left", maxWidth: 220 }}>Message</th>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>Queued</th>
                  <th style={{ padding: "8px 12px" }}></th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "10px 12px", fontWeight: 600 }}>
                      {(r.customer_name || "—").replace(/\b\w/g, c => c.toUpperCase())}
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right", color: "var(--rose)", fontWeight: 700 }}>
                      {nairaFull(r.balance)}
                    </td>
                    <td style={{ padding: "10px 12px", color: r.due_date && new Date(r.due_date) < new Date() ? "var(--rose)" : "var(--ink)" }}>
                      {dateStr(r.due_date) || "—"}
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      <StatusBadge status={r.status} />
                    </td>
                    <td style={{ padding: "10px 12px", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-muted)", fontSize: 12 }}>
                      {r.message_text || "—"}
                    </td>
                    <td style={{ padding: "10px 12px", color: "var(--text-muted)", fontSize: 12 }}>
                      {dateTimeStr(r.created_at)}
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      {r.status !== "SENT" && r.customer_phone && (
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={sending === r.id}
                          onClick={() => handleSend(r.id)}
                          style={{ whiteSpace: "nowrap" }}
                        >
                          <Send size={11} /> {sending === r.id ? "Sending…" : "Send"}
                        </button>
                      )}
                      {r.status === "SENT" && (
                        <span style={{ fontSize: 12, color: "var(--brand)", fontWeight: 600 }}>✓ Sent</span>
                      )}
                      {r.status !== "SENT" && !r.customer_phone && (
                        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>No phone</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
