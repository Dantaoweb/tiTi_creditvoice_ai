// Format a user-typed amount/quantity with thousands separators as they type.
// Keeps an optional single decimal point (for fractional quantities). Returns a
// display string; use parseAmt() to get the number for submission.
export function fmtAmt(value) {
  let s = String(value ?? "").replace(/,/g, "").replace(/[^\d.]/g, "");
  const dot = s.indexOf(".");
  if (dot !== -1) {
    s = s.slice(0, dot + 1) + s.slice(dot + 1).replace(/\./g, "");
  }
  if (s === "") return "";
  const [intPart, decPart] = s.split(".");
  const intFmt = intPart ? Number(intPart).toLocaleString("en-US") : "0";
  return decPart !== undefined ? `${intFmt}.${decPart}` : intFmt;
}

// Strip separators and return a Number (0 when empty/invalid).
export function parseAmt(value) {
  const n = Number(String(value ?? "").replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}

export function naira(value) {
  const n = Number(value || 0);
  if (n >= 1_000_000) return `₦${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `₦${(n / 1_000).toFixed(1)}k`;
  return `₦${n.toLocaleString()}`;
}

export function nairaFull(value) {
  const n = Math.round(Number(value || 0));
  return `₦${n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;
}

const _ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
  "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
  "Seventeen", "Eighteen", "Nineteen"];
const _TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

function _toWords(n) {
  if (n === 0) return "";
  if (n < 20) return _ONES[n];
  if (n < 100) return _TENS[Math.floor(n / 10)] + (n % 10 ? " " + _ONES[n % 10] : "");
  if (n < 1_000) return _ONES[Math.floor(n / 100)] + " Hundred" + (n % 100 ? " " + _toWords(n % 100) : "");
  if (n < 1_000_000) return _toWords(Math.floor(n / 1_000)) + " Thousand" + (n % 1_000 ? " " + _toWords(n % 1_000) : "");
  if (n < 1_000_000_000) return _toWords(Math.floor(n / 1_000_000)) + " Million" + (n % 1_000_000 ? " " + _toWords(n % 1_000_000) : "");
  return _toWords(Math.floor(n / 1_000_000_000)) + " Billion" + (n % 1_000_000_000 ? " " + _toWords(n % 1_000_000_000) : "");
}

export function nairaInWords(value) {
  const n = Math.floor(Number(value || 0));
  if (n === 0) return "Zero Naira";
  return _toWords(n) + " Naira";
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
