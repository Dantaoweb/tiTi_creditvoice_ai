import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Send, Mic, MicOff, Zap, ShoppingCart, Package, CreditCard, Users, BarChart2, Egg, Coins } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useApp } from "../context/AppContext";
import { apiFetch, apiPost } from "../lib/api";
import { getBizLabels } from "../lib/bizLabels";

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  let binary = "";
  new Uint8Array(buffer).forEach(b => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

export default function Chat() {
  const { user } = useAuth();
  const { ownerPhone } = useApp();
  const navigate = useNavigate();
  const L = getBizLabels(user?.menu_group);
  const firstName = user?.name?.split(" ")[0] || "there";

  // Goal-oriented quick-start — answers "what do I want to do?" for a new user
  // instead of only showing transaction examples. Tailored to the business type;
  // each button lands them on the right screen (or the right guided form).
  const noProducts = user?.menu_group === "thrift" || user?.menu_group === "fee";
  const isPoultry = user?.business_type === "poultry_farm";
  const isThriftBiz = user?.menu_group === "thrift";
  const quickStart = [
    { icon: ShoppingCart, label: `Record a ${L.saleNoun || "sale"}`, to: "/capture?form=sale" },
    { icon: CreditCard, label: "Record a payment", to: "/capture?form=payment" },
    !noProducts && { icon: Package, label: "Add stock", to: "/capture?form=stock" },
    { icon: Users, label: `See who owes me`, to: "/customers" },
    isPoultry && { icon: Egg, label: "Log eggs & feed", to: "/poultry" },
    isThriftBiz && { icon: Coins, label: "Savings groups (ajo)", to: "/thrift" },
    { icon: BarChart2, label: "See my numbers", to: "/dashboard" },
  ].filter(Boolean);

  const [messages, setMessages]     = useState([]);
  const [input, setInput]           = useState("");
  const [busy, setBusy]             = useState(false);
  const [recording, setRecording]   = useState(false);
  const [voiceStatus, setVoiceStatus] = useState("");
  const [fastMode, setFastMode]     = useState({ enabled: false });
  const [fastBusy, setFastBusy]     = useState(false);

  const inputRef    = useRef(null);
  const bottomRef   = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef   = useRef([]);
  const audioBlobRef = useRef(null);

  // Only auto-focus the input on desktop. On mobile, focusing on mount pops the
  // on-screen keyboard and scrolls the page up, hiding the header (hamburger) and
  // the welcome instructions — the first thing a new user needs to see.
  useEffect(() => {
    if (window.matchMedia("(min-width: 769px)").matches) {
      inputRef.current?.focus();
    }
  }, []);

  // Keep the newest message in view — but only once the thread has content, and
  // scoped to the thread container ("nearest") so it never scrolls the whole
  // page and pushes the header off-screen on the empty first-load state.
  useEffect(() => {
    if (messages.length === 0) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, busy]);

  // Fetch fast mode state on mount
  useEffect(() => {
    apiFetch("fast-mode").then(setFastMode).catch(() => {});
  }, []);

  const toggleFastMode = useCallback(async () => {
    if (fastBusy) return;
    const next = !fastMode.enabled;
    setFastBusy(true);
    try {
      const res = await apiPost("fast-mode", {
        enabled: next,
        start_hour: fastMode.start_hour,
        end_hour: fastMode.end_hour,
      });
      setFastMode(prev => ({ ...prev, enabled: res.enabled }));
      pushMsg("titi",
        res.enabled
          ? "⚡ Fast mode ON — transactions save instantly without confirmation. Tap ⚡ again to turn off."
          : "Fast mode OFF — transactions will ask for confirmation again.",
        true,
      );
    } catch {
      // silent fail
    } finally {
      setFastBusy(false);
      inputRef.current?.focus();
    }
  }, [fastMode, fastBusy]);

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
      // Refresh fast mode state in case user typed "fast mode on/off"
      apiFetch("fast-mode").then(setFastMode).catch(() => {});
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
        audioBlobRef.current = blob;
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
            setVoiceStatus("No speech detected. Try again.");
          }
        } catch (err) {
          setVoiceStatus(/go plan/i.test(err?.message || "") ? err.message : "Transcription failed. Try typing instead.");
        }
        audioBlobRef.current = null;
      });
      recorderRef.current.start();
      setRecording(true);
      setVoiceStatus("Recording… tap mic to stop");
    } catch {
      setVoiceStatus("Microphone not available.");
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state !== "inactive") recorderRef.current.stop();
  }

  return (
    <div className="chat-shell">

      {/* ── Scrollable thread ── */}
      <div className="chat-thread">

        {/* Greeting + chips shown when thread is empty */}
        {messages.length === 0 && (
          <>
            <div className="chat-msg-titi">
              <div className="chat-titi-avatar chat-titi-avatar-sm">Ti</div>
              <div className="chat-bubble-titi">
                Hi {firstName}! 👋 What would you like to do? Tap one below — or just type it.
              </div>
            </div>
            <div className="chat-quickstart chat-chips-offset">
              {quickStart.map(a => (
                <button key={a.label} className="chat-qs-btn" onClick={() => navigate(a.to)}>
                  <a.icon size={17} />
                  <span>{a.label}</span>
                </button>
              ))}
            </div>
            <div className="chat-qs-hint chat-chips-offset">Or type it yourself, e.g.</div>
            <div className="chat-chips chat-chips-offset">
              {L.examples.map(ex => (
                <button key={ex.label} className="chat-chip" onClick={() => setInput(ex.text)}>
                  {ex.label}
                </button>
              ))}
            </div>
          </>
        )}

        {/* Message thread */}
        {messages.map((msg, i) =>
          msg.from === "you" ? (
            <div key={i} className="chat-msg-you">
              <div className="chat-bubble-you">{msg.text}</div>
            </div>
          ) : (
            <div key={i} className="chat-msg-titi">
              <div className="chat-titi-avatar chat-titi-avatar-sm">Ti</div>
              <div className={`chat-bubble-titi${msg.ok === false ? " chat-bubble-err" : ""}`}>
                {msg.text.split("\n").map((line, j) =>
                  line ? <p key={j}>{line}</p> : <br key={j} />
                )}
              </div>
            </div>
          )
        )}

        {/* Typing indicator */}
        {busy && (
          <div className="chat-msg-titi">
            <div className="chat-titi-avatar chat-titi-avatar-sm">Ti</div>
            <div className="chat-bubble-titi">
              <div className="chat-typing-dots">
                <span className="chat-typing-dot" />
                <span className="chat-typing-dot" />
                <span className="chat-typing-dot" />
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Fast mode status bar ── */}
      {fastMode.enabled && (
        <div className="chat-fast-bar">
          <Zap size={13} />
          <span>Fast mode — transactions save instantly</span>
          <button
            className="chat-fast-bar-off"
            onClick={toggleFastMode}
            disabled={fastBusy}
          >
            Turn off
          </button>
        </div>
      )}

      {/* ── Voice status line ── */}
      {voiceStatus && (
        <div className="chat-voice-status">{voiceStatus}</div>
      )}

      {/* ── Input bar ── */}
      <form onSubmit={e => { e.preventDefault(); send(); }} className={`chat-input-bar${fastMode.enabled ? " chat-input-fast" : ""}`}>
        <button
          type="button"
          className={`chat-mic-btn${recording ? " chat-mic-active" : ""}`}
          onClick={recording ? stopRecording : startRecording}
          disabled={busy}
          title={recording ? "Stop recording" : "Voice message"}
        >
          {recording ? <MicOff size={18} /> : <Mic size={18} />}
        </button>

        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder={fastMode.enabled ? "Type and send — saves instantly" : L.examples[0].text}
          disabled={busy || recording}
          autoComplete="off"
        />

        <button
          type="button"
          className={`chat-fast-btn${fastMode.enabled ? " chat-fast-btn-on" : ""}`}
          onClick={toggleFastMode}
          disabled={fastBusy || recording}
          title={fastMode.enabled ? "Fast mode ON — click to turn off" : "Turn on fast mode"}
        >
          <Zap size={15} />
        </button>

        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy || !input.trim()}
        >
          {busy ? "…" : <Send size={15} />}
        </button>
      </form>

      <a
        href="mailto:support@creditvoiceai.com"
        className="chat-support-link"
      >
        Contact Support
      </a>

    </div>
  );
}
