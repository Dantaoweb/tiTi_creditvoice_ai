import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Globe, Copy, ExternalLink, Share2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { nairaFull, dateTimeStr } from "../lib/format";

/* The business's own public page (business_page.py): what it shows, and the
   quotation requests visitors send from it. */
export default function BusinessPage() {
  const { user } = useAuth();
  const isOwner = !user?.parent_id;
  const navigate = useNavigate();
  const [st, setSt] = useState(null);
  const [form, setForm] = useState(null);
  const [enquiries, setEnquiries] = useState([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  function apply(d) {
    setSt(d);
    setForm({ about: d.about, hours: d.hours, show_prices: d.show_prices, items: d.items });
  }
  function loadEnquiries() {
    apiFetch("business-page/enquiries").then(d => setEnquiries(d.enquiries || [])).catch(() => {});
  }
  useEffect(() => {
    apiFetch("business-page").then(apply).catch(e => setErr(e.message));
    loadEnquiries();
  }, []);

  const picked = useMemo(() => new Set(form?.items || []), [form]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (st?.products || []).filter(p => !t || p.name.toLowerCase().includes(t) || (p.category || "").toLowerCase().includes(t));
  }, [st, q]);

  if (err && !st) return <div className="pos-error" style={{ margin: 24 }}>{err}</div>;
  if (!st || !form) return <div className="page-loading">Loading…</div>;

  async function save(extra = {}) {
    setBusy("save"); setErr(""); setMsg("");
    try {
      apply(await apiPut("business-page", { ...form, ...extra }));
      setMsg(extra.on === true ? "Your page is on." : extra.on === false ? "Your page is off." : "Saved.");
    } catch (e) { setErr(e.message); }
    finally { setBusy(""); }
  }

  function toggleItem(id) {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else if (next.size >= st.max_items) { setErr(`Show up to ${st.max_items} products.`); return; }
    else next.add(id);
    setForm({ ...form, items: [...next] });
  }

  async function copyLink() {
    try { await navigator.clipboard.writeText(st.url); setMsg("Link copied."); }
    catch { setMsg(st.url); }
  }

  async function quote(e) {
    setBusy(`q${e.id}`); setErr("");
    try { const r = await apiPost(`business-page/enquiries/${e.id}/quote`, {}); navigate(`/invoices/${r.invoice_id}`); }
    catch (x) { setErr(x.message); setBusy(""); }
  }
  async function close(e) {
    try { await apiPost(`business-page/enquiries/${e.id}/close`, {}); loadEnquiries(); }
    catch (x) { setErr(x.message); }
  }

  const waText = encodeURIComponent(`See our products and prices, and ask for a quotation: ${st.url}`);

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 760 }}>
      {!st.enabled ? (
        <div className="card" style={{ padding: 20, display: "grid", gap: 10 }}>
          <h2 style={{ margin: 0, display: "flex", gap: 8, alignItems: "center" }}><Globe size={20} /> Your own business page</h2>
          <p style={{ margin: 0 }}>
            A page of your own at <strong>creditvoiceai.com/b/your-business-name</strong> that customers can find on Google
            and you can share on WhatsApp, flyers and your signboard. It shows your products, prices (if you want),
            address, opening hours, and buttons to call or chat with you.
          </p>
          <p style={{ margin: 0 }}>
            Visitors can <strong>ask for a quotation</strong>. Their request comes here, and one tap turns it into a quotation.
          </p>
          <p className="td-muted" style={{ margin: 0 }}>
            The business page is a one-time payment. Contact CreditVoice to get it; we switch it on for you.
          </p>
        </div>
      ) : (
        <>
          <div className="card" style={{ padding: 16, display: "grid", gap: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <div style={{ minWidth: 0 }}>
                <div className="td-muted" style={{ fontSize: 12 }}>Your page</div>
                <strong style={{ wordBreak: "break-all" }}>{st.url}</strong>
              </div>
              <span style={{ fontSize: 12, fontWeight: 700, padding: "3px 10px", borderRadius: 999,
                background: st.live ? "rgba(22,163,74,0.12)" : "rgba(100,116,139,0.14)", color: st.live ? "#166534" : "#475569" }}>
                {st.live ? "On — anyone can see it" : "Off"}
              </span>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {isOwner && (
                <button className={`btn btn-sm ${st.on ? "btn-ghost" : "btn-primary"}`} disabled={!!busy}
                  onClick={() => save({ on: !st.on })}>{st.on ? "Turn page off" : "Turn page on"}</button>
              )}
              <button className="btn btn-ghost btn-sm" onClick={copyLink}><Copy size={13} /> Copy link</button>
              <a className="btn btn-ghost btn-sm" href={st.url} target="_blank" rel="noreferrer"><ExternalLink size={13} /> Open</a>
              <a className="btn btn-ghost btn-sm" href={`https://wa.me/?text=${waText}`} target="_blank" rel="noreferrer"><Share2 size={13} /> Share on WhatsApp</a>
            </div>
            {!st.on && isOwner && <span className="form-hint">Choose what it shows below, then turn it on.</span>}
          </div>

          {isOwner && (
            <div className="card" style={{ padding: 16, display: "grid", gap: 12 }}>
              <h3 style={{ margin: 0 }}>What your page shows</h3>
              <span className="form-hint">Your business name, logo, phone and address come from My Profile; branch addresses from Branches.</span>
              <div className="form-group">
                <label className="form-label">About your business <span className="text-subtle">(optional)</span></label>
                <textarea rows={4} maxLength={600} value={form.about} onChange={e => setForm({ ...form, about: e.target.value })}
                  placeholder="e.g. Water tanks, WCs, wash hand basins, tiles, doors and water heaters. Delivery across Lagos." />
              </div>
              <div className="form-group">
                <label className="form-label">Opening hours <span className="text-subtle">(optional)</span></label>
                <input maxLength={120} value={form.hours} onChange={e => setForm({ ...form, hours: e.target.value })}
                  placeholder="e.g. Mon–Sat 8am–6pm" />
              </div>
              <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
                <input type="checkbox" style={{ width: "auto" }} checked={form.show_prices}
                  onChange={e => setForm({ ...form, show_prices: e.target.checked })} />
                Show prices (off: "Ask for price")
              </label>

              <div style={{ display: "grid", gap: 6 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                  <label className="form-label" style={{ margin: 0 }}>Products on your page</label>
                  <span className="td-muted" style={{ fontSize: 12 }}>{picked.size} of {st.max_items} picked · stock counts are never shown</span>
                </div>
                <input placeholder="Search products…" value={q} onChange={e => setQ(e.target.value)} />
                <div style={{ maxHeight: 320, overflowY: "auto", border: "1px solid var(--line)", borderRadius: 8 }}>
                  {shown.length === 0 && <div className="td-muted" style={{ padding: 12 }}>No products{q ? " match" : " yet — add them in Inventory"}.</div>}
                  {shown.map(p => (
                    <label key={p.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 12px",
                      borderBottom: "1px solid var(--line-2)", cursor: "pointer" }}>
                      <input type="checkbox" style={{ width: "auto" }} checked={picked.has(p.id)} onChange={() => toggleItem(p.id)} />
                      <span style={{ flex: 1, minWidth: 0 }}>
                        {p.name}{p.category && <span className="td-muted" style={{ fontSize: 12 }}> · {p.category}</span>}
                      </span>
                      <span className="td-muted" style={{ fontSize: 13, whiteSpace: "nowrap" }}>{p.price ? nairaFull(p.price) : "No price"}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <button className="btn btn-primary" disabled={!!busy} onClick={() => save()}>{busy === "save" ? "Saving…" : "Save"}</button>
                {msg && <span className="td-muted" style={{ fontSize: 13 }}>{msg}</span>}
              </div>
            </div>
          )}
        </>
      )}
      {err && <div className="pos-error">{err}</div>}

      {(st.enabled || enquiries.length > 0) && (
        <div className="card" style={{ padding: 16, display: "grid", gap: 10 }}>
          <h3 style={{ margin: 0 }}>Quotation requests ({enquiries.filter(e => e.status === "new").length} new)</h3>
          {enquiries.length === 0 && <div className="td-muted">None yet. Requests from your page appear here.</div>}
          {enquiries.map(e => (
            <div key={e.id} style={{ borderTop: "1px solid var(--line)", paddingTop: 10, display: "grid", gap: 4,
              opacity: e.status === "closed" ? 0.6 : 1 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <strong>{e.name} · <a href={`tel:${e.phone}`}>{e.phone}</a></strong>
                <span className="td-muted" style={{ fontSize: 12 }}>{dateTimeStr(e.created_at)}
                  {e.status === "quoted" ? " · quotation made" : e.status === "closed" ? " · closed" : " · new"}</span>
              </div>
              {e.items.length > 0 && <div style={{ fontSize: 14 }}>{e.items.map(i => `${i.qty} × ${i.name}`).join(", ")}</div>}
              {e.message && <div className="td-muted" style={{ fontSize: 14 }}>“{e.message}”</div>}
              <div style={{ display: "flex", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
                {e.status === "quoted" && e.invoice_id ? (
                  <button className="btn btn-secondary btn-sm" onClick={() => navigate(`/invoices/${e.invoice_id}`)}>Open quotation</button>
                ) : e.status === "new" && (
                  <button className="btn btn-primary btn-sm" disabled={!!busy} onClick={() => quote(e)}>
                    {busy === `q${e.id}` ? "Making…" : "Make quotation"}</button>
                )}
                {e.status !== "quoted" && (
                  <button className="btn btn-ghost btn-sm" onClick={() => close(e)}>{e.status === "closed" ? "Reopen" : "Close"}</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
