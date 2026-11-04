"""
Production — for businesses that make what they sell (bakery, food, blocks,
furniture, tailoring…).

A recipe says what one batch of a product uses: 1 bag of flour + 2 kg sugar +
0.5 kg yeast → 80 loaves, plus other costs per batch that aren't stock (gas,
labour). Recording a production run ("baked 160 loaves") puts the loaves into
stock and takes the flour, sugar and yeast out — no adjusting each one by hand —
and works out what one loaf really cost to make.

The product's cost price becomes the average of what's in stock and what was
just made, so profit on every sale uses the real cost.

Using more than is in stock is refused unless the person says to record it
anyway (they made it, so the materials were there — the purchases weren't
recorded). Then the material goes to 0 and the run notes the shortfall.
"""
import json
from datetime import datetime, timedelta

from models import InventoryItem, InventoryMovement, ProductionRun, Recipe, RecipeLine, StockBatch, utcnow

# Shown in the menu automatically for these; anyone else turns it on in Settings
PRODUCER_TYPES = ("bakery", "food_vendor", "catering", "block_making", "carpentry_furniture",
                  "welding_fabrication", "tailor_fashion")


class ProductionError(ValueError):
    pass


def _num(q):
    q = round(float(q or 0), 3)
    return int(q) if q.is_integer() else q


def _item(db, owner_phone, item_id, branch_id=None):
    it = db.query(InventoryItem).filter(InventoryItem.id == item_id, InventoryItem.owner_phone == owner_phone,
                                        InventoryItem.is_available.isnot(False)).first()
    if not it:
        raise ProductionError("That product isn't in your stock.")
    if branch_id is not None and it.branch_id not in (None, branch_id):
        raise ProductionError(f"{it.name.title()} belongs to another branch.")
    return it


def _qty(v, what="quantity"):
    try:
        q = float(v)
    except (TypeError, ValueError):
        raise ProductionError(f"Enter the {what} as a number.")
    if not 0 < q <= 10_000_000:
        raise ProductionError(f"Enter a {what} above 0.")
    return q


# ── Recipes ─────────────────────────────────────────────────────────────────

def get_recipe(db, owner_phone, product_id):
    return db.query(Recipe).filter(Recipe.owner_phone == owner_phone, Recipe.product_id == product_id).first()


def recipe_dict(db, r):
    if not r:
        return None
    lines = db.query(RecipeLine).filter(RecipeLine.recipe_id == r.id).order_by(RecipeLine.id).all()
    items = {i.id: i for i in db.query(InventoryItem).filter(
        InventoryItem.id.in_([l.item_id for l in lines] or [0])).all()}
    return {
        "id": r.id, "product_id": r.product_id, "yield_qty": _num(r.yield_qty), "extra_cost": r.extra_cost or 0,
        "note": r.note,
        "lines": [{"item_id": l.item_id, "name": (items[l.item_id].name or "").title() if l.item_id in items else "?",
                   "unit": items[l.item_id].unit if l.item_id in items else None, "qty": _num(l.qty)}
                  for l in lines],
    }


def save_recipe(db, owner_phone, product_id, yield_qty, lines, extra_cost=0, note=None, branch_id=None):
    product = _item(db, owner_phone, product_id, branch_id)
    yq = _qty(yield_qty, "number one batch makes")
    try:
        extra = int(extra_cost or 0)
    except (TypeError, ValueError):
        raise ProductionError("Enter other costs as an amount, e.g. 5000.")
    if extra < 0:
        raise ProductionError("Other costs can't be negative.")
    clean, seen = [], set()
    for l in lines or []:
        iid = int(l.get("item_id") or 0)
        if not iid:
            continue
        if iid == product.id:
            raise ProductionError(f"{product.name.title()} can't be used to make itself.")
        if iid in seen:
            raise ProductionError("Each material once, please — add the amounts together.")
        mat = _item(db, owner_phone, iid, branch_id)
        clean.append((mat.id, _qty(l.get("qty"), f"amount of {mat.name}")))
        seen.add(iid)
    if not clean:
        raise ProductionError("Add at least one material the product is made from.")
    r = get_recipe(db, owner_phone, product.id)
    if not r:
        r = Recipe(owner_phone=owner_phone, product_id=product.id, created_at=utcnow())
        db.add(r)
        db.flush()
    r.yield_qty, r.extra_cost, r.note, r.updated_at = yq, extra, (note or "").strip()[:300] or None, utcnow()
    db.query(RecipeLine).filter(RecipeLine.recipe_id == r.id).delete()
    for iid, q in clean:
        db.add(RecipeLine(recipe_id=r.id, item_id=iid, qty=q))
    db.commit()
    return r


def delete_recipe(db, owner_phone, product_id):
    r = get_recipe(db, owner_phone, product_id)
    if r:
        db.query(RecipeLine).filter(RecipeLine.recipe_id == r.id).delete()
        db.delete(r)
        db.commit()


