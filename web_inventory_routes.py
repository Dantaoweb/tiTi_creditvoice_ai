"""
Inventory routes: list, add, catalog, bulk-add, edit, adjust stock.

Split out of web_routes.py. Register with register_inventory_routes(app);
shared helpers come from web_common. Stock management is owner/branch-admin only
(via _require_stock_manager).
"""
import json
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import User, InventoryItem, InventoryMovement, utcnow
from web_auth import require_web_auth
from web_common import (
    _session_owner_phone, _owner_filter, _scoped_read, _money, _iso,
    _require_stock_manager, _check_inventory_limit, _session_user, _active_inventory_count,
)


def _clean_attributes(user, raw):
    """Keep only the keys defined for this business's stock fields, as trimmed
    strings. Returns a JSON string (or None when empty)."""
    from business_templates import inventory_fields_for_user
    allowed = {f["key"] for f in inventory_fields_for_user(user)}
    clean = {}
    for k, v in (raw or {}).items():
        if k in allowed and v is not None and str(v).strip():
            clean[k] = str(v).strip()
    return json.dumps(clean) if clean else None


def _load_attributes(item):
    try:
        return json.loads(item.attributes_json) if item.attributes_json else {}
    except Exception:
        return {}


class AddInventoryRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    name: str = Field(max_length=120)
    unit: Optional[str] = Field(default=None, max_length=30)
    quantity: Optional[float] = 0.0
    cost_price: Optional[int] = None
    selling_price: Optional[int] = None
    low_stock_alert: Optional[int] = None
    is_service: bool = False
    retail_unit: Optional[str] = Field(default=None, max_length=30)
    retail_per_base: Optional[int] = None
    retail_price: Optional[int] = None
    attributes: dict = Field(default_factory=dict)   # per-business custom stock fields


class EditInventoryRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    unit: Optional[str] = Field(default=None, max_length=30)
    cost_price: Optional[int] = None
    selling_price: Optional[int] = None
    low_stock_alert: Optional[int] = None
    is_available: Optional[bool] = None
    retail_unit: Optional[str] = Field(default=None, max_length=30)
    retail_per_base: Optional[int] = None
    retail_price: Optional[int] = None
    attributes: Optional[dict] = None


class AdjustStockRequest(BaseModel):
    qty_delta: int
    note: Optional[str] = Field(default=None, max_length=500)


class StockReceivedRequest(BaseModel):
    # Either an existing item_id, or a product name to create/receive into.
    item_id: Optional[int] = None
    product: Optional[str] = Field(default=None, max_length=120)
    unit: Optional[str] = Field(default=None, max_length=30)
    quantity: float
    cost_per_unit: Optional[int] = None
    paid_now: Optional[int] = None   # None → fully paid; less than total → records supplier debt
    supplier: Optional[str] = Field(default=None, max_length=120)   # blank → "Others"
    note: Optional[str] = Field(default=None, max_length=500)
    due_date: Optional[str] = None   # "YYYY-MM-DD" — when the supplier balance is due


class BulkCatalogItem(BaseModel):
    name: str = Field(max_length=120)
    unit: Optional[str] = Field(default=None, max_length=30)
    selling_price: Optional[int] = None
    is_service: bool = False


class BulkAddInventoryRequest(BaseModel):
    owner_phone: str = Field(max_length=20)
    names: list[str] = Field(default_factory=list, max_length=100)   # plain product names
    items: list[BulkCatalogItem] = Field(default_factory=list, max_length=100)  # priced/service items


