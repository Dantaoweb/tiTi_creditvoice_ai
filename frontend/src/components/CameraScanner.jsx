import { useEffect, useRef, useState } from "react";
import { X, Camera } from "lucide-react";
import { useSettings } from "../lib/settings";
import {
  deviceForcesPhoto, isSamsung, markCameraOpened, markCameraOpening, setDevicePhotoMode,
} from "../lib/cameraSafety";

// The phone's camera as a barcode scanner, for shops without a USB/Bluetooth
// scanner — which is most of them. (A USB/Bluetooth scanner never comes here:
// it types into the page like a keyboard, and nothing below touches that.)
//
// Two ways to scan:
// - live: the camera runs inside the page and reads barcodes by itself;
// - photo: the phone's own Camera app takes a picture and the barcode is read
//   from it. For phones that switch off when a browser opens the camera
//   (several Samsungs) — chosen in Settings, or set automatically on a phone
//   that went off last time (lib/cameraSafety.js).
//
// Android Chrome reads barcodes itself (BarcodeDetector), so nothing extra is
// downloaded there. Phones whose browser can't (iPhone Safari, some Android
// browsers) load a small reader (ZXing) the first time someone taps Scan.
//
// onCode(code) may return (or resolve to) { label, ok, close }: the label is
// shown in the viewfinder ("Added Peak Milk"), and close shuts the camera
// (e.g. an unknown code the cashier now needs to attach by hand).

const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "itf", "qr_code"];
const SAME_CODE_MS = 1800;   // holding the camera on one packet is one scan, not ten

// Gentle on the phone. A camera is one of the hardest jobs a phone does: the
// sensor, its picture chip and the processor all run at once, and a phone
// that is already warm (in use, charging, a hot shop) switches itself off to
// protect its battery. So:
// - a small, slow picture, and only its middle strip is read (shrunk);
// - ONE read at a time, with a rest in between, on every phone;
// - the camera goes off soon after the last scan, when the app is left, and
//   for a rest after a few minutes of non-stop scanning.
const REST_MS = 400;              // pause after each read before the next one
const IDLE_MS = 20_000;           // no scan for 20 seconds → camera off
const MAX_RUN_MS = 3 * 60_000;    // 3 minutes of camera non-stop → a rest
const READ_WIDTH = 480;           // the strip is shrunk to this width before reading
const PHOTO_MAX = 1280;           // a photo is shrunk to this before reading

let audioCtx = null;           // one, reused — not a new one per beep
function beep() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = audioCtx || new Ctx();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.frequency.value = 1450;
    gain.gain.value = 0.12;
    osc.connect(gain); gain.connect(audioCtx.destination);
    osc.start(); osc.stop(audioCtx.currentTime + 0.09);
  } catch { /* no sound is fine */ }
  try { navigator.vibrate?.(70); } catch { /* not every phone */ }
}

async function nativeDetector() {
  if (!("BarcodeDetector" in window)) return null;
  try {
    const supported = await window.BarcodeDetector.getSupportedFormats();
    const formats = FORMATS.filter(f => supported.includes(f));
    return formats.length ? new window.BarcodeDetector({ formats }) : null;
  } catch { return null; }
}

// The fallback reader, shaped like BarcodeDetector so both go through the
// same code. `tryHarder` for a still photo, where there's time to look closely.
async function zxingDetector(tryHarder = false) {
  const [{ BrowserMultiFormatReader }, { DecodeHintType, BarcodeFormat }] = await Promise.all([
    import("@zxing/browser"), import("@zxing/library"),
  ]);
  const hints = new Map();
  // Only the codes printed on shop goods: fewer formats is less work per frame.
  hints.set(DecodeHintType.POSSIBLE_FORMATS, [
    BarcodeFormat.EAN_13, BarcodeFormat.EAN_8, BarcodeFormat.UPC_A, BarcodeFormat.UPC_E,
    BarcodeFormat.CODE_128, BarcodeFormat.CODE_39, BarcodeFormat.ITF, BarcodeFormat.QR_CODE,
  ]);
  if (tryHarder) hints.set(DecodeHintType.TRY_HARDER, true);
  const reader = new BrowserMultiFormatReader(hints);
  return {
    async detect(canvas) {
      try { return [{ rawValue: reader.decodeFromCanvas(canvas).getText() }]; }
      catch { return []; }               // nothing readable in this picture
    },
  };
}

function explain(err) {
  if (!window.isSecureContext) return "The camera only works on the secure (https) address of CreditVoice.";
  const name = err?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Camera access is blocked. Allow the camera for this site in your browser settings, then try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return "No camera was found on this device.";
  if (name === "NotReadableError")
    return "The camera is being used by another app. Close it and try again.";
  return "The camera could not start. You can still type the barcode number.";
}

