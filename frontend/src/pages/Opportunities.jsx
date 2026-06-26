import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { ExternalLink } from "lucide-react";

const CATEGORY_COLORS = {
  finance:   { bg: "#eff6ff", border: "#bfdbfe", text: "#1d4ed8" },
  equipment: { bg: "#f0fdf4", border: "#bbf7d0", text: "#15803d" },
  trade:     { bg: "#fef3c7", border: "#fcd34d", text: "#b45309" },
  products:  { bg: "#fdf2f8", border: "#f0abfc", text: "#7e22ce" },
  general:   { bg: "#f9fafb", border: "#e5e7eb", text: "#374151" },
};

const CATEGORY_LABELS = {
  finance:   "Finance",
  equipment: "Equipment",
  trade:     "Trade",
  products:  "Products",
  general:   "General",
};

function OpportunityCard({ opp }) {
  const c = CATEGORY_COLORS[opp.category] || CATEGORY_COLORS.general;

  return (
    <div style={{
      background: "#fff", border: "1px solid var(--border)",
      borderRadius: 12, overflow: "hidden", display: "flex", flexDirection: "column",
    }}>
      <div style={{ background: c.bg, borderBottom: `1px solid ${c.border}`, padding: "12px 20px",
        display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: c.text, textTransform: "uppercase", letterSpacing: 0.5 }}>
          {CATEGORY_LABELS[opp.category] || opp.category}
        </span>
        {opp.partner_name && (
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{opp.partner_name}</span>
        )}
      </div>
      <div style={{ padding: "18px 20px", flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0, lineHeight: 1.4 }}>{opp.title}</h3>
        <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.7, margin: 0, flex: 1 }}>
          {opp.description}
        </p>
      </div>
      {opp.link_url && (
        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)" }}>
          <a href={opp.link_url} target="_blank" rel="noopener noreferrer"
            className="btn btn-primary" style={{ fontSize: 13, justifyContent: "center", width: "100%", textDecoration: "none" }}>
            Learn more <ExternalLink size={12} style={{ marginLeft: 4 }} />
          </a>
        </div>
      )}
    </div>
  );
}

export default function Opportunities() {
  const [opps, setOpps]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter]   = useState("all");

  useEffect(() => {
    apiFetch("opportunities")
      .then(d => setOpps(d.opportunities || []))
      .catch(() => setOpps([]))
      .finally(() => setLoading(false));
  }, []);

  const categories = ["all", ...new Set(opps.map(o => o.category))];
  const visible = filter === "all" ? opps : opps.filter(o => o.category === filter);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>

      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 800, margin: "0 0 6px" }}>Opportunities</h1>
        <p style={{ fontSize: 14, color: "var(--text-muted)", margin: 0 }}>
          Finance, equipment, partnerships and deals curated for CreditVoice businesses.
        </p>
      </div>

      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading opportunities…</p>
      ) : opps.length === 0 ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-muted)" }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🔮</div>
          <p style={{ fontWeight: 600, fontSize: 15 }}>No opportunities yet</p>
          <p style={{ fontSize: 13 }}>Check back soon — new partner offers and deals will appear here.</p>
        </div>
      ) : (
        <>
          {categories.length > 2 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20 }}>
              {categories.map(c => (
                <button key={c} onClick={() => setFilter(c)} style={{
                  padding: "6px 14px", borderRadius: 99, border: "1px solid",
                  cursor: "pointer", fontSize: 13, fontWeight: filter === c ? 700 : 400,
                  borderColor: filter === c ? "var(--brand)" : "var(--border)",
                  background: filter === c ? "var(--brand)" : "transparent",
                  color: filter === c ? "#fff" : "var(--text-secondary)",
                }}>
                  {c === "all" ? "All" : (CATEGORY_LABELS[c] || c)}
                </button>
              ))}
            </div>
          )}

          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 20,
          }}>
            {visible.map(o => <OpportunityCard key={o.id} opp={o} />)}
          </div>
        </>
      )}
    </div>
  );
}