def register_inventory_routes(app):

    @app.get("/app/api/inventory/fields")
    def web_inventory_fields(session: dict = Depends(require_web_auth)):
        """Custom stock-field definitions for this business (e.g. car dealers get
        maker/model/year/colour/chassis/engine). Empty for most businesses."""
        from business_templates import inventory_fields_for_user
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            return {"fields": inventory_fields_for_user(user) if user else []}
        finally:
            db.close()

    @app.get("/app/api/inventory")
    def web_inventory(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _session_owner_phone(db, session)
            query = _owner_filter(db.query(InventoryItem), InventoryItem, owner_phone)
            # Branch staff see only their branch's stock. (Unassigned staff and
            # owners see the full catalogue so they can still sell/manage.)
            eff_branch, _rec = _scoped_read(db, session)
            if eff_branch is not None:
                query = query.filter(InventoryItem.branch_id == eff_branch)
            rows = query.order_by(InventoryItem.updated_at.desc()).limit(200).all()
            return {
                "items": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "unit": item.unit,
                        "quantity": item.quantity,
                        "cost_price": _money(item.cost_price),
                        "selling_price": _money(item.selling_price),
                        "low_stock_alert": item.low_stock_alert,
                        "is_available": bool(item.is_available),
                        "is_service": item.quantity is None or item.category == "service",
                        "retail_unit": item.retail_unit,
                        "retail_per_base": item.retail_per_base,
                        "retail_price": item.retail_price,
                        "attributes": _load_attributes(item),
                        "updated_at": _iso(item.updated_at),
                    }
                    for item in rows
                ]
            }
        finally:
            db.close()

    @app.post("/app/api/inventory")
    def web_add_inventory(
        payload: AddInventoryRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)

            # Enforce active-inventory limit for Basic plan when a price is being set
            if payload.selling_price is not None:
                from subscriptions import get_business_subscription
                owner = db.query(User).filter(User.phone == owner_phone).first()
                sub = get_business_subscription(db, owner) if owner else None
                err = _check_inventory_limit(db, owner_phone, sub)
                if err:
                    raise HTTPException(status_code=403, detail=err)

            _qty = None if payload.is_service else (payload.quantity or 0.0)
            from transaction_save import _get_recording_branch_id
            owner_user = db.query(User).filter(User.phone == owner_phone).first()
            item = InventoryItem(
                owner_phone=owner_phone,
                name=payload.name.strip().lower(),
                unit=(payload.unit or "").strip() or None,
                quantity=_qty,
                cost_price=None if payload.is_service else payload.cost_price,
                selling_price=payload.selling_price,
                low_stock_alert=None if payload.is_service else payload.low_stock_alert,
                is_available=True,
                branch_id=_get_recording_branch_id(db, owner_phone, _session_user(db, session)),
                category="service" if payload.is_service else None,
                retail_unit=payload.retail_unit.strip().lower() if payload.retail_unit else None,
                retail_per_base=payload.retail_per_base,
                retail_price=payload.retail_price,
                attributes_json=_clean_attributes(owner_user, payload.attributes),
            )
            db.add(item)
            if not payload.is_service and _qty:
                db.flush()
                db.add(InventoryMovement(
                    owner_phone=owner_phone,
                    item_id=item.id,
                    movement_type="IN",
                    quantity=_qty,
                    unit_price=payload.cost_price,
                    source_type="WEB_ADD",
                    source_id=None,
                    recorded_by_id=session["user_id"],
                    note="Initial stock",
                ))
            db.commit()
            db.refresh(item)
            return {
                "id": item.id, "name": item.name, "unit": item.unit,
                "quantity": item.quantity or 0,
                "cost_price": _money(item.cost_price),
                "selling_price": _money(item.selling_price),
            }
        finally:
            db.close()

    @app.get("/app/api/inventory/catalog")
    def web_inventory_catalog(session: dict = Depends(require_web_auth)):
        from business_templates import (
            INDUSTRY_PRODUCT_CATALOG, template_key_for_user,
            has_service_price_catalog, service_price_catalog_for_user,
        )
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == session["user_id"]).first()

            # Service businesses (laundry, barber, car wash, tailor, mechanic…)
            # get their own industry price list — never the retail/provisions
            # fallback. Entries carry the suggested price and variant.
            if user and has_service_price_catalog(user):
                services = []
                for name, variant, price in service_price_catalog_for_user(user):
                    label = f"{name} ({variant})" if variant else name
                    services.append({
                        "name": label,        # unique display/name incl. variant
                        "variant": variant,
                        "price": price,
                    })
                return {"kind": "service", "services": services}

            # Product businesses → category → names (retail fallback only applies
            # to businesses that actually sell goods).
            key = template_key_for_user(user) if user else None
            btype = getattr(user, "business_type", None) if user else None
            entries = (
                INDUSTRY_PRODUCT_CATALOG.get(btype)
                or (INDUSTRY_PRODUCT_CATALOG.get(key, []) if key else [])
                or INDUSTRY_PRODUCT_CATALOG.get("retail_trading", [])
            )
            categories = {}
            for name, cat in entries:
                categories.setdefault(cat, []).append(name)
            return {"kind": "product", "catalog": categories}
        finally:
            db.close()

    @app.post("/app/api/inventory/bulk")
    def web_bulk_add_inventory(
        payload: BulkAddInventoryRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            saved, skipped = 0, 0
            from transaction_save import _get_recording_branch_id
            _import_branch_id = _get_recording_branch_id(db, owner_phone, _session_user(db, session))

            # Enforce the active-product cap (Basic = 5). Extra priced items are
            # still saved, but as unlimited drafts (no price) rather than active
            # products, and we report how many so the UI can prompt an upgrade.
            from subscriptions import get_business_subscription
            from plans import plan_limit
            sub = get_business_subscription(db, _session_user(db, session))
            active_limit = plan_limit(sub["plan"], "active_inventory_items")
            active_count = _active_inventory_count(db, owner_phone)
            priced_blocked = 0

            # Normalize plain names and priced/service catalog items into one list
            rows = [{"name": n} for n in payload.names]
            rows += [
                {"name": it.name, "unit": it.unit,
                 "selling_price": it.selling_price, "is_service": it.is_service}
                for it in payload.items
            ]

            for row in rows:
                name_clean = str(row.get("name", "")).strip().lower()
                if not name_clean:
                    continue
                existing = db.query(InventoryItem).filter(
                    InventoryItem.owner_phone == owner_phone,
                    InventoryItem.name == name_clean,
                ).first()
                if existing:
                    skipped += 1
                    continue
                item = InventoryItem(
                    owner_phone=owner_phone,
                    name=name_clean,
                    is_available=True,
                    branch_id=_import_branch_id,
                )
                want_price = bool(row.get("selling_price"))
                if want_price and active_limit is not None and active_count >= active_limit:
                    # No active slots left — keep it as a draft (unlimited).
                    want_price = False
                    priced_blocked += 1
                if want_price:
                    item.selling_price = int(row["selling_price"])
                    active_count += 1
                if row.get("unit"):
                    item.unit = row["unit"]
                if row.get("is_service"):
                    item.category = "service"
                    item.quantity = None   # services have no stock
                db.add(item)
                saved += 1
            if saved:
                db.commit()
            resp = {"saved": saved, "already_existed": skipped}
            if priced_blocked:
                resp["priced_blocked"] = priced_blocked
                resp["active_limit"] = active_limit
                resp["message"] = (
                    f"{priced_blocked} item(s) were saved without a price because you've "
                    f"reached the Basic limit of {active_limit} active products. "
                    "Upgrade to Go for unlimited priced products."
                )
            return resp
        finally:
            db.close()

    @app.put("/app/api/inventory/{item_id}")
    def web_edit_inventory(
        item_id: int,
        payload: EditInventoryRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            item = db.query(InventoryItem).filter(
                InventoryItem.id == item_id,
                InventoryItem.owner_phone == owner_phone,
            ).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found.")
            if payload.name is not None:
                item.name = payload.name.strip().lower()
            if payload.unit is not None:
                item.unit = payload.unit.strip() or None
            if payload.cost_price is not None:
                item.cost_price = payload.cost_price
            if payload.selling_price is not None:
                # Only enforce limit when activating a previously draft item
                if item.selling_price is None:
                    from subscriptions import get_business_subscription
                    owner = db.query(User).filter(User.phone == owner_phone).first()
                    sub = get_business_subscription(db, owner) if owner else None
                    err = _check_inventory_limit(db, owner_phone, sub)
                    if err:
                        raise HTTPException(status_code=403, detail=err)
                item.selling_price = payload.selling_price
            if payload.low_stock_alert is not None:
                item.low_stock_alert = payload.low_stock_alert
            if payload.is_available is not None:
                item.is_available = payload.is_available
            if payload.retail_unit is not None:
                item.retail_unit = payload.retail_unit.strip().lower() or None
            if payload.retail_per_base is not None:
                item.retail_per_base = payload.retail_per_base or None
            if payload.retail_price is not None:
                item.retail_price = payload.retail_price or None
            if payload.attributes is not None:
                owner_user = db.query(User).filter(User.phone == owner_phone).first()
                item.attributes_json = _clean_attributes(owner_user, payload.attributes)
            item.updated_at = utcnow()
            db.commit()
            return {"id": item.id, "name": item.name, "selling_price": _money(item.selling_price)}
        finally:
            db.close()

    @app.post("/app/api/inventory/{item_id}/adjust")
    def web_adjust_stock(
        item_id: int,
        payload: AdjustStockRequest,
        session: dict = Depends(require_web_auth),
    ):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            item = db.query(InventoryItem).filter(
                InventoryItem.id == item_id,
                InventoryItem.owner_phone == owner_phone,
            ).first()
            if not item:
                raise HTTPException(status_code=404, detail="Item not found.")
            delta = payload.qty_delta
            item.quantity = (item.quantity or 0) + delta
            item.updated_at = utcnow()
            db.add(InventoryMovement(
                owner_phone=item.owner_phone,
                item_id=item.id,
                movement_type="IN" if delta > 0 else "OUT",
                quantity=abs(delta),
                source_type="WEB_ADJUST",
                source_id=None,
                recorded_by_id=session["user_id"],
                note=payload.note or ("Stock added" if delta > 0 else "Stock removed"),
            ))
            db.commit()
            return {"id": item.id, "new_quantity": item.quantity}
        except HTTPException:
            raise
        except Exception:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=400, detail="Could not adjust stock. Please try again.")
        finally:
            db.close()

    @app.post("/app/api/inventory/stock-received")
    def web_stock_received(
        payload: StockReceivedRequest,
        session: dict = Depends(require_web_auth),
    ):
        """Record stock received from a supplier: adds to physical inventory
        (creating the product if new) AND records a SupplierPurchase against the
        supplier (defaulting to 'Others' when none is given)."""
        from models import SupplierPurchase
        from inventory_suppliers import find_or_create_supplier, add_inventory_movement
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)

            qty = payload.quantity
            if not qty or qty <= 0:
                raise HTTPException(status_code=400, detail="Quantity received must be greater than zero.")

            # Resolve the product name/unit — from an existing item, or a new name.
            unit = payload.unit
            if payload.item_id:
                existing = db.query(InventoryItem).filter(
                    InventoryItem.id == payload.item_id,
                    InventoryItem.owner_phone == owner_phone,
                ).first()
                if not existing:
                    raise HTTPException(status_code=404, detail="Item not found.")
                product = existing.name
                unit = unit or existing.unit
            else:
                product = (payload.product or "").strip()
                if not product:
                    raise HTTPException(status_code=400, detail="Product name is required.")

            supplier_name = (payload.supplier or "").strip() or "Others"
            supplier = find_or_create_supplier(db, owner_phone, supplier_name)
            db.flush()

            cost = payload.cost_per_unit
            total = int(round(cost * qty)) if cost else 0
            # Default: fully paid (owned). A smaller paid_now records supplier debt.
            paid_amount = total if payload.paid_now is None else max(0, min(int(payload.paid_now), total))
            due_dt = None
            if payload.due_date:
                from datetime import datetime as _dt
                try:
                    due_dt = _dt.strptime(payload.due_date[:10], "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid due date. Use YYYY-MM-DD.")
            purchase = SupplierPurchase(
                supplier_id=supplier.id,
                owner_phone=owner_phone,
                product=product,
                quantity=qty,
                unit=unit,
                unit_price=cost,
                total=total,
                paid_amount=paid_amount,
                due_date=due_dt,
                recorded_by_id=session["user_id"],
                created_at=utcnow(),
            )
            db.add(purchase)
            db.flush()

            # Adds quantity to physical stock (creating the item if it doesn't
            # exist yet) and logs the IN movement linked to this purchase.
            item = add_inventory_movement(
                db, owner_phone, product, qty, unit, cost,
                "IN", "SUPPLIER_PURCHASE", purchase.id, session["user_id"],
                (payload.note or "").strip() or f"Received from {supplier.name.title()}",
            )
            db.commit()
            return {
                "ok": True,
                "product": product,
                "new_quantity": item.quantity if item else None,
                "supplier": supplier.name.title(),
                "purchase_id": purchase.id,
            }
        except HTTPException:
            raise
        except Exception:
            import traceback; traceback.print_exc()
            db.rollback()
            raise HTTPException(status_code=400, detail="Could not record stock received. Please try again.")
        finally:
            db.close()
