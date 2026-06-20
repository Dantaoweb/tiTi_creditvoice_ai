import { WifiOff } from "lucide-react";

export default function StaleDataBanner({ isStale }) {
  if (!isStale) return null;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      background: "#fef3c7", color: "#92400e",
      borderRadius: 8, padding: "8px 12px",
      fontSize: 13, fontWeight: 500, marginBottom: 16,
      border: "1px solid #fde68a",
    }}>
      <WifiOff size={14} style={{ flexShrink: 0 }} />
      You're offline — showing last saved data. Changes will sync when you reconnect.
    </div>
  );
}
