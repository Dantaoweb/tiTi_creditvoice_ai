import { useState } from "react";

/* Small graphs drawn as SVG — no charting package to download, so they load
   fast on cheap phones, work offline in the installed app, and follow light /
   dark mode through the colour tokens. Tap (or hover) a point to read it. */

export const COLORS = {
  brand: "var(--brand)", green: "#16a34a", amber: "var(--amber)", rose: "var(--rose)",
  blue: "var(--blue)", muted: "var(--subtle)",
};

export function naira(n) {
  const v = Math.abs(Number(n) || 0);
  const s = v >= 1e9 ? `${(v / 1e9).toFixed(1)}b` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}m`
    : v >= 1e3 ? `${Math.round(v / 1e3)}k` : `${Math.round(v)}`;
  return `${n < 0 ? "−" : ""}₦${s.replace(".0", "")}`;
}
const full = n => `₦${Math.round(Number(n) || 0).toLocaleString()}`;

function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

const W = 600, PAD_L = 58, PAD_R = 8, PAD_T = 12, PAD_B = 30;

function Frame({ height, max, min = 0, labels, children, onPick }) {
  const innerH = height - PAD_T - PAD_B;
  const ticks = [0, 0.5, 1].map(f => min + (max - min) * f);
  const y = v => PAD_T + innerH - ((v - min) / (max - min || 1)) * innerH;
  const every = Math.max(1, Math.ceil(labels.length / 8));
  const step = (W - PAD_L - PAD_R) / Math.max(labels.length, 1);
  return (
    <svg viewBox={`0 0 ${W} ${height}`} style={{ width: "100%", height: "auto", display: "block", touchAction: "pan-y" }}
      role="img" onMouseLeave={() => onPick(null)}>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={PAD_L} x2={W - PAD_R} y1={y(t)} y2={y(t)} style={{ stroke: "var(--line)" }} strokeDasharray={i ? "3 4" : ""} />
          <text x={PAD_L - 6} y={y(t) + 4} textAnchor="end" fontSize="14" style={{ fill: "var(--muted)" }}>{naira(t)}</text>
        </g>
      ))}
      {labels.map((l, i) => i % every === 0 && (
        <text key={i} x={PAD_L + step * (i + 0.5)} y={height - 8} textAnchor="middle" fontSize="14" style={{ fill: "var(--muted)" }}>{l}</text>
      ))}
      {children({ y, step, innerH })}
      {/* invisible hit areas — tap or hover a column to read it */}
      {labels.map((_l, i) => (
        <rect key={`h${i}`} x={PAD_L + step * i} y={PAD_T} width={step} height={innerH} fill="transparent"
          onMouseEnter={() => onPick(i)} onClick={() => onPick(i)} />
      ))}
    </svg>
  );
}

function Readout({ data, keys, picked, labelKey = "label" }) {
  const row = picked != null ? data[picked] : null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", fontSize: 12.5, marginTop: 6, minHeight: 20 }}>
      {row && <strong style={{ marginRight: 4 }}>{row[labelKey]}:</strong>}
      {keys.map(k => (
        <span key={k.key} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: k.color, display: "inline-block" }} />
          {k.label}{row ? ` ${full(row[k.key])}` : ""}
        </span>
      ))}
    </div>
  );
}

/* Columns per period; `stacked` puts the keys on top of each other. */
export function BarChart({ data, keys, stacked = false, height = 200 }) {
  const [picked, setPicked] = useState(null);
  const totals = data.map(d => stacked ? keys.reduce((s, k) => s + Math.max(0, d[k.key] || 0), 0)
    : Math.max(...keys.map(k => d[k.key] || 0)));
  const max = niceMax(Math.max(0, ...totals));
  return (
    <div>
      <Frame height={height} max={max} labels={data.map(d => d.label)} onPick={setPicked}>
        {({ y, step }) => data.map((d, i) => {
          const bw = Math.max(2, step * (stacked ? 0.62 : 0.72) / (stacked ? 1 : keys.length));
          let base = 0;
          return keys.map((k, j) => {
            const v = Math.max(0, d[k.key] || 0);
            const x = stacked ? PAD_L + step * i + (step - bw) / 2 : PAD_L + step * i + step * 0.14 + bw * j;
            const top = y(stacked ? base + v : v), bottom = y(stacked ? base : 0);
            if (stacked) base += v;
            return <rect key={`${i}${k.key}`} x={x} y={top} width={bw} height={Math.max(0, bottom - top)} rx="2"
              style={{ fill: k.color, opacity: picked == null || picked === i ? 1 : 0.45 }} />;
          });
        })}
      </Frame>
      <Readout data={data} keys={keys} picked={picked} />
    </div>
  );
}

/* Lines over the periods. */
export function LineChart({ data, keys, height = 200, area = false }) {
  const [picked, setPicked] = useState(null);
  const vals = data.flatMap(d => keys.map(k => d[k.key] || 0));
  const max = niceMax(Math.max(0, ...vals));
  const min = Math.min(0, ...vals);
  return (
    <div>
      <Frame height={height} max={max} min={min < 0 ? -niceMax(-min) : 0} labels={data.map(d => d.label)} onPick={setPicked}>
        {({ y, step }) => keys.map(k => {
          const pts = data.map((d, i) => [PAD_L + step * (i + 0.5), y(d[k.key] || 0)]);
          const path = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
          return (
            <g key={k.key}>
              {area && pts.length > 1 && (
                <path d={`${path} L${pts[pts.length - 1][0]},${y(0)} L${pts[0][0]},${y(0)} Z`}
                  style={{ fill: k.color, opacity: 0.12 }} />
              )}
              <path d={path} fill="none" strokeWidth="2.5" strokeLinejoin="round" style={{ stroke: k.color }} />
              {pts.map((p, i) => (picked === i || pts.length <= 12) && (
                <circle key={i} cx={p[0]} cy={p[1]} r={picked === i ? 4.5 : 2.5} style={{ fill: k.color }} />
              ))}
            </g>
          );
        })}
      </Frame>
      <Readout data={data} keys={keys} picked={picked} />
    </div>
  );
}

/* A ranked list as horizontal bars: top products, busiest days. */
export function HBars({ items, color = COLORS.brand, valueKey = "amount" }) {
  const max = Math.max(1, ...items.map(i => i[valueKey] || 0));
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {items.map((it, n) => (
        <div key={n} style={{ display: "grid", gridTemplateColumns: "minmax(70px, 34%) 1fr auto", gap: 8, alignItems: "center", fontSize: 13 }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.label ?? it.name}</span>
          <span style={{ background: "var(--line-2)", borderRadius: 4, height: 12, overflow: "hidden" }}>
            <span style={{ display: "block", height: "100%", width: `${Math.max(2, 100 * (it[valueKey] || 0) / max)}%`, background: color, borderRadius: 4 }} />
          </span>
          <span style={{ fontWeight: 600, minWidth: 54, textAlign: "right" }}>{naira(it[valueKey])}</span>
        </div>
      ))}
    </div>
  );
}
