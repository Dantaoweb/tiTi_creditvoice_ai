import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

// What a barcode says about the packet: an invalid code (made up or
// misprinted), the name it is known by, and a warning when that name is
// clearly a different product. A barcode can't prove a product is genuine —
// this only catches the careless cases, so it warns and never blocks.

export function InsightNotes({ insight, onUseName }) {
  if (!insight) return null;
  const { warnings = [], suggestion, unknown } = insight;
  return (
    <div className="bc-insight">
      {warnings.map((w, i) => (
        <div key={i} className="bc-insight__warn">⚠️ {w.text}</div>
      ))}
      {suggestion && !warnings.some(w => w.kind === "mismatch") && (
        <div className="bc-insight__known">
          Known as <strong>{suggestion.name}</strong>
          <span className="bc-insight__src">
            {suggestion.source === "shops" ? ` · by ${suggestion.shops} CreditVoice shops` : " · public product records"}
          </span>
          {onUseName && (
            <button type="button" className="link-btn" onClick={() => onUseName(suggestion.name)}>Use this name</button>
          )}
        </div>
      )}
      {unknown && !warnings.length && (
        <div className="bc-insight__note">No one has recorded this barcode yet — worth a quick look at the packet.</div>
      )}
    </div>
  );
}

/** Looks a typed or scanned code up (after a pause) and shows what it says. */
export default function BarcodeInsight({ code, name, onUseName }) {
  const [insight, setInsight] = useState(null);
  const clean = (code || "").trim();
  useEffect(() => {
    if (clean.length < 8) return undefined;
    let live = true;
    const t = setTimeout(() => {
      apiFetch("barcodes/insight", { code: clean, name: (name || "").trim() || undefined })
        .then(d => { if (live) setInsight(d); })
        .catch(() => { if (live) setInsight(null); });
    }, 500);
    return () => { live = false; clearTimeout(t); };
  }, [clean, name]);
  if (clean.length < 8) return null;
  return <InsightNotes insight={insight} onUseName={onUseName} />;
}
