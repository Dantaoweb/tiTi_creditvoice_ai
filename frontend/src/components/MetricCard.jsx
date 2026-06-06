export default function MetricCard({ label, value, sub, color = "green", loading }) {
  return (
    <div className={`metric-card ${color}`}>
      <div className="metric-label">{label}</div>
      {loading ? (
        <div className="skeleton skeleton-line" style={{ width: "70%", marginTop: 10 }} />
      ) : (
        <div className="metric-value">{value}</div>
      )}
      {sub && !loading && <div className="metric-sub">{sub}</div>}
    </div>
  );
}
