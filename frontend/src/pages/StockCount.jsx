import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Printer, Send, Check, XCircle } from "lucide-react";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { dateTimeStr, nairaFull } from "../lib/format";

/* One stock count.
   - Counting: type what is really on the shelf. Saved as you go. Blind by
     default — the app's numbers stay hidden so nobody copies them.
   - Waiting for approval: the owner sees app vs counted, the difference and
     what it's worth, picks a reason for each, and approves.
   - Approved: the record, to print and sign. */
export default function StockCount() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [counts, setCounts] = useState({});      // line id → typed value
  const [reasons, setReasons] = useState({});
  const [filter, setFilter] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [saved, setSaved] = useState("");
  const dirty = useRef({});

  function take(d) {
    setDoc(d);
    setCounts(Object.fromEntries(d.lines.map(l => [l.id, l.counted ?? ""])));
    setReasons(Object.fromEntries(d.lines.map(l => [l.id, l.reason || ""])));
  }
  useEffect(() => { apiFetch(`stock-counts/${id}`).then(take).catch(e => setErr(e.message)); }, [id]);

  async function saveNow() {
    const changed = dirty.current;
    if (!Object.keys(changed).length) return;
    dirty.current = {};
    try {
      await apiPut(`stock-counts/${id}/counts`, {
        counts: Object.fromEntries(Object.keys(changed).map(k => [k, counts[k] === "" ? null : Number(counts[k])])),
      });
      setSaved("Saved"); setTimeout(() => setSaved(""), 1200);
    } catch (e) { setErr(e.message); }
  }

  async function act(name, path, body) {
    setBusy(name); setErr("");
    try { take(await apiPost(`stock-counts/${id}/${path}`, body || {})); }
    catch (e) { setErr(e.message); }
    finally { setBusy(""); }
  }

  if (err && !doc) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!doc) return <div className="page-loading">Loading count…</div>;

  const counting = doc.status === "counting";
  const review = doc.status === "submitted";
  const allCounts = () => Object.fromEntries(Object.entries(counts).map(([k, v]) => [k, v === "" ? null : Number(v)]));
  const shown = doc.lines.filter(l => !filter || l.product.toLowerCase().includes(filter.toLowerCase()));
  const differ = l => l.difference != null && l.difference !== 0;

  return (
    <div className="receipt-shell" style={{ alignItems: "stretch", maxWidth: 760 }}>
      <div className="receipt-actions no-print" style={{ flexWrap: "wrap" }}>
        <button className="btn btn-ghost" onClick={() => navigate("/stock-counts")}><ArrowLeft size={15} /> Stock counts</button>
        {doc.status === "approved" && (
          <button className="btn btn-primary" onClick={() => window.print()}><Printer size={15} /> Download / Print</button>
        )}
      </div>

      <div className="card receipt-paper count-paper">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <div>
            <div className="receipt-brand">Stock count {doc.number}</div>
            <div className="receipt-muted">{doc.scope} · started {dateTimeStr(doc.created_at)}</div>
            {doc.counted_by && <div className="receipt-muted">Counted by {doc.counted_by}</div>}
            {doc.approved_by && <div className="receipt-muted">Approved by {doc.approved_by} · {dateTimeStr(doc.approved_at)}</div>}
          </div>
          <div style={{ textAlign: "right", fontSize: 13 }}>
            <div><strong>{doc.counted}</strong> of {doc.total} counted</div>
            {doc.differ != null && <div>{doc.differ} differ from the app</div>}
            {doc.value_lost != null && doc.value_lost > 0 && <div style={{ color: "var(--rose)", fontWeight: 700 }}>{nairaFull(doc.value_lost)} missing</div>}
            {doc.value_found != null && doc.value_found > 0 && <div style={{ color: "#166534" }}>{nairaFull(doc.value_found)} found extra</div>}
          </div>
        </div>

        {counting && (
          <div className="no-print" style={{ fontSize: 13, margin: "12px 0", padding: 10, background: "var(--bg)", borderRadius: 8 }}>
            Type what is really on the shelf{doc.blind ? " — the app's numbers are hidden so you count, not copy" : ""}.
            Leave a box empty to skip that product; it won't change. Your counts save as you go.
          </div>
        )}
        {review && (
          <div className="no-print" style={{ fontSize: 13, margin: "12px 0", padding: 10, background: "var(--bg)", borderRadius: 8 }}>
            {doc.can_approve
              ? "Check each difference and pick why. Stock changes only when you tap Approve — by the difference, so sales made since the count are kept."
              : "Sent to the owner for approval. Stock changes when they approve."}
          </div>
        )}

        <input className="no-print" placeholder="Find a product…" value={filter} onChange={e => setFilter(e.target.value)}
          style={{ width: "100%", margin: "8px 0" }} />

        {/* On a phone each product stacks into a labelled block (count-table in index.css) */}
        <table className="receipt-table count-table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>Product</th>
              {"expected" in (doc.lines[0] || {}) && <th className="receipt-right">App</th>}
              <th className="receipt-right">Counted</th>
              {!counting && <th className="receipt-right">Difference</th>}
              {!counting && doc.value_lost != null && <th className="receipt-right">Value (₦)</th>}
              {!counting && <th>Reason</th>}
            </tr>
          </thead>
          <tbody>
            {shown.map(l => (
              <tr key={l.id} style={!counting && differ(l) ? { background: l.difference < 0 ? "rgba(185,28,28,0.06)" : "rgba(22,101,52,0.06)" } : undefined}>
                <td className="count-product">{l.product}{l.unit ? <span className="td-muted"> ({l.unit})</span> : ""}
                  {l.category && <div className="td-muted" style={{ fontSize: 11 }}>{l.category}</div>}</td>
                {"expected" in l && <td className="receipt-right" data-label="App">{l.expected ?? "—"}</td>}
                <td className="receipt-right" data-label="Counted">
                  {counting ? (
                    <input type="number" min={0} inputMode="decimal" value={counts[l.id] ?? ""} style={{ width: 80 }}
                      onChange={e => { setCounts(c => ({ ...c, [l.id]: e.target.value })); dirty.current[l.id] = true; }}
                      onBlur={saveNow} />
                  ) : (l.counted ?? <span className="td-muted">not counted</span>)}
                </td>
                {!counting && <td className="receipt-right" data-label="Difference" style={{ fontWeight: differ(l) ? 700 : 400 }}>
                  {l.difference == null ? "—" : l.difference > 0 ? `+${l.difference}` : l.difference}</td>}
                {!counting && doc.value_lost != null && <td className="receipt-right" data-label="Value (₦)">
                  {l.value ? (l.value < 0 ? `−${Math.abs(l.value).toLocaleString()}` : `+${l.value.toLocaleString()}`) : "—"}</td>}
                {!counting && <td data-label="Reason" className={differ(l) ? "" : "count-empty"}>
                  {differ(l) ? (review && doc.can_approve ? (
                    <select value={reasons[l.id] || ""} onChange={e => setReasons(r => ({ ...r, [l.id]: e.target.value }))}>
                      <option value="">Why?</option>
                      {Object.entries(doc.reasons).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>
                  ) : (doc.reasons[l.reason] || "—")) : ""}
                </td>}
              </tr>
            ))}
          </tbody>
        </table>

        {doc.status === "approved" && (
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 32 }}>
            {["Counted by (sign)", "Approved by (sign)"].map(t => (
              <div key={t} style={{ flex: 1, minWidth: 160 }}>
                <div style={{ borderBottom: "1px solid #333", height: 32 }} />
                <div className="receipt-muted" style={{ marginTop: 4 }}>{t}</div>
              </div>
            ))}
          </div>
        )}
        {doc.status === "cancelled" && <div style={{ color: "var(--rose)", fontWeight: 700, marginTop: 10 }}>CANCELLED — stock was not changed.</div>}
      </div>

      {err && <div className="modal-error no-print">{err}</div>}
      <div className="no-print" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {counting && (
          <button className="btn btn-primary" disabled={!!busy}
            onClick={() => window.confirm("Done counting? It goes to the owner for approval and can't be edited after.")
              && act("submit", "submit", { counts: allCounts() })}>
            <Send size={15} /> {busy === "submit" ? "Sending…" : "Send for approval"}
          </button>
        )}
        {review && doc.can_approve && (
          <button className="btn btn-primary" disabled={!!busy}
            onClick={() => window.confirm("Approve? Stock will change by each difference.") && act("approve", "approve", { reasons })}>
            <Check size={15} /> {busy === "approve" ? "Approving…" : "Approve — fix my stock"}
          </button>
        )}
        {(counting || review) && (
          <button className="btn btn-ghost" disabled={!!busy} style={{ color: "#b91c1c" }}
            onClick={() => window.confirm("Cancel this count? Nothing in stock changes.") && act("cancel", "cancel")}>
            <XCircle size={15} /> Cancel count
          </button>
        )}
        {saved && <span className="td-muted" style={{ fontSize: 12 }}>{saved} ✓</span>}
      </div>
    </div>
  );
}
