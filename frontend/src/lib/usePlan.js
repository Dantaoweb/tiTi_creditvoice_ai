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

  // Treat as BASIC if subscription has expired client-side
  const expired = user?.subscription_expires_at
    ? new Date(user.subscription_expires_at) < new Date()
    : false;

  const plan = (ORDER[raw] && !expired) ? raw : "BASIC";
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