# ── A production run ────────────────────────────────────────────────────────

def plan(db, owner_phone, product_id, made_qty, batches=None, lines=None, extra_cost=None, branch_id=None):
    """What making `made_qty` uses and costs. `lines` (what was actually used)
    overrides the recipe; without either, there's nothing to take out."""
    product = _item(db, owner_phone, product_id, branch_id)
    made = _qty(made_qty, "number made")
    r = get_recipe(db, owner_phone, product.id)
    if batches in (None, ""):
        batches = (made / r.yield_qty) if (r and r.yield_qty) else None
    else:
        batches = _qty(batches, "number of batches")
    if lines is None:
        lines = [{"item_id": l.item_id, "qty": l.qty * (batches or 0)}
                 for l in (db.query(RecipeLine).filter(RecipeLine.recipe_id == r.id).all() if r else [])]
    out, materials, seen = [], 0.0, set()
    for l in lines:
        iid = int(l.get("item_id") or 0)
        try:
            q = float(l.get("qty") or 0)
        except (TypeError, ValueError):
            raise ProductionError("Enter amounts used as numbers.")
        if not iid or q <= 0:
            continue
        if iid == product.id or iid in seen:
            raise ProductionError("Each material once, and not the product itself.")
        seen.add(iid)
        mat = _item(db, owner_phone, iid, branch_id)
        unit_cost = float(mat.cost_price or 0)
        have = float(mat.quantity or 0) if mat.quantity is not None else None
        out.append({"item_id": mat.id, "name": (mat.name or "").title(), "unit": mat.unit, "qty": round(q, 3),
                    "unit_cost": unit_cost, "cost": round(q * unit_cost), "in_stock": _num(have) if have is not None else None,
                    "short": _num(max(0.0, q - have)) if have is not None and q > have else 0})
        materials += q * unit_cost
    if extra_cost in (None, ""):
        extra = round((r.extra_cost or 0) * (batches or 0)) if r else 0
    else:
        try:
            extra = max(0, int(float(extra_cost)))
        except (TypeError, ValueError):
            raise ProductionError("Enter other costs as an amount.")
    total = round(materials) + extra
    return {
        "product_id": product.id, "product": (product.name or "").title(), "unit": product.unit,
        "made_qty": _num(made), "batches": round(batches, 3) if batches else None,
        "has_recipe": bool(r), "lines": out, "materials_cost": round(materials), "extra_cost": extra,
        "total_cost": total, "cost_per_unit": round(total / made, 2) if made else None,
        "no_cost_price": [l["name"] for l in out if not l["unit_cost"]],
        "short": [l for l in out if l["short"]],
    }


def record_run(db, owner_phone, user_id, product_id, made_qty, *, batches=None, lines=None, extra_cost=None,
               note=None, expiry_date=None, allow_short=False, branch_id=None):
    p = plan(db, owner_phone, product_id, made_qty, batches, lines, extra_cost, branch_id)
    if p["short"] and not allow_short:
        raise ProductionError("Not enough in stock: " + ", ".join(
            f"{l['name']} (need {_num(l['qty'])}, have {l['in_stock']})" for l in p["short"])
            + ". Record the purchase first, or record this anyway.")
    product = _item(db, owner_phone, product_id, branch_id)
    made = float(p["made_qty"])
    label = f"Used to make {_num(made)} {product.name}"
    now = utcnow()

    recipe = get_recipe(db, owner_phone, product.id)
    run = ProductionRun(owner_phone=owner_phone, branch_id=branch_id or product.branch_id, product_id=product.id,
                        recipe_id=recipe.id if recipe else None, batches=p["batches"],
                        made_qty=made, materials_cost=p["materials_cost"], extra_cost=p["extra_cost"],
                        cost_per_unit=p["cost_per_unit"], lines_json=json.dumps(p["lines"]),
                        note=(note or "").strip()[:300] or None, created_by_id=user_id, created_at=now)
    db.add(run)
    db.flush()

    for l in p["lines"]:
        mat = db.query(InventoryItem).filter(InventoryItem.id == l["item_id"]).first()
        if mat.quantity is not None:
            mat.quantity = max(0.0, float(mat.quantity or 0) - l["qty"])
        mat.updated_at = now
        db.add(InventoryMovement(owner_phone=owner_phone, item_id=mat.id, movement_type="OUT", quantity=l["qty"],
                                 unit_price=mat.cost_price, source_type="PRODUCTION_USE", source_id=str(run.id),
                                 recorded_by_id=user_id, note=label + (" (not all was in stock)" if l["short"] else "")))

    # The real cost: the average of what was in stock and what was just made
    cpu = p["cost_per_unit"] or 0
    if cpu > 0:
        old_q, old_c = max(0.0, float(product.quantity or 0)), product.cost_price
        product.cost_price = round((old_q * old_c + made * cpu) / (old_q + made)) if (old_c and old_q > 0) \
            else round(cpu)
    product.quantity = float(product.quantity or 0) + made
    product.updated_at = now
    db.add(InventoryMovement(owner_phone=owner_phone, item_id=product.id, movement_type="IN", quantity=made,
                             unit_price=round(cpu) if cpu else None, source_type="PRODUCTION",
                             source_id=str(run.id), recorded_by_id=user_id,
                             note=f"Made — batch {run.id}"))
    db.add(StockBatch(owner_phone=owner_phone, item_id=product.id, quantity=made, expiry_date=expiry_date,
                      batch_no=f"P{run.id}", source_type="PRODUCTION"))
    db.commit()
    return run


