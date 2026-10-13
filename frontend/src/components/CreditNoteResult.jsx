/* What happened after a credit note was issued: the note the customer got,
   or a button to send it from the owner's own WhatsApp. */
export default function CreditNoteResult({ result, onClose }) {
  return (
    <>
      <div className="modal-body">
        <div style={{ fontWeight: 600, marginBottom: 8 }}>
          ✓ Credit note {result.number} · ₦{Number(result.amount).toLocaleString()}{" "}
          {result.mode === "REFUND" ? "refunded" : "taken off their balance"}
        </div>
        <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13, background: "var(--bg)", padding: 10, borderRadius: 8, margin: 0 }}>
          {result.message}
        </pre>
        <span className="form-hint">
          {result.sent ? "Sent to the customer's WhatsApp."
            : result.wa_link ? "WhatsApp couldn't deliver it from tiTi — send it from your own phone."
            : "No phone saved — share this credit note with the customer yourself."}
        </span>
      </div>
      <div className="modal-footer">
        {result.wa_link && (
          <a className="btn btn-secondary" href={result.wa_link} target="_blank" rel="noreferrer">
            Send from my WhatsApp
          </a>
        )}
        <button className="btn btn-primary" onClick={onClose}>Done</button>
      </div>
    </>
  );
}

/* Off the balance (they hadn't paid) or money handed back (they had). */
export function MoneyModeChoice({ mode, setMode, allowCredit = true }) {
  const opt = (value, title, hint) => (
    <label style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 8, cursor: "pointer", background: mode === value ? "var(--bg)" : "transparent" }}>
      <input type="radio" name="cn-mode" checked={mode === value} onChange={() => setMode(value)} style={{ width: "auto", marginTop: 3 }} />
      <span><strong style={{ fontSize: 13 }}>{title}</strong><div className="td-muted" style={{ fontSize: 12 }}>{hint}</div></span>
    </label>
  );
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {allowCredit && opt("CREDIT", "Take it off what they owe", "They hadn't paid for these — their debt goes down.")}
      {opt("REFUND", "Give the money back", "They had paid — record the cash you hand back.")}
    </div>
  );
}
