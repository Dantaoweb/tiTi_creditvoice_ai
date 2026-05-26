import re

from datetime import datetime, timedelta

from sqlalchemy import func

from item_normalizer import normalize_item
from models import (
    InventoryItem,
    InventoryMovement,
    Supplier,
    SupplierPayment,
    SupplierPurchase,
)


def find_or_create_supplier(db, owner_phone, supplier_name):
    supplier_name = supplier_name.strip().lower()
    supplier = db.query(Supplier).filter(
        Supplier.owner_phone == owner_phone,
        func.lower(Supplier.name) == supplier_name
    ).first()
    if supplier:
        return supplier
    supplier = Supplier(name=supplier_name, owner_phone=owner_phone)
    db.add(supplier)
    db.flush()
    return supplier


def find_inventory_item(db, owner_phone, product, unit=None):
    product, unit = normalize_item(product, unit)
    query = db.query(InventoryItem).filter(
        InventoryItem.owner_phone == owner_phone,
        func.lower(InventoryItem.name) == product.lower()
    )
    if unit:
        query = query.filter(InventoryItem.unit == unit)
    else:
        query = query.filter(InventoryItem.unit.is_(None))
    return query.first()


def find_matching_inventory_item(db, owner_phone, product, unit=None):
    product, unit = normalize_item(product, unit)
    item = find_inventory_item(db, owner_phone, product, unit)
    if item:
        return item

    if unit:
        legacy_name = f"{unit} of {product}".lower()
        item = find_inventory_item(db, owner_phone, legacy_name, None)
        if item:
            return item

    unit_match = re.match(r"^(?P<unit>[a-z]+)\s+of\s+(?P<product>.+)$", product.lower())
    if unit_match:
        item = find_inventory_item(
            db,
            owner_phone,
            unit_match.group("product"),
            unit_match.group("unit"),
        )
        if item:
            return item

    return None


def add_inventory_movement(db, owner_phone, product, quantity, unit, unit_price, movement_type, source_type, source_id, recorded_by_id=None, note=None):
    if not product or not quantity:
        return None
    product, unit = normalize_item(product, unit)
    item = find_matching_inventory_item(db, owner_phone, product, unit)
    if not item:
        item = InventoryItem(
            owner_phone=owner_phone,
            name=product.lower(),
            unit=unit,
            quantity=0,
            cost_price=unit_price
        )
        db.add(item)
        db.flush()

    if movement_type == "IN":
        item.quantity = (item.quantity or 0) + quantity
        if unit_price:
            item.cost_price = unit_price
    elif movement_type == "OUT":
        item.quantity = (item.quantity or 0) - quantity
    else:
        item.quantity = (item.quantity or 0) + quantity
    item.updated_at = datetime.utcnow()

    movement = InventoryMovement(
        owner_phone=owner_phone,
        item_id=item.id,
        movement_type=movement_type,
        quantity=quantity,
        unit_price=unit_price,
        source_type=source_type,
        source_id=source_id,
        recorded_by_id=recorded_by_id,
        note=note
    )
    db.add(movement)
    return item


def deduct_inventory_for_items(db, owner_phone, items, source_type, source_id, recorded_by_id=None):
    updates = []
    missing = []
    for item_data in items or []:
        product = (item_data.get("product") or "").lower().strip()
        quantity = item_data.get("quantity") or 1
        unit = item_data.get("unit")
        product, unit = normalize_item(product, unit)
        if not product:
            continue
        item = find_matching_inventory_item(db, owner_phone, product, unit)
        if not item:
            missing.append(product.title())
            continue
        add_inventory_movement(
            db,
            owner_phone,
            product,
            quantity,
            unit,
            item_data.get("unit_price"),
            "OUT",
            source_type,
            source_id,
            recorded_by_id,
            "Sold"
        )
        unit_label = f" {unit}" if unit else ""
        updates.append(f"{product.title()}: {item.quantity:,}{unit_label} left")
    return updates, missing


def get_supplier_balance(db, supplier_id):
    total_purchase = db.query(func.coalesce(func.sum(SupplierPurchase.total), 0)).filter(
        SupplierPurchase.supplier_id == supplier_id
    ).scalar()
    paid_on_purchase = db.query(func.coalesce(func.sum(SupplierPurchase.paid_amount), 0)).filter(
        SupplierPurchase.supplier_id == supplier_id
    ).scalar()
    payments = db.query(func.coalesce(func.sum(SupplierPayment.amount), 0)).filter(
        SupplierPayment.supplier_id == supplier_id
    ).scalar()
    return total_purchase - paid_on_purchase - payments


def build_inventory_list_message(db, owner_phone, product=None):
    query = db.query(InventoryItem).filter(InventoryItem.owner_phone == owner_phone)
    if product:
        query = query.filter(func.lower(InventoryItem.name).like(f"%{product.lower()}%"))
    items = query.order_by(InventoryItem.name.asc()).limit(20).all()
    if not items:
        return "No stock found yet.\n\nTo add stock, send:\nAyo supply me 12kg cocoa at 5000"

    title = "Stock" if not product else f"Stock: {product.title()}"
    msg = f"{title}\n\n"
    for index, item in enumerate(items, start=1):
        unit = f" {item.unit}" if item.unit else ""
        value = (item.quantity or 0) * (item.cost_price or 0)
        msg += f"{index}. {item.name.title()}: {item.quantity:,}{unit}"
        if item.cost_price:
            msg += f" | Cost: N{item.cost_price:,} | Value: N{value:,}"
        msg += "\n"
    return msg.strip()


def build_supplier_list_message(db, owner_phone):
    suppliers = db.query(Supplier).filter(
        Supplier.owner_phone == owner_phone
    ).order_by(Supplier.name.asc()).limit(20).all()
    if not suppliers:
        return "No supplier record yet.\n\nExample:\nAyo supply me 12kg cocoa at 5000"

    msg = "Suppliers You Owe\n\n"
    total = 0
    count = 0
    for supplier in suppliers:
        balance = get_supplier_balance(db, supplier.id)
        if balance <= 0:
            continue
        count += 1
        total += balance
        msg += f"{count}. {supplier.name.title()} - N{balance:,}\n"
    if count == 0:
        return "No supplier debt right now."
    msg += f"\nTotal supplier debt: N{total:,}"
    return msg


def build_supplier_due_message(db, owner_phone):
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    purchases = db.query(SupplierPurchase, Supplier).join(
        Supplier,
        SupplierPurchase.supplier_id == Supplier.id
    ).filter(
        SupplierPurchase.owner_phone == owner_phone,
        SupplierPurchase.due_date >= start,
        SupplierPurchase.due_date < end
    ).order_by(SupplierPurchase.due_date.asc()).all()
    if not purchases:
        return "No supplier payment due today."

    msg = "Supplier Due Today\n\n"
    count = 0
    for purchase, supplier in purchases:
        balance = max((purchase.total or 0) - (purchase.paid_amount or 0), 0)
        if balance == 0:
            continue
        count += 1
        msg += f"{count}. {supplier.name.title()} - N{balance:,} for {purchase.product.title()}\n"
    return msg.strip() if count else "No supplier payment due today."
