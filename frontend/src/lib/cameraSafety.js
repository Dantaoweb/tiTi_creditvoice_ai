import { apiPost } from "./api";

/* Some phones (several Samsungs) switch off the moment a browser opens the
   camera. A page can't catch that — the phone is gone — so a note is left
   just before the camera opens and cleared once it has opened. If the note is
   still there when the app opens again, the camera took the phone down: this
   phone is switched to "scan from photo" (the phone's own Camera app, which
   these phones handle fine) and we are told which phone and browser it was. */

const OPENING_KEY = "cv_cam_opening";
const MODE_KEY = "cv_cam_mode";            // "photo" when this phone must not use the live camera

function read(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key, value) {
  try { value == null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* private mode */ }
}

export const isSamsung = () => /SM-|SAMSUNG|SamsungBrowser/i.test(navigator.userAgent || "");

export function deviceForcesPhoto() {
  return read(MODE_KEY) === "photo";
}

export function setDevicePhotoMode(on) {
  write(MODE_KEY, on ? "photo" : null);
}

export function markCameraOpening(details) {
  write(OPENING_KEY, JSON.stringify({ at: new Date().toISOString(), ...(details || {}) }));
}

export function markCameraOpened() {
  write(OPENING_KEY, null);
}

let notice = "";
export function takeCrashNotice() {
  const n = notice;
  notice = "";
  return n;
}

/* Called when the app starts. A note older than a few seconds means the last
   camera open never finished — the phone or the browser went down. */
export function checkForCameraCrash() {
  const raw = read(OPENING_KEY);
  if (!raw) return false;
  let note = {};
  try { note = JSON.parse(raw) || {}; } catch { /* a broken note is still a crash */ }
  const age = Date.now() - new Date(note.at || 0).getTime();
  if (age < 5000) return false;                 // still opening in another tab
  write(OPENING_KEY, null);
  setDevicePhotoMode(true);
  notice = "Your phone switched off the last time the camera opened, so scanning on this phone now uses " +
           "your phone's own Camera app: take a photo of the barcode and it is read from the photo.";
  apiPost("client/camera-crash", {
    user_agent: navigator.userAgent || "",
    stage: note.stage || "opening",
    details: note,
    crashed_at: note.at || null,
  }).catch(() => {});
  return true;
}
