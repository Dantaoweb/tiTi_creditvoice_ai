import { useState, useEffect } from "react";
import { Wallet, ArrowDownCircle, Link, Users, Bell, CheckCircle } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";

function PreviewCard({ label, value, sub, color = "green" }) {
  return (
    <div className="card" style={{ opacity: 0.45, pointerEvents: "none", userSelect: "none" }}>
      <div className="card-subtitle">{label}</div>
      <div className={`metric-value color-${color}`} style={{ fontSize: 22, fontWeight: 800 }}>{value}</div>
      {sub && <div className="card-subtitle" style={{ marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export default function WalletPage() {
  const { user } = useAuth();
  const [interested, setInterested] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [walletData, setWalletData] = useState(null);

  useEffect(() => {
    apiFetch("wallet").then(d => {
      setWalletData(d);
      if (d.waitlist) setInterested(true);
    }).catch(() => {});
  }, []);

  async function handleInterest() {
    if (interested || submitting) return;
    setSubmitting(true);
    try {
      await apiPost("wallet/interest", {});
      setInterested(true);
    } catch {
      // silent
    } finally {
      setSubmitting(false);
    }
  }

  const isLive = walletData?.live;

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", display: "grid", gap: 20 }}>

      {/* ── Coming soon banner ── */}
      {!isLive && (
        <div className="card" style={{ borderLeft: "4px solid var(--brand)", background: "linear-gradient(135deg, #f0fdf4 0%, #fff 100%)" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
            <div style={{ background: "var(--brand)", borderRadius: 10, padding: 10, flexShrink: 0 }}>
              <Wallet size={22} color="#fff" />
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 17, marginBottom: 4 }}>CreditVoice Wallet — coming soon</div>
              <div style={{ color: "var(--text-muted)", fontSize: 13.5, lineHeight: 1.6 }}>
                A business wallet built for the way you already work. Customers pay directly
                into your CreditVoice account — it lands, gets matched to the right person's
                debt, and updates your records. No chasing screenshots. No manual entry.
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gap: 10, margin: "20px 0 18px" }}>
            {[
              { icon: ArrowDownCircle, text: "Customers pay by bank transfer to your dedicated virtual account number" },
              { icon: CheckCircle,     text: "Payment automatically matched to the customer and marked as paid in your ledger" },
              { icon: Bell,            text: "Instant WhatsApp notification the moment money lands" },
              { icon: Link,            text: "Shareable payment link — send to any customer on any channel" },
              { icon: Users,           text: "Thrift collections, school fees, and service payments — all reconciled automatically" },
            ].map(({ icon: Icon, text }) => (
              <div key={text} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                <Icon size={15} style={{ color: "var(--brand)", flexShrink: 0, marginTop: 2 }} />
                <span style={{ fontSize: 13.5, color: "#374151" }}>{text}</span>
              </div>
            ))}
          </div>

          {interested ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--brand)", fontWeight: 600, fontSize: 13.5 }}>
              <CheckCircle size={16} />
              You're on the list — we'll notify you when it launches.
            </div>
          ) : (
            <button
              className="btn btn-primary"
              onClick={handleInterest}
              disabled={submitting}
              style={{ width: "100%", justifyContent: "center" }}
            >
              {submitting ? "Saving…" : "Notify me when it's ready"}
            </button>
          )}
        </div>
      )}

      {/* ── Preview (blurred placeholder) ── */}
      {!isLive && (
        <>
          <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 1, color: "var(--text-muted)", fontWeight: 600 }}>
            Preview
          </div>

          <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <PreviewCard label="Wallet balance" value="₦48,500" color="green" />
            <PreviewCard label="Received (month)" value="₦183,000" color="blue" />
            <PreviewCard label="Unmatched" value="2 payments" sub="Need review" color="amber" />
          </div>

          <div className="card" style={{ opacity: 0.45, pointerEvents: "none", userSelect: "none" }}>
            <div className="card-title" style={{ marginBottom: 12 }}>Your virtual account</div>
            <div style={{ display: "grid", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
                <span style={{ color: "var(--text-muted)" }}>Bank</span>
                <strong>Providus Bank</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
                <span style={{ color: "var(--text-muted)" }}>Account number</span>
                <strong style={{ letterSpacing: 2 }}>6200 4891 23</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
                <span style={{ color: "var(--text-muted)" }}>Account name</span>
                <strong>CV / {user?.name?.toUpperCase() || "YOUR BUSINESS"}</strong>
              </div>
            </div>
          </div>

          <div className="card" style={{ opacity: 0.45, pointerEvents: "none", userSelect: "none" }}>
            <div className="card-title" style={{ marginBottom: 12 }}>Recent payments</div>
            {[
              { name: "Adebayo John",    bank: "GTBank",  amount: 15000, matched: true  },
              { name: "Ngozi Okonkwo",   bank: "Opay",    amount: 8500,  matched: true  },
              { name: "Unknown sender",  bank: "Kuda",    amount: 5000,  matched: false },
            ].map((p, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: i < 2 ? "1px solid var(--border)" : "none" }}>
                <ArrowDownCircle size={16} style={{ color: "var(--brand)", flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>{p.name}</div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{p.bank}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontWeight: 700, color: "var(--brand)" }}>{nairaFull(p.amount)}</div>
                  <div style={{ fontSize: 11, color: p.matched ? "var(--brand)" : "var(--amber)" }}>
                    {p.matched ? "✓ Matched" : "⚠ Unmatched"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── Live wallet (post-integration) ── */}
      {isLive && walletData && (
        <>
          <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <div className="card">
              <div className="card-subtitle">Wallet balance</div>
              <div className="metric-value color-green">{nairaFull(walletData.balance)}</div>
            </div>
            <div className="card">
              <div className="card-subtitle">Total received</div>
              <div className="metric-value color-blue">{nairaFull(walletData.total_received)}</div>
            </div>
            <div className="card">
              <div className="card-subtitle">Unmatched</div>
              <div className="metric-value color-amber">{walletData.unmatched_count}</div>
            </div>
          </div>

          <div className="card">
            <div className="card-title" style={{ marginBottom: 12 }}>Your virtual account</div>
            <div style={{ display: "grid", gap: 8 }}>
              <Row label="Bank" value={walletData.virtual_account_bank} />
              <Row label="Account number" value={walletData.virtual_account_number} mono />
              <Row label="Account name" value={walletData.virtual_account_name} />
            </div>
          </div>

          {walletData.transactions?.length > 0 && (
            <div className="card">
              <div className="card-title" style={{ marginBottom: 12 }}>Recent payments</div>
              {walletData.transactions.map((t, i) => (
                <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: i < walletData.transactions.length - 1 ? "1px solid var(--border)" : "none" }}>
                  <ArrowDownCircle size={16} style={{ color: "var(--brand)", flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 13.5 }}>{t.sender_name || "Unknown sender"}</div>
                    <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{t.sender_bank}{t.narration ? ` · ${t.narration}` : ""}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontWeight: 700, color: "var(--brand)" }}>{nairaFull(t.amount)}</div>
                    <div style={{ fontSize: 11, color: t.matched_customer_id ? "var(--brand)" : "var(--amber)" }}>
                      {t.matched_customer_id ? `✓ ${t.matched_by === "auto" ? "Auto" : "Manual"}` : "⚠ Unmatched"}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Row({ label, value, mono = false }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <strong style={mono ? { letterSpacing: 2, fontFamily: "monospace" } : {}}>{value || "—"}</strong>
    </div>
  );
}
