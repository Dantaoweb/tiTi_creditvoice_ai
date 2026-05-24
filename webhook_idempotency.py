from models import ProcessedMessage


def record_processed_message(db, message_id):
    already_processed = db.query(ProcessedMessage).filter(
        ProcessedMessage.message_id == message_id
    ).first()

    if already_processed:
        return {"status": "duplicate"}

    db.add(ProcessedMessage(message_id=message_id))
    try:
        db.commit()
    except Exception:
        return {"status": "duplicate_race_condition"}

    return None