def undo_run(db, owner_phone, run_id, user_id):
    """A run recorded by mistake: the product comes back out, the materials go
    back in. Only while what was made is still in stock."""
    run = db.query(ProductionRun).filter(ProductionRun.id == run_id, ProductionRun.owner_phone == owner_phone).first()
    if not run:
        raise ProductionError("That production run was not found.")
    if run.undone_at:
        raise ProductionError("This run was already undone.")
    product = db.query(InventoryItem).filter(InventoryItem.id == run.product_id).first()
    if not product or float(product.quantity or 0) < float(run.made_qty or 0):
        raise ProductionError("Some of what was made has been sold or used, so it can't be undone. "
                              "Remove the mistake from stock with a reason instead.")
    now = utcnow()
    product.quantity = float(product.quantity or 0) - float(run.made_qty)
    db.add(InventoryMovement(owner_phone=owner_phone, item_id=product.id, movement_type="OUT", quantity=run.made_qty,
                             unit_price=product.cost_price, source_type="PRODUCTION_UNDO", source_id=str(run.id),
                             recorded_by_id=user_id, note=f"Batch {run.id} undone"))
    db.query(StockBatch).filter(StockBatch.item_id == product.id, StockBatch.batch_no == f"P{run.id}").delete()
    for l in json.loads(run.lines_json or "[]"):
        mat = db.query(InventoryItem).filter(InventoryItem.id == l["item_id"]).first()
        if not mat:
            continue
        back = float(l["qty"]) - float(l.get("short") or 0)       # what really came out of stock
        if mat.quantity is not None and back > 0:
            mat.quantity = float(mat.quantity or 0) + back
            db.add(InventoryMovement(owner_phone=owner_phone, item_id=mat.id, movement_type="IN", quantity=back,
                                     unit_price=mat.cost_price, source_type="PRODUCTION_UNDO",
                                     source_id=str(run.id), recorded_by_id=user_id,
                                     note=f"Batch {run.id} undone"))
    run.undone_at = now
    db.commit()
    return run


def run_dict(db, run, names=None):
    from models import User
    names = names or {}
    if run.product_id not in names:
        it = db.query(InventoryItem).filter(InventoryItem.id == run.product_id).first()
        names[run.product_id] = ((it.name or "").title(), it.unit) if it else ("?", None)
    by = db.query(User.name).filter(User.id == run.created_by_id).scalar() if run.created_by_id else None
    return {
        "id": run.id, "product_id": run.product_id, "product": names[run.product_id][0], "unit": names[run.product_id][1],
        "made_qty": _num(run.made_qty), "batches": run.batches, "materials_cost": run.materials_cost or 0,
        "extra_cost": run.extra_cost or 0, "total_cost": (run.materials_cost or 0) + (run.extra_cost or 0),
        "cost_per_unit": run.cost_per_unit, "lines": json.loads(run.lines_json or "[]"), "note": run.note,
        "by": by, "created_at": run.created_at.isoformat() if run.created_at else None,
        "undone": bool(run.undone_at),
    }


def list_runs(db, owner_phone, days=30, branch_id=None):
    since = datetime.utcnow() - timedelta(days=days)
    q = db.query(ProductionRun).filter(ProductionRun.owner_phone == owner_phone, ProductionRun.created_at >= since)
    if branch_id is not None:
        q = q.filter(ProductionRun.branch_id == branch_id)
    names = {}
    runs = [run_dict(db, r, names) for r in q.order_by(ProductionRun.created_at.desc()).limit(500).all()]
    totals = {}
    for r in runs:
        if r["undone"]:
            continue
        t = totals.setdefault(r["product_id"], {"product": r["product"], "unit": r["unit"], "made": 0, "cost": 0})
        t["made"] += float(r["made_qty"])
        t["cost"] += r["total_cost"]
    for t in totals.values():
        t["made"] = _num(t["made"])
        t["cost_per_unit"] = round(t["cost"] / float(t["made"]), 2) if float(t["made"]) else None
    return {"runs": runs, "totals": sorted(totals.values(), key=lambda t: t["product"])}
