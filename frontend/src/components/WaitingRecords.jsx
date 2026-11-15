import { useState, useEffect } from "react";
import { CloudOff } from "lucide-react";
import { myQueue, myFailed, retryFailed, removeFailed, waitingFor } from "../lib/offlineQueue";
import { dateTimeStr } from "../lib/format";

function useQueueTick() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const on = () => setTick(t => t + 1);
    window.addEventListener("cv:queue-updated", on);
    window.addEventListener("online", on);
    window.addEventListener("offline", on);
    return () => {
      window.removeEventListener("cv:queue-updated", on);
      window.removeEventListener("online", on);
      window.removeEventListener("offline", on);
    };
  }, []);
}

/* Top bar → "N waiting" / "N failed": everything made on this phone that
   hasn't reached the server yet, and what it refused (try again or remove). */
export default function WaitingRecords({ onClose, onRetry }) {
  useQueueTick();
  const waiting = myQueue();
  const failed = myFailed();
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Waiting to send</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 10, fontSize: 14 }}>
          <div className="td-muted" style={{ fontSize: 13 }}>
            {navigator.onLine
              ? "These are being sent now. Each is recorded once, however many times the phone tries."
              : "No internet. These are kept on this phone and sent by themselves when the internet returns."}
          </div>
          {waiting.length === 0 && failed.length === 0 && <div className="td-muted">Nothing waiting — everything has been sent.</div>}
          {waiting.map(item => (
            <div key={item.id} style={{ display: "flex", justifyContent: "space-between", gap: 8, borderTop: "1px solid var(--line)", paddingTop: 8 }}>
              <span style={{ minWidth: 0 }}>{item.label || item.endpoint}</span>
              <span className="td-muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{dateTimeStr(item.queued_at)}</span>
            </div>
          ))}
          {failed.length > 0 && (
            <>
              <strong style={{ color: "#b91c1c", marginTop: 6 }}>Not accepted ({failed.length})</strong>
              <span className="form-hint">The server refused these — usually something changed meanwhile (e.g. not enough stock). Try again, or remove it and record it again.</span>
              {failed.map(item => (
                <div key={item.id} style={{ borderTop: "1px solid var(--line)", paddingTop: 8, display: "grid", gap: 4 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span>{item.label || item.endpoint}</span>
                    <span className="td-muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{dateTimeStr(item.queued_at)}</span>
                  </div>
                  <span style={{ fontSize: 13, color: "#b91c1c" }}>{item.error}</span>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn btn-secondary btn-sm" onClick={() => { retryFailed(item.id); onRetry?.(); }}>Try again</button>
                    <button className="btn btn-ghost btn-sm" style={{ color: "#b91c1c" }}
                      onClick={() => { if (window.confirm("Remove this record for good? It won't be recorded.")) removeFailed(item.id); }}>Remove</button>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
        <div className="modal-footer"><button className="btn btn-ghost" onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}

/* On a screen: what was made here offline and is still waiting to be sent,
   so it can be seen before it reaches the server. */
export function WaitingHere({ pattern, what = "records" }) {
  useQueueTick();
  const items = waitingFor(pattern);
  if (!items.length) return null;
  return (
    <div className="waiting-here" role="status">
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700 }}>
        <CloudOff size={15} /> {items.length} {what} waiting to send
      </div>
      {items.slice(0, 8).map(item => (
        <div key={item.id} style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 13 }}>
          <span style={{ minWidth: 0 }}>{item.label || item.endpoint}</span>
          <span className="td-muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{dateTimeStr(item.queued_at)}</span>
        </div>
      ))}
      {items.length > 8 && <span className="td-muted" style={{ fontSize: 12 }}>+{items.length - 8} more</span>}
    </div>
  );
}
