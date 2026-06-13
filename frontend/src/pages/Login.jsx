import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, KeyRound, UserPlus, Loader2 } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";

function Spinner() {
  return <Loader2 size={15} className="spin" />;
}

// mode: "login" | "register" | "request_otp" | "set_pin"
export default function Login() {
  const { login, authLoading, authError, persistSession } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const [mode, setMode] = useState(params.get("mode") === "register" ? "register" : "login");
  const [titiNumber, setTitiNumber] = useState("");
  const [categories, setCategories] = useState([]);

  // Login fields
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");

  // Register fields
  const [regName, setRegName] = useState("");
  const [regPhone, setRegPhone] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regNewsletter, setRegNewsletter] = useState(false);
  const [regCat, setRegCat] = useState("");
  const [regType, setRegType] = useState("");
  const [regPin, setRegPin] = useState("");
  const [regConfirm, setRegConfirm] = useState("");

  // OTP / set-pin fields
  const [otpPhone, setOtpPhone] = useState("");
  const [selectedChannel, setSelectedChannel] = useState(""); // "email" | "whatsapp"
  const [otp, setOtp] = useState("");
  const [newPin, setNewPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    apiFetch("auth/config").then(d => setTitiNumber(d.titi_whatsapp || "")).catch(() => {});
    apiFetch("auth/business-categories").then(d => setCategories(d.categories || [])).catch(() => {});
  }, []);

  const selectedCat = categories.find(c => c.key === regCat);
  const businesses = selectedCat?.businesses || [];

  function reset() { setErr(""); setInfo(""); }
  function goMode(m) { reset(); setMode(m); }

  const waLink = titiNumber ? `https://wa.me/${titiNumber}?text=Hello` : null;

  // ── Sign in ──────────────────────────────────────────────────────────────
  async function handleLogin(e) {
    e.preventDefault();
    setErr("");
    if (!phone.trim()) { setErr("Enter your phone number."); return; }
    if (!pin.trim())   { setErr("Enter your PIN."); return; }
    try {
      await login(phone.trim(), pin.trim());
      navigate("/home", { replace: true });
    } catch (e) { setErr(e.message); }
  }

  // ── Register ─────────────────────────────────────────────────────────────
  async function handleRegister(e) {
    e.preventDefault();
    setErr("");
    if (!regName.trim())  { setErr("Enter your full name."); return; }
    if (!regPhone.trim()) { setErr("Enter your phone number."); return; }
    if (!regPin.trim() || regPin.trim().length < 4) { setErr("PIN must be at least 4 digits."); return; }
    if (regPin.trim() !== regConfirm.trim()) { setErr("PINs do not match."); return; }
    setBusy(true);
    try {
      const typLabel = businesses.find(b => b.key === regType)?.label || "";
      const data = await apiPost("auth/register", {
        name: regName.trim(),
        phone: regPhone.trim(),
        pin: regPin.trim(),
        email: regEmail.trim() || null,
        newsletter_consent: regNewsletter,
        business_category: regCat || null,
        business_type: regType || null,
        business_type_label: typLabel || null,
      });
      persistSession(data.token, data.user);
      navigate("/home", { replace: true });
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  // ── Request OTP (auto channel: email if set, else WhatsApp) ──────────────
  async function handleRequestOtp(e) {
    e.preventDefault();
    setErr("");
    if (!otpPhone.trim()) { setErr("Enter your phone number."); return; }
    setBusy(true);
    try {
      const res = await apiPost("auth/request-otp", { phone: otpPhone.trim(), channel: "auto" });
      setSelectedChannel(res.channel);
      const dest = res.channel === "email" ? `email (${res.hint})` : `WhatsApp`;
      setInfo(`A 6-digit code was sent to your ${dest}.`);
      goMode("set_pin");
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  // ── Set PIN ───────────────────────────────────────────────────────────────
  async function handleSetPin(e) {
    e.preventDefault();
    setErr("");
    const channelLabel = selectedChannel === "email" ? "your email" : "your WhatsApp";
    if (!otp.trim())    { setErr(`Enter the code from ${channelLabel}.`); return; }
    if (!newPin.trim()) { setErr("Choose a PIN."); return; }
    if (newPin.trim().length < 4) { setErr("PIN must be at least 4 digits."); return; }
    if (newPin.trim() !== confirmPin.trim()) { setErr("PINs do not match."); return; }
    setBusy(true);
    try {
      const data = await apiPost("auth/set-pin", {
        phone: otpPhone.trim(),
        otp: otp.trim(),
        new_pin: newPin.trim(),
      });
      persistSession(data.token, data.user);
      navigate("/home", { replace: true });
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="login-shell">
      <div className="login-card">

        <div className="login-brand">
          <div className="sidebar-mark" style={{ width: 44, height: 44, fontSize: 18 }}>CV</div>
          <div>
            <div className="login-title">CreditVoice</div>
            <div className="login-sub">Business Desk</div>
          </div>
        </div>

        {/* ── Sign In ── */}
        {mode === "login" && (
          <form onSubmit={handleLogin} className="login-form">
            <div className="form-group">
              <label className="form-label">Phone Number</label>
              <input
                type="tel"
                value={phone}
                onChange={e => setPhone(e.target.value)}
                placeholder="e.g. 2348012345678"
                autoComplete="username"
                disabled={authLoading}
              />
              <span className="form-hint">Include country code, no + (234 for Nigeria)</span>
            </div>

            <div className="form-group">
              <label className="form-label">PIN</label>
              <input
                type="password"
                inputMode="numeric"
                value={pin}
                onChange={e => setPin(e.target.value)}
                placeholder="4-digit PIN"
                maxLength={8}
                autoComplete="current-password"
                disabled={authLoading}
              />
            </div>

            {(err || authError) && <div className="login-error">{err || authError}</div>}

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: "100%", justifyContent: "center" }}
              disabled={authLoading}
            >
              {authLoading ? <><Spinner /> Signing in…</> : "Sign In"}
            </button>

            <button type="button" className="login-text-btn" onClick={() => { goMode("request_otp"); setOtpPhone(phone); }}>
              <KeyRound size={13} /> Forgot PIN or never set one?
            </button>

            <div className="login-divider"><span>No account yet?</span></div>

            <button type="button" className="btn btn-secondary" style={{ width: "100%", justifyContent: "center" }} onClick={() => goMode("register")}>
              <UserPlus size={15} /> Create an account
            </button>
          </form>
        )}

        {/* ── Register ── */}
        {mode === "register" && (
          <form onSubmit={handleRegister} className="login-form">
            <button type="button" className="login-back-btn" onClick={() => goMode("login")}>
              <ArrowLeft size={14} /> Back to sign in
            </button>

            <div className="login-section-title">Create Your Account</div>

            <div className="form-group">
              <label className="form-label">Full Name *</label>
              <input value={regName} onChange={e => setRegName(e.target.value)} placeholder="Your name" autoFocus disabled={busy} />
            </div>

            <div className="form-group">
              <label className="form-label">Phone Number *</label>
              <input type="tel" value={regPhone} onChange={e => setRegPhone(e.target.value)} placeholder="e.g. 2348012345678" disabled={busy} />
              <span className="form-hint">Include country code, no +</span>
            </div>

            <div className="form-group">
              <label className="form-label">Email Address</label>
              <input
                type="email"
                value={regEmail}
                onChange={e => setRegEmail(e.target.value)}
                placeholder="your@email.com"
                autoComplete="email"
                disabled={busy}
              />
              <span className="form-hint">Optional — used for PIN recovery and updates</span>
            </div>

            <div className="form-group">
              <label className="form-label">Business Type</label>
              <select value={regCat} onChange={e => { setRegCat(e.target.value); setRegType(""); }} disabled={busy}>
                <option value="">Select category…</option>
                {categories.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
              </select>
            </div>

            {businesses.length > 0 && (
              <div className="form-group">
                <label className="form-label">Business</label>
                <select value={regType} onChange={e => setRegType(e.target.value)} disabled={busy}>
                  <option value="">Select business…</option>
                  {businesses.map(b => <option key={b.key} value={b.key}>{b.label}</option>)}
                </select>
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Set a PIN *</label>
              <input type="password" inputMode="numeric" value={regPin} onChange={e => setRegPin(e.target.value)} placeholder="4 digits minimum" maxLength={8} disabled={busy} />
            </div>

            <div className="form-group">
              <label className="form-label">Confirm PIN *</label>
              <input type="password" inputMode="numeric" value={regConfirm} onChange={e => setRegConfirm(e.target.value)} placeholder="Repeat PIN" maxLength={8} disabled={busy} />
            </div>

            <label className="login-checkbox-row">
              <input
                type="checkbox"
                checked={regNewsletter}
                onChange={e => setRegNewsletter(e.target.checked)}
                disabled={busy}
              />
              <span>
                Send me tips and product updates by email.{" "}
                <span className="login-hint-muted" style={{ display: "inline" }}>Unsubscribe any time.</span>
              </span>
            </label>

            {err && (
              <div className="login-error">
                {err}
                {err.toLowerCase().includes("sign in") && (
                  <button
                    type="button"
                    className="login-text-btn"
                    style={{ marginTop: 8, display: "flex" }}
                    onClick={() => { goMode("login"); setPhone(regPhone); }}
                  >
                    Go to sign in →
                  </button>
                )}
              </div>
            )}

            <button type="submit" className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }} disabled={busy}>
              {busy ? <><Spinner /> Creating account…</> : "Create Account & Sign In"}
            </button>

            {waLink && (
              <p className="login-hint-muted">
                After signing in, link WhatsApp to unlock reminders and voice capture.
              </p>
            )}
          </form>
        )}

        {/* ── Request OTP: enter phone ── */}
        {mode === "request_otp" && (
          <form onSubmit={handleRequestOtp} className="login-form">
            <button type="button" className="login-back-btn" onClick={() => goMode("login")}>
              <ArrowLeft size={14} /> Back to sign in
            </button>

            <div className="login-section-title">Reset Your PIN</div>
            <p className="login-hint-muted">Enter your phone number. We'll send a one-time code to your email or WhatsApp.</p>

            <div className="form-group">
              <label className="form-label">Phone Number</label>
              <input type="tel" value={otpPhone} onChange={e => setOtpPhone(e.target.value)} placeholder="e.g. 2348012345678" autoFocus disabled={busy} />
            </div>

            {err && <div className="login-error">{err}</div>}

            <button type="submit" className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }} disabled={busy}>
              {busy ? <><Spinner /> Sending code…</> : "Send Code"}
            </button>
          </form>
        )}

        {/* ── Set PIN ── */}
        {mode === "set_pin" && (
          <form onSubmit={handleSetPin} className="login-form">
            <button type="button" className="login-back-btn" onClick={() => goMode("request_otp")}>
              <ArrowLeft size={14} /> Resend code
            </button>

            <div className="login-section-title">Enter Code & Set PIN</div>
            {info && <div className="login-info">{info}</div>}

            <div className="form-group">
              <label className="form-label">Verification Code</label>
              <input
                type="text"
                inputMode="numeric"
                value={otp}
                onChange={e => setOtp(e.target.value)}
                placeholder="6-digit code"
                maxLength={6}
                autoFocus
                disabled={busy}
              />
              <span className="form-hint">
                {selectedChannel === "email" ? "Check your email inbox (and spam folder)" : "Check your WhatsApp messages"}
              </span>
            </div>

            <div className="form-group">
              <label className="form-label">New PIN</label>
              <input type="password" inputMode="numeric" value={newPin} onChange={e => setNewPin(e.target.value)} placeholder="Choose a PIN" maxLength={8} disabled={busy} />
            </div>

            <div className="form-group">
              <label className="form-label">Confirm PIN</label>
              <input type="password" inputMode="numeric" value={confirmPin} onChange={e => setConfirmPin(e.target.value)} placeholder="Repeat PIN" maxLength={8} disabled={busy} />
            </div>

            {err && <div className="login-error">{err}</div>}

            <button type="submit" className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }} disabled={busy}>
              {busy ? <><Spinner /> Saving…</> : "Set PIN & Sign In"}
            </button>
          </form>
        )}

      </div>
    </div>
  );
}
