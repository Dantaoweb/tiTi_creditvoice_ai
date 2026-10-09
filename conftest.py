import calendar
import os
from datetime import datetime, timedelta

# Provide an in-memory SQLite database for all tests that don't set their own URL.
# This must run before any module that imports database.py.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Tests never reach the public product database; tests that need it fake it.
os.environ.setdefault("BARCODE_LOOKUP", "off")


def month_slot(months_back, slot=0, days_apart=5, per_month=1):
    """A timestamp inside ONE calendar month, `months_back` months ago.

    The scorecard buckets revenue by calendar month. Seeding with 30-day
    arithmetic (`utcnow() - timedelta(days=30 * m + …)`) splits a "month" of
    sales across two buckets whenever today's day-of-month is small, so
    months_recorded, the monthly average and the worst month all change with the
    date the suite happens to run on. This anchors every slot to a day that
    exists in each month, and never to a day in the future.

    `slot` spreads the sales within the month `days_apart` days apart, so a test
    can still control how many active days a month has.
    """
    from models import utcnow

    now = utcnow()
    span = max(0, (per_month - 1)) * days_apart
    # Seed into the current month only if it is far enough in to hold every
    # slot; otherwise start from the last day of the previous month.
    if now.day > span:
        anchor = now
    else:
        anchor = now.replace(day=1) - timedelta(days=1)

    year, month = anchor.year, anchor.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    day = max(1, min(anchor.day - slot * days_apart, calendar.monthrange(year, month)[1]))

    when = datetime(year, month, day, 9, 0)
    if when > now:                       # same day, earlier in the day
        when = now - timedelta(hours=1)
    return when
