export default function Skeleton({ rows = 5 }) {
  return (
    <div style={{ padding: "16px 18px", display: "grid", gap: 12 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <div className="skeleton skeleton-line" style={{ flex: 2, opacity: 1 - i * 0.1 }} />
          <div className="skeleton skeleton-line" style={{ flex: 1, opacity: 1 - i * 0.1 }} />
          <div className="skeleton skeleton-line" style={{ flex: 1, opacity: 1 - i * 0.1 }} />
        </div>
      ))}
    </div>
  );
}
