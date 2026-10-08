import { useEffect, useState } from "react";
import { apiFetch, apiPost, apiDelete } from "../lib/api";
import { useAuth } from "../context/AuthContext";

/**
 * A business writes its own review of CreditVoice.
 *
 * The reason anyone bothers: a featured review carries their business name, town
 * and phone number on the public homepage — a free advert. That is also why the
 * consent box is not optional, and why an edit goes back for approval.
 */
export default function MyReview() {
  const { user } = useAuth();
  const [review, setReview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  function blank() {
    return {
      business_name: user?.name || "",
      business_type: user?.business_type_label || "",
      location: "",
      quote: "",
      contact_phone: user?.phone || "",
      contact_link: "",
      consent_public: false,
    };
  }

  useEffect(() => {
    apiFetch("my-review")
      .then(d => setReview(d.review || null))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function startEditing() {
    setMsg(""); setErr("");
    setForm(review ? { ...review, consent_public: false } : blank());
    setOpen(true);
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true); setErr(""); setMsg("");
    try {
      const d = await apiPost("my-review", form);
      setReview(d.review);
      setOpen(false);
      setMsg(d.message || "Thank you.");
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  }

  async function withdraw() {
    if (!window.confirm("Remove your review? It also comes off the homepage.")) return;
    try { await apiDelete("my-review"); setReview(null); setMsg("Your review was removed."); }
    catch (e2) { setErr(e2.message); }
  }

  if (loading) return null;

  const status = review?.status;
  const statusLine =
    !review ? null
      : review.is_featured ? ["badge-green", "Live on our homepage"]
        : status === "APPROVED" ? ["badge-blue", "Approved — waiting for a slot on the homepage"]
          : status === "REJECTED" ? ["badge-rose", "Not published"]
            : ["badge-amber", "Waiting for review"];

  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <div className="card-header">
        <span className="card-title">Your review — free advert</span>
        {statusLine && <span className={`badge ${statusLine[0]}`}>{statusLine[1]}</span>}
      </div>

      <div className="card-body" style={{ display: "grid", gap: 12 }}>
        <div className="text-subtle text-sm">
          Tell other business owners what CreditVoice does for you. If we feature it on
          our <a href="/" target="_blank" rel="noopener">homepage</a>, your business name,
          town and phone number go with it — so customers looking at us can find you too.
        </div>

        {review && !open && (
          <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
            <div style={{ fontStyle: "italic" }}>“{review.quote}”</div>
            <div className="text-subtle text-sm" style={{ marginTop: 6 }}>
              {review.business_name}
              {[review.business_type, review.location].filter(Boolean).length
                ? ` · ${[review.business_type, review.location].filter(Boolean).join(" · ")}`
                : ""}
            </div>
            {review.contact_phone && (
              <div className="text-subtle text-sm">Contact shown: {review.contact_phone}</div>
            )}
            {review.status === "REJECTED" && (
              <div className="text-sm" style={{ marginTop: 8, color: "var(--rose)" }}>
                {review.rejection_reason ? `Why: ${review.rejection_reason}. ` : ""}
                Change it and send it again to be reconsidered.
              </div>
            )}
          </div>
        )}

        {msg && <div style={{ color: "#16a34a", fontSize: 13 }}>{msg}</div>}
        {err && !open && <div className="login-error">{err}</div>}

        {open && (
          <form onSubmit={save} style={{ display: "grid", gap: 12 }}>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">Business name, as you want it shown *</label>
              <input value={form.business_name} disabled={busy}
                onChange={e => set("business_name", e.target.value)} />
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <div className="form-group" style={{ margin: 0, flex: "1 1 180px" }}>
                <label className="form-label">What you do</label>
                <input value={form.business_type || ""} disabled={busy}
                  placeholder="e.g. Provisions shop" onChange={e => set("business_type", e.target.value)} />
              </div>
              <div className="form-group" style={{ margin: 0, flex: "1 1 180px" }}>
                <label className="form-label">Town / state</label>
                <input value={form.location || ""} disabled={busy}
                  placeholder="e.g. Osogbo, Osun" onChange={e => set("location", e.target.value)} />
              </div>
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">Your words *</label>
              <textarea rows={3} maxLength={600} value={form.quote} disabled={busy}
                placeholder="e.g. I now know who owes me without checking my book."
                onChange={e => set("quote", e.target.value)} style={{ resize: "vertical" }} />
              <span className="form-hint">{(form.quote || "").length}/600</span>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <div className="form-group" style={{ margin: 0, flex: "1 1 180px" }}>
                <label className="form-label">Phone to show</label>
                <input value={form.contact_phone || ""} disabled={busy}
                  onChange={e => set("contact_phone", e.target.value)} />
              </div>
              <div className="form-group" style={{ margin: 0, flex: "1 1 180px" }}>
                <label className="form-label">Your page or website</label>
                <input value={form.contact_link || ""} disabled={busy}
                  placeholder="https://…" onChange={e => set("contact_link", e.target.value)} />
              </div>
            </div>

            {/* The permission to publish someone's name and phone number is the
                most important thing on this form, so it is the most visible —
                a tick box the size of body text was being missed entirely, and
                the send button looked broken for no stated reason. */}
            <label className={`consent-box${form.consent_public ? " consent-box--on" : ""}`}>
              <input type="checkbox" checked={!!form.consent_public} disabled={busy}
                onChange={e => set("consent_public", e.target.checked)} />
              <span>
                <strong>Yes, show my business publicly</strong>
                <span className="consent-box__detail">
                  My business name, town, words and the contact above can appear on the
                  CreditVoice homepage. I can remove it any time.
                </span>
              </span>
            </label>

            {err && <div className="login-error">{err}</div>}

            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button type="submit" className="btn btn-primary"
                disabled={busy || !form.consent_public || !form.quote.trim() || !form.business_name.trim()}>
                {busy ? "Sending…" : review ? "Send the change" : "Send my review"}
              </button>
              {!form.consent_public && (
                <span className="text-subtle text-sm">
                  Tick the box above to send it.
                </span>
              )}
              <button type="button" className="btn btn-ghost" disabled={busy}
                onClick={() => { setOpen(false); setErr(""); }}>Cancel</button>
            </div>
            {review && (
              <span className="form-hint">
                Changing it means an admin reads it again before it goes back up.
              </span>
            )}
          </form>
        )}

        {!open && (
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" onClick={startEditing}>
              {review ? "Edit my review" : "Write a review"}
            </button>
            {review && (
              <button className="btn btn-ghost text-rose" onClick={withdraw}>Remove</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
