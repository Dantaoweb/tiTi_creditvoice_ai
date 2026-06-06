import { useRef, useState } from "react";
import { Mic, MicOff, Play, Send, X, CheckCircle } from "lucide-react";
import { useApp } from "../context/AppContext";
import { apiPost } from "../lib/api";
import { nairaFull } from "../lib/format";
import { useToast } from "../components/Toast";

const EXAMPLES = [
  { label: "Credit + payment", text: "Amina bought rice 12000 paid 5000 due 20/06/2026" },
  { label: "Credit only",      text: "Tunde bought cement 15 bags at 800" },
  { label: "Payment",          text: "Amina paid 5000" },
  { label: "Direct sale",      text: "I sold phone 45000" },
];

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  let binary = "";
  new Uint8Array(buffer).forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

export default function Capture() {
  const { ownerPhone } = useApp();
  const toast = useToast();

  const [phone, setPhone]         = useState(ownerPhone || "");
  const [text, setText]           = useState("");
  const [preview, setPreview]     = useState(null);
  const [previewState, setPS]     = useState("empty"); // empty | loading | ready | error
  const [saving, setSaving]       = useState(false);
  const [saved, setSaved]         = useState(false);

  const [recording, setRecording] = useState(false);
  const [hasAudio, setHasAudio]   = useState(false);
  const [voiceStatus, setVS]      = useState("Ready to record");
  const recorderRef               = useRef(null);
  const chunksRef                 = useRef([]);
  const audioBlobRef              = useRef(null);
  const audioRef                  = useRef(null);

  async function handlePreview(e) {
    e.preventDefault();
    if (!phone || !text.trim()) return;
    setPS("loading");
    setSaved(false);
    setPreview(null);
    try {
      const data = await apiPost("capture/preview", { phone, text: text.trim() });
      setPreview(data);
      setPS("ready");
    } catch (err) {
      setPS("error");
      setPreview({ message: err.message });
    }
  }

  async function handleConfirm() {
    if (!preview?.pending) return;
    setSaving(true);
    try {
      const data = await apiPost("capture/confirm", { phone });
      setSaved(true);
      setPreview(data);
      toast(data.messages?.[0] || "Transaction saved.", "success");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  function handleClear() {
    setText(""); setPreview(null); setPS("empty"); setSaved(false);
    setHasAudio(false); setVS("Ready to record");
    audioBlobRef.current = null;
    if (audioRef.current) { audioRef.current.src = ""; audioRef.current.hidden = true; }
  }

  async function startRecording() {
    if (!navigator.mediaDevices) { toast("Microphone not available", "error"); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      recorderRef.current = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current.addEventListener("dataavailable", (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      });
      recorderRef.current.addEventListener("stop", () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
        audioBlobRef.current = blob;
        if (audioRef.current) {
          audioRef.current.src = URL.createObjectURL(blob);
          audioRef.current.hidden = false;
        }
        setHasAudio(true);
        setVS("Recording ready — transcribe to fill text");
        setRecording(false);
      });
      recorderRef.current.start();
      setRecording(true);
      setVS("Recording…");
    } catch {
      toast("Microphone permission denied", "error");
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state !== "inactive") recorderRef.current.stop();
  }

  async function handleTranscribe() {
    if (!audioBlobRef.current) return;
    setVS("Transcribing…");
    try {
      const b64 = await blobToBase64(audioBlobRef.current);
      const data = await apiPost("capture/voice", {
        phone,
        audio_base64: b64,
        mime_type: audioBlobRef.current.type || "audio/webm",
      });
      if (data.transcript) setText(data.transcript);
      setPreview(data);
      setPS("ready");
      setVS("Transcription done");
    } catch (err) {
      toast(err.message, "error");
      setVS("Transcription failed");
    }
  }

  const pending = preview?.pending;

  const SUMMARY_FIELDS = [
    ["Action",      pending?.action],
    ["Customer",    pending?.customer_name || "Direct sale"],
    ["Product",     pending?.product],
    ["Quantity",    pending?.quantity ? `${pending.quantity} ${pending.unit || ""}`.trim() : null],
    ["Sale amount", pending?.buy_amount ? nairaFull(pending.buy_amount) : null],
    ["Payment",     pending?.paid_amount ? nairaFull(pending.paid_amount) : null],
    ["Due date",    pending?.due_date ? new Date(pending.due_date).toLocaleDateString("en-NG") : null],
  ].filter(([, v]) => v);

  return (
    <div className="capture-grid">
      {/* ── Left: input form ── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Record transaction</span>
          <span className="card-subtitle">Same style as WhatsApp</span>
        </div>
        <form onSubmit={handlePreview} style={{ display: "grid", gap: 16, padding: 18 }}>
          <div className="form-group">
            <label className="form-label">Registered phone</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="234..." className="form-full" />
          </div>

          {/* Voice box */}
          <div className="voice-box">
            <div>
              <div className="voice-label">Voice capture</div>
              <div className="voice-status">{voiceStatus}</div>
            </div>
            <audio ref={audioRef} controls hidden style={{ width: "100%", height: 36 }} />
            <div className="gap-2">
              <button type="button" className="btn btn-secondary btn-sm"
                onClick={recording ? stopRecording : startRecording}
              >
                {recording ? <><MicOff size={14} /> Stop</> : <><Mic size={14} /> Record</>}
              </button>
              <button type="button" className="btn btn-secondary btn-sm"
                disabled={!hasAudio || recording}
                onClick={handleTranscribe}
              >
                <Play size={14} /> Transcribe
              </button>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Transaction text</label>
            <textarea
              rows={5}
              className="form-full"
              placeholder="Amina bought rice 12000 paid 5000 due 20/06/2026"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>

          <div className="example-chips">
            {EXAMPLES.map((ex) => (
              <button key={ex.label} type="button" className="example-chip"
                onClick={() => setText(ex.text)}
              >
                {ex.label}
              </button>
            ))}
          </div>

          <div className="gap-2">
            <button type="submit" className="btn btn-primary" disabled={previewState === "loading"}>
              <Send size={14} />
              {previewState === "loading" ? "Reading…" : "Preview"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={handleClear}>
              <X size={14} /> Clear
            </button>
          </div>
        </form>
      </div>

      {/* ── Right: preview result ── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Preview</span>
          <span className="card-subtitle">Confirm before saving</span>
        </div>
        <div style={{ padding: 18 }}>
          {previewState === "empty" && (
            <div className="capture-result empty">Enter a transaction and click Preview.</div>
          )}

          {previewState === "loading" && (
            <div className="capture-result empty">Reading transaction…</div>
          )}

          {previewState === "error" && (
            <div className="capture-result">
              <div style={{ color: "var(--rose)", fontSize: 13.5 }}>{preview?.message}</div>
            </div>
          )}

          {previewState === "ready" && preview && (
            <div className="capture-result">
              {preview.transcript && (
                <div style={{ background: "#f0f7f3", borderLeft: "3px solid var(--brand)", borderRadius: "0 6px 6px 0", padding: "10px 14px" }}>
                  <div className="form-label" style={{ marginBottom: 4 }}>Transcript</div>
                  <div style={{ fontSize: 13.5 }}>{preview.transcript}</div>
                </div>
              )}

              {preview.messages?.map((m, i) => (
                <div key={i} className="message-bubble">{m}</div>
              ))}

              {pending && !saved && (
                <>
                  <div className="form-label">Parsed details</div>
                  <div className="parsed-preview">
                    {SUMMARY_FIELDS.map(([label, value]) => (
                      <div key={label} className="parsed-cell">
                        <span>{label}</span>
                        <strong>{value}</strong>
                      </div>
                    ))}
                  </div>
                  <button
                    className="btn btn-primary"
                    disabled={saving}
                    onClick={handleConfirm}
                  >
                    <CheckCircle size={15} />
                    {saving ? "Saving…" : "Confirm & save"}
                  </button>
                </>
              )}

              {saved && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--brand)", fontWeight: 600 }}>
                  <CheckCircle size={18} /> Transaction saved. Check Dashboard for updated totals.
                </div>
              )}

              {preview.message && !pending && (
                <div style={{ color: "var(--muted)", fontSize: 13.5 }}>{preview.message}</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
