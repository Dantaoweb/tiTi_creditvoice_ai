export default function MetricCard({ label, value, sub, color = "green", loading, small }) {
  return (
    <div className={`metric-card ${color}${small ? " metric-card--small" : ""}`}>
      <div className="metric-label">{label}</div>
      {loading ? (
        <div className="skeleton skeleton-line" style={{ width: "70%", marginTop: 8 }} />
      ) : (
        <div className={small ? "metric-value metric-value--small" : "metric-value"}>{value}</div>
      )}
      {sub && !loading && <div className="metric-sub">{sub}</div>}
    </div>
  );
}
