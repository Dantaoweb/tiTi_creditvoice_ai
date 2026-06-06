export function naira(value) {
  const n = Number(value || 0);
  if (n >= 1_000_000) return `₦${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `₦${(n / 1_000).toFixed(1)}k`;
  return `₦${n.toLocaleString()}`;
}

export function nairaFull(value) {
  return `₦${Number(value || 0).toLocaleString()}`;
}

export function dateStr(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-NG", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function dateTimeStr(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-NG", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeDate(value) {
  if (!value) return "—";
  const now = Date.now();
  const diff = now - new Date(value).getTime();
  const minutes = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days = Math.floor(diff / 86_400_000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return dateStr(value);
}

export function qty(quantity, unit) {
  if (!quantity && quantity !== 0) return "—";
  return unit ? `${Number(quantity).toLocaleString()} ${unit}` : Number(quantity).toLocaleString();
}