// Phones with several back cameras (main, wide, zoom, macro) can open the
// wrong one; some Samsungs crash on the wide / macro ones. Once the camera
// has been allowed, the names are known: pick the main back camera — on
// Android that is the lowest-numbered "camera2 N, facing back".
async function mainBackCameraId() {
  try {
    const cams = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput" && d.label);
    const back = cams.filter(d => /back|rear|environment/i.test(d.label));
    if (!back.length) return null;
    const num = d => { const m = d.label.match(/camera2?\s*(\d+)/i); return m ? Number(m[1]) : 99; };
    back.sort((a, b) => num(a) - num(b));
    return back[0].deviceId || null;
  } catch { return null; }
}

// Charging and a low battery are the two things we can see that make a
// camera switch a phone off (browsers don't tell anyone the temperature).
function useBatteryTip() {
  const [tip, setTip] = useState("");
  useEffect(() => {
    let battery = null;
    const update = () => {
      if (!battery) return;
      if (battery.charging) setTip("Your phone is charging — scanning while charging heats it up. Unplug it if it gets hot.");
      else if (battery.level <= 0.15) setTip("Battery low — the camera may switch your phone off. Charge it first, or type the barcode.");
      else setTip("");
    };
    navigator.getBattery?.().then(b => {
      battery = b; update();
      b.addEventListener("chargingchange", update);
      b.addEventListener("levelchange", update);
    }).catch(() => {});
    return () => {
      battery?.removeEventListener("chargingchange", update);
      battery?.removeEventListener("levelchange", update);
    };
  }, []);
  return tip;
}

// Read a barcode from a photo the phone's Camera app took. The photo is shrunk,
// turned the right way up, read whole, then the middle on its own (bigger).
async function readPhoto(file) {
  let bitmap;
  try { bitmap = await createImageBitmap(file, { imageOrientation: "from-image" }); }
  catch {
    bitmap = await new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = URL.createObjectURL(file);
    });
  }
  const bw = bitmap.width, bh = bitmap.height;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const attempt = async (sx, sy, sw, sh) => {
    const scale = Math.min(1, PHOTO_MAX / Math.max(sw, sh));
    canvas.width = Math.round(sw * scale);
    canvas.height = Math.round(sh * scale);
    ctx.drawImage(bitmap, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    const native = await nativeDetector();
    const codes = native ? await native.detect(canvas).catch(() => []) : [];
    if (codes.length) return codes[0].rawValue;
    const zx = await zxingDetector(true);
    const z = await zx.detect(canvas);
    return z.length ? z[0].rawValue : null;
  };
  return (await attempt(0, 0, bw, bh))
      || (await attempt(bw * 0.2, bh * 0.25, bw * 0.6, bh * 0.5))
      || null;
}

function PhotoScan({ title, onClose, found, continuous, canGoLive, onGoLive, batteryTip }) {
  const inputRef = useRef(null);
  const [state, setState] = useState("ready");      // ready | reading | none
  const [feedback, setFeedback] = useState(null);

  async function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";                              // the same photo again still fires
    if (!file) return;
    setState("reading");
    try {
      const code = await readPhoto(file);
      if (!code) { setState("none"); return; }
      const res = await found(code);
      if (res?.label) setFeedback({ label: res.label, ok: res.ok !== false });
      setState("ready");
    } catch { setState("none"); }
  }

  return (
    <div className="cam-scan" role="dialog" aria-label={title}>
      <div className="cam-scan__bar">
        <strong>{title}</strong>
        <button type="button" className="cam-scan__close" onClick={onClose} aria-label="Close">
          <X size={20} />
        </button>
      </div>
      <div className="cam-scan__view" style={{ display: "grid", placeItems: "center" }}>
        <input ref={inputRef} type="file" accept="image/*" capture="environment"
          onChange={onFile} style={{ display: "none" }} />
        <div className="cam-scan__msg" style={{ position: "static" }}>
          {state === "reading" ? "Reading the barcode…" : (
            <>
              {state === "none" && (
                <div style={{ marginBottom: 10, color: "#fca5a5" }}>
                  Couldn't read a barcode in that photo. Hold the phone closer, keep the barcode flat
                  and in good light, then try again.
                </div>
              )}
              <button type="button" className="btn btn-primary" onClick={() => inputRef.current?.click()}
                style={{ fontSize: 16, padding: "12px 18px" }}>
                <Camera size={18} /> {feedback ? "Take another photo" : "Take a photo of the barcode"}
              </button>
              <div style={{ marginTop: 10, fontSize: 13, opacity: 0.85 }}>
                Your phone's own Camera app opens. Snap the barcode up close; it's read from the photo.
              </div>
            </>
          )}
        </div>
        {feedback && (
          <div className={`cam-scan__feedback${feedback.ok ? "" : " cam-scan__feedback--bad"}`}>
            {feedback.label}
          </div>
        )}
      </div>
      <div className="cam-scan__foot">
        {batteryTip && <span style={{ color: "#fcd34d", fontWeight: 600 }}>⚠ {batteryTip}</span>}
        {canGoLive && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onGoLive}>
            Use the live camera instead
          </button>
        )}
        <button type="button" className="btn btn-primary" onClick={onClose}>
          {continuous ? "Done" : "Close"}
        </button>
      </div>
    </div>
  );
}

