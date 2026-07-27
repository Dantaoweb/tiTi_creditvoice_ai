import { useEffect, useState } from "react";
import { MapPin, Plus, Star, Trash2, Lock } from "lucide-react";
import { apiFetch, apiPost, apiPut } from "../lib/api";
import { useToast } from "../components/Toast";
import { usePlan } from "../lib/usePlan";

export default function Branches() {
  const { allows } = usePlan();
  const canUseBranches = allows("BRANCHES");

  const [branches, setBranches] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [name, setName]         = useState("");
  const [addr, setAddr]         = useState("");
  const [saving, setSaving]     = useState(false);
  const [editId, setEditId]     = useState(null);
  const [editName, setEditName] = useState("");
  const [editAddr, setEditAddr] = useState("");
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
      await apiPost("branches", { name: name.trim(), address: addr.trim() || null });
      setName(""); setAddr("");
      await load();
      toast("Branch added.", "success");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(b) { setEditId(b.id); setEditName(b.name); setEditAddr(b.address || ""); }

  async function handleUpdate(id) {
    if (!editName.trim()) return;
    try {
      await apiPut(`branches/${id}`, { name: editName.trim(), address: editAddr.trim() || null });
      setEditId(null);
      await load();
      toast("Branch updated.", "success");
    } catch (e) {
      toast(e.message, "error");
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

        <form className="branches-add-row" onSubmit={handleAdd} style={{ flexWrap: "wrap" }}>
          <input
            className="branches-add-input"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Branch name (e.g. Ikeja Store)"
            maxLength={60}
          />
          <input
            className="branches-add-input"
            value={addr}
            onChange={e => setAddr(e.target.value)}
            placeholder="Branch address (optional) — shown on receipts"
            maxLength={300}
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
              <li key={b.id} className={`branch-item${b.is_default ? " branch-item--default" : ""}`}
                  style={{ flexWrap: "wrap" }}>
                <MapPin size={15} className="branch-item-icon" />
                {editId === b.id ? (
                  <div style={{ display: "flex", gap: 6, flex: 1, flexWrap: "wrap" }}>
                    <input value={editName} onChange={e => setEditName(e.target.value)} maxLength={60}
                      placeholder="Name" style={{ flex: "1 1 120px" }} />
                    <input value={editAddr} onChange={e => setEditAddr(e.target.value)} maxLength={300}
                      placeholder="Address" style={{ flex: "2 1 180px" }} />
                    <button className="btn btn-primary btn-sm" onClick={() => handleUpdate(b.id)}>Save</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditId(null)}>Cancel</button>
                  </div>
                ) : (
                  <>
                    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
                      <span className="branch-item-name">{b.name}</span>
                      {b.address && <span className="td-muted" style={{ fontSize: 12 }}>{b.address}</span>}
                    </div>
                    {b.is_default && (
                      <span className="branch-default-chip"><Star size={11} /> Default</span>
                    )}
                    <div className="branch-item-actions">
                      {!b.is_default && (
                        <button className="btn btn-ghost btn-sm" onClick={() => handleSetDefault(b.id)} title="Set as default">
                          <Star size={13} /> Set default
                        </button>
                      )}
                      <button className="btn btn-ghost btn-sm" onClick={() => startEdit(b)} title="Edit branch">Edit</button>
                      <button className="btn btn-ghost btn-sm branch-delete-btn" onClick={() => handleDelete(b.id)} title="Delete branch">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
