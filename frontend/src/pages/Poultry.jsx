import { useEffect, useState } from "react";
import { Egg, Wheat, Check, AlertCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { apiFetch, apiPost } from "../lib/api";
import { dateStr } from "../lib/format";
import MetricCard from "../components/MetricCard";

const todayISO = () => new Date().toISOString().slice(0, 10);
const toInt = v => { const n = parseInt(String(v).replace(/[^\d]/g, ""), 10); return isNaN(n) ? 0 : n; };
const cap = s => (s || "—").replace(/\b\w/g, c => c.toUpperCase());

export default function Poultry() {
  const [cfg, setCfg] = useState(null);
  const [tab, setTab] = useState("eggs");
  const [date, setDate] = useState(todayISO());
  const [eggs, setEggs] = useState({});      // grade key -> string
  const [feed, setFeed] = useState({});      // item id  -> string
  const [saving, setSaving] = useState(false);
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");
  const [eggHist, setEggHist] = useState([]);
  const [feedHist, setFeedHist] = useState([]);

  function loadConfig() {
    apiFetch("poultry/config").then(setCfg).catch(e => setError(e.message));
  }
  function loadHistory() {
    apiFetch("poultry/egg-history").then(d => setEggHist(d.days || [])).catch(() => {});
    apiFetch("poultry/feed-history").then(d => setFeedHist(d.days || [])).catch(() => {});
  }
  useEffect(() => { loadConfig(); loadHistory(); }, []);

  const grades = cfg?.grades || [];
  const feeds = cfg?.feeds || [];
  const perCrate = cfg?.eggs_per_crate || 30;
  const s = cfg?.summary || {};

  const eggTotal = grades.reduce((t, g) => t + toInt(eggs[g.key]), 0);
  const feedTotal = feeds.reduce((t, f) => t + toInt(feed[f.id]), 0);

  function showFlash(msg) { setFlash(msg); setTimeout(() => setFlash(""), 3500); }

  async function saveEggs() {
    const rows = grades.map(g => ({ grade: g.key, crates: toInt(eggs[g.key]) })).filter(r => r.crates > 0);
    if (!rows.length) return;
    setSaving(true); setError("");
    try {
      const r = await apiPost("poultry/egg-collection", { date, rows });
      setCfg(c => ({ ...c, summary: r.summary }));
      setEggs({}); loadHistory();
      showFlash(`Saved ${r.crates.toLocaleString()} crate${r.crates === 1 ? "" : "s"} collected.`);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  }

  async function saveFeed() {
    const rows = feeds.map(f => ({ item_id: f.id, quantity: toInt(feed[f.id]) })).filter(r => r.quantity > 0);
    if (!rows.length) return;
    setSaving(true); setError("");
    try {
      const r = await apiPost("poultry/feed-usage", { date, rows });
      setCfg(c => ({ ...c, summary: r.summary }));
      setFeed({}); loadHistory();
      showFlash(`Saved ${r.quantity.toLocaleString()} used.`);
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  }

  return (
    <>
      <div className="card-body" style={{ padding: "0 0 4px" }}>
        <h2 style={{ margin: "0 0 2px" }}>Egg &amp; Feed</h2>
        <p className="text-subtle text-sm" style={{ margin: 0 }}>
          Log today's egg collection and feed used. Eggs go into stock by grade; feed comes out of stock.
        </p>
      </div>

      {/* Summary */}
      <div className="metrics-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
        <MetricCard loading={!cfg} label="Eggs collected today" value={`${(s.eggs_collected_today || 0).toLocaleString()} crates`} color="brand" />
        <MetricCard loading={!cfg} label="Feed used today"      value={(s.feed_used_today || 0).toLocaleString()} color="amber" />
        <MetricCard loading={!cfg} label="Eggs in stock"        value={`${(s.eggs_in_stock || 0).toLocaleString()} crates`} color="green" small />
        <MetricCard loading={!cfg} label="Feed in stock"        value={(s.feed_in_stock || 0).toLocaleString()} color="blue" small />
      </div>

      {error && (
        <div className="card card-body" style={{ color: "var(--rose)", display: "flex", gap: 8 }}>
          <AlertCircle size={16} /> {error}
        </div>
      )}
      {flash && (
        <div className="card card-body" style={{ color: "var(--brand)", display: "flex", gap: 8, fontWeight: 600 }}>
          <Check size={16} /> {flash}
        </div>
      )}

      {/* Tabs */}
      <div className="page-tabs">
        <button className={`page-tab${tab === "eggs" ? " active" : ""}`} onClick={() => setTab("eggs")}>
          <Egg size={15} /> Egg Collection
        </button>
        <button className={`page-tab${tab === "feed" ? " active" : ""}`} onClick={() => setTab("feed")}>
          <Wheat size={15} /> Feed Usage
        </button>
      </div>

      {/* Date */}
      <div className="card card-body" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <label className="text-sm text-subtle" style={{ fontWeight: 600 }}>Date</label>
        <input type="date" value={date} max={todayISO()}
          onChange={e => setDate(e.target.value)} style={{ maxWidth: 180 }} />
      </div>

      {tab === "eggs" ? (
        <div className="card">
          <div className="card-header"><span className="card-title">Crates collected — by grade</span></div>
          <div className="card-body" style={{ display: "grid", gap: 8 }}>
            {grades.map(g => (
              <div key={g.key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                <span>{g.label}</span>
                <input inputMode="numeric" placeholder="0" value={eggs[g.key] || ""}
                  onChange={e => setEggs(p => ({ ...p, [g.key]: e.target.value }))}
                  style={{ maxWidth: 110, textAlign: "right" }} />
              </div>
            ))}
          </div>
          <div className="card-body" style={{ borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <strong>{eggTotal.toLocaleString()} crates</strong>
              <span className="text-subtle text-sm"> ({(eggTotal * perCrate).toLocaleString()} eggs)</span>
            </div>
            <button className="btn btn-primary" disabled={saving || eggTotal === 0} onClick={saveEggs}>
              {saving ? "Saving…" : "Save collection"}
            </button>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="card-header"><span className="card-title">Feed used today</span></div>
          {feeds.length === 0 ? (
            <p className="td-muted card-body">
              No feed products yet. Add feed via <Link to="/capture">Quick Record → Stock Received</Link> first
              (e.g. "layer mash"), then log daily usage here.
            </p>
          ) : (
            <>
              <div className="card-body" style={{ display: "grid", gap: 8 }}>
                {feeds.map(f => (
                  <div key={f.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <span>{cap(f.name)}
                      <span className="text-subtle text-sm"> · {(f.in_stock || 0).toLocaleString()} {f.unit} in stock</span>
                    </span>
                    <input inputMode="numeric" placeholder="0" value={feed[f.id] || ""}
                      onChange={e => setFeed(p => ({ ...p, [f.id]: e.target.value }))}
                      style={{ maxWidth: 110, textAlign: "right" }} />
                  </div>
                ))}
              </div>
              <div className="card-body" style={{ borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <strong>{feedTotal.toLocaleString()} used</strong>
                <button className="btn btn-primary" disabled={saving || feedTotal === 0} onClick={saveFeed}>
                  {saving ? "Saving…" : "Save feed used"}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* History */}
      <HistoryCard
        title={tab === "eggs" ? "Egg collection history" : "Feed usage history"}
        unit={tab === "eggs" ? "crates" : ""}
        rows={tab === "eggs" ? eggHist : feedHist}
      />
    </>
  );
}

function HistoryCard({ title, unit, rows }) {
  return (
    <div className="card">
      <div className="card-header"><span className="card-title">{title}</span></div>
      {rows.length === 0 ? (
        <p className="td-muted card-body">No entries yet.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="history-table">
            <thead><tr><th>Date</th><th>Total</th><th>Breakdown</th></tr></thead>
            <tbody>
              {rows.map(d => (
                <tr key={d.date}>
                  <td className="td-muted">{dateStr(d.date)}</td>
                  <td><strong>{d.total.toLocaleString()}{unit ? ` ${unit}` : ""}</strong></td>
                  <td className="td-muted text-sm">
                    {Object.entries(d.by_name)
                      .map(([n, q]) => `${n.replace(/^egg \(|\)$/g, "").replace(/\b\w/g, c => c.toUpperCase())}: ${q.toLocaleString()}`)
                      .join(" · ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