export default function CameraScanner({ onCode, onClose, continuous = false, title = "Scan a barcode" }) {
  const { display } = useSettings();
  const settingMode = display?.scan_mode || "keep";      // keep | tap | photo
  const [forcedPhoto, setForcedPhoto] = useState(deviceForcesPhoto);
  const photo = forcedPhoto || settingMode === "photo";
  const batteryTip = useBatteryTip();
  const handler = useRef(onCode);
  const closer = useRef(onClose);
  useEffect(() => { handler.current = onCode; closer.current = onClose; });

  if (photo) {
    // One photo at a time: the duplicate guard is the cashier taking a new one.
    const foundPhoto = async (code) => {
      beep();
      const res = (await handler.current(code)) || {};
      if (res.close || !continuous) closer.current();
      return res;
    };
    return (
      <PhotoScan title={title} onClose={onClose} found={foundPhoto} continuous={continuous}
        batteryTip={batteryTip}
        canGoLive={settingMode !== "photo"}
        onGoLive={() => { setDevicePhotoMode(false); setForcedPhoto(false); }} />
    );
  }
  return (
    <LiveScan title={title} onClose={onClose} continuous={continuous} tapMode={settingMode === "tap"}
      handler={handler} closer={closer} batteryTip={batteryTip}
      onUsePhoto={() => { setDevicePhotoMode(true); setForcedPhoto(true); }} />
  );
}

