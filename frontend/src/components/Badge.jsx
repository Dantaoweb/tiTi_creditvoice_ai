const TYPE_COLOR = {
  BUY: "blue",
  PAY: "green",
  SALE: "green",
  COMBINED: "blue",
  SUPPLIER_PURCHASE: "amber",
  SUPPLIER_PAYMENT: "green",
};

const STATUS_COLOR = {
  pending:  "amber",
  sent:     "green",
  failed:   "rose",
  skipped:  "gray",
  queued:   "blue",
};

export function TxTypeBadge({ type, voided }) {
  if (voided) return <span className="badge badge-voided">Voided</span>;
  const color = TYPE_COLOR[type] || "gray";
  return <span className={`badge badge-${color}`}>{type}</span>;
}

export function StatusBadge({ status }) {
  const color = STATUS_COLOR[(status || "").toLowerCase()] || "gray";
  return <span className={`badge badge-${color}`}>{status || "—"}</span>;
}

export function StockBadge({ available, quantity, alert }) {
  if (!available) return <span className="badge badge-rose">Unavailable</span>;
  if (alert !== null && alert !== undefined && quantity <= alert)
    return <span className="badge badge-amber">Low stock</span>;
  return <span className="badge badge-green">In stock</span>;
}
