import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TrendingUp, AlertCircle, MessageCircle, X, Download, FileText, MapPin, Ticket, CheckCircle, Share2, Copy, BarChart2, AlertTriangle } from "lucide-react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiDownload, apiPost } from "../lib/api";
import { nairaFull, relativeDate } from "../lib/format";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import { TxTypeBadge } from "../components/Badge";
import { getBizLabels } from "../lib/bizLabels";
import StaleDataBanner from "../components/StaleDataBanner";
import { usePlan } from "../lib/usePlan";
import { useToast } from "../components/Toast";
import { Lock } from "lucide-react";

const WA_NUDGE_KEY = "cv_wa_nudge_dismissed";

function InviteCard() {
  const [data, setData]       = useState(null);
  const [open, setOpen]       = useState(false);
  const [codeInput, setCodeInput] = useState("");
  const [saving, setSaving]   = useState(false);
  const [saveErr, setSaveErr] = useState("");
  const [copied, setCopied]   = useState(false);

  const [titiNumber, setTitiNumber] = useState("");

  function load() {
    apiFetch("referral").then(setData).catch(() => {});
  }

  useEffect(() => {
    load();
    apiFetch("auth/config").then(d => setTitiNumber(d.titi_whatsapp || "")).catch(() => {});
  }, []);

  async function setCode(e) {
    e.preventDefault();
    if (!codeInput.trim()) return;
    setSaving(true); setSaveErr("");
    try {
      await apiPost("referral/set-code", { code: codeInput.trim() });
      load();
      setCodeInput("");
    } catch (e) { setSaveErr(e.message); }
    finally { setSaving(false); }
  }

  function copyLink() {
    if (!data?.link) return;
    navigator.clipboard.writeText(data.link).then(() => {
      setCopied("web");
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const atLimit = data?.invite_limit !== null && data?.invite_used >= data?.invite_limit;

  return (
    <div className="card" style={{ borderLeft: "3px solid rgba(134,59,255,0.4)" }}>
      <div className="card-header" style={{ cursor: "pointer" }} onClick={() => setOpen(o => !o)}>
        <span className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Share2 size={15} color="#a78bfa" /> Invite a Friend
          {data?.invite_used > 0 && (
            <span style={{ fontSize: 11, background: data.active_go > 0 ? "rgba(22,163,74,0.15)" : "rgba(134,59,255,0.15)", color: data.active_go > 0 ? "#16a34a" : "#a78bfa", borderRadius: 4, padding: "2px 6px" }}>
              {data.active_go > 0 ? `${data.active_go} active` : `${data.invite_used} joined`}
            </span>
          )}
        </span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{open ? "▲" : "▼"}</span>
      </div>

      {open && (
        <div style={{ marginTop: 12, display: "grid", gap: 14 }}>
          {/* Reward info */}
          <div style={{ fontSize: 13, color: "rgba(255,255,255,0.65)", background: "rgba(134,59,255,0.08)", borderRadius: 8, padding: "10px 12px", lineHeight: 1.6 }}>
            Your friend gets <strong style={{ color: "#a78bfa" }}>14 days on GO plan</strong> free.{" "}
            {data?.plan === "BASIC"
              ? <>You can invite <strong style={{ color: "var(--ink)" }}>{Math.max(0, 2 - (data?.invite_used || 0))} more</strong> friend{Math.max(0, 2 - (data?.invite_used || 0)) !== 1 ? "s" : ""} on your Basic plan.</>
              : <>For each friend with an <strong style={{ color: "#16a34a" }}>active GO subscription</strong>, you earn <strong style={{ color: "#16a34a" }}>₦{(data?.cashback_per_referral || 0).toLocaleString()}</strong> plan credit that month — automatically off your next payment.</>
            }
          </div>

          {/* Set / show referral code */}
          {data?.referral_code ? (
            <div style={{ display: "grid", gap: 10 }}>
              <div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>Your referral code</div>
                <span style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 18, letterSpacing: 3, color: "#a78bfa" }}>
                  {data.referral_code}
                </span>
              </div>

              {/* Web link */}
              {data.link && (
                <div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>Web sign-up link</div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 11, color: "var(--text-muted)", wordBreak: "break-all", flex: 1 }}>{data.link}</span>
                    <button className="btn btn-secondary btn-sm" onClick={copyLink}>
                      {copied === "web" ? <><CheckCircle size={12} /> Copied!</> : <><Copy size={12} /> Copy</>}
                    </button>
                  </div>
                </div>
              )}

              {/* WhatsApp link */}
              {titiNumber && (
                <div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>WhatsApp link (friend messages tiTi directly)</div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 11, color: "var(--text-muted)", flex: 1 }}>
                      {`https://wa.me/${titiNumber}?text=${encodeURIComponent("join " + data.referral_code)}`}
                    </span>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => {
                        navigator.clipboard.writeText(`https://wa.me/${titiNumber}?text=${encodeURIComponent("join " + data.referral_code)}`);
                        setCopied("wa");
                        setTimeout(() => setCopied(false), 2000);
                      }}
                    >
                      {copied === "wa" ? <><CheckCircle size={12} /> Copied!</> : <><Copy size={12} /> Copy</>}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <form onSubmit={setCode}>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>Choose your referral code (letters & numbers, 3–20 chars)</div>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={codeInput}
                  onChange={e => setCodeInput(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                  placeholder="e.g. DANSHOP"
                  style={{ flex: 1, fontFamily: "monospace", letterSpacing: 1 }}
                  maxLength={20}
                  disabled={saving}
                />
                <button className="btn btn-primary btn-sm" type="submit" disabled={saving || !codeInput.trim()}>
                  {saving ? "Saving…" : "Set Code"}
                </button>
              </div>
              {saveErr && <div className="login-error" style={{ marginTop: 6 }}>{saveErr}</div>}
            </form>
          )}

          {/* Stats */}
          {data?.invite_used > 0 && (
            <div style={{ display: "grid", gap: 8 }}>
              {/* Invite counts */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <div style={{ textAlign: "center", background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "10px 4px" }}>
                  <div style={{ fontWeight: 700, fontSize: 20 }}>{data.invite_used}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Friends joined</div>
                </div>
                <div style={{ textAlign: "center", background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "10px 4px" }}>
                  <div style={{ fontWeight: 700, fontSize: 20, color: "#f59e0b" }}>{data.not_yet_go ?? 0}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Not yet on GO</div>
                </div>
              </div>

              {/* Plan credit block — only visible to GO/PRO */}
              {data?.plan !== "BASIC" && (
                <div style={{
                  background: data.active_go > 0 ? "rgba(22,163,74,0.1)" : "rgba(255,255,255,0.04)",
                  border: `1px solid ${data.active_go > 0 ? "rgba(22,163,74,0.3)" : "var(--border)"}`,
                  borderRadius: 10, padding: "14px 16px",
                }}>
                  <div style={{ fontSize: 11, color: "rgba(255,255,255,0.5)", marginBottom: 4 }}>
                    Plan credit this month
                  </div>
                  <div style={{ fontWeight: 800, fontSize: 28, color: data.active_go > 0 ? "#16a34a" : "var(--text-muted)", letterSpacing: -0.5 }}>
                    ₦{(data.credit_this_month || 0).toLocaleString()}
                  </div>
                  <div style={{ fontSize: 12, color: "rgba(255,255,255,0.5)", marginTop: 4 }}>
                    {data.active_go > 0
                      ? <>{data.active_go} friend{data.active_go !== 1 ? "s" : ""} active on GO × ₦{(data.cashback_per_referral || 0).toLocaleString()} each</>
                      : "None of your friends are on an active GO plan yet"}
                  </div>
                  {data.active_go > 0 && (
                    <div style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", marginTop: 6 }}>
                      Deducted automatically when you renew. Credit resets if their plan lapses.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {atLimit && (
            <div style={{ fontSize: 13, color: "#f59e0b" }}>
              You've used both Basic invites. <Link to="/wallet" style={{ color: "#a78bfa" }}>Upgrade to GO</Link> for unlimited invites + cashback.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RedeemCodeCard({ onRedeemed }) {
  const [open, setOpen]   = useState(false);
  const [code, setCode]   = useState("");
  const [busy, setBusy]   = useState(false);
  const [err, setErr]     = useState("");
  const [done, setDone]   = useState(null);

  async function redeem(e) {
    e.preventDefault();
    if (!code.trim()) { setErr("Enter a code."); return; }
    setBusy(true); setErr("");
    try {
      const res = await apiPost("token-codes/redeem", { code: code.trim() });
      setDone(res);
      setCode("");
      if (onRedeemed) onRedeemed(res);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  if (done) {
    return (
      <div className="card" style={{ borderLeft: "3px solid #16a34a", display: "flex", alignItems: "center", gap: 12 }}>
        <CheckCircle size={20} color="#16a34a" />
        <div>
          <div style={{ fontWeight: 700 }}>Plan activated!</div>
          <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{done.message}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ borderLeft: "3px solid rgba(134,59,255,0.4)" }}>
      <div
        className="card-header"
        style={{ cursor: "pointer" }}
        onClick={() => setOpen(o => !o)}
      >
        <span className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Ticket size={15} color="#a78bfa" /> Have a plan code?
        </span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <form onSubmit={redeem} style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <input
            value={code}
            onChange={e => setCode(e.target.value.toUpperCase())}
            placeholder="e.g. GO-A1B2C3D4"
            style={{ flex: 1, minWidth: 180, fontFamily: "monospace", letterSpacing: 1 }}
            disabled={busy}
            autoFocus
          />
          <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
            {busy ? "Activating…" : "Activate"}
          </button>
          {err && <div className="login-error" style={{ width: "100%", marginTop: 0 }}>{err}</div>}
        </form>
      )}
    </div>
  );
}

function WhatsAppNudge({ titiNumber }) {
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(WA_NUDGE_KEY) === "1"
  );
  if (dismissed || !titiNumber) return null;
  const waLink = `https://wa.me/${titiNumber}?text=${encodeURIComponent("Hello")}`;
  return (
    <div className="wa-nudge">
      <MessageCircle size={18} className="wa-nudge-icon" />
      <div className="wa-nudge-text">
        <strong>Link WhatsApp to unlock more</strong>
        <span>Send reminders to customers, use voice capture, and access tiTi from your phone — send <em>Hello</em> to tiTi on WhatsApp.</span>
      </div>
      <a href={waLink} target="_blank" rel="noopener noreferrer" className="btn btn-whatsapp btn-sm">
        Open WhatsApp
      </a>
      <button className="wa-nudge-close" onClick={() => { setDismissed(true); localStorage.setItem(WA_NUDGE_KEY, "1"); }}>
        <X size={14} />
      </button>
    </div>
  );
}

export default function Dashboard() {
  const { ownerPhone, period } = useApp();
  const { user } = useAuth();
  const { allows } = usePlan();
  const canExport = allows("EXPORT");
  const L = getBizLabels(user?.menu_group);
  const toast = useToast();
  const [titiNumber, setTitiNumber] = useState("");

  useEffect(() => {
    apiFetch("auth/config").then(d => setTitiNumber(d.titi_whatsapp || "")).catch(() => {});
    apiFetch("branches").then(d => setBranches(d.branches || [])).catch(() => {});
  }, []);
  const [data, setData]       = useState(null);
  const [txData, setTxData]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [isStale, setIsStale] = useState(false);
  const [exportingType, setExportingType]   = useState(null);
  const [downloadingPDF, setDownloadingPDF] = useState(false);
  const [branches, setBranches]   = useState([]);
  const [branchId, setBranchId]   = useState("");

  async function handleExport(exportType) {
    setExportingType(exportType);
    try {
      const params = { export_type: exportType, owner_phone: ownerPhone, period };
      if (branchId) params.branch_id = branchId;
      await apiDownload("export", params);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setExportingType(null);
    }
  }

  async function handleLoanStatement() {
    setDownloadingPDF(true);
    try {
      await apiDownload("loan-statement", { owner_phone: ownerPhone, period });
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setDownloadingPDF(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = { period };
    if (branchId) params.branch_id = branchId;
    const txParams = { period };
    if (branchId) txParams.branch_id = branchId;
    Promise.all([
      apiFetch("dashboard", params),
      apiFetch("transactions", txParams),
    ])
      .then(([d, t]) => { setData(d); setTxData(t); setIsStale(!navigator.onLine); })
      .catch((e) => { setError(e.message); setIsStale(true); })
      .finally(() => setLoading(false));
  }, [ownerPhone, period, branchId]);

  const s = data?.summary || {};

  const PERIOD_LABEL = {
    TODAY: "today", WEEK: "this week", MONTH: "this month", YEAR: "this year",
  };
  const periodLabel = PERIOD_LABEL[period] || "all time";

  return (
    <>
      <WhatsAppNudge titiNumber={titiNumber} />
      <StaleDataBanner isStale={isStale} />

      {error && (
        <div className="card card-body gap-2" style={{ color: "var(--rose)", display: "flex", gap: 8 }}>
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {branches.length > 0 && (
        <div className="branch-filter-bar">
          <MapPin size={14} className="branch-filter-icon" />
          <span className="branch-filter-label">Branch:</span>
          {[{ id: "", name: "All" }, ...branches].map(b => (
            <button
              key={b.id}
              className={`btn btn-sm btn-pill ${branchId === (b.id ? String(b.id) : "") ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setBranchId(b.id ? String(b.id) : "")}
            >
              {b.name}
            </button>
          ))}
        </div>
      )}

      {/* ── Primary metrics ── */}
      <div className="metrics-grid">
        <MetricCard loading={loading} label={`${L.totalSales || "Sales"} ${periodLabel}`} value={nairaFull(s.total_sales_amount)} color="green" />
        <MetricCard loading={loading} label={L.payments    || "Payments received"}       value={nairaFull(s.total_pay_amount)}   color="blue"  />
        <MetricCard loading={loading} label={L.outstanding || "Outstanding balance"}     value={nairaFull(s.total_outstanding)}  color="amber" />
        <MetricCard loading={loading} label={L.totalCustomers}                           value={Number(s.total_customers || 0).toLocaleString()} color="rose" />
      </div>

      {/* ── Secondary metrics ── */}
      <div className="metrics-grid metrics-grid--secondary">
        <MetricCard loading={loading} label={`Credit sales ${periodLabel}`}  value={nairaFull(s.credit_sales_amount)}                     color="rose"  small />
        <MetricCard loading={loading} label={`Direct sales ${periodLabel}`}  value={nairaFull(s.direct_sales_amount)}                     color="green" small />
        <MetricCard loading={loading} label={`New ${L.customers || "customers"} ${periodLabel}`} value={Number(s.new_customers || 0).toLocaleString()} color="blue"  small />
        <MetricCard loading={loading} label={`Paid ${L.customers || "customers"} ${periodLabel}`} value={Number(s.paid_customers || 0).toLocaleString()} color="brand" small />
        <MetricCard loading={loading} label={`Transactions ${periodLabel}`}  value={Number(s.total_transactions || 0).toLocaleString()}   color="muted" small />
      </div>

      {/* ── Cards row ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 20 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">{L.topDebtors}</span>
            <Link to="/customers" className="btn btn-ghost btn-sm">View all</Link>
          </div>
          <DataTable
            loading={loading}
            rows={data?.top_debtors || []}
            emptyText="No outstanding balances."
            columns={[
              { key: "name",    label: L.customer,  render: (r) => <strong>{r.name}</strong> },
              { key: "balance", label: "Balance",   render: (r) => <span className="text-rose font-bold">{nairaFull(r.balance)}</span>, sortKey: "balance" },
              { key: "due",     label: "Due",        render: (r) => r.overdue
                ? <span className="badge" style={{ background: "rgba(239,68,68,0.12)", color: "var(--rose)", fontSize: 11 }}>Overdue {r.overdue_days}d</span>
                : r.due_date
                  ? <span className="td-muted" style={{ fontSize: 11 }}>{new Date(r.due_date).toLocaleDateString("en-NG", { day: "2-digit", month: "short" })}</span>
                  : <span className="td-muted">—</span>
              },
            ]}
          />
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Recent transactions</span>
            <Link to="/transactions" className="btn btn-ghost btn-sm">View all</Link>
          </div>
          <DataTable
            loading={loading}
            rows={(txData?.transactions || []).slice(0, 8)}
            emptyText="No transactions yet."
            columns={[
              { key: "type",       label: "Type",       render: (r) => <TxTypeBadge type={r.type} voided={r.is_voided} /> },
              { key: "customer",   label: L.customer,   render: (r) => r.customer || <span className="text-subtle">{L.directSale}</span> },
              { key: "amount",     label: "Amount",     render: (r) => nairaFull(r.amount) },
              { key: "created_at", label: "When",       render: (r) => <span className="td-muted">{relativeDate(r.created_at)}</span> },
            ]}
          />
        </div>

        {/* Product leaderboard */}
        {(loading || (data?.top_products || []).length > 0) && (
          <div className="card">
            <div className="card-header">
              <span className="card-title" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <BarChart2 size={15} /> Top Products {periodLabel}
              </span>
              <Link to="/inventory" className="btn btn-ghost btn-sm">View all</Link>
            </div>
            <DataTable
              loading={loading}
              rows={data?.top_products || []}
              emptyText="No product sales yet."
              columns={[
                { key: "name",   label: "Product", render: (r) => <strong>{r.name}</strong> },
                { key: "qty",    label: "Qty",     render: (r) => <span>{Number(r.qty).toLocaleString()}</span> },
                { key: "amount", label: "Revenue", render: (r) => <span className="text-green">{nairaFull(r.amount)}</span>, sortKey: "amount" },
              ]}
            />
          </div>
        )}
      </div>

      {/* ── Margin insight ── */}
      {!loading && data?.margin && (data.margin.discount_gap > 0 || data.margin.below_cost_products?.length > 0) && (
        <div className="card card-body" style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 14 }}>
            <AlertTriangle size={15} color="var(--amber)" /> Margin Insight
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
            <div style={{ background: "var(--line-2)", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>Expected revenue</div>
              <div style={{ fontWeight: 700 }}>{nairaFull(data.margin.expected)}</div>
            </div>
            <div style={{ background: "var(--line-2)", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>Actual recorded</div>
              <div style={{ fontWeight: 700 }}>{nairaFull(data.margin.actual)}</div>
            </div>
            {data.margin.discount_gap > 0 && (
              <div style={{ background: "rgba(239,68,68,0.08)", borderRadius: 8, padding: "10px 12px" }}>
                <div style={{ fontSize: 11, color: "var(--rose)", marginBottom: 3 }}>Discount gap</div>
                <div style={{ fontWeight: 700, color: "var(--rose)" }}>{nairaFull(data.margin.discount_gap)}</div>
              </div>
            )}
          </div>
          {data.margin.below_cost_products?.length > 0 && (
            <div style={{ fontSize: 12, color: "var(--rose)" }}>
              Selling below cost: <strong>{data.margin.below_cost_products.slice(0, 5).join(", ")}</strong>
              {data.margin.below_cost_products.length > 5 && ` +${data.margin.below_cost_products.length - 5} more`}
            </div>
          )}
        </div>
      )}

      {!!data?.low_stock_count && (
        <div className="card card-body" style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--amber)" }}>
          <TrendingUp size={16} />
          <strong>{data.low_stock_count}</strong> product{data.low_stock_count !== 1 ? "s" : ""} running low on stock.
          <Link to="/inventory" className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }}>View inventory</Link>
        </div>
      )}

      <div className="stmt-banner">
        <div className="stmt-banner-left">
          <FileText size={18} className="stmt-banner-icon" />
          <div>
            <div className="stmt-banner-title">Loan-Ready Statement</div>
            <div className="stmt-banner-sub">A professional PDF showing your revenue, receivables, and stock — ready to share with a bank or microfinance institution.</div>
          </div>
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={handleLoanStatement}
          disabled={downloadingPDF}
        >
          <Download size={14} />
          {downloadingPDF ? "Generating PDF…" : "Download Statement PDF"}
        </button>
      </div>

      <InviteCard />
      <RedeemCodeCard onRedeemed={() => window.location.reload()} />

      <div className="export-strip">
        <div className="export-strip-label">
          <Download size={13} />
          Export data
        </div>
        {canExport ? (
          [
            { key: "transactions", label: "Transactions" },
            { key: "debtors",      label: "Unpaid Debtors" },
            { key: "customers",    label: "Customers" },
            { key: "stock",        label: "Stock Inventory" },
          ].map(({ key, label }) => (
            <button
              key={key}
              className="btn btn-ghost btn-sm"
              onClick={() => handleExport(key)}
              disabled={exportingType === key}
            >
              {exportingType === key ? "Downloading…" : `${label} CSV`}
            </button>
          ))
        ) : (
          <button
            className="btn btn-ghost btn-sm"
            style={{ opacity: 0.6, cursor: "not-allowed" }}
            title="CSV export is available on the Go plan."
            onClick={() => window.location.href = "/app/upgrade"}
          >
            <Lock size={11} style={{ color: "#a78bfa" }} />
            <Download size={13} /> Export (Go plan)
          </button>
        )}
      </div>
    </>
  );
}