function LiveScan({ title, onClose, continuous, tapMode, handler, closer, batteryTip, onUsePhoto }) {
  const videoRef = useRef(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(true);
  const [paused, setPaused] = useState(null);         // null | "idle" | "rest" — camera off
  const [run, setRun] = useState(0);                  // bump to start the camera again
  const [feedback, setFeedback] = useState(null);     // { label, ok }
  const [keepGoing, setKeepGoing] = useState(continuous && !tapMode);
  const keepRef = useRef(continuous && !tapMode);
  useEffect(() => { keepRef.current = keepGoing; }, [keepGoing]);
  // The setting may arrive after the camera opened
  useEffect(() => { if (tapMode) setKeepGoing(false); }, [tapMode]);

  useEffect(() => {
    let stream = null, loopTimer = null, idleTimer = null, restTimer = null, stopped = false;
    let last = { code: "", at: 0 }, busy = false;
    const canvas = document.createElement("canvas");
    const ctx2d = canvas.getContext("2d", { willReadFrequently: true });

    function stop() {
      stopped = true;
      clearTimeout(loopTimer);
      clearTimeout(idleTimer);
      clearTimeout(restTimer);
      stream?.getTracks().forEach(t => t.stop());
      stream = null;
      const video = videoRef.current;
      if (video) video.srcObject = null;
    }

    function pause(why) {
      if (stopped) return;
      stop();
      setPaused(why);
    }

    function stillUsed() {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => pause("idle"), IDLE_MS);
    }

    // Leaving the app or locking the phone turns the camera off.
    function onVisibility() { if (document.hidden) pause("idle"); }
    document.addEventListener("visibilitychange", onVisibility);

    async function found(raw) {
      const code = String(raw || "").trim();
      if (!code || busy) return;
      const now = Date.now();
      if (code === last.code && now - last.at < SAME_CODE_MS) return;
      last = { code, at: now };
      busy = true;
      stillUsed();
      beep();
      try {
        const res = (await handler.current(code)) || {};
        if (res.label) setFeedback({ label: res.label, ok: res.ok !== false });
        if (res.close || !keepRef.current) { stop(); closer.current(); }
      } finally { busy = false; }
    }

    // The middle strip of the frame, shrunk: where a barcode is held, at a
    // fraction of the pixels.
    function strip(video) {
      const vw = video.videoWidth, vh = video.videoHeight;
      if (!vw || !vh) return null;
      const sw = vw * 0.8, sh = vh * 0.5;
      const scale = Math.min(1, READ_WIDTH / sw);
      canvas.width = Math.round(sw * scale);
      canvas.height = Math.round(sh * scale);
      ctx2d.drawImage(video, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, canvas.width, canvas.height);
      return canvas;
    }

    // One read at a time; the next starts only after this one has finished.
    async function readLoop(video, detector) {
      if (stopped) return;
      if (!busy && video.readyState >= 2) {
        try {
          const frame = strip(video);
          const codes = frame ? await detector.detect(frame) : [];
          if (codes.length) await found(codes[0].rawValue);
        } catch { /* a dropped frame */ }
      }
      if (!stopped) loopTimer = setTimeout(() => readLoop(video, detector), REST_MS);
    }

    (async () => {
      const samsung = isSamsung();
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera api");
        // The main back camera when we know which it is; otherwise "a back camera".
        const mainId = await mainBackCameraId();
        const video = mainId ? { deviceId: { exact: mainId } } : { facingMode: { ideal: "environment" } };
        // Samsungs start the camera the plain way, as ordinary apps do — some
        // crash when asked for a particular size and speed. Others get the
        // small, slow picture that keeps a phone cool.
        if (!samsung) Object.assign(video, {
          width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 10, max: 15 },
        });
        // If the phone goes down right here, this note is still there next
        // time and the phone is switched to scanning from a photo.
        markCameraOpening({ stage: "opening", samsung, main_camera: !!mainId, constraints: video });
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
        } catch (first) {
          if (!mainId || first?.name === "NotAllowedError") throw first;
          // That camera id went away (a new phone, a reset): any back camera
          stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: "environment" } }, audio: false,
          });
        }
        if (stopped) { markCameraOpened(); stream.getTracks().forEach(t => t.stop()); return; }
        const el = videoRef.current;
        el.srcObject = stream;
        el.setAttribute("playsinline", "true");     // iPhone: stay in the page
        await el.play();
        markCameraOpened();
        setStarting(false);
        stillUsed();
        // Non-stop scanning for a few minutes → let the phone cool a moment
        restTimer = setTimeout(() => pause("rest"), MAX_RUN_MS);

        const detector = (await nativeDetector()) || (await zxingDetector());
        if (stopped) return;
        readLoop(el, detector);
      } catch (e) {
        markCameraOpened();
        setStarting(false);
        setError(explain(e));
      }
    })();

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [run]);

  function resume() {
    setPaused(null);
    setStarting(true);
    setRun(r => r + 1);
  }

  return (
    <div className="cam-scan" role="dialog" aria-label={title}>
      <div className="cam-scan__bar">
        <strong>{title}</strong>
        <button type="button" className="cam-scan__close" onClick={onClose} aria-label="Close camera">
          <X size={20} />
        </button>
      </div>

      <div className="cam-scan__view">
        <video ref={videoRef} muted playsInline />
        {!error && !paused && <div className="cam-scan__aim" aria-hidden="true" />}
        {starting && !error && !paused && <div className="cam-scan__msg">Starting the camera…</div>}
        {paused && !error && (
          <div className="cam-scan__msg">
            {paused === "rest"
              ? <>Camera resting so your phone doesn't get too hot.<br />
                  <span style={{ fontSize: 13, opacity: 0.85 }}>If it feels warm, give it a minute before you carry on.
                    Scanning a lot every day? A USB or Bluetooth scanner works with CreditVoice and doesn't heat your phone.</span></>
              : "Camera paused to save your battery."}
            <div style={{ marginTop: 10 }}>
              <button type="button" className="btn btn-primary" onClick={resume}>Resume scanning</button>
            </div>
          </div>
        )}
        {error && <div className="cam-scan__msg cam-scan__msg--err">{error}</div>}
        {feedback && !error && (
          <div className={`cam-scan__feedback${feedback.ok ? "" : " cam-scan__feedback--bad"}`}>
            {feedback.label}
          </div>
        )}
      </div>

      <div className="cam-scan__foot">
        {batteryTip && !error && (
          <span style={{ color: "#fcd34d", fontWeight: 600 }}>⚠ {batteryTip}</span>
        )}
        {!error && <span>Point the camera at the barcode — it scans by itself.</span>}
        {continuous && !error && (
          <label className="cam-scan__keep">
            <input type="checkbox" checked={keepGoing} onChange={e => setKeepGoing(e.target.checked)} />
            Keep scanning
          </label>
        )}
        <button type="button" className="btn btn-ghost btn-sm" onClick={onUsePhoto}>
          Phone switching off? Scan from a photo instead
        </button>
        <button type="button" className="btn btn-primary" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}
