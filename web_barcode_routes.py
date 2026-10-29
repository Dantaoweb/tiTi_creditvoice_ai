"""
The shop's own barcodes (barcodes.make_instore): make one for a product,
give one to every product that has none, and the details for printing labels.
Only the people who manage stock (owner / authorised staff).
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import InventoryItem, User
from web_auth import require_web_auth
from web_common import _require_stock_manager, _session_owner_phone


class ItemIds(BaseModel):
    item_ids: list[int] = Field(max_length=1000)


def register_barcode_routes(app):
    import barcodes

    @app.get("/app/api/barcodes/new")
    def web_new_barcode(session: dict = Depends(require_web_auth)):
        """A free in-store code for a product being added (saved with it)."""
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            return {"code": barcodes.make_instore(db, _session_owner_phone(db, session))}
        finally:
            db.close()

    @app.get("/app/api/barcodes/missing")
    def web_missing_barcodes(session: dict = Depends(require_web_auth)):
        """Products (not services) with no barcode yet."""
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            rows = (db.query(InventoryItem)
                    .filter(InventoryItem.owner_phone == owner_phone,
                            (InventoryItem.barcode.is_(None)) | (InventoryItem.barcode == ""),
                            (InventoryItem.category.is_(None)) | (InventoryItem.category != "service"))
                    .order_by(InventoryItem.name).limit(1000).all())
            return {"items": [{"id": i.id, "name": i.name, "unit": i.unit, "quantity": i.quantity} for i in rows]}
        finally:
            db.close()

    @app.post("/app/api/barcodes/give")
    def web_give_barcodes(payload: ItemIds, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            try:
                done = barcodes.give_barcodes(db, _session_owner_phone(db, session), payload.item_ids)
            except ValueError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))
            db.commit()
            return {"given": len(done), "codes": {str(k): v for k, v in done.items()}}
        finally:
            db.close()

    @app.post("/app/api/barcodes/labels")
    def web_label_details(payload: ItemIds, session: dict = Depends(require_web_auth)):
        """What goes on each label: code, name, price — and the business name."""
        from business_templates import business_display_name
        db = SessionLocal()
        try:
            _require_stock_manager(db, session)
            owner_phone = _session_owner_phone(db, session)
            items = (db.query(InventoryItem)
                     .filter(InventoryItem.owner_phone == owner_phone, InventoryItem.id.in_(payload.item_ids))
                     .order_by(InventoryItem.name).all())
            owner = db.query(User).filter(User.phone == owner_phone).first()
            return {"biz_name": business_display_name(owner) if owner else "",
                    "items": [{"id": i.id, "name": i.name, "barcode": i.barcode or None, "unit": i.unit,
                               "selling_price": int(i.selling_price or 0), "quantity": i.quantity}
                              for i in items]}
        finally:
            db.close()
