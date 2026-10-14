import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useSettings } from "../lib/settings";

// The phone's camera as a barcode scanner, for shops without a USB/Bluetooth
// scanner — which is most of them. (A USB/Bluetooth scanner never comes here:
// it types into the page like a keyboard, and nothing below touches that.)
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
// - ONE read at a time, with a rest in between — on every phone, including
//   the ones that use the fallback reader, which used to read whole frames;
// - the camera goes off soon after the last scan, when the app is left, and
//   for a rest after a few minutes of non-stop scanning.
const REST_MS = 400;              // pause after each read before the next one
const IDLE_MS = 20_000;           // no scan for 20 seconds → camera off
const MAX_RUN_MS = 3 * 60_000;    // 3 minutes of camera non-stop → a rest
const READ_WIDTH = 480;           // the strip is shrunk to this width before reading

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
// same gentle loop and both read only the small middle strip.
async function zxingDetector() {
  const [{ BrowserMultiFormatReader }, { DecodeHintType, BarcodeFormat }] = await Promise.all([
    import("@zxing/browser"), import("@zxing/library"),
  ]);
  const hints = new Map();
  // Only the codes printed on shop goods: fewer formats is less work per frame.
  hints.set(DecodeHintType.POSSIBLE_FORMATS, [
    BarcodeFormat.EAN_13, BarcodeFormat.EAN_8, BarcodeFormat.UPC_A, BarcodeFormat.UPC_E,
    BarcodeFormat.CODE_128, BarcodeFormat.CODE_39, BarcodeFormat.ITF, BarcodeFormat.QR_CODE,
  ]);
  const reader = new BrowserMultiFormatReader(hints);
  return {
    async detect(canvas) {
      try { return [{ rawValue: reader.decodeFromCanvas(canvas).getText() }]; }
      catch { return []; }               // nothing readable in this frame
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

export default function CameraScanner({ onCode, onClose, continuous = false, title = "Scan a barcode" }) {
  const videoRef = useRef(null);
  const { display } = useSettings();
  // Settings → My display → Phone camera scanning: "tap" reads one barcode and closes
  const tapMode = display?.scan_mode === "tap";
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(true);
  const [paused, setPaused] = useState(null);         // null | "idle" | "rest" — camera off
  const [run, setRun] = useState(0);                  // bump to start the camera again
  const [feedback, setFeedback] = useState(null);     // { label, ok }
  const [keepGoing, setKeepGoing] = useState(continuous && !tapMode);
  const keepRef = useRef(continuous && !tapMode);
  const batteryTip = useBatteryTip();
  // Kept in refs so a parent re-render never restarts the camera.
  const handler = useRef(onCode);
  const closer = useRef(onClose);
  useEffect(() => { handler.current = onCode; closer.current = onClose; });
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
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera api");
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 640 }, height: { ideal: 480 },
            frameRate: { ideal: 10, max: 15 },
          },
          audio: false,
        });
        if (stopped) { stream.getTracks().forEach(t => t.stop()); return; }
        const video = videoRef.current;
        video.srcObject = stream;
        video.setAttribute("playsinline", "true");     // iPhone: stay in the page
        await video.play();
        setStarting(false);
        stillUsed();
        // Non-stop scanning for a few minutes → let the phone cool a moment
        restTimer = setTimeout(() => pause("rest"), MAX_RUN_MS);

        const detector = (await nativeDetector()) || (await zxingDetector());
        if (stopped) return;
        readLoop(video, detector);
      } catch (e) {
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
        <button type="button" className="btn btn-primary" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}
