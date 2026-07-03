import { useEffect, useState, useRef } from "react";
import { Check, X, Zap, Building2, Users, BarChart2, Download, Bell, Package, CreditCard, Banknote } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";

// ── Plan feature matrix ──────────────────────────────────────────────────────
const FEATURES = [
  { label: "Customers",              basic: "Up to 50",       go: "Unlimited",  pro: "Unlimited",  icon: Users },
  { label: "Transactions / month",   basic: "Up to 100",      go: "Unlimited",  pro: "Unlimited",  icon: Zap },
  { label: "Inventory items",        basic: "Up to 5",        go: "Unlimited",  pro: "Unlimited",  icon: Package },
  { label: "Invoice / multi-item",   basic: "5 / month",      go: "Unlimited",  pro: "Unlimited",  icon: null },
  { label: "Debt reminders",         basic: true,             go: true,         pro: true },
  { label: "POS",                    basic: true,             go: true,         pro: true },
  { label: "Exports (Excel/PDF)",    basic: false,            go: true,         pro: true,         icon: Download },
  { label: "Advanced reports",       basic: false,            go: true,         pro: true,         icon: BarChart2 },
  { label: "Voice notes",            basic: false,            go: true,         pro: true },
  { label: "Auto send reminders",    basic: false,            go: true,         pro: true,         icon: Bell },
  { label: "Staff accounts",         basic: false,            go: false,        pro: true,         icon: Users },
  { label: "Branches",               basic: false,            go: false,        pro: true,         icon: Building2 },
  { label: "Partners / Investors",   basic: false,            go: false,        pro: true },
];

