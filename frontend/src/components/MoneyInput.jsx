import { fmtAmt } from "../lib/format";

// Text input that shows thousands separators (commas) as the user types, for
// prices, amounts, and quantities. Stores/returns the formatted string via
// onChange; call parseAmt(value) on submit to get the number.
//
// Usage:
//   <MoneyInput value={form.price} onChange={v => set("price", v)} placeholder="0" />
export default function MoneyInput({ value, onChange, ...rest }) {
  return (
    <input
      type="text"
      inputMode="decimal"
      value={fmtAmt(value)}
      onChange={e => onChange(fmtAmt(e.target.value))}
      {...rest}
    />
  );
}
