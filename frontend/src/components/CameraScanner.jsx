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

function beep() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 1450;
    gain.gain.value = 0.12;
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + 0.09);
    osc.onended = () => ctx.close();
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
  const [feedback, setFeedback] = useState(null);     // { label, ok }
  const [keepGoing, setKeepGoing] = useState(continuous);
  const keepRef = useRef(continuous);
  // Kept in refs so a parent re-render never restarts the camera.
  const handler = useRef(onCode);
  const closer = useRef(onClose);
  useEffect(() => { handler.current = onCode; closer.current = onClose; });
  useEffect(() => { keepRef.current = keepGoing; }, [keepGoing]);

  useEffect(() => {
    let stream = null, timer = null, zxingControls = null, stopped = false;
    let last = { code: "", at: 0 }, busy = false;

    async function found(raw) {
      const code = String(raw || "").trim();
      if (!code || busy) return;
      const now = Date.now();
      if (code === last.code && now - last.at < SAME_CODE_MS) return;
      last = { code, at: now };
      busy = true;
      beep();
      try {
        const res = (await handler.current(code)) || {};
        if (res.label) setFeedback({ label: res.label, ok: res.ok !== false });
        if (res.close || !keepRef.current) { stop(); closer.current(); }
      } finally { busy = false; }
    }

    function stop() {
      stopped = true;
      if (timer) clearInterval(timer);
      try { zxingControls?.stop(); } catch { /* already stopped */ }
      stream?.getTracks().forEach(t => t.stop());
    }

    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera api");
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        if (stopped) { stream.getTracks().forEach(t => t.stop()); return; }
        const video = videoRef.current;
        video.srcObject = stream;
        video.setAttribute("playsinline", "true");     // iPhone: stay in the page
        await video.play();
        setStarting(false);

        const detector = await nativeDetector();
        if (detector) {
          timer = setInterval(async () => {
            if (stopped || busy || video.readyState < 2) return;
            try {
              const codes = await detector.detect(video);
              if (codes.length) found(codes[0].rawValue);
            } catch { /* a dropped frame */ }
          }, 180);
        } else {
          const { BrowserMultiFormatReader } = await import("@zxing/browser");
          const reader = new BrowserMultiFormatReader();
          zxingControls = await reader.decodeFromVideoElement(video, result => {
            if (result && !stopped) found(result.getText());
          });
        }
      } catch (e) {
        setStarting(false);
        setError(explain(e));
      }
    })();

    return stop;
  }, []);

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
        {!error && <div className="cam-scan__aim" aria-hidden="true" />}
        {starting && !error && <div className="cam-scan__msg">Starting the camera…</div>}
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
