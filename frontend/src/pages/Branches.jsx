import { useEffect, useState } from "react";
import { MapPin, Plus, Star, Trash2, Lock } from "lucide-react";
import { apiFetch, apiPost } from "../lib/api";
import { useToast } from "../components/Toast";
import { usePlan } from "../lib/usePlan";

export default function Branches() {
  const { allows } = usePlan();
  const canUseBranches = allows("BRANCHES");

  const [branches, setBranches] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [name, setName]         = useState("");
  const [saving, setSaving]     = useState(false);
  const toast = useToast();

  if (!canUseBranches) {
    return (
      <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
        <Lock size={36} color="#a78bfa" style={{ margin: "0 auto 16px" }} />
        <div style={{ fontSize: 18, fontWeight: 700, color: "#fff", marginBottom: 8 }}>
          Branches requires Pro
        </div>
        <div style={{ color: "rgba(255,255,255,0.55)", fontSize: 14, maxWidth: 420, margin: "0 auto 20px" }}>
          Tag transactions to multiple shop locations and see performance per branch.
          Available on the Pro plan.
        </div>
        <button className="btn btn-primary" onClick={() => window.location.href = "/app/upgrade"}>
          Upgrade to Pro
        </button>
      </div>
    );
  }

  async function load() {
    setLoading(true);
    try {
      const d = await apiFetch("branches");
      setBranches(d.branches || []);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      await apiPost("branches", { name: name.trim() });
      setName("");
      await load();
      toast("Branch added.", "success");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id) {
    if (!confirm("Delete this branch? Past transactions will keep their branch tag.")) return;
    try {
      await apiFetch(`branches/${id}`, {}, { method: "DELETE" });
      await load();
      toast("Branch deleted.", "success");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function handleSetDefault(id) {
    try {
      await apiPost(`branches/${id}/default`, {});
      await load();
      toast("Default branch updated.", "success");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  return (
    <div className="branches-page">
      <div className="card">
        <div className="card-header">
          <span className="card-title">
            <MapPin size={16} style={{ marginRight: 6 }} />
            Branch / Location Tags
          </span>
        </div>
        <div className="branches-intro">
          Add named locations for your business (e.g. "Main Shop", "Oshodi Branch"). Each transaction
          recorded from the web or WhatsApp will be tagged to the default branch automatically.
          You can change which branch a transaction belongs to when recording it.
        </div>

        <form className="branches-add-row" onSubmit={handleAdd}>
          <input
            className="branches-add-input"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Branch name (e.g. Ikeja Store)"
            maxLength={60}
          />
          <button className="btn btn-primary" type="submit" disabled={saving || !name.trim()}>
            <Plus size={14} />
            {saving ? "Adding…" : "Add Branch"}
          </button>
        </form>

        {loading ? (
          <div className="branches-empty">Loading…</div>
        ) : branches.length === 0 ? (
          <div className="branches-empty">No branches yet. Add one above to start tagging transactions.</div>
        ) : (
          <ul className="branches-list">
            {branches.map(b => (
              <li key={b.id} className={`branch-item${b.is_default ? " branch-item--default" : ""}`}>
                <MapPin size={15} className="branch-item-icon" />
                <span className="branch-item-name">{b.name}</span>
                {b.is_default && (
                  <span className="branch-default-chip">
                    <Star size={11} /> Default
                  </span>
                )}
                <div className="branch-item-actions">
                  {!b.is_default && (
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => handleSetDefault(b.id)}
                      title="Set as default"
                    >
                      <Star size={13} /> Set default
                    </button>
                  )}
                  <button
                    className="btn btn-ghost btn-sm branch-delete-btn"
                    onClick={() => handleDelete(b.id)}
                    title="Delete branch"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
