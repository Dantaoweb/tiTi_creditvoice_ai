// A discount off the whole sale, as typed in DiscountInput: { input, pct }.

const digits = s => String(s ?? "").replace(/[^\d.]/g, "");

export const NO_DISCOUNT = { input: "", pct: false };

/** Naira off `subtotal` for what was typed, never below 0 or above the subtotal. */
export function discountAmount(subtotal, value) {
  const n = Number(digits(value?.input)) || 0;
  const raw = value?.pct ? subtotal * Math.min(n, 100) / 100 : n;
  return Math.min(subtotal, Math.max(0, Math.round(raw)));
}
