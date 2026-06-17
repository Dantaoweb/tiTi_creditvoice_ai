import { useEffect, useState } from "react";
import { Bell, Bot, ChevronRight, Clock, Zap } from "lucide-react";
import { useApp } from "../context/AppContext";
import { apiFetch, apiPost } from "../lib/api";
import { Link } from "react-router-dom";

// ── Toggle row ────────────────────────────────────────────────────────────────
function ToggleRow({ label, description, checked, onChange, disabled, disabledNote }) {
  return (
    <div className={`auto-toggle-row ${disabled ? "auto-toggle-row--disabled" : ""}`}>
      <div className="auto-toggle-info">
        <div className="auto-toggle-label">{label}</div>
        {description && <div className="auto-toggle-desc">{description}</div>}
        {disabled && disabledNote && <div className="auto-toggle-locked">{disabledNote}</div>}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        className={`auto-switch ${checked ? "auto-switch--on" : ""} ${disabled ? "auto-switch--locked" : ""}`}
        onClick={() => !disabled && onChange(!checked)}
      >
        <span className="auto-switch-thumb" />
      </button>
    </div>
  );
}

// ── Section card ──────────────────────────────────────────────────────────────
function Section({ icon: Icon, title, children }) {
  return (
    <div className="card auto-section">
      <div className="card-header">
        <span className="card-title auto-section-title">
          <Icon size={16} className="auto-section-icon" />
          {title}
        </span>
      </div>
      <div className="auto-section-body">{children}</div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Automation() {
  const { ownerPhone } = useApp();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  // local editable state
  const [reminder, setReminder] = useState({
    preview_enabled: true,
    auto_send_enabled: false,
    reminder_time: "08:00",
  });
  const [bot, setBot] = useState({
    bot_enabled: false,
    auto_reply_enabled: true,
    auto_order_enabled: false,
    allow_part_payment: true,
    payment_modes: "",
    delivery_note: "",
    pickup_address: "",
  });
  const [isPro, setIsPro] = useState(false);

  useEffect(() => {
    if (!ownerPhone) return;
    setLoading(true);
    Promise.all([
      apiFetch("automation", { owner_phone: ownerPhone }),
      apiFetch("auth/config"),
    ])
      .then(([d, cfg]) => {
        setData(d);
        setReminder({
          preview_enabled: d.reminder.preview_enabled,
          auto_send_enabled: d.reminder.auto_send_enabled,
          reminder_time: d.reminder.reminder_time,
        });
        if (d.bot) setBot(d.bot);
        setIsPro(cfg.plan === "PRO" || cfg.plan === "ENTERPRISE");
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [ownerPhone]);

  function setR(k, v) { setReminder(p => ({ ...p, [k]: v })); }
  function setB(k, v) { setBot(p => ({ ...p, [k]: v })); }

  async function save() {
    setSaving(true); setSaved(false);
    try {
      await apiPost("automation", {
        owner_phone: ownerPhone,
        reminder_preview_enabled: reminder.preview_enabled,
        reminder_auto_send_enabled: reminder.auto_send_enabled,
        reminder_time: reminder.reminder_time,
        ...(data?.has_bot ? {
          bot_enabled: bot.bot_enabled,
          auto_reply_enabled: bot.auto_reply_enabled,
          auto_order_enabled: bot.auto_order_enabled,
          allow_part_payment: bot.allow_part_payment,
          payment_modes: bot.payment_modes,
          delivery_note: bot.delivery_note,
          pickup_address: bot.pickup_address,
        } : {}),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="auto-loading">Loading automation settings…</div>;
  if (error) return <div className="auto-error">{error}</div>;

  return (
    <div className="auto-page">

      <div className="auto-intro">
        <Zap size={18} className="auto-intro-icon" />
        <div>
          <strong>Automation</strong> saves you time by sending reminders and answering customers automatically.
          Changes here apply immediately — no WhatsApp command needed.
        </div>
      </div>

      {/* ── Reminder automation ─────────────────────────────────────── */}
      <Section icon={Bell} title="Payment Reminders">
        <p className="auto-section-desc">
          tiTi can automatically remind customers who owe you money. You control when it runs and whether
          you review the messages first.
        </p>

        <ToggleRow
          label="Preview before sending"
          description="You approve each reminder message before it goes out. Recommended."
          checked={reminder.preview_enabled}
          onChange={v => setR("preview_enabled", v)}
        />

        <ToggleRow
          label="Auto-send reminders"
          description="Send reminders automatically at the scheduled time without your review."
          checked={reminder.auto_send_enabled}
          onChange={v => setR("auto_send_enabled", v)}
          disabled={!isPro}
          disabledNote="Upgrade to PRO to enable auto-send."
        />

        <div className="auto-field-row">
          <label className="auto-field-label">
            <Clock size={13} /> Reminder time
          </label>
          <input
            type="time"
            className="auto-time-input"
            value={reminder.reminder_time}
            onChange={e => setR("reminder_time", e.target.value)}
          />
          <span className="auto-field-hint">Time of day reminders go out (your local time)</span>
        </div>

        <div className="auto-queue-link">
          <Link to="/reminders" className="btn btn-ghost btn-sm">
            View reminder queue <ChevronRight size={13} />
          </Link>
        </div>

        <div className="auto-whatsapp-tip">
          You can also manage reminders via WhatsApp — send <code>reminder queue</code> to see
          pending reminders, or <code>run reminder automation</code> to generate today's batch.
        </div>
      </Section>

      {/* ── Customer bot (retail/food/salon/pharmacy only) ───────────── */}
      {data?.has_bot && (
        <Section icon={Bot} title="Customer Bot">
          <p className="auto-section-desc">
            The customer bot answers price and availability questions from your customers on WhatsApp
            automatically — so you don't have to reply manually to every inquiry.
          </p>

          <ToggleRow
            label="Bot active"
            description="When on, the bot handles incoming customer messages from unknown numbers."
            checked={bot.bot_enabled}
            onChange={v => setB("bot_enabled", v)}
          />

          <ToggleRow
            label="Auto-reply"
            description="Bot answers product/price questions automatically. If off, all messages go to you."
            checked={bot.auto_reply_enabled}
            onChange={v => setB("auto_reply_enabled", v)}
          />

          <ToggleRow
            label="Auto-create orders"
            description="Bot creates an order record automatically when a customer confirms they want to buy."
            checked={bot.auto_order_enabled}
            onChange={v => setB("auto_order_enabled", v)}
          />

          <ToggleRow
            label="Allow part-payment"
            description="Bot accepts deposit/part-payment from customers (you confirm receipt separately)."
            checked={bot.allow_part_payment}
            onChange={v => setB("allow_part_payment", v)}
          />

          <div className="auto-field-group">
            <div className="auto-field">
              <label className="auto-field-label">Payment instructions</label>
              <textarea
                className="auto-textarea"
                rows={2}
                placeholder="e.g. Transfer to GTBank 0123456789 (Adebayo Stores)"
                value={bot.payment_modes}
                onChange={e => setB("payment_modes", e.target.value)}
              />
              <span className="auto-field-hint">Shown to customers when they ask how to pay</span>
            </div>

            <div className="auto-field">
              <label className="auto-field-label">Delivery note</label>
              <textarea
                className="auto-textarea"
                rows={2}
                placeholder="e.g. Delivery within Lagos only. ₦1,000 delivery fee."
                value={bot.delivery_note}
                onChange={e => setB("delivery_note", e.target.value)}
              />
              <span className="auto-field-hint">Shown to customers asking about delivery</span>
            </div>

            <div className="auto-field">
              <label className="auto-field-label">Pickup address</label>
              <input
                className="auto-input"
                placeholder="e.g. 14 Broad Street, Lagos Island"
                value={bot.pickup_address}
                onChange={e => setB("pickup_address", e.target.value)}
              />
              <span className="auto-field-hint">For customers who want to collect in person</span>
            </div>
          </div>

          <div className="auto-whatsapp-tip">
            WhatsApp commands: <code>bot on</code> / <code>bot off</code> · <code>auto reply on/off</code>
            · <code>set payment [instructions]</code> · <code>set delivery [note]</code>
          </div>
        </Section>
      )}

      <div className="auto-save-bar">
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        {saved && <span className="auto-saved-msg">Saved ✓</span>}
      </div>
    </div>
  );
}
