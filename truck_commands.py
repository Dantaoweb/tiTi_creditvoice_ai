"""
Truck wizard flows for energy & quarry businesses.

Two wizards:
  ADD TRUCK   — step-by-step: plate → driver name → driver phone → save
  RECORD TRIP — step-by-step: truck → product → quantity+unit → price → confirm
"""

import json
import re

from constants import (
    ACTION_TRUCK_ADD_PLATE,
    ACTION_TRUCK_ADD_DRIVER,
    ACTION_TRUCK_ADD_PHONE,
    ACTION_TRIP_TRUCK,
    ACTION_TRIP_PRODUCT,
    ACTION_TRIP_QTY,
    ACTION_TRIP_PRICE,
    ACTION_TRIP_CONFIRM,
)
from models import Customer, PendingAction


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load(pending):
    try:
        return json.loads(pending.payload_json or "{}")
    except Exception:
        return {}


def _save(pending, data):
    pending.payload_json = json.dumps(data)


def _clear_and_create(db, phone, action, payload):
    db.query(PendingAction).filter(PendingAction.phone == phone).delete()
    p = PendingAction(
        phone=phone,
        action=action,
        customer_name="",
        last_customer="",
        payload_json=json.dumps(payload),
    )
    db.add(p)
    db.commit()
    return p


# ─────────────────────────────────────────────────────────────────────────────
# ADD TRUCK WIZARD
# ─────────────────────────────────────────────────────────────────────────────

def start_add_truck_wizard(db, phone, send_message, plate=None):
    """Entry: user typed 'add truck' with no plate, or from menu."""
    if plate:
        _clear_and_create(db, phone, ACTION_TRUCK_ADD_DRIVER, {"plate": plate})
        send_message(phone, f"Truck *{plate}*\n\nDriver name? (or send *skip*)")
    else:
        _clear_and_create(db, phone, ACTION_TRUCK_ADD_PLATE, {})
        send_message(phone, "Enter truck plate number:\n(e.g. KJA 234 AB)")


def handle_add_truck_pending(db, phone, text, pending, send_message):
    action = pending.action
    payload = _load(pending)
    normalized = text.strip().lower()

    if action == ACTION_TRUCK_ADD_PLATE:
        plate = text.strip().upper()
        if len(plate) < 3:
            send_message(phone, "Plate number too short. Try again:\n(e.g. KJA 234 AB)")
            return {"status": "truck_plate_retry"}
        pending.action = ACTION_TRUCK_ADD_DRIVER
        _save(pending, {"plate": plate})
        db.commit()
        send_message(phone, f"Truck *{plate}*\n\nDriver name? (or send *skip*)")
        return {"status": "truck_plate_ok"}

    if action == ACTION_TRUCK_ADD_DRIVER:
        driver = "" if normalized == "skip" else text.strip().title()
        payload["driver"] = driver
        pending.action = ACTION_TRUCK_ADD_PHONE
        _save(pending, payload)
        db.commit()
        drv_line = f"Driver: {driver}\n" if driver else ""
        send_message(phone, f"Truck *{payload['plate']}*\n{drv_line}\nDriver WhatsApp number? (or send *skip*)")
        return {"status": "truck_driver_ok"}

    if action == ACTION_TRUCK_ADD_PHONE:
        plate = payload.get("plate", "")
        driver = payload.get("driver", "")
        driver_phone = ""
        if normalized != "skip":
            _ph = re.sub(r"\s+", "", text.strip())
            if re.match(r"^(0\d{10}|\+234\d{10})$", _ph):
                driver_phone = _ph
            else:
                send_message(phone, "Invalid number. Send a valid phone (e.g. 08012345678) or *skip*.")
                return {"status": "truck_phone_retry"}

        # Save or update truck customer
        existing = (
            db.query(Customer)
            .filter(
                Customer.owner_phone == phone,
                Customer.name.ilike(plate),
                Customer.is_truck.is_(True),
            )
            .first()
        )
        if existing:
            if driver:
                existing.category = driver
            if driver_phone:
                existing.secondary_phone = driver_phone
        else:
            truck = Customer(
                owner_phone=phone,
                name=plate,
                category=driver or None,
                secondary_phone=driver_phone or None,
                is_truck=True,
            )
            db.add(truck)

        db.delete(pending)
        db.commit()

        lines = [f"Truck registered."]
        lines.append(f"Plate:     *{plate}*")
        if driver:
            lines.append(f"Driver:    {driver}")
        if driver_phone:
            lines.append(f"Driver Ph: {driver_phone}")
        lines.append(f"\nTo record a trip, send:\nrecord trip")
        send_message(phone, "\n".join(lines))
        return {"status": "truck_registered"}

    db.delete(pending)
    db.commit()
    return {"status": "truck_wizard_unknown"}


