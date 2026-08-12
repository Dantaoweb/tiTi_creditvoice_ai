import { useAuth } from "../context/AuthContext";

const ORDER = { BASIC: 1, GO: 2, PRO: 3, PREMIUM: 4 };

const LIMITS = {
  BASIC:   { active_inventory_items: 5, school_teachers: 3, branches: 0, partners: 0, investors: 0 },
  GO:      { active_inventory_items: null, school_teachers: null, branches: 0, partners: 0, investors: 0 },
  PRO:     { active_inventory_items: null, school_teachers: null, branches: 1, partners: 1, investors: 1 },
  PREMIUM: { active_inventory_items: null, school_teachers: null, branches: null, partners: null, investors: null },
};

const FEATURE_MIN = {
  EXPORT:            "GO",
  ADVANCED_REPORTS:  "GO",
  BRANCHES:          "PRO",
  STAFF:             "PRO",
  SCHOOL_APP_STAFF:  "PRO",
  PARTNERS:          "PRO",
  INVOICE:           "GO",
  VOICE_TEXT:        "GO",
};

export function usePlan() {
  const { user } = useAuth();
  const raw  = (user?.subscription_plan || "BASIC").toUpperCase();

  // Trust the backend-resolved plan. get_business_subscription is the authority:
  // during the grace window it KEEPS the paid plan (e.g. "PRO") so paying users
  // aren't cut off early, and only AFTER grace does it downgrade to BASIC and
  // persist it. Re-deriving expiry on the client (a past expires_at during
  // grace) wrongly dropped paying users to BASIC. Expiry is communicated to the
  // user by the SubscriptionBanner (grace = renew soon, expired = upgrade).
  const plan = ORDER[raw] ? raw : "BASIC";
  const tier = ORDER[plan];

  function allows(feature) {
    const min = FEATURE_MIN[feature];
    if (!min) return true;
    return tier >= ORDER[min];
  }

  function limit(key) {
    return LIMITS[plan]?.[key] ?? null;
  }

  function withinLimit(key, currentCount) {
    const lim = limit(key);
    return lim === null || currentCount < lim;
  }

  function upgradeRequired(feature) {
    return !allows(feature);
  }

  function upgradeTarget(feature) {
    return FEATURE_MIN[feature] || "GO";
  }

  return { plan, tier, allows, limit, withinLimit, upgradeRequired, upgradeTarget };
}
