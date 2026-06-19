import { useState, useRef, useEffect } from "react";
import { MessageSquare, X, Send, Mic, MicOff } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useApp } from "../context/AppContext";
import { apiPost } from "../lib/api";

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  let binary = "";
  new Uint8Array(buffer).forEach(b => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

export default function TitiPanel() {
  const { user } = useAuth();
  const { ownerPhone } = useApp();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState("");

  const inputRef   = useRef(null);
  const bottomRef  = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef  = useRef([]);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 80);
    }
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  function pushMsg(from, text, ok) {
    setMessages(prev => [...prev, { from, text, ok }]);
  }

  async function send(overrideText) {
    const text = (overrideText ?? input).trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    pushMsg("you", text);
    try {
      const data = await apiPost("chat/send", { text });
      pushMsg("titi", data.reply || "Done!", data.ok !== false);
    } catch (err) {
      pushMsg("titi", err.message || "Something went wrong.", false);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  async function startRecording() {
    if (!navigator.mediaDevices || recording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      recorderRef.current = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current.addEventListener("dataavailable", e => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      });
      recorderRef.current.addEventListener("stop", async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
        setRecording(false);
        setVoiceStatus("Transcribing…");
        try {
          const b64 = await blobToBase64(blob);
          const data = await apiPost("capture/voice", {
            phone: user?.phone || ownerPhone,
            audio_base64: b64,
            mime_type: blob.type || "audio/webm",
          });
          if (data.transcript) {
            setInput(data.transcript);
            setVoiceStatus("");
            inputRef.current?.focus();
          } else {
            setVoiceStatus("No speech detected.");
          }
        } catch {
          setVoiceStatus("Transcription failed.");
        }
      });
      recorderRef.current.start();
      setRecording(true);
      setVoiceStatus("Recording…");
    } catch {
      setVoiceStatus("Microphone not available.");
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state !== "inactive") recorderRef.current.stop();
  }

  const firstName = user?.name?.split(" ")[0] || "there";

  return (
    <>
      {/* Floating button */}
      {!open && (
        <button className="titi-fab" onClick={() => setOpen(true)} title="Chat with tiTi">
          <MessageSquare size={22} />
          <span>tiTi</span>
        </button>
      )}

      {/* Overlay */}
      {open && (
        <div className="titi-overlay" onClick={() => setOpen(false)} />
      )}

      {/* Panel */}
      <div className={`titi-panel${open ? " titi-panel-open" : ""}`}>
        <div className="titi-panel-header">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div className="titi-panel-avatar">Ti</div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14, color: "#fff" }}>tiTi</div>
              <div style={{ fontSize: 11, color: "rgba(255,255,255,0.5)" }}>Business Assistant</div>
            </div>
          </div>
          <button className="titi-panel-close" onClick={() => setOpen(false)}>
            <X size={18} />
          </button>
        </div>

        <div className="titi-panel-thread">
          {messages.length === 0 && (
            <div className="titi-bubble titi-bubble-titi">
              Hi {firstName}! Ask me anything or record a transaction.
            </div>
          )}
          {messages.map((msg, i) =>
            msg.from === "you" ? (
              <div key={i} className="titi-bubble titi-bubble-you">{msg.text}</div>
            ) : (
              <div key={i} className={`titi-bubble titi-bubble-titi${msg.ok === false ? " titi-bubble-err" : ""}`}>
                <div style={{ whiteSpace: "pre-wrap" }}>{msg.text}</div>
              </div>
            )
          )}
          {busy && (
            <div className="titi-bubble titi-bubble-titi">
              <span className="titi-typing">●●●</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {voiceStatus && (
          <div style={{ fontSize: 11, textAlign: "center", color: "var(--text-muted)", padding: "4px 12px" }}>
            {voiceStatus}
          </div>
        )}

        <div className="titi-panel-input">
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Type a transaction or question…"
            disabled={busy}
          />
          <button
            className={`titi-mic-btn${recording ? " recording" : ""}`}
            onClick={recording ? stopRecording : startRecording}
            disabled={busy}
            title={recording ? "Stop recording" : "Voice input"}
          >
            {recording ? <MicOff size={16} /> : <Mic size={16} />}
          </button>
          <button className="titi-send-btn" onClick={() => send()} disabled={busy || !input.trim()}>
            <Send size={16} />
          </button>
        </div>
      </div>
    </>
  );
}
