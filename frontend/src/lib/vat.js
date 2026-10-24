// The same VAT sum as vat.py on the server — keep them in step (round half up),
// so the till shows exactly the total the sale is recorded at.
//   lines: [{ total, exempt }]; settings: the business settings.
export function vatFor(lines, discount, settings) {
  const linesTotal = lines.reduce((s, l) => s + l.total, 0);
  const net = linesTotal - (discount || 0);
  const rate = Number(settings?.vat_rate) || 0;
  if (!settings?.vat_enabled || rate <= 0 || linesTotal <= 0) return { amount: 0, total: net, mode: null, rate };
  const taxable = lines.filter(l => !l.exempt).reduce((s, l) => s + l.total, 0);
  const taxableNet = taxable * (net / linesTotal);
  const round = x => Math.floor(x + 0.5);
  if (settings.vat_mode === "inclusive") {
    return { amount: round(taxableNet * rate / (100 + rate)), total: net, mode: "inclusive", rate };
  }
  const amount = round(taxableNet * rate / 100);
  return { amount, total: net + amount, mode: "add", rate };
}

export const vatLabel = (rate, mode) => `VAT ${rate}%${mode === "inclusive" ? " (included)" : ""}`;
