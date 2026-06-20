import { Lock } from "lucide-react";

/**
 * Wraps any feature that requires an upgrade.
 *
 * Usage:
 *   <UpgradeGate allowed={allows("EXPORT")} plan="GO" feature="Exporting records">
 *     <ExportButton />
 *   </UpgradeGate>
 *
 * When locked it renders a blurred overlay with an upgrade prompt instead.
 * When `inline` is true it renders a compact inline badge instead of an overlay.
 */
export default function UpgradeGate({ allowed, plan = "Go", feature = "This feature", inline = false, children }) {
  if (allowed) return children;

  if (inline) {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        background: "#1e1b4b", border: "1px solid #4c1d95",
        borderRadius: 6, padding: "2px 8px",
        fontSize: 12, color: "#a78bfa", fontWeight: 600,
        cursor: "default", userSelect: "none",
      }}>
        <Lock size={10} /> {plan}
      </span>
    );
  }

  return (
    <div style={{ position: "relative" }}>
      <div style={{ filter: "blur(2px)", pointerEvents: "none", userSelect: "none", opacity: 0.4 }}>
        {children}
      </div>
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        background: "rgba(12,31,74,0.75)",
        borderRadius: 10, gap: 8,
        backdropFilter: "blur(1px)",
      }}>
        <Lock size={20} color="#a78bfa" />
        <div style={{ color: "#fff", fontWeight: 700, fontSize: 14 }}>{feature}</div>
        <div style={{ color: "rgba(255,255,255,0.6)", fontSize: 12 }}>
          Available on the <strong style={{ color: "#a78bfa" }}>{plan}</strong> plan
        </div>
        <button
          style={{
            marginTop: 4, background: "#863bff", color: "#fff", border: "none",
            borderRadius: 8, padding: "7px 18px", fontSize: 13, fontWeight: 600,
            cursor: "pointer",
          }}
          onClick={() => window.location.href = "/app/upgrade"}
        >
          Upgrade to {plan}
        </button>
      </div>
    </div>
  );
}

/**
 * Simple inline lock badge for buttons / table actions.
 */
export function LockBadge({ plan = "Go" }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 3,
      background: "rgba(134,59,255,0.15)", border: "1px solid rgba(134,59,255,0.3)",
      borderRadius: 4, padding: "1px 6px",
      fontSize: 11, color: "#a78bfa", fontWeight: 600,
    }}>
      <Lock size={9} /> {plan}
    </span>
  );
}

/**
 * Limit bar — shows "3 / 5 used · Upgrade to Go for unlimited"
 */
export function LimitBar({ used, limit, label, upgradePlan = "Go" }) {
  if (limit === null) return null;
  const pct   = Math.min(100, Math.round((used / limit) * 100));
  const atMax = used >= limit;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        fontSize: 12, color: atMax ? "#f87171" : "var(--text-muted)",
        marginBottom: 4,
      }}>
        <span>{used} / {limit} {label} used</span>
        {atMax && (
          <span style={{ color: "#a78bfa", fontWeight: 600, cursor: "pointer" }}
            onClick={() => window.location.href = "/app/upgrade"}>
            Upgrade to {upgradePlan} →
          </span>
        )}
      </div>
      <div style={{ height: 4, background: "rgba(255,255,255,0.08)", borderRadius: 2 }}>
        <div style={{
          height: "100%", borderRadius: 2,
          width: `${pct}%`,
          background: atMax ? "#ef4444" : "#863bff",
          transition: "width 0.3s",
        }} />
      </div>
    </div>
  );
}
