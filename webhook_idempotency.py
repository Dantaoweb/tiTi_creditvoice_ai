from sqlalchemy import inspect

from models import ProcessedMessage


def record_processed_message(db, message_id):
    already_processed = db.query(ProcessedMessage).filter(
        ProcessedMessage.message_id == message_id
    ).first()

    if already_processed:
        return {"status": "duplicate"}

    processed_message = ProcessedMessage(message_id=message_id)
    if db.bind.dialect.name == "sqlite":
        db_columns = {
            column["name"]: str(column["type"]).upper()
            for column in inspect(db.bind).get_columns("processed_messages")
        }
        if not db_columns.get("id", "").startswith("INTEGER"):
            processed_message.id = message_id

    db.add(processed_message)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        print("Processed message insert failed:", repr(exc), flush=True)
        return {"status": "duplicate_race_condition"}

    return None
