import { useEffect, useState } from "react";
import { apiFetch, apiPut } from "./api";

/* Settings people choose (app_settings.py). Display choices apply to the page
   at once; business choices are shared by every screen through one cached
   load, refreshed when someone saves on the Settings page. */

const ZOOM = { small: 0.9, normal: 1, large: 1.12, xlarge: 1.25 };
const DISPLAY_KEY = "cv_display";

let media = null;

export function applyDisplay(display) {
  const d = { text_size: "normal", theme: "system", density: "comfortable", ...(display || {}) };
  const root = document.documentElement;
  // Text size scales the whole app, so px-sized text, icons and buttons grow together
  document.body.style.zoom = ZOOM[d.text_size] && ZOOM[d.text_size] !== 1 ? String(ZOOM[d.text_size]) : "";
  root.dataset.density = d.density;
  const setTheme = () => {
    const dark = d.theme === "dark" || (d.theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
    root.dataset.theme = dark ? "dark" : "light";
  };
  setTheme();
  if (media) media.removeEventListener?.("change", media._cv);
  media = null;
  if (d.theme === "system" && window.matchMedia) {
    media = window.matchMedia("(prefers-color-scheme: dark)");
    media._cv = setTheme;
    media.addEventListener?.("change", setTheme);
  }
  try { localStorage.setItem(DISPLAY_KEY, JSON.stringify(d)); } catch { /* private mode */ }
}

// Before the network answers, use what this device last had — no flash of the wrong theme
export function applySavedDisplay() {
  try { applyDisplay(JSON.parse(localStorage.getItem(DISPLAY_KEY) || "null")); }
  catch { applyDisplay(null); }
}

let cache = null;
let inflight = null;
const listeners = new Set();

export function loadSettings(force = false) {
  if (cache && !force) return Promise.resolve(cache);
  if (inflight && !force) return inflight;
  inflight = apiFetch("settings")
    .then(s => { cache = s; inflight = null; listeners.forEach(fn => fn(s)); return s; })
    .catch(e => { inflight = null; throw e; });
  return inflight;
}

export function clearSettingsCache() { cache = null; }

export async function saveDisplay(changes) {
  const r = await apiPut("settings/display", changes);
  applyDisplay(r.display);
  if (cache) { cache = { ...cache, display: r.display }; listeners.forEach(fn => fn(cache)); }
  return r.display;
}

export async function saveBusiness(values) {
  const r = await apiPut("settings/business", { values });
  if (cache) { cache = { ...cache, business: r.business }; listeners.forEach(fn => fn(cache)); }
  return r.business;
}

/* The business settings for any screen: { group_by_category, group_on_pos, … }.
   Until loaded, the defaults (how the app worked before settings). */
export const BUSINESS_DEFAULTS = {
  group_by_category: false, group_on_pos: true, category_source: "suggest",
  default_low_stock: null, allow_negative_stock: true, show_part_delivery: true,
  daily_summary: false, daily_summary_time: "20:00", category_order: [],
};

export function useSettings() {
  const [s, setS] = useState(cache);
  useEffect(() => {
    const fn = v => setS(v);
    listeners.add(fn);
    loadSettings().then(setS).catch(() => {});
    return () => listeners.delete(fn);
  }, []);
  return {
    loaded: !!s,
    display: s?.display,
    business: { ...BUSINESS_DEFAULTS, ...(s?.business || {}) },
    canEditBusiness: !!s?.can_edit_business,
  };
}
