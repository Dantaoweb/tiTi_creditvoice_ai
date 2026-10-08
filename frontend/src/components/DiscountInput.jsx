// A discount off the whole sale, typed as naira or as a percentage of the
// subtotal. Used by the till, New Receipt and invoices so all three behave
// the same; the server receives the naira amount from discountAmount()
// (lib/discount.js).
import { NO_DISCOUNT } from "../lib/discount";

const digits = s => String(s ?? "").replace(/[^\d.]/g, "");
const withCommas = s => {
  const raw = String(s ?? "").replace(/[^\d]/g, "");
  return raw ? Number(raw).toLocaleString("en-NG") : "";
};

export default function DiscountInput({ value, onChange, label = "Discount" }) {
  const v = value || NO_DISCOUNT;
  const setMode = pct => onChange({ input: "", pct });
  return (
    <div className="pos-discount-row">
      <span>{label}</span>
      <div className="pos-discount-input">
        <input inputMode="decimal" placeholder="0" aria-label={label}
          value={v.input}
          onChange={e => onChange({ ...v, input: v.pct ? digits(e.target.value) : withCommas(e.target.value) })} />
        <button type="button" className={`pos-discount-mode${v.pct ? "" : " on"}`}
          onClick={() => setMode(false)} aria-pressed={!v.pct}>₦</button>
        <button type="button" className={`pos-discount-mode${v.pct ? " on" : ""}`}
          onClick={() => setMode(true)} aria-pressed={v.pct}>%</button>
      </div>
    </div>
  );
}
