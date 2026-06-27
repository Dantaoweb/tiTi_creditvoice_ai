import { useState, useEffect } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { ArrowLeft, KeyRound, UserPlus, Loader2, AlertTriangle } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { apiFetch, apiPost } from "../lib/api";

const PARTIAL_SUPPORT = {
  hotel_guest_house: { works: "Track guest bills, payments, and outstanding balances", missing: "Room booking, availability management, and check-in/check-out" },
  property_manager:  { works: "Track rent payments and outstanding balances per tenant", missing: "Property listings, lease contracts, and unit management" },
  estate_agent:      { works: "Track client payments and outstanding balances", missing: "Property listings, commissions workflow, and deal tracking" },
  clinic:            { works: "Track patient bills, consultation fees, and outstanding balances", missing: "Patient records, prescriptions, and clinical management" },
  dental_clinic:     { works: "Track patient bills and outstanding fee balances", missing: "Patient records, treatment history, and clinical notes" },
  eye_clinic:        { works: "Track patient bills and outstanding fee balances", missing: "Patient records, prescription notes, and frame/lens stock by patient" },
  laboratory:        { works: "Track patient bills and outstanding balances", missing: "Test result records, sample tracking, and patient referrals" },
};

function Spinner() {
  return <Loader2 size={15} className="spin" />;
}

const COUNTRIES = [
  { code: "234", flag: "🇳🇬", label: "Nigeria (+234)" },
];

