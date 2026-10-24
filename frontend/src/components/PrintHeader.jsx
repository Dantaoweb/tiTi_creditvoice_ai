/* The business header every printable shares — receipt, invoice / quotation,
   waybill, supplier receipt — laid out as the owner chose in Settings →
   Receipts & printables (`doc.print`, from printables.py on the server). */

export default function PrintHeader({ doc, title, date, refText, children }) {
  const p = doc.print || {};
  const align = p.align === "left" ? "left" : "center";
  const addr = doc.branch_address || doc.biz_address;
  const showLogo = doc.biz_logo && p.logo !== "none";
  const beside = showLogo && (p.logo === "left" || p.logo === "right");
  const logo = showLogo && (
    <img src={doc.biz_logo} alt="" className="print-logo" style={{
      margin: beside ? 0 : align === "center" ? "0 auto 6px" : "0 0 6px",
      display: "block",
    }} />
  );
  const details = (
    <div style={{ minWidth: 0, flex: beside ? 1 : undefined, textAlign: beside && p.logo === "right" && align === "left" ? "left" : undefined }}>
      <div className="receipt-brand">{doc.biz_name}</div>
      {p.show_phone !== false && doc.biz_phone && <div className="receipt-muted">Tel: {doc.biz_phone}</div>}
      {p.show_address !== false && addr && <div className="receipt-muted" style={{ whiteSpace: "pre-line" }}>{addr}</div>}
      {p.show_email !== false && doc.biz_email && <div className="receipt-muted">{doc.biz_email}</div>}
      {doc.vat_number && <div className="receipt-muted">VAT no: {doc.vat_number}</div>}
      {doc.branch_name && <div className="receipt-muted">{doc.branch_name} branch</div>}
    </div>
  );
  return (
    <div className="receipt-header" style={{ textAlign: align }}>
      {beside ? (
        <div style={{
          display: "flex", alignItems: "center", gap: 12,
          flexDirection: p.logo === "right" ? "row-reverse" : "row",
          justifyContent: align === "center" ? "center" : "flex-start",
        }}>
          {logo}{details}
        </div>
      ) : (
        <>{logo}{details}</>
      )}
      {title && <div className="receipt-sub">{title}</div>}
      {date && <div className="receipt-date">{date}</div>}
      {refText && <div className="receipt-ref">{refText}</div>}
      {children}
    </div>
  );
}

/* "Pay to" bank details — on invoices and quotations, and on receipts when
   the owner switched that on (the server sends them only then). */
export function PrintBank({ doc, label = "Pay to" }) {
  const accounts = doc.bank_accounts || [];
  if (!accounts.length) return null;
  return (
    <div className="print-bank" style={{ textAlign: doc.print?.align === "left" ? "left" : "center" }}>
      <div className="receipt-label">{label}</div>
      {accounts.map((a, i) => (
        <div key={i}>
          <strong>{a.bank}</strong> · {a.number}{a.name ? ` · ${a.name}` : ""}
        </div>
      ))}
    </div>
  );
}
