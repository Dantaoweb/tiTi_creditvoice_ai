// "Amount paid now" for goods bought (stock received, a supplier purchase).
//
// Empty means NOTHING paid — the whole amount is owed to the supplier and
// shown in red. It used to be pre-filled with the full total, so a purchase
// on credit that nobody corrected was saved as paid and the debt vanished.
// "Paid in full" fills the total in one tap.

const fmt = n => `₦${Math.max(0, Math.round(n)).toLocaleString("en-NG")}`;
const withCommas = s => {
  const raw = String(s ?? "").replace(/[^\d]/g, "");
  return raw ? Number(raw).toLocaleString("en-NG") : "";
};

/** What was typed as a number (empty = 0 = nothing paid). */
export function paidAmount(value) {
  return Number(String(value || "").replace(/,/g, "")) || 0;
}

export default function PaidNowField({ value, onChange, total, who = "the supplier", label = "Amount paid now (₦)" }) {
  const paid = Math.min(paidAmount(value), total || 0);
  const owed = Math.max(0, (total || 0) - paid);
  return (
    <div className="form-group">
      <label className="form-label">{label}</label>
      <div style={{ display: "flex", gap: 6 }}>
        <input inputMode="numeric" value={value} placeholder="0 — nothing paid yet"
          onChange={e => onChange(withCommas(e.target.value))} style={{ flex: 1 }} />
        {total > 0 && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange(withCommas(String(total)))}>
            Paid in full
          </button>
        )}
      </div>
      {total > 0 && (
        owed > 0
          ? <span className="owe-line owe-line--due">Total {fmt(total)} — you'll owe {who} {fmt(owed)}</span>
          : <span className="owe-line owe-line--paid">Total {fmt(total)} — paid in full ✓</span>
      )}
    </div>
  );
}
