import { nairaFull, dateTimeStr } from "../lib/format";

/* Till → Held: carts put aside while their customers get ready (pos_held.py).
   Open one to carry on, or delete it if the customer left. */
export default function HeldSales({ held, currentId, onOpen, onDelete, onClose }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Held sales ({held.length})</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body" style={{ display: "grid", gap: 10, fontSize: 14 }}>
          {held.length === 0 && <div className="td-muted">No sales on hold.</div>}
          {held.map(h => (
            <div key={h.id} className="card" style={{ padding: "10px 12px", display: "grid", gap: 6,
              outline: h.id === currentId ? "2px solid var(--brand)" : "none" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                <strong style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {h.customer?.name || h.label || "Walk-in customer"}
                </strong>
                <strong style={{ whiteSpace: "nowrap" }}>{nairaFull(h.total)}</strong>
              </div>
              <div className="td-muted" style={{ fontSize: 12 }}>
                {h.items.slice(0, 3).map(it => `${it.qty} ${it.name}`).join(", ")}
                {h.items.length > 3 ? ` +${h.items.length - 3} more` : ""}
              </div>
              <div className="td-muted" style={{ fontSize: 12 }}>
                Held {dateTimeStr(h.created_at)}{h.by ? ` by ${h.by}` : ""}
                {h.id === currentId && " · open now"}
              </div>
              {h.stale && <div className="pos-credit-warn">Held for over a week — is this customer still coming?</div>}
              {h.short.map((s, i) => (
                <div key={i} className="pos-credit-warn">
                  {s.removed ? `${s.name} is no longer sold.` : `Only ${qty0(s.free)} ${s.name} can be sold now.`}
                </div>
              ))}
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-primary btn-sm" style={{ flex: 1 }} onClick={() => onOpen(h)}
                  disabled={h.id === currentId}>Open</button>
                <button className="btn btn-ghost btn-sm" style={{ color: "#b91c1c" }} onClick={() => onDelete(h)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

const qty0 = n => Number(n || 0).toLocaleString();
