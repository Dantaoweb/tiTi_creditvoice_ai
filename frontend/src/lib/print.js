// The paper a printable is laid out for (Settings → Receipts & printables):
// small thermal printer (80mm, the default), 58mm, or an A4 page.
export function paperClass(doc) {
  return `receipt-paper paper-${doc?.print?.paper || "80mm"}`;
}
