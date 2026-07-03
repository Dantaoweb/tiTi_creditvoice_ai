import { useState, useEffect, useRef } from "react";
import { Mic, MicOff, Play, Send, X, CheckCircle, ShoppingCart, CreditCard, Package } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { enqueue, isNetworkError } from "../lib/offlineQueue";
import { nairaFull } from "../lib/format";
import { useToast } from "../components/Toast";
import { getBizLabels } from "../lib/bizLabels";

function fmtAmt(s) {
  const raw = String(s || "").replace(/[^0-9]/g, "");
  return raw ? Number(raw).toLocaleString("en-NG") : "";
}
function parseAmt(s) { return Number(String(s || "").replace(/,/g, "")); }

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  let binary = "";
  new Uint8Array(buffer).forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

// ── Shared search inputs ─────────────────────────────────────────────────────

function CustomerSearch({ ownerPhone, placeholder, filterDebtors = false, onSelect, value }) {
  const [customers, setCustomers] = useState([]);
  const [search, setSearch]       = useState("");
  const [open, setOpen]           = useState(false);

  useEffect(() => {
    if (!ownerPhone) return;
    apiFetch("customers", { owner_phone: ownerPhone })
      .then(d => {
        let list = d.customers || [];
        if (filterDebtors) list = list.filter(c => c.balance > 0);
        setCustomers(list);
      })
      .catch(() => {});
  }, [ownerPhone, filterDebtors]);

  const filtered = search.trim()
    ? customers.filter(c => c.name.toLowerCase().includes(search.toLowerCase()))
    : filterDebtors ? customers.slice(0, 8) : [];

  if (value) {
    return (
      <div className="qf-pill">
        <span>
          {value.name}
          {value.balance > 0 && <span className="text-rose"> — owes {nairaFull(value.balance)}</span>}
        </span>
        <button type="button" onClick={() => onSelect(null)}>×</button>
      </div>
    );
  }

  return (
    <div className="qf-search-wrap">
      <input
        value={search}
        onChange={e => { setSearch(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder}
      />
      {open && filtered.length > 0 && (
        <div className="qf-dropdown">
          {filtered.map(c => (
            <button key={c.id} type="button" onMouseDown={() => { onSelect(c); setSearch(""); setOpen(false); }}>
              <span>{c.name}</span>
              {c.balance > 0 && <span className="text-rose text-sm">{nairaFull(c.balance)}</span>}
            </button>
          ))}
        </div>
      )}
      {open && filterDebtors && customers.length === 0 && (
        <div className="qf-dropdown">
          <div style={{ padding: "10px 14px", color: "var(--muted)", fontSize: 13 }}>No debtors found.</div>
        </div>
      )}
    </div>
  );
}

function InventorySearch({ ownerPhone, onSelect, value }) {
  const [items, setItems]   = useState([]);
  const [search, setSearch] = useState("");
  const [open, setOpen]     = useState(false);

  useEffect(() => {
    if (!ownerPhone) return;
    apiFetch("inventory", { owner_phone: ownerPhone })
      .then(d => setItems(d.items || []))
      .catch(() => {});
  }, [ownerPhone]);

  const filtered = search.trim()
    ? items.filter(i => i.name.toLowerCase().includes(search.toLowerCase()))
    : [];

  if (value) {
    return (
      <div className="qf-pill">
        <span>{value.name} <span className="text-subtle">— {value.quantity} {value.unit || "units"} in stock</span></span>
        <button type="button" onClick={() => onSelect(null)}>×</button>
      </div>
    );
  }

  return (
    <div className="qf-search-wrap">
      <input
        value={search}
        onChange={e => { setSearch(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search product name…"
      />
      {open && filtered.length > 0 && (
        <div className="qf-dropdown">
          {filtered.map(i => (
            <button key={i.id} type="button" onMouseDown={() => { onSelect(i); setSearch(""); setOpen(false); }}>
              <span>{i.name}</span>
              <span className="text-subtle text-sm">{i.quantity} {i.unit || "units"}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Branch selector ───────────────────────────────────────────────────────────

function BranchSelector({ ownerPhone, value, onChange }) {
  const [branches, setBranches] = useState([]);

  useEffect(() => {
    if (!ownerPhone) return;
    apiFetch("branches")
      .then(d => {
        const list = d.branches || [];
        setBranches(list);
        if (!value && list.length > 0) {
          const def = list.find(b => b.is_default) || list[0];
          onChange(def.id);
        }
      })
      .catch(() => {});
  }, [ownerPhone]);

  if (branches.length === 0) return null;

  return (
    <div className="form-group">
      <label className="form-label">Branch / Location</label>
      <select value={value || ""} onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">— No branch tag —</option>
        {branches.map(b => (
          <option key={b.id} value={b.id}>{b.name}{b.is_default ? " (default)" : ""}</option>
        ))}
      </select>
    </div>
  );
}

// ── Form panels ──────────────────────────────────────────────────────────────

function SaleForm({ ownerPhone, onSuccess }) {
  const { user }                = useAuth();
  const L                       = getBizLabels(user?.menu_group);
  const [product, setProduct]   = useState("");
  const [qty, setQty]           = useState("1");
  const [unit, setUnit]         = useState("");
  const [amount, setAmount]     = useState("");
  const [customer, setCustomer] = useState(null);
  const [branchId, setBranchId] = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!product.trim() || !amount) return;
    setLoading(true); setError(null);
    try {
      const qtyNum = Math.max(1, Number(qty) || 1);
      const total  = parseAmt(amount);
      const body   = {
        owner_phone:    ownerPhone,
        customer_id:    customer?.id || null,
        items:          [{ name: product.trim(), qty: qtyNum, unit: unit || null, unit_price: Math.round(total / qtyNum) }],
        payment_amount: customer ? 0 : total,
        branch_id:      branchId || null,
      };
      await apiPost("pos/save", body);
      onSuccess(`Sale of ${nairaFull(total)} recorded${customer ? ` — credit to ${customer.name}` : " (cash)"}.`);
      setProduct(""); setQty("1"); setUnit(""); setAmount(""); setCustomer(null);
    } catch (e) {
      if (isNetworkError(e)) {
        const qtyNum = Math.max(1, Number(qty) || 1);
        const total  = parseAmt(amount);
        enqueue("pos/save", {
          owner_phone: ownerPhone, customer_id: customer?.id || null,
          items: [{ name: product.trim(), qty: qtyNum, unit: unit || null, unit_price: Math.round(total / qtyNum) }],
          payment_amount: customer ? 0 : total,
          branch_id: branchId || null,
        }, `Sale ${nairaFull(total)}${customer ? ` — ${customer.name}` : " (cash)"}`);
        onSuccess(`No internet — sale saved offline. Will sync automatically when you reconnect.`);
        setProduct(""); setQty("1"); setUnit(""); setAmount(""); setCustomer(null);
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="qf-form">
      <div className="qf-row qf-row--lg-sm">
        <div className="form-group">
          <label className="form-label">Product / Service *</label>
          <input value={product} onChange={e => setProduct(e.target.value)} placeholder="Rice, Cement, Haircut…" required />
        </div>
        <div className="form-group">
          <label className="form-label">Qty</label>
          <input type="number" min="0.01" step="any" value={qty} onChange={e => setQty(e.target.value)} />
        </div>
      </div>
      <div className="qf-row qf-row--sm-lg">
        <div className="form-group">
          <label className="form-label">Unit</label>
          <input value={unit} onChange={e => setUnit(e.target.value)} placeholder="bags, pcs…" />
        </div>
        <div className="form-group">
          <label className="form-label">Amount (₦) *</label>
          <input inputMode="numeric" value={amount} onChange={e => setAmount(fmtAmt(e.target.value))} placeholder="0" required />
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">{L.customer} <span className="text-subtle">— leave blank for cash sale</span></label>
        <CustomerSearch ownerPhone={ownerPhone} placeholder={`Search ${L.customerName.toLowerCase()}…`} onSelect={setCustomer} value={customer} />
      </div>
      <BranchSelector ownerPhone={ownerPhone} value={branchId} onChange={setBranchId} />
      <div className="qf-type-hint">
        {customer
          ? `Credit sale → will increase ${customer.name}'s balance`
          : "Cash sale → no customer debt"}
      </div>
      {error && <div className="modal-error">{error}</div>}
      <button type="submit" className="btn btn-primary qf-btn" disabled={loading}>
        {loading ? "Saving…" : "Record Sale"}
      </button>
    </form>
  );
}

function PaymentForm({ ownerPhone, onSuccess }) {
  const { user }                = useAuth();
  const L                       = getBizLabels(user?.menu_group);
  const [customer, setCustomer] = useState(null);
  const [amount, setAmount]     = useState("");
  const [note, setNote]         = useState("");
  const [branchId, setBranchId] = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!customer || !amount) return;
    setLoading(true); setError(null);
    try {
      await apiPost(`customers/${customer.id}/pay`, { amount: parseAmt(amount), note: note || null, branch_id: branchId || null });
      onSuccess(`Payment of ${nairaFull(parseAmt(amount))} from ${customer.name} recorded.`);
      setCustomer(null); setAmount(""); setNote("");
    } catch (e) {
      if (isNetworkError(e)) {
        enqueue(
          `customers/${customer.id}/pay`,
          { amount: parseAmt(amount), note: note || null, branch_id: branchId || null },
          `Payment ${nairaFull(parseAmt(amount))} from ${customer.name}`,
        );
        onSuccess(`No internet — payment saved offline. Will sync automatically when you reconnect.`);
        setCustomer(null); setAmount(""); setNote("");
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="qf-form">
      <div className="form-group">
        <label className="form-label">{L.customer} who paid *</label>
        <CustomerSearch ownerPhone={ownerPhone} placeholder={`Search ${L.customerName.toLowerCase()}…`} filterDebtors onSelect={setCustomer} value={customer} />
        <div className="form-hint">Shows {L.customers.toLowerCase()} with outstanding balance.</div>
      </div>
      <div className="qf-row qf-row--sm-xl">
        <div className="form-group">
          <label className="form-label">Amount paid (₦) *</label>
          <input
            inputMode="numeric"
            value={amount}
            onChange={e => setAmount(fmtAmt(e.target.value))}
            placeholder={customer?.balance > 0 ? fmtAmt(String(customer.balance)) : "0"}
            required
          />
        </div>
        <div className="form-group">
          <label className="form-label">Note <span className="text-subtle">(optional)</span></label>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="Bank transfer, cash…" />
        </div>
      </div>
      <BranchSelector ownerPhone={ownerPhone} value={branchId} onChange={setBranchId} />
      {error && <div className="modal-error">{error}</div>}
      <button type="submit" className="btn btn-primary qf-btn" disabled={loading || !customer}>
        {loading ? "Saving…" : "Record Payment"}
      </button>
    </form>
  );
}

function StockForm({ ownerPhone, onSuccess }) {
  const [item, setItem]       = useState(null);
  const [qty, setQty]         = useState("");
  const [cost, setCost]       = useState("");
  const [note, setNote]       = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!item || !qty) return;
    setLoading(true); setError(null);
    try {
      const body = {
        qty_delta: Number(qty),
        note:      note || (cost ? `Received @ N${parseAmt(cost)}/unit` : "Stock received"),
      };
      await apiPost(`inventory/${item.id}/adjust`, body);
      onSuccess(`${qty} ${item.unit || "units"} of ${item.name} added to stock.`);
      setItem(null); setQty(""); setCost(""); setNote("");
    } catch (e) {
      if (isNetworkError(e)) {
        enqueue(
          `inventory/${item.id}/adjust`,
          { qty_delta: Number(qty), note: note || (cost ? `Received @ N${cost}/unit` : "Stock received") },
          `Stock +${qty} ${item.unit || "units"} of ${item.name}`,
        );
        onSuccess(`No internet — stock entry saved offline. Will sync automatically when you reconnect.`);
        setItem(null); setQty(""); setCost(""); setNote("");
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="qf-form">
      <div className="form-group">
        <label className="form-label">Product *</label>
        <InventorySearch ownerPhone={ownerPhone} onSelect={setItem} value={item} />
      </div>
      <div className="qf-row qf-row--sm-lg">
        <div className="form-group">
          <label className="form-label">Qty received *</label>
          <input type="number" min="0.01" step="any" value={qty} onChange={e => setQty(e.target.value)} placeholder="10" required />
        </div>
        <div className="form-group">
          <label className="form-label">Cost per unit (₦)</label>
          <input inputMode="numeric" value={cost} onChange={e => setCost(fmtAmt(e.target.value))} placeholder="0" />
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">Note <span className="text-subtle">(optional)</span></label>
        <input value={note} onChange={e => setNote(e.target.value)} placeholder="Supplier name, delivery ref…" />
      </div>
      {error && <div className="modal-error">{error}</div>}
      <button type="submit" className="btn btn-primary qf-btn" disabled={loading || !item}>
        {loading ? "Saving…" : "Add to Stock"}
      </button>
    </form>
  );
}

// ── Quick Form panel ──────────────────────────────────────────────────────────

const FORM_TABS = [
  { key: "sale",    label: "Record Sale",    icon: ShoppingCart },
  { key: "payment", label: "Record Payment", icon: CreditCard   },
  { key: "stock",   label: "Stock Received", icon: Package      },
];

function QuickFormPanel({ ownerPhone }) {
  const [formTab, setFormTab] = useState("sale");
  const [success, setSuccess] = useState(null);

  function handleSuccess(msg) {
    setSuccess(msg);
    setTimeout(() => setSuccess(null), 5000);
  }

  return (
    <div className="card" style={{ maxWidth: 560, overflow: "visible" }}>
      <div style={{ paddingBottom: 0 }}>
        <span className="card-title">Quick Record</span>
        <div className="card-subtitle" style={{ marginTop: 2 }}>Fill in the fields — no command syntax needed</div>
      </div>
      <div className="qf-sub-tabs">
        {FORM_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            className={`qf-sub-tab${formTab === key ? " active" : ""}`}
            onClick={() => { setFormTab(key); setSuccess(null); }}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>
      {success && (
        <div className="qf-success">
          <CheckCircle size={15} />
          {success}
        </div>
      )}
      <div style={{ padding: "4px 20px 20px" }}>
        {formTab === "sale"    && <SaleForm    ownerPhone={ownerPhone} onSuccess={handleSuccess} />}
        {formTab === "payment" && <PaymentForm ownerPhone={ownerPhone} onSuccess={handleSuccess} />}
        {formTab === "stock"   && <StockForm   ownerPhone={ownerPhone} onSuccess={handleSuccess} />}
      </div>
    </div>
  );
}

// ── Text / Voice panel (original Capture logic) ───────────────────────────────

function TextVoicePanel({ ownerPhone }) {
  const { user }  = useAuth();
  const L         = getBizLabels(user?.menu_group);
  // Prefer the user's business-type-specific prompts (from the server, mirroring
  // WhatsApp); fall back to the menu-group examples when none are provided.
  const exampleItems = (user?.examples?.length
    ? user.examples.map(t => ({ text: t, label: t.length > 26 ? t.slice(0, 24) + "…" : t }))
    : L.examples);
  const toast     = useToast();

  const [phone, setPhone]         = useState(ownerPhone || "");
  const [text, setText]           = useState("");
  const [preview, setPreview]     = useState(null);
  const [previewState, setPS]     = useState("empty");
  const [saving, setSaving]       = useState(false);
  const [saved, setSaved]         = useState(false);

  const [recording, setRecording] = useState(false);
  const [hasAudio, setHasAudio]   = useState(false);
  const [voiceStatus, setVS]      = useState("Ready to record");
  const recorderRef               = useRef(null);
  const chunksRef                 = useRef([]);
  const audioBlobRef              = useRef(null);
  const audioRef                  = useRef(null);

  useEffect(() => { if (ownerPhone) setPhone(ownerPhone); }, [ownerPhone]);

  async function handlePreview(e) {
    e.preventDefault();
    if (!phone || !text.trim()) return;
    setPS("loading"); setSaved(false); setPreview(null);
    try {
      const data = await apiPost("capture/preview", { phone, text: text.trim() });
      setPreview(data); setPS("ready");
    } catch (err) {
      setPS("error"); setPreview({ message: err.message });
    }
  }

  async function handleConfirm() {
    if (!preview?.pending) return;
    setSaving(true);
    try {
      const data = await apiPost("capture/confirm", { phone });
      setSaved(true); setPreview(data);
      toast(data.messages?.[0] || "Transaction saved.", "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  function handleClear() {
    setText(""); setPreview(null); setPS("empty"); setSaved(false);
    setHasAudio(false); setVS("Ready to record");
    audioBlobRef.current = null;
    if (audioRef.current) { audioRef.current.src = ""; audioRef.current.hidden = true; }
  }

  async function startRecording() {
    if (!navigator.mediaDevices) { toast("Microphone not available", "error"); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      recorderRef.current = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current.addEventListener("dataavailable", (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      });
      recorderRef.current.addEventListener("stop", () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
        audioBlobRef.current = blob;
        if (audioRef.current) {
          audioRef.current.src = URL.createObjectURL(blob);
          audioRef.current.hidden = false;
        }
        setHasAudio(true); setVS("Recording ready — transcribe to fill text"); setRecording(false);
      });
      recorderRef.current.start();
      setRecording(true); setVS("Recording…");
    } catch { toast("Microphone permission denied", "error"); }
  }

  function stopRecording() {
    if (recorderRef.current?.state !== "inactive") recorderRef.current.stop();
  }

  async function handleTranscribe() {
    if (!audioBlobRef.current) return;
    setVS("Transcribing…");
    try {
      const b64  = await blobToBase64(audioBlobRef.current);
      const data = await apiPost("capture/voice", {
        phone, audio_base64: b64, mime_type: audioBlobRef.current.type || "audio/webm",
      });
      if (data.transcript) setText(data.transcript);
      setPreview(data); setPS("ready"); setVS("Transcription done");
    } catch (err) {
      toast(err.message, "error"); setVS("Transcription failed");
    }
  }

  const pending = preview?.pending;

  const SUMMARY_FIELDS = [
    ["Action",      pending?.action],
    [L.customer,    pending?.customer_name || L.directSale],
    ["Product",     pending?.product],
    ["Quantity",    pending?.quantity ? `${pending.quantity} ${pending.unit || ""}`.trim() : null],
    ["Sale amount", pending?.buy_amount  ? nairaFull(pending.buy_amount)  : null],
    ["Payment",     pending?.paid_amount ? nairaFull(pending.paid_amount) : null],
    ["Due date",    pending?.due_date    ? new Date(pending.due_date).toLocaleDateString("en-NG") : null],
  ].filter(([, v]) => v);

  return (
    <div className="capture-grid">
      <div className="card">
        <div className="card-header">
          <span className="card-title">Record transaction</span>
          <span className="card-subtitle">Same style as WhatsApp</span>
        </div>
        <form onSubmit={handlePreview} style={{ display: "grid", gap: 16, padding: 18 }}>
          <div className="form-group">
            <label className="form-label">Registered phone</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="234..." className="form-full" />
          </div>
          <div className="voice-box">
            <div>
              <div className="voice-label">Voice capture</div>
              <div className="voice-status">{voiceStatus}</div>
            </div>
            <audio ref={audioRef} controls hidden style={{ width: "100%", height: 36 }} />
            <div className="gap-2">
              <button type="button" className="btn btn-secondary btn-sm"
                onClick={recording ? stopRecording : startRecording}
              >
                {recording ? <><MicOff size={14} /> Stop</> : <><Mic size={14} /> Record</>}
              </button>
              <button type="button" className="btn btn-secondary btn-sm"
                disabled={!hasAudio || recording}
                onClick={handleTranscribe}
              >
                <Play size={14} /> Transcribe
              </button>
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">Transaction text</label>
            <textarea rows={5} className="form-full" placeholder={exampleItems[0]?.text || ""}
              value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          <div className="example-chips">
            {exampleItems.map((ex, i) => (
              <button key={(ex.label || ex.text) + i} type="button" className="example-chip" onClick={() => setText(ex.text)}>
                {ex.label}
              </button>
            ))}
          </div>
          <div className="gap-2">
            <button type="submit" className="btn btn-primary" disabled={previewState === "loading"}>
              <Send size={14} />
              {previewState === "loading" ? "Reading…" : "Preview"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={handleClear}>
              <X size={14} /> Clear
            </button>
          </div>
        </form>
      </div>
      <div className="card">
        <div className="card-header">
          <span className="card-title">Preview</span>
          <span className="card-subtitle">Confirm before saving</span>
        </div>
        <div style={{ padding: 18 }}>
          {previewState === "empty" && (
            <div className="capture-result empty">Enter a transaction and click Preview.</div>
          )}
          {previewState === "loading" && (
            <div className="capture-result empty">Reading transaction…</div>
          )}
          {previewState === "error" && (
            <div className="capture-result">
              <div style={{ color: "var(--rose)", fontSize: 13.5 }}>{preview?.message}</div>
            </div>
          )}
          {previewState === "ready" && preview && (
            <div className="capture-result">
              {preview.transcript && (
                <div style={{ background: "#f0f7f3", borderLeft: "3px solid var(--brand)", borderRadius: "0 6px 6px 0", padding: "10px 14px" }}>
                  <div className="form-label" style={{ marginBottom: 4 }}>Transcript</div>
                  <div style={{ fontSize: 13.5 }}>{preview.transcript}</div>
                </div>
              )}
              {preview.messages?.map((m, i) => (
                <div key={i} className="message-bubble">{m}</div>
              ))}
              {pending && !saved && (
                <>
                  <div className="form-label">Parsed details</div>
                  <div className="parsed-preview">
                    {SUMMARY_FIELDS.map(([label, value]) => (
                      <div key={label} className="parsed-cell">
                        <span>{label}</span>
                        <strong>{value}</strong>
                      </div>
                    ))}
                  </div>
                  <button className="btn btn-primary" disabled={saving} onClick={handleConfirm}>
                    <CheckCircle size={15} />
                    {saving ? "Saving…" : "Confirm & save"}
                  </button>
                </>
              )}
              {saved && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--brand)", fontWeight: 600 }}>
                  <CheckCircle size={18} /> Transaction saved. Check Dashboard for updated totals.
                </div>
              )}
              {preview.message && !pending && (
                <div style={{ color: "var(--muted)", fontSize: 13.5 }}>{preview.message}</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Root Capture page ─────────────────────────────────────────────────────────

export default function Capture() {
  const { ownerPhone } = useApp();
  const [mode, setMode] = useState("form");

  return (
    <>
      <div className="capture-mode-bar">
        <button
          className={`capture-mode-btn${mode === "form" ? " active" : ""}`}
          onClick={() => setMode("form")}
        >
          Quick Form
        </button>
        <button
          className={`capture-mode-btn${mode === "text" ? " active" : ""}`}
          onClick={() => setMode("text")}
        >
          Text / Voice
        </button>
      </div>

      {mode === "form" && <QuickFormPanel ownerPhone={ownerPhone} />}
      {mode === "text" && <TextVoicePanel ownerPhone={ownerPhone} />}
    </>
  );
}