function PhoneInput({ value, onChange, disabled, autoFocus }) {
  // value/onChange use the full stored format: "2348012345678"
  const prefix = "234";
  const local = value.startsWith(prefix) ? value.slice(prefix.length) : value;

  function handleLocal(e) {
    let raw = e.target.value.replace(/\D/g, "");
    if (raw.startsWith("0")) raw = raw.slice(1); // strip leading 0
    onChange(prefix + raw);
  }

  return (
    <div className="phone-input-row">
      <select className="phone-country-select" disabled={disabled} value={prefix} onChange={() => {}}>
        {COUNTRIES.map(c => (
          <option key={c.code} value={c.code}>{c.flag} +{c.code}</option>
        ))}
      </select>
      <input
        type="tel"
        className="phone-local-input"
        value={local}
        onChange={handleLocal}
        placeholder="8012345678"
        maxLength={10}
        disabled={disabled}
        autoFocus={autoFocus}
      />
    </div>
  );
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
  const [selectedChannel, setSelectedChannel] = useState("whatsapp"); // "email" | "whatsapp"
  const [otpEmailInput, setOtpEmailInput] = useState("");   // email entered if not on account
  const [otpEmailHint, setOtpEmailHint] = useState(null);  // masked email from server
  const [otpHasEmail, setOtpHasEmail] = useState(false);
  const [otp, setOtp] = useState("");
  const [newPin, setNewPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");

  // Accept invite fields
  const [invitePhone, setInvitePhone] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [acceptedName, setAcceptedName] = useState("");

  // Referral code (from URL ?ref= or manual entry)
  const refFromUrl = params.get("ref") || "";
  const [refCode, setRefCode] = useState(refFromUrl.toUpperCase());

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

  const waLink = titiNumber ? `https://wa.me/${titiNumber}?text=${encodeURIComponent("Hello")}` : null;

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
    if (!regName.trim())  { setErr("Enter your business name."); return; }
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
        ref_code: refCode.trim() || null,
      });
      persistSession(data.user);
      setMode("registered");
      setTimeout(() => navigate("/home", { replace: true }), 3000);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  // ── Fetch channel info when phone is filled ──────────────────────────────
  async function fetchOtpChannels(phone) {
    if (!phone || phone.length < 10) return;
    try {
      const res = await apiFetch("auth/otp-channels", { phone });
      setOtpHasEmail(!!res.has_email);
      setOtpEmailHint(res.email_hint || null);
    } catch { /* user may not exist yet — ignore */ }
  }

  // ── Request OTP ───────────────────────────────────────────────────────────
  async function handleRequestOtp(e) {
    e.preventDefault();
    setErr("");
    if (!otpPhone.trim()) { setErr("Enter your phone number."); return; }
    if (selectedChannel === "email" && !otpHasEmail && !otpEmailInput.trim()) {
      setErr("Enter your email address to receive the code."); return;
    }
    setBusy(true);
    try {
      const body = { phone: otpPhone.trim(), channel: selectedChannel };
      if (selectedChannel === "email" && !otpHasEmail && otpEmailInput.trim()) {
        body.email = otpEmailInput.trim();
      }
      const res = await apiPost("auth/request-otp", body);
      setSelectedChannel(res.channel);
      const channels = res.channels || [res.channel];
      const dest = channels.includes("email") && channels.includes("whatsapp")
        ? `email (${res.hint}) and WhatsApp`
        : channels.includes("email") ? `email (${res.hint})` : `WhatsApp (+${otpPhone.trim()})`;
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
      persistSession(data.user);
      navigate("/home", { replace: true });
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  // ── Accept staff invitation ───────────────────────────────────────────
  async function handleAcceptInvite(e) {
    e.preventDefault();
    setErr("");
    if (!invitePhone.trim()) { setErr("Enter your phone number."); return; }
    if (!inviteCode.trim())  { setErr("Enter the accept code from your employer."); return; }
    setBusy(true);
    try {
      const data = await apiPost("staff/accept", { phone: invitePhone.trim(), code: inviteCode.trim() });
      setAcceptedName(data.name || "");
      if (data.has_pin) {
        setInfo(`Welcome, ${(data.name || "").split(" ")[0] || "there"}! You can now sign in with your phone and PIN.`);
        goMode("login");
        setPhone(invitePhone.trim());
      } else {
        setInfo(`Invitation accepted! Hi ${(data.name || "").split(" ")[0] || "there"} — set a PIN to finish signing in.`);
        setOtpPhone(invitePhone.trim());
        goMode("request_otp");
      }
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

        {/* ── Registration success ── */}
        {mode === "registered" && (
          <div className="login-form" style={{ textAlign: "center", padding: "2rem 0" }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🎉</div>
            <div className="login-section-title" style={{ marginBottom: 8 }}>Welcome to CreditVoice!</div>
            <p style={{ color: "var(--text-secondary)", marginBottom: 4 }}>Your account has been created successfully.</p>
            <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>Taking you to your dashboard…</p>
          </div>
        )}

        {/* ── Sign In ── */}
        {mode === "login" && (
          <form onSubmit={handleLogin} className="login-form">
            <div className="form-group">
              <label className="form-label">Phone Number</label>
              <PhoneInput value={phone} onChange={setPhone} disabled={authLoading} />
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

            <button type="button" className="login-text-btn" onClick={() => goMode("accept_invite")}>
              Accept a staff invitation
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
              <label className="form-label">Business Name *</label>
              <input value={regName} onChange={e => setRegName(e.target.value)} placeholder="e.g. Emeka Stores, Grace Pharmacy" autoFocus disabled={busy} />
            </div>

            <div className="form-group">
              <label className="form-label">Phone Number *</label>
              <PhoneInput value={regPhone} onChange={setRegPhone} disabled={busy} />
            </div>

            <div className="form-group">
              <label className="form-label">
                Email Address <span style={{ color: "#d97706", fontSize: 11, fontWeight: 600 }}>Recommended</span>
              </label>
              <input
                type="email"
                value={regEmail}
                onChange={e => setRegEmail(e.target.value)}
                placeholder="your@email.com"
                autoComplete="email"
                disabled={busy}
              />
              <span className="form-hint">
                {regEmail.trim()
                  ? "✓ If you forget your PIN, we'll send a reset code to this email."
                  : "Without an email, you can only recover your account via WhatsApp — adding one is safer."}
              </span>
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
                {regType && PARTIAL_SUPPORT[regType] && (
                  <div className="partial-support-note">
                    <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 2 }} />
                    <div>
                      <strong>Limited fit</strong>
                      <span className="partial-support-works">✅ {PARTIAL_SUPPORT[regType].works}</span>
                      <span className="partial-support-missing">Not yet: {PARTIAL_SUPPORT[regType].missing}</span>
                    </div>
                  </div>
                )}
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

            <div className="form-group">
              <label className="form-label">
                Referral Code <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(optional)</span>
              </label>
              <input
                value={refCode}
                onChange={e => setRefCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                placeholder="e.g. DANSHOP"
                maxLength={20}
                style={{ fontFamily: "monospace", letterSpacing: 1 }}
                disabled={busy || !!refFromUrl}
              />
              {refFromUrl && (
                <span className="form-hint" style={{ color: "#a78bfa" }}>
                  ✓ Referral code applied — you'll get 14 days on GO plan free.
                </span>
              )}
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
            <p className="login-hint-muted">Enter your phone number and choose how to receive your code.</p>

            <div className="form-group">
              <label className="form-label">Phone Number</label>
              <PhoneInput
                value={otpPhone}
                onChange={v => { setOtpPhone(v); fetchOtpChannels(v); setOtpHasEmail(false); setOtpEmailHint(null); }}
                disabled={busy}
                autoFocus
              />
            </div>

            <div className="form-group">
              <label className="form-label">Send code via</label>
              <div style={{ display: "flex", gap: 10 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 14 }}>
                  <input type="radio" name="otp_channel" value="whatsapp"
                    checked={selectedChannel === "whatsapp"}
                    onChange={() => setSelectedChannel("whatsapp")} />
                  WhatsApp
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 14 }}>
                  <input type="radio" name="otp_channel" value="email"
                    checked={selectedChannel === "email"}
                    onChange={() => setSelectedChannel("email")} />
                  Email {otpEmailHint ? `(${otpEmailHint})` : ""}
                </label>
              </div>
            </div>

            {selectedChannel === "email" && !otpHasEmail && (
              <div className="form-group">
                <label className="form-label">Your Email Address</label>
                <input
                  type="email"
                  value={otpEmailInput}
                  onChange={e => setOtpEmailInput(e.target.value)}
                  placeholder="e.g. you@gmail.com"
                  disabled={busy}
                />
                <span className="form-hint">We'll save this to your account for future use.</span>
              </div>
            )}

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

        {/* ── Accept staff invitation ── */}
        {mode === "accept_invite" && (
          <form onSubmit={handleAcceptInvite} className="login-form">
            <button type="button" className="login-back-btn" onClick={() => goMode("login")}>
              <ArrowLeft size={14} /> Back to sign in
            </button>

            <div className="login-section-title">Accept Staff Invitation</div>
            <p className="login-hint-muted">Enter your phone number and the 6-digit code your employer shared with you.</p>

            <div className="form-group">
              <label className="form-label">Your Phone Number</label>
              <PhoneInput value={invitePhone} onChange={setInvitePhone} disabled={busy} autoFocus />
            </div>

            <div className="form-group">
              <label className="form-label">Accept Code</label>
              <input
                type="text"
                inputMode="numeric"
                value={inviteCode}
                onChange={e => setInviteCode(e.target.value)}
                placeholder="6-digit code from your employer"
                maxLength={8}
                disabled={busy}
              />
            </div>

            {err && <div className="login-error">{err}</div>}

            <button type="submit" className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }} disabled={busy}>
              {busy ? <><Spinner /> Checking…</> : "Accept Invitation"}
            </button>
          </form>
        )}

      </div>

      <div className="login-footer">
        <p>
          By signing up you agree to our{" "}
          <Link to="/terms">Terms of Service</Link>{" "}and{" "}
          <Link to="/privacy">Privacy Policy</Link>
        </p>
        <p>© {new Date().getFullYear()} CreditVoice Technology Services</p>
      </div>
    </div>
  );
}
