import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch, apiPost } from "../lib/api";

/**
 * The card that appears over the dashboard — artwork, one line, one button.
 *
 * It asks the server for the next card for this person; the server decides who
 * qualifies and how often, so there is no targeting logic here. Three rules it
 * does keep: never more than one card, always closable, and it never appears
 * while the person is in the middle of something — it waits a moment after the
 * screen settles.
 */
export default function PromoCard() {
  const navigate = useNavigate();
  const [card, setCard] = useState(null);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      apiFetch("campaigns/next")
        .then(d => { if (!cancelled && d.campaign) setCard(d.campaign); })
        .catch(() => {});
    }, 1200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  if (!card) return null;

  function close(action) {
    setLeaving(true);
    apiPost(`campaigns/${card.id}/${action}`, {}).catch(() => {});
    setTimeout(() => setCard(null), 180);
  }

  function act() {
    const link = card.cta_link || "";
    close("clicked");
    if (!link) return;
    if (link.startsWith("http")) window.open(link, "_blank", "noopener");
    else navigate(link);
  }

  return (
    <div className={`promo-overlay${leaving ? " promo-leaving" : ""}`}
      onClick={e => e.target === e.currentTarget && close("dismissed")}>
      <div className={`promo-card promo-${card.theme || "navy"}`} role="dialog" aria-label={card.title}>
        <button className="promo-close" onClick={() => close("dismissed")} aria-label="Close">×</button>

        {card.image_url ? (
          <img className="promo-art" src={card.image_url} alt="" />
        ) : (
          /* No artwork uploaded: the card draws its own, in the brand's colours. */
          <div className="promo-art promo-art-drawn" aria-hidden="true">
            <svg viewBox="0 0 120 90" width="150" height="112">
              <rect x="18" y="20" width="84" height="56" rx="8" fill="rgba(255,255,255,.14)"
                stroke="rgba(255,255,255,.4)" />
              <path d="M30 44h40M30 54h26" stroke="rgba(255,255,255,.75)" strokeWidth="4"
                strokeLinecap="round" />
              <circle cx="88" cy="30" r="14" fill="#f5a623" />
              <path d="m82 30 4 4 8-9" stroke="#3a2500" strokeWidth="3.4" fill="none"
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        )}

        <h3 className="promo-title">{card.title}</h3>
        <p className="promo-body">{card.body}</p>

        {card.cta_label && (
          <button className="promo-cta" onClick={act}>{card.cta_label}</button>
        )}
        <button className="promo-later" onClick={() => close("dismissed")}>Maybe later</button>
      </div>
    </div>
  );
}
