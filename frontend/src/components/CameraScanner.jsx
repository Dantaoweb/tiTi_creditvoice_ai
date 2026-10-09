import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

// The phone's camera as a barcode scanner, for shops without a USB/Bluetooth
// scanner — which is most of them.
//
// Android Chrome reads barcodes itself (BarcodeDetector), so nothing extra is
// downloaded there. iPhone Safari cannot, so a small reader (ZXing) is loaded
// the first time someone there taps Scan; nobody else pays for it.
//
// onCode(code) may return (or resolve to) { label, ok, close }: the label is
// shown in the viewfinder ("Added Peak Milk"), and close shuts the camera
// (e.g. an unknown code the cashier now needs to attach by hand).

const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "itf", "qr_code"];
const SAME_CODE_MS = 1800;   // holding the camera on one packet is one scan, not ten

// Gentle on the phone. Cheap phones overheated and switched off when every
// frame was read at HD, with reads stacking up faster than they finished.
// So: a small picture, ONE read at a time with a rest in between, only the
// middle strip where the barcode is, and the camera off when it isn't used.
const REST_MS = 350;           // pause after each read before the next one
const IDLE_MS = 60_000;        // no scan for a minute → camera off (battery, heat)
const READ_WIDTH = 480;        // the strip is shrunk to this width before reading

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

async function zxingReader() {
  const [{ BrowserMultiFormatReader }, { DecodeHintType, BarcodeFormat }] = await Promise.all([
    import("@zxing/browser"), import("@zxing/library"),
  ]);
  const hints = new Map();
  // Only the codes printed on shop goods: fewer formats is less work per frame.
  hints.set(DecodeHintType.POSSIBLE_FORMATS, [
    BarcodeFormat.EAN_13, BarcodeFormat.EAN_8, BarcodeFormat.UPC_A, BarcodeFormat.UPC_E,
    BarcodeFormat.CODE_128, BarcodeFormat.CODE_39, BarcodeFormat.ITF, BarcodeFormat.QR_CODE,
  ]);
  return new BrowserMultiFormatReader(hints, { delayBetweenScanAttempts: REST_MS, delayBetweenScanSuccess: 1000 });
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

export default function CameraScanner({ onCode, onClose, continuous = false, title = "Scan a barcode" }) {
  const videoRef = useRef(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(true);
  const [paused, setPaused] = useState(false);        // camera off to save battery
  const [run, setRun] = useState(0);                  // bump to start the camera again
  const [feedback, setFeedback] = useState(null);     // { label, ok }
  const [keepGoing, setKeepGoing] = useState(continuous);
  const keepRef = useRef(continuous);
  // Kept in refs so a parent re-render never restarts the camera.
  const handler = useRef(onCode);
  const closer = useRef(onClose);
  useEffect(() => { handler.current = onCode; closer.current = onClose; });
  useEffect(() => { keepRef.current = keepGoing; }, [keepGoing]);

  useEffect(() => {
    let stream = null, loopTimer = null, idleTimer = null, zxingControls = null, stopped = false;
    let last = { code: "", at: 0 }, busy = false;
    const canvas = document.createElement("canvas");
    const ctx2d = canvas.getContext("2d", { willReadFrequently: true });

    function stop() {
      stopped = true;
      clearTimeout(loopTimer);
      clearTimeout(idleTimer);
      try { zxingControls?.stop(); } catch { /* already stopped */ }
      stream?.getTracks().forEach(t => t.stop());
      stream = null;
      const video = videoRef.current;
      if (video) video.srcObject = null;
    }

    function pause() {
      if (stopped) return;
      stop();
      setPaused(true);
    }

    function stillUsed() {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(pause, IDLE_MS);
    }

    // Leaving the app or locking the phone turns the camera off.
    function onVisibility() { if (document.hidden) pause(); }
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
            frameRate: { ideal: 15, max: 24 },
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

        const detector = await nativeDetector();
        if (stopped) return;
        if (detector) {
          readLoop(video, detector);
        } else {
          const reader = await zxingReader();
          if (stopped) return;
          zxingControls = await reader.decodeFromVideoElement(video, result => {
            if (result && !stopped) found(result.getText());
          });
        }
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
    setPaused(false);
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
            Camera paused to save your battery.
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