# ─────────────────────────────────────────────────────────────────────────────
# RECORD TRIP WIZARD
# ─────────────────────────────────────────────────────────────────────────────

def _truck_list_message(trucks):
    lines = ["*Which truck?*\n"]
    for i, t in enumerate(trucks, 1):
        drv = f" — {t.category}" if t.category else ""
        lines.append(f"{i}. {t.name}{drv}")
    lines.append("\nReply the *number* or type the plate.")
    return "\n".join(lines)


def start_record_trip_wizard(db, phone, user, send_message):
    """Entry: user typed 'record trip' or pressed the menu option."""
    trucks = (
        db.query(Customer)
        .filter(
            Customer.owner_phone == phone,
            Customer.is_truck.is_(True),
        )
        .order_by(Customer.name)
        .all()
    )

    if not trucks:
        db.query(PendingAction).filter(PendingAction.phone == phone).delete()
        db.commit()
        send_message(
            phone,
            "No trucks registered yet.\n\nAdd one first:\nadd truck KJA234AB driver Emeka 08012345678"
        )
        return {"status": "trip_no_trucks"}

    _clear_and_create(db, phone, ACTION_TRIP_TRUCK, {
        "truck_ids": [t.id for t in trucks],
        "truck_names": [t.name for t in trucks],
    })
    send_message(phone, _truck_list_message(trucks))
    return {"status": "trip_wizard_started"}


