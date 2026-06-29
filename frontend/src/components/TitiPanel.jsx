import { useState, useRef, useEffect, useCallback } from "react";
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

const FAB_POS_KEY = "cv_fab_pos";
const DRAG_THRESHOLD = 6;

function clamp(val, min, max) { return Math.max(min, Math.min(max, val)); }

function loadSavedPos() {
  try {
    const saved = localStorage.getItem(FAB_POS_KEY);
    if (saved) return JSON.parse(saved);
  } catch {}
  return null;
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

  // Drag state
  const fabRef    = useRef(null);
  const [fabPos, setFabPos] = useState(loadSavedPos); // null = use CSS default
  const fabPosRef = useRef(fabPos);
  const drag = useRef({ active: false, moved: false, startPX: 0, startPY: 0, startLeft: 0, startTop: 0 });

  const inputRef   = useRef(null);
  const bottomRef  = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef  = useRef([]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 80);
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  // ── Drag handlers ────────────────────────────────────────────────────────
  const onPointerDown = useCallback((e) => {
    const el = fabRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    drag.current = {
      active: true,
      moved: false,
      startPX: e.clientX,
      startPY: e.clientY,
      startLeft: rect.left,
      startTop: rect.top,
    };
    el.setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e) => {
    if (!drag.current.active) return;
    const dx = e.clientX - drag.current.startPX;
    const dy = e.clientY - drag.current.startPY;
    if (!drag.current.moved && Math.abs(dx) + Math.abs(dy) < DRAG_THRESHOLD) return;
    drag.current.moved = true;

    const el = fabRef.current;
    const w = el ? el.offsetWidth  : 100;
    const h = el ? el.offsetHeight : 44;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    const newLeft = clamp(drag.current.startLeft + dx, 8, vw - w - 8);
    const newTop  = clamp(drag.current.startTop  + dy, 8, vh - h - 8);
    const pos = { left: newLeft, top: newTop };

    fabPosRef.current = pos;
    setFabPos(pos);
    e.preventDefault();
  }, []);

  const onPointerUp = useCallback(() => {
    if (!drag.current.active) return;
    drag.current.active = false;
    if (drag.current.moved) {
      localStorage.setItem(FAB_POS_KEY, JSON.stringify(fabPosRef.current));
    }
  }, []);

  function handleFabClick() {
    if (drag.current.moved) { drag.current.moved = false; return; }
    setOpen(true);
  }

  // ── Panel position follows FAB ───────────────────────────────────────────
  function getPanelStyle() {
    if (!fabPos) return {}; // CSS handles default position
    const el = fabRef.current;
    const fabW = el ? el.offsetWidth  : 100;
    const fabH = el ? el.offsetHeight : 44;
    const vw   = window.innerWidth;
    const vh   = window.innerHeight;
    const panelW = Math.min(360, vw - 32);
    const panelH = Math.min(520, vh - 100);
    const gap    = 10;

    // Horizontal: align left edge with FAB, clamped
    const left = clamp(fabPos.left, 8, vw - panelW - 8);

    // Vertical: prefer above the FAB; below if no room
    let top = fabPos.top - panelH - gap;
    if (top < 8) top = fabPos.top + fabH + gap;
    top = clamp(top, 8, vh - panelH - 8);

    return { left, top, bottom: "auto", right: "auto", width: panelW, maxHeight: panelH };
  }

  // ── Chat ─────────────────────────────────────────────────────────────────
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

  // Inline style overrides when a saved/dragged position exists
  const fabInlineStyle = fabPos
    ? { left: fabPos.left, top: fabPos.top, bottom: "auto", right: "auto" }
    : {};

  return (
    <>
      {/* Floating button */}
      {!open && (
        <button
          ref={fabRef}
          className="titi-fab"
          style={fabInlineStyle}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onClick={handleFabClick}
          title="Chat with tiTi — drag to move"
        >
          <MessageSquare size={22} />
          <span>tiTi</span>
        </button>
      )}

      {/* Overlay */}
      {open && (
        <div className="titi-overlay" onClick={() => setOpen(false)} />
      )}

      {/* Panel */}
      <div
        className={`titi-panel${open ? " titi-panel-open" : ""}`}
        style={open ? getPanelStyle() : {}}
      >
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

        <div style={{
          fontSize: 10, textAlign: "center", color: "rgba(255,255,255,0.3)",
          padding: "4px 12px 2px", lineHeight: 1.4,
        }}>
          tiTi can make mistakes — double-check figures. Your messages help improve tiTi.
        </div>

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
