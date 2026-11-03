import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { dateStr } from "../lib/format";

/* Quotation → Accepted → Paid → Delivered → Completed (invoices.py
   invoice_progress). Done steps are ticked, the one in progress is marked,
   the rest wait. */
export default function InvoiceProgress({ steps }) {
  if (!steps?.length) return null;
  const current = steps.findIndex(s => !s.done);
  return (
    <ol className="inv-steps" aria-label="Progress">
      {steps.map((s, i) => {
        const state = s.done ? "done" : (i === current || s.partial) ? "now" : "todo";
        return (
          <li key={s.key} className={`inv-step inv-step--${state}`}>
            <span className="inv-step__dot" aria-hidden="true">{s.done ? <Check size={12} strokeWidth={3} /> : i + 1}</span>
            <span className="inv-step__label">{s.label}</span>
            {s.ref && (s.receipt_id
              ? <Link className="inv-step__ref" to={`/pos/receipt/${s.receipt_id}`}>{s.ref}</Link>
              : <span className="inv-step__ref">{s.ref}</span>)}
            {s.date && <span className="inv-step__date">{dateStr(s.date)}</span>}
            {s.partial && s.key === "delivered" && <span className="inv-step__date">Part delivered</span>}
          </li>
        );
      })}
    </ol>
  );
}
