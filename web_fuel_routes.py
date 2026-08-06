"""
Filling-station operations (fuel businesses): tanks, pumps, price per litre,
tanker deliveries, attendant shift reconciliation (pump meter open/close vs
cash), and tank dips for wet-stock variance.

Web-first. Register with register_fuel_routes(app). Branch-scoped and limited to
energy/fuel businesses. Setup (tanks/pumps/price/deliveries) is owner/
stock-manager only; shifts and dips may be recorded by attendants (any staff).
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from models import (
    User, FuelTank, FuelPump, FuelPrice, FuelDelivery, FuelShift, FuelDip, utcnow,
)
from web_auth import require_web_auth
from web_common import (
    _session_owner_phone, _session_user, _scoped_read, _require_stock_manager,
    _money, _iso,
)

FUEL_PRODUCTS = ("PMS", "AGO", "DPK", "LPG")


# ── request models ────────────────────────────────────────────────────────────
class TankRequest(BaseModel):
    name: str = Field(max_length=60)
    product: str = Field(max_length=20)
    capacity_litres: Optional[float] = None
    current_level_litres: Optional[float] = None


class PumpRequest(BaseModel):
    name: str = Field(max_length=60)
    product: str = Field(max_length=20)
    tank_id: Optional[int] = None
    current_meter: Optional[float] = None


class PriceRequest(BaseModel):
    product: str = Field(max_length=20)
    price_per_litre: int


class DeliveryRequest(BaseModel):
    tank_id: int
    litres: float
    cost_per_litre: Optional[int] = None
    supplier: Optional[str] = Field(default=None, max_length=120)
    waybill: Optional[str] = Field(default=None, max_length=60)


class ShiftOpenRequest(BaseModel):
    pump_id: int
    attendant_id: Optional[str] = Field(default=None, max_length=60)
    shift_label: Optional[str] = Field(default=None, max_length=20)
    opening_meter: Optional[float] = None


class ShiftCloseRequest(BaseModel):
    closing_meter: float
    cash_amount: int = 0
    pos_amount: int = 0
    transfer_amount: int = 0
    credit_amount: int = 0


class DipRequest(BaseModel):
    tank_id: int
    dipped_litres: float
    note: Optional[str] = Field(default=None, max_length=200)


def register_fuel_routes(app):

    # ── helpers ──────────────────────────────────────────────────────────────
    def _fuel_owner(db, session):
        """Resolve the business owner and ensure it's a fuel/energy business."""
        owner_phone = _session_owner_phone(db, session)
        from business_templates import template_key_for_user
        owner = db.query(User).filter(User.phone == owner_phone).first()
        if not owner or template_key_for_user(owner) != "energy_fuel":
            raise HTTPException(status_code=403, detail="This feature is for fuel / energy businesses.")
        return owner_phone

    def _rec_branch(db, owner_phone, user):
        from transaction_save import _get_recording_branch_id
        return _get_recording_branch_id(db, owner_phone, user)

    def _norm_product(p):
        p = (p or "").strip().upper()
        return p if p else "PMS"

    def _current_price(db, owner_phone, branch_id, product):
        q = db.query(FuelPrice).filter(
            FuelPrice.owner_phone == owner_phone, FuelPrice.product == product,
        )
        if branch_id is not None:
            q = q.filter(FuelPrice.branch_id == branch_id)
        row = q.order_by(FuelPrice.updated_at.desc(), FuelPrice.id.desc()).first()
        return row.price_per_litre if row else 0

    # ── overview ───────────────────────────────────────────────────────────
    @app.get("/app/api/fuel/overview")
    def fuel_overview(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            eff_branch, _rec = _scoped_read(db, session)

            def _scope(q, model):
                q = q.filter(model.owner_phone == owner_phone)
                if eff_branch is not None:
                    q = q.filter(model.branch_id == eff_branch)
                return q

            tanks = _scope(db.query(FuelTank), FuelTank).order_by(FuelTank.name).all()
            pumps = _scope(db.query(FuelPump), FuelPump).order_by(FuelPump.name).all()

            # Latest price per product
            prices = {}
            for p in FUEL_PRODUCTS:
                pr = _current_price(db, owner_phone, eff_branch, p)
                if pr:
                    prices[p] = pr

            # Today's closed-shift totals
            today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            shifts_today = _scope(db.query(FuelShift), FuelShift).filter(
                FuelShift.status == "closed", FuelShift.closed_at >= today,
            ).all()
            litres_today = sum(s.litres_sold or 0 for s in shifts_today)
            collected_today = sum((s.cash_amount or 0) + (s.pos_amount or 0)
                                  + (s.transfer_amount or 0) + (s.credit_amount or 0)
                                  for s in shifts_today)
            shortfall_today = sum(s.shortfall or 0 for s in shifts_today)
            open_shifts = _scope(db.query(FuelShift), FuelShift).filter(
                FuelShift.status == "open").count()

            return {
                "tanks": [
                    {"id": t.id, "name": t.name, "product": t.product,
                     "capacity_litres": t.capacity_litres,
                     "current_level_litres": t.current_level_litres,
                     "ullage_litres": (t.capacity_litres or 0) - (t.current_level_litres or 0)}
                    for t in tanks
                ],
                "pumps": [
                    {"id": p.id, "name": p.name, "product": p.product,
                     "tank_id": p.tank_id, "current_meter": p.current_meter,
                     "is_active": bool(p.is_active)}
                    for p in pumps
                ],
                "prices": prices,
                "today": {
                    "litres_sold": round(litres_today, 2),
                    "collected": collected_today,
                    "shortfall": shortfall_today,
                    "open_shifts": open_shifts,
                },
            }
        finally:
            db.close()

    # ── tanks ────────────────────────────────────────────────────────────────
    @app.post("/app/api/fuel/tanks")
    def fuel_add_tank(payload: TankRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            _require_stock_manager(db, session)
            user = _session_user(db, session)
            tank = FuelTank(
                owner_phone=owner_phone,
                branch_id=_rec_branch(db, owner_phone, user),
                name=payload.name.strip(),
                product=_norm_product(payload.product),
                capacity_litres=payload.capacity_litres or 0.0,
                current_level_litres=payload.current_level_litres or 0.0,
            )
            db.add(tank)
            db.commit()
            db.refresh(tank)
            return {"id": tank.id, "name": tank.name, "product": tank.product}
        finally:
            db.close()

    @app.put("/app/api/fuel/tanks/{tank_id}")
    def fuel_edit_tank(tank_id: int, payload: TankRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            _require_stock_manager(db, session)
            tank = db.query(FuelTank).filter(
                FuelTank.id == tank_id, FuelTank.owner_phone == owner_phone).first()
            if not tank:
                raise HTTPException(status_code=404, detail="Tank not found.")
            tank.name = payload.name.strip()
            tank.product = _norm_product(payload.product)
            if payload.capacity_litres is not None:
                tank.capacity_litres = payload.capacity_litres
            if payload.current_level_litres is not None:
                tank.current_level_litres = payload.current_level_litres
            tank.updated_at = utcnow()
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.delete("/app/api/fuel/tanks/{tank_id}")
    def fuel_delete_tank(tank_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            _require_stock_manager(db, session)
            tank = db.query(FuelTank).filter(
                FuelTank.id == tank_id, FuelTank.owner_phone == owner_phone).first()
            if not tank:
                raise HTTPException(status_code=404, detail="Tank not found.")
            db.delete(tank)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    # ── pumps ────────────────────────────────────────────────────────────────
    @app.post("/app/api/fuel/pumps")
    def fuel_add_pump(payload: PumpRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            _require_stock_manager(db, session)
            user = _session_user(db, session)
            pump = FuelPump(
                owner_phone=owner_phone,
                branch_id=_rec_branch(db, owner_phone, user),
                name=payload.name.strip(),
                product=_norm_product(payload.product),
                tank_id=payload.tank_id,
                current_meter=payload.current_meter or 0.0,
                is_active=True,
            )
            db.add(pump)
            db.commit()
            db.refresh(pump)
            return {"id": pump.id, "name": pump.name, "product": pump.product}
        finally:
            db.close()

    @app.put("/app/api/fuel/pumps/{pump_id}")
    def fuel_edit_pump(pump_id: int, payload: PumpRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            _require_stock_manager(db, session)
            pump = db.query(FuelPump).filter(
                FuelPump.id == pump_id, FuelPump.owner_phone == owner_phone).first()
            if not pump:
                raise HTTPException(status_code=404, detail="Pump not found.")
            pump.name = payload.name.strip()
            pump.product = _norm_product(payload.product)
            pump.tank_id = payload.tank_id
            if payload.current_meter is not None:
                pump.current_meter = payload.current_meter
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.delete("/app/api/fuel/pumps/{pump_id}")
    def fuel_delete_pump(pump_id: int, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            _require_stock_manager(db, session)
            pump = db.query(FuelPump).filter(
                FuelPump.id == pump_id, FuelPump.owner_phone == owner_phone).first()
            if not pump:
                raise HTTPException(status_code=404, detail="Pump not found.")
            db.delete(pump)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    # ── price ────────────────────────────────────────────────────────────────
    @app.post("/app/api/fuel/price")
    def fuel_set_price(payload: PriceRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            _require_stock_manager(db, session)
            user = _session_user(db, session)
            if payload.price_per_litre < 0:
                raise HTTPException(status_code=400, detail="Price must be zero or more.")
            row = FuelPrice(
                owner_phone=owner_phone,
                branch_id=_rec_branch(db, owner_phone, user),
                product=_norm_product(payload.product),
                price_per_litre=payload.price_per_litre,
                updated_by_id=session["user_id"],
                updated_at=utcnow(),
            )
            db.add(row)
            db.commit()
            return {"ok": True, "product": row.product, "price_per_litre": row.price_per_litre}
        finally:
            db.close()

    # ── deliveries ─────────────────────────────────────────────────────────
    @app.get("/app/api/fuel/deliveries")
    def fuel_list_deliveries(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            eff_branch, _rec = _scoped_read(db, session)
            q = db.query(FuelDelivery).filter(FuelDelivery.owner_phone == owner_phone)
            if eff_branch is not None:
                q = q.filter(FuelDelivery.branch_id == eff_branch)
            rows = q.order_by(FuelDelivery.delivered_at.desc()).limit(100).all()
            return {"deliveries": [
                {"id": d.id, "tank_id": d.tank_id, "product": d.product,
                 "litres": d.litres, "cost_per_litre": d.cost_per_litre,
                 "supplier": d.supplier, "waybill": d.waybill,
                 "delivered_at": _iso(d.delivered_at)}
                for d in rows
            ]}
        finally:
            db.close()

    @app.post("/app/api/fuel/deliveries")
    def fuel_add_delivery(payload: DeliveryRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            _require_stock_manager(db, session)
            user = _session_user(db, session)
            if payload.litres <= 0:
                raise HTTPException(status_code=400, detail="Litres must be greater than zero.")
            tank = db.query(FuelTank).filter(
                FuelTank.id == payload.tank_id, FuelTank.owner_phone == owner_phone).first()
            if not tank:
                raise HTTPException(status_code=404, detail="Tank not found.")
            delivery = FuelDelivery(
                owner_phone=owner_phone,
                branch_id=tank.branch_id,
                tank_id=tank.id,
                product=tank.product,
                litres=payload.litres,
                cost_per_litre=payload.cost_per_litre,
                supplier=(payload.supplier or "").strip() or None,
                waybill=(payload.waybill or "").strip() or None,
                delivered_at=utcnow(),
                recorded_by_id=session["user_id"],
            )
            db.add(delivery)
            # Deliveries raise the tank level.
            tank.current_level_litres = (tank.current_level_litres or 0) + payload.litres
            tank.updated_at = utcnow()
            db.commit()
            return {"ok": True, "tank_level": tank.current_level_litres}
        finally:
            db.close()

    # ── shifts (attendant meter reconciliation) ──────────────────────────────
    @app.get("/app/api/fuel/shifts")
    def fuel_list_shifts(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            eff_branch, _rec = _scoped_read(db, session)
            q = db.query(FuelShift).filter(FuelShift.owner_phone == owner_phone)
            if eff_branch is not None:
                q = q.filter(FuelShift.branch_id == eff_branch)
            rows = q.order_by(FuelShift.opened_at.desc()).limit(100).all()
            return {"shifts": [
                {"id": s.id, "pump_id": s.pump_id, "product": s.product,
                 "attendant_name": s.attendant_name, "shift_label": s.shift_label,
                 "opening_meter": s.opening_meter, "closing_meter": s.closing_meter,
                 "price_per_litre": s.price_per_litre, "litres_sold": s.litres_sold,
                 "expected_amount": _money(s.expected_amount),
                 "cash_amount": _money(s.cash_amount), "pos_amount": _money(s.pos_amount),
                 "transfer_amount": _money(s.transfer_amount), "credit_amount": _money(s.credit_amount),
                 "shortfall": _money(s.shortfall), "status": s.status,
                 "opened_at": _iso(s.opened_at), "closed_at": _iso(s.closed_at)}
                for s in rows
            ]}
        finally:
            db.close()

    @app.post("/app/api/fuel/shifts/open")
    def fuel_open_shift(payload: ShiftOpenRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)   # any staff may open their shift
            pump = db.query(FuelPump).filter(
                FuelPump.id == payload.pump_id, FuelPump.owner_phone == owner_phone).first()
            if not pump:
                raise HTTPException(status_code=404, detail="Pump not found.")
            existing = db.query(FuelShift).filter(
                FuelShift.pump_id == pump.id, FuelShift.status == "open").first()
            if existing:
                raise HTTPException(status_code=409, detail="This pump already has an open shift. Close it first.")

            attendant_name = None
            if payload.attendant_id:
                att = db.query(User).filter(User.id == payload.attendant_id).first()
                attendant_name = att.name if att else None
            else:
                me = _session_user(db, session)
                attendant_name = me.name if me else None
                payload.attendant_id = session["user_id"]

            opening = payload.opening_meter if payload.opening_meter is not None else (pump.current_meter or 0.0)
            price = _current_price(db, owner_phone, pump.branch_id, pump.product)
            shift = FuelShift(
                owner_phone=owner_phone,
                branch_id=pump.branch_id,
                pump_id=pump.id,
                product=pump.product,
                attendant_id=payload.attendant_id,
                attendant_name=attendant_name,
                shift_label=(payload.shift_label or "").strip() or None,
                opening_meter=opening,
                price_per_litre=price,
                status="open",
                opened_at=utcnow(),
                recorded_by_id=session["user_id"],
            )
            db.add(shift)
            db.commit()
            db.refresh(shift)
            return {"id": shift.id, "opening_meter": shift.opening_meter,
                    "price_per_litre": shift.price_per_litre}
        finally:
            db.close()

    @app.post("/app/api/fuel/shifts/{shift_id}/close")
    def fuel_close_shift(shift_id: int, payload: ShiftCloseRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            shift = db.query(FuelShift).filter(
                FuelShift.id == shift_id, FuelShift.owner_phone == owner_phone).first()
            if not shift:
                raise HTTPException(status_code=404, detail="Shift not found.")
            if shift.status == "closed":
                raise HTTPException(status_code=409, detail="This shift is already closed.")
            if payload.closing_meter < (shift.opening_meter or 0):
                raise HTTPException(status_code=400, detail="Closing meter cannot be less than the opening meter.")

            litres = round(payload.closing_meter - (shift.opening_meter or 0), 2)
            expected = int(round(litres * (shift.price_per_litre or 0)))
            collected = (payload.cash_amount or 0) + (payload.pos_amount or 0) \
                + (payload.transfer_amount or 0) + (payload.credit_amount or 0)

            shift.closing_meter = payload.closing_meter
            shift.litres_sold = litres
            shift.expected_amount = expected
            shift.cash_amount = payload.cash_amount or 0
            shift.pos_amount = payload.pos_amount or 0
            shift.transfer_amount = payload.transfer_amount or 0
            shift.credit_amount = payload.credit_amount or 0
            shift.shortfall = expected - collected
            shift.status = "closed"
            shift.closed_at = utcnow()

            # Roll the pump meter forward and draw the litres from its tank.
            pump = db.query(FuelPump).filter(FuelPump.id == shift.pump_id).first()
            if pump:
                pump.current_meter = payload.closing_meter
                if pump.tank_id:
                    tank = db.query(FuelTank).filter(FuelTank.id == pump.tank_id).first()
                    if tank:
                        tank.current_level_litres = (tank.current_level_litres or 0) - litres
                        tank.updated_at = utcnow()
            db.commit()
            return {"ok": True, "litres_sold": litres, "expected_amount": _money(expected),
                    "collected": _money(collected), "shortfall": _money(shift.shortfall)}
        finally:
            db.close()

    # ── dips (wet-stock variance) ────────────────────────────────────────────
    @app.get("/app/api/fuel/dips")
    def fuel_list_dips(session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            eff_branch, _rec = _scoped_read(db, session)
            q = db.query(FuelDip).filter(FuelDip.owner_phone == owner_phone)
            if eff_branch is not None:
                q = q.filter(FuelDip.branch_id == eff_branch)
            rows = q.order_by(FuelDip.dipped_at.desc()).limit(100).all()
            return {"dips": [
                {"id": d.id, "tank_id": d.tank_id, "dipped_litres": d.dipped_litres,
                 "computed_litres": d.computed_litres, "variance_litres": d.variance_litres,
                 "note": d.note, "dipped_at": _iso(d.dipped_at)}
                for d in rows
            ]}
        finally:
            db.close()

    @app.post("/app/api/fuel/dips")
    def fuel_add_dip(payload: DipRequest, session: dict = Depends(require_web_auth)):
        db = SessionLocal()
        try:
            owner_phone = _fuel_owner(db, session)
            tank = db.query(FuelTank).filter(
                FuelTank.id == payload.tank_id, FuelTank.owner_phone == owner_phone).first()
            if not tank:
                raise HTTPException(status_code=404, detail="Tank not found.")
            computed = tank.current_level_litres or 0.0
            variance = round(payload.dipped_litres - computed, 2)
            dip = FuelDip(
                owner_phone=owner_phone,
                branch_id=tank.branch_id,
                tank_id=tank.id,
                dipped_litres=payload.dipped_litres,
                computed_litres=computed,
                variance_litres=variance,
                note=(payload.note or "").strip() or None,
                dipped_at=utcnow(),
                recorded_by_id=session["user_id"],
            )
            db.add(dip)
            db.commit()
            # The dip records variance for investigation; it does NOT silently
            # overwrite the book level (that would hide losses/theft).
            return {"ok": True, "computed_litres": computed, "variance_litres": variance}
        finally:
            db.close()