// ── Bank Transfer modal ──────────────────────────────────────────────────────
function BankTransferModal({ plan, status, onClose, onDone }) {
  const [step, setStep] = useState("details"); // details | confirm | done
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState(null);

  useEffect(() => {
    setLoading(true);
    apiPost("subscription/request", { plan })
      .then(d => { setInfo(d); setLoading(false); })
      .catch(e => { setErr(e.message); setLoading(false); });
  }, [plan]);

  const bankLines = (info?.bank_details || "").split("\n").filter(Boolean);

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Pay by Bank Transfer — {plan}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {loading && <div className="td-muted">Loading payment details…</div>}
          {err && <div className="modal-error">{err}</div>}
          {info && step === "details" && (
            <>
              <div className="upgrade-bank-amount">
                <Banknote size={20} />
                Pay <strong>{nairaFull(info.amount)}</strong> to:
              </div>
              <div className="upgrade-bank-card">
                {bankLines.map((line, i) => (
                  <div key={i} className="upgrade-bank-line">
                    <span className="upgrade-bank-label">{line.split(":")[0]}</span>
                    <span className="upgrade-bank-value">{line.split(":").slice(1).join(":").trim()}</span>
                  </div>
                ))}
                <div className="upgrade-bank-line">
                  <span className="upgrade-bank-label">Reference / Narration</span>
                  <span className="upgrade-bank-value" style={{ fontWeight: 700 }}>{info.reference}</span>
                </div>
              </div>
              <div className="form-hint" style={{ marginTop: 8 }}>
                Use your phone number as the transfer reference/narration so we can identify your payment. Activation happens within 1–24 hours after we confirm receipt.
              </div>
            </>
          )}
          {step === "done" && (
            <div style={{ textAlign: "center", padding: "16px 0" }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
              <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 8 }}>Payment request noted!</div>
              <div className="td-muted">We'll activate your {plan} plan within 1–24 hours after confirming the transfer.</div>
            </div>
          )}
        </div>
        <div className="modal-footer">
          {step === "details" && info && (
            <>
              <button className="btn btn-ghost" onClick={onClose}>Close</button>
              <button className="btn btn-primary" onClick={async () => {
                // Alert admins (WhatsApp + email) that this user reports paying.
                // Non-blocking: still advance the UI even if the ping fails.
                try { await apiPost("subscription/confirm-payment", { plan }); } catch { /* ignore */ }
                setStep("done"); onDone && onDone();
              }}>
                I've made the transfer
              </button>
            </>
          )}
          {step === "done" && (
            <button className="btn btn-primary" onClick={onClose}>Got it</button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Monnify payment ──────────────────────────────────────────────────────────
function useMonnifySDK() {
  const loaded = useRef(false);
  useEffect(() => {
    if (loaded.current || document.getElementById("monnify-sdk")) return;
    const script = document.createElement("script");
    script.id = "monnify-sdk";
    script.src = "https://sdk.monnify.com/plugin/monnify.js";
    script.async = true;
    document.body.appendChild(script);
    loaded.current = true;
  }, []);
}

function MonnifyButton({ plan, amount, disabled, onSuccess, onError }) {
  useMonnifySDK();
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (busy || disabled) return;
    setBusy(true);
    try {
      const init = await apiPost("subscription/monnify/init", { plan });
      const MonnifySDK = window.MonnifySDK;
      if (!MonnifySDK) {
        throw new Error("Monnify SDK not loaded yet. Please try again.");
      }
      MonnifySDK.initialize({
        amount:              init.amount,
        currency:            "NGN",
        reference:           init.reference,
        customerFullName:    init.customer_name,
        customerEmail:       init.customer_email,
        apiKey:              init.api_key,
        contractCode:        init.contract_code,
        paymentDescription:  init.description,
        isTestMode:          init.is_test,
        onLoadStart: () => {},
        onLoadComplete: () => { setBusy(false); },
        onComplete: async (response) => {
          setBusy(true);
          try {
            const result = await apiPost("subscription/monnify/verify", {
              reference: init.reference,
              transaction_reference: response.transactionReference,
            });
            onSuccess(result);
          } catch (e) {
            onError(e.message);
          } finally {
            setBusy(false);
          }
        },
        onClose: () => { setBusy(false); },
      });
    } catch (e) {
      setBusy(false);
      onError(e.message);
    }
  }

  return (
    <button
      className="btn btn-primary upgrade-pay-btn"
      onClick={handleClick}
      disabled={busy || disabled}
    >
      <CreditCard size={14} />
      {busy ? "Loading…" : `Pay ${nairaFull(amount)} with Card / Transfer`}
    </button>
  );
}

// ── Feature cell ─────────────────────────────────────────────────────────────
function Cell({ val }) {
  if (val === true)  return <span className="upgrade-check"><Check size={14} /></span>;
  if (val === false) return <span className="upgrade-cross"><X size={12} /></span>;
  return <span className="upgrade-cell-text">{val}</span>;
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Upgrade() {
  const { user, refreshUser } = useAuth();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [bankModal, setBankModal] = useState(null);  // "GO" | "PRO" | null
  const [successMsg, setSuccessMsg] = useState("");
  const [monnifyErr, setMonnifyErr] = useState("");

  function load() {
    setLoading(true);
    apiFetch("subscription/status")
      .then(d => { setStatus(d); setLoading(false); })
      .catch(e => { setErr(e.message); setLoading(false); });
  }

  useEffect(load, []);

  const currentPlan = (status?.plan || user?.subscription_plan || "BASIC").toUpperCase();
  const prices = status?.prices || { GO: 3000, PRO: 7000 };

  function handleMonnifySuccess(result) {
    setSuccessMsg(`🎉 Payment confirmed! Your ${result.plan} plan is now active.`);
    load();
    if (refreshUser) refreshUser();
  }

  const PLANS = [
    {
      key: "BASIC",
      label: "Basic",
      price: null,
      desc: "Get started — free forever",
      color: "var(--muted)",
      bg: "var(--surface, #f9fafb)",
    },
    {
      key: "GO",
      label: "Go",
      price: prices.GO,
      desc: "For growing businesses",
      color: "#863bff",
      bg: "linear-gradient(135deg, #f3e8ff 0%, #ede9fe 100%)",
    },
    {
      key: "PRO",
      label: "Pro",
      price: prices.PRO,
      desc: "Full team & multi-branch",
      color: "#d97706",
      bg: "linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)",
    },
  ];

  return (
    <div className="upgrade-shell">

      {/* Current plan banner */}
      {status && (
        <div className="upgrade-current-banner">
          <div>
            <span className="upgrade-current-label">Current plan: </span>
            <strong style={{ color: currentPlan === "BASIC" ? "var(--muted)" : "#863bff" }}>
              {currentPlan}
            </strong>
            {status.expires_at && (
              <span className="td-muted" style={{ marginLeft: 10, fontSize: 12 }}>
                · expires {new Date(status.expires_at).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" })}
              </span>
            )}
          </div>
          {status.pending_payment && (
            <div className="upgrade-pending-chip">
              ⏳ {status.pending_payment.plan} upgrade pending ({status.pending_payment.method === "BANK_TRANSFER" ? "Bank Transfer" : "Monnify"})
            </div>
          )}
        </div>
      )}

      {successMsg && (
        <div className="upgrade-success-banner">{successMsg}</div>
      )}

      {err && <div style={{ color: "var(--rose)", marginBottom: 12 }}>{err}</div>}
      {monnifyErr && (
        <div className="modal-error" style={{ marginBottom: 12 }}>
          Monnify error: {monnifyErr} — try bank transfer instead.
        </div>
      )}

      {loading ? (
        <div className="td-muted" style={{ padding: 40, textAlign: "center" }}>Loading…</div>
      ) : (
        <>
          {/* Plan cards */}
          <div className="upgrade-cards">
            {PLANS.map(p => {
              const isCurrent = currentPlan === p.key;
              const isLower = p.key === "BASIC" && currentPlan !== "BASIC";
              return (
                <div
                  key={p.key}
                  className={`upgrade-card${isCurrent ? " upgrade-card--current" : ""}${p.key === "GO" ? " upgrade-card--featured" : ""}`}
                  style={{ background: p.bg }}
                >
                  {p.key === "GO" && <div className="upgrade-popular-badge">Most Popular</div>}
                  <div className="upgrade-card-name" style={{ color: p.color }}>{p.label}</div>
                  <div className="upgrade-card-price">
                    {p.price ? (
                      <>{nairaFull(p.price)}<span className="upgrade-card-period">/month</span></>
                    ) : (
                      <span style={{ color: "var(--muted)" }}>Free</span>
                    )}
                  </div>
                  <div className="upgrade-card-desc">{p.desc}</div>

                  {isCurrent ? (
                    <div className="upgrade-card-current-chip">✓ Current plan</div>
                  ) : isLower ? (
                    <div className="td-muted" style={{ fontSize: 12, textAlign: "center", padding: "8px 0" }}>
                      Contact support to downgrade
                    </div>
                  ) : (
                    <div className="upgrade-card-actions">
                      {/* Bank transfer */}
                      <button
                        className="btn btn-ghost upgrade-pay-btn"
                        onClick={() => setBankModal(p.key)}
                      >
                        <Banknote size={14} /> Pay by Bank Transfer
                      </button>
                      {/* Monnify */}
                      <MonnifyButton
                        plan={p.key}
                        amount={p.price}
                        disabled={false}
                        onSuccess={handleMonnifySuccess}
                        onError={msg => setMonnifyErr(msg)}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Feature comparison table */}
          <div className="upgrade-table-wrap">
            <div className="upgrade-table-title">Full feature comparison</div>
            <table className="upgrade-table">
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>Basic</th>
                  <th style={{ color: "#863bff" }}>Go</th>
                  <th style={{ color: "#d97706" }}>Pro</th>
                </tr>
              </thead>
              <tbody>
                {FEATURES.map((f, i) => (
                  <tr key={i} className={i % 2 === 0 ? "upgrade-row-alt" : ""}>
                    <td className="upgrade-feature-label">{f.label}</td>
                    <td><Cell val={f.basic} /></td>
                    <td><Cell val={f.go} /></td>
                    <td><Cell val={f.pro} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Help note */}
          <div className="upgrade-help-note">
            Questions? Send <strong>UPGRADE</strong> on WhatsApp to tiTi or{" "}
            <a href="mailto:support@creditvoice.ai">email support</a>.
          </div>
        </>
      )}

      {bankModal && (
        <BankTransferModal
          plan={bankModal}
          onClose={() => setBankModal(null)}
          onDone={() => load()}
        />
      )}
    </div>
  );
}