def handle_record_trip_pending(db, phone, text, pending, user, business_owner_phone, send_message):
    action = pending.action
    payload = _load(pending)
    normalized = text.strip().lower()

    # ── Step 1: select truck ─────────────────────────────────────────────────
    if action == ACTION_TRIP_TRUCK:
        truck_names = payload.get("truck_names", [])
        truck_ids = payload.get("truck_ids", [])
        truck = None

        if normalized.isdigit():
            idx = int(normalized) - 1
            if 0 <= idx < len(truck_ids):
                truck = db.query(Customer).filter(Customer.id == truck_ids[idx]).first()
        else:
            # match by plate text
            truck = (
                db.query(Customer)
                .filter(
                    Customer.owner_phone == business_owner_phone,
                    Customer.name.ilike(f"%{text.strip()}%"),
                    Customer.is_truck.is_(True),
                )
                .first()
            )

        if not truck:
            send_message(phone, "Truck not found. Reply the number from the list or the plate number.")
            return {"status": "trip_truck_retry"}

        payload["truck_id"] = truck.id
        payload["truck_name"] = truck.name
        pending.action = ACTION_TRIP_PRODUCT
        _save(pending, payload)
        db.commit()

        # Build product hint from stock or catalog
        from business_templates import INDUSTRY_PRODUCT_CATALOG, template_key_for_user
        btype = getattr(user, "business_type", None)
        tkey = template_key_for_user(user)
        catalog = (
            INDUSTRY_PRODUCT_CATALOG.get(btype)
            or INDUSTRY_PRODUCT_CATALOG.get(tkey, [])
        )
        hint = ""
        if catalog:
            examples = [n for n, _ in catalog[:4]]
            hint = f"\n(e.g. {', '.join(examples)})"

        send_message(phone, f"Truck: *{truck.name}*\n\nWhat product / material?{hint}")
        return {"status": "trip_truck_selected"}

    # ── Step 2: product ──────────────────────────────────────────────────────
    if action == ACTION_TRIP_PRODUCT:
        product = text.strip().lower()
        if len(product) < 2:
            send_message(phone, "Please enter the product name (e.g. granite, diesel, sand).")
            return {"status": "trip_product_retry"}
        payload["product"] = product
        pending.action = ACTION_TRIP_QTY
        _save(pending, payload)
        db.commit()

        from business_templates import INDUSTRY_DEFAULT_UNITS, template_key_for_user
        tkey = template_key_for_user(user)
        units = INDUSTRY_DEFAULT_UNITS.get(tkey, ["units"])
        unit_hint = f" (e.g. 5000 {units[0]})" if units else ""
        send_message(phone, f"Product: *{product.title()}*\n\nQuantity and unit?{unit_hint}")
        return {"status": "trip_product_ok"}

    # ── Step 3: quantity + unit ──────────────────────────────────────────────
    if action == ACTION_TRIP_QTY:
        qty_m = re.match(
            r"^(?P<qty>[\d,]+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z][a-zA-Z\s]*)?\s*$",
            text.strip()
        )
        if not qty_m:
            send_message(phone, "Please enter quantity and unit (e.g. 5000 tonnes, 200 litres).")
            return {"status": "trip_qty_retry"}

        qty_raw = qty_m.group("qty").replace(",", "")
        try:
            qty = float(qty_raw)
        except ValueError:
            send_message(phone, "Invalid quantity. Try again (e.g. 5000 tonnes).")
            return {"status": "trip_qty_retry"}

        unit = (qty_m.group("unit") or "").strip() or "units"
        payload["quantity"] = qty
        payload["unit"] = unit
        pending.action = ACTION_TRIP_PRICE
        _save(pending, payload)
        db.commit()

        send_message(phone, f"Qty: *{qty:,.0f} {unit}*\n\nRate per {unit}? (e.g. 500)")
        return {"status": "trip_qty_ok"}

    # ── Step 4: unit price ───────────────────────────────────────────────────
    if action == ACTION_TRIP_PRICE:
        price_raw = re.sub(r"[,\s]", "", text.strip())
        # handle shorthand k/m
        if price_raw.lower().endswith("k"):
            price_raw = price_raw[:-1] + "000"
        elif price_raw.lower().endswith("m"):
            price_raw = price_raw[:-1] + "000000"
        try:
            price = int(float(price_raw))
        except ValueError:
            send_message(phone, "Invalid price. Enter the rate per unit (e.g. 500).")
            return {"status": "trip_price_retry"}

        qty = payload.get("quantity", 1)
        unit = payload.get("unit", "units")
        product = payload.get("product", "")
        truck_name = payload.get("truck_name", "")
        total = int(qty * price)

        payload["unit_price"] = price
        payload["total"] = total
        pending.action = ACTION_TRIP_CONFIRM
        _save(pending, payload)
        db.commit()

        send_message(
            phone,
            f"*Trip Summary*\n\n"
            f"Truck:   {truck_name}\n"
            f"Product: {product.title()}\n"
            f"Qty:     {qty:,.0f} {unit}\n"
            f"Rate:    N{price:,} per {unit}\n"
            f"Total:   N{total:,}\n\n"
            f"Reply *YES* to record or *EDIT* to restart."
        )
        return {"status": "trip_price_ok"}

    # ── Step 5: confirm ──────────────────────────────────────────────────────
    if action == ACTION_TRIP_CONFIRM:
        if normalized in ["no", "edit", "cancel", "back"]:
            db.delete(pending)
            db.commit()
            send_message(phone, "Trip cancelled. Send *record trip* to start again.")
            return {"status": "trip_cancelled"}

        if normalized not in ["yes", "y", "confirm", "ok", "save"]:
            send_message(phone, "Reply *YES* to save or *EDIT* to cancel.")
            return {"status": "trip_confirm_wait"}

        truck_id = payload.get("truck_id")
        product = payload.get("product", "")
        qty = payload.get("quantity", 1)
        unit = payload.get("unit", "units")
        unit_price = payload.get("unit_price", 0)
        total = payload.get("total", 0)

        truck = db.query(Customer).filter(Customer.id == truck_id).first()
        if not truck:
            db.delete(pending)
            db.commit()
            send_message(phone, "Truck not found. Please try again.")
            return {"status": "trip_truck_missing"}

        from models import Transaction
        from web_pos import next_receipt_number
        tx = Transaction(
            type="BUY",
            amount=total,
            product=product,
            quantity=int(qty),
            unit=unit,
            unit_price=unit_price,
            customer_id=truck.id,
            owner_phone=business_owner_phone,
            recorded_by_id=None,
            created_at=_utcnow(),
            receipt_number=next_receipt_number(db, business_owner_phone),
        )
        db.add(tx)
        db.delete(pending)
        db.commit()

        send_message(
            phone,
            f"Trip recorded.\n\n"
            f"Truck:   {truck.name}\n"
            f"Product: {product.title()}\n"
            f"Qty:     {qty:,.0f} {unit}\n"
            f"Total:   N{total:,}\n\n"
            f"Send *print receipt {truck.name}* for the ticket."
        )

        # Send receipt to driver's WhatsApp if phone on file
        if truck.secondary_phone:
            try:
                from business_templates import receipt_config_for_user, DEFAULT_RECEIPT_CONFIG
                from models import User as _U
                owner = db.query(_U).filter(_U.phone == business_owner_phone).first()
                cfg = receipt_config_for_user(owner) if owner else DEFAULT_RECEIPT_CONFIG
                business_name = (owner.name if owner else "") or "Business"
                from customer_commands import _build_reprint_receipt
                receipt = _build_reprint_receipt(db, business_name, business_owner_phone, truck, tx, total, cfg)
                send_message(truck.secondary_phone, receipt)
            except Exception:
                pass

        return {"status": "trip_saved"}

    db.delete(pending)
    db.commit()
    return {"status": "trip_wizard_unknown"}
