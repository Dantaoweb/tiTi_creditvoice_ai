import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { useAuth } from "../context/AuthContext";

// App-wide subscription notice, driven by the backend-resolved status:
//   • GRACE   → paid plan just lapsed but still working; urge renewal before it drops
//   • EXPIRED → already downgraded to Basic; urge upgrade to restore benefits
// Dismissible per browser session; reappears on the next visit (and whenever the
// status changes) so the nudge keeps returning without nagging within a session.
export default function SubscriptionBanner() {
  const { user } = useAuth();
  const status = (user?.subscription_status || "").toUpperCase();
  const plan   = (user?.subscription_plan || "").toUpperCase();
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem("cv_sub_banner_dismissed") === status,
  );

  if ((status !== "GRACE" && status !== "EXPIRED") || dismissed) return null;

  const isGrace = status === "GRACE";
  const expiresStr = user?.subscription_expires_at
    ? new Date(user.subscription_expires_at).toLocaleDateString("en-NG", { day: "numeric", month: "short", year: "numeric" })
    : null;

  function dismiss() {
    sessionStorage.setItem("cv_sub_banner_dismissed", status);
    setDismissed(true);
  }

  return (
    <div className={`sub-banner sub-banner--${isGrace ? "grace" : "expired"}`}>
      <AlertTriangle size={16} className="sub-banner-icon" />
      <div className="sub-banner-text">
        {isGrace ? (
          <>
            <strong>Your {plan || "paid"} plan has lapsed{expiresStr ? ` (expired ${expiresStr})` : ""}.</strong>{" "}
            Renew now to keep your features — otherwise your account drops to the free Basic plan.
          </>
        ) : (
          <>
            <strong>Your subscription expired — you're on the free Basic plan now.</strong>{" "}
            Upgrade to restore your features and higher limits.
          </>
        )}
      </div>
      <Link to="/upgrade" className="sub-banner-btn">{isGrace ? "Renew" : "Upgrade"}</Link>
      <button type="button" className="sub-banner-close" onClick={dismiss} aria-label="Dismiss">×</button>
    </div>
  );
}
