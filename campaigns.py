"""
Who sees an in-app card, and when it stops.

The rules here are the whole feature. A card that interrupts the wrong person,
or the right person too often, costs more than it earns — so a campaign reaches
someone only when they have used the app enough to have an opinion, it is
capped and snoozed when closed, and it stops on its own the moment they do the
thing it asked for.

The copy, the artwork and every threshold are admin-editable; nothing here is
written for one campaign.
"""
import logging
from datetime import timedelta

from models import Campaign, CampaignView, Transaction, User, utcnow

_log = logging.getLogger(__name__)

# A campaign with a goal stops asking once the goal is met. Each goal answers
# one question: has this business already done it?
GOALS = {
    "review": lambda db, user: _has_review(db, user),
    "upgrade": lambda db, user: (user.subscription_plan or "BASIC").upper() != "BASIC",
}


def _has_review(db, user):
    from models import Testimonial
    return bool(
        db.query(Testimonial.id)
        .filter(Testimonial.owner_phone == user.phone)
        .first()
    )


def goal_reached(db, campaign, user):
    check = GOALS.get((campaign.goal or "").strip().lower())
    if not check:
        return False
    try:
        return bool(check(db, user))
    except Exception:
        _log.exception("campaign goal check failed for %s", campaign.key)
        return False


def _recorded_count(db, user):
    """How much this business has actually recorded — voided entries excluded,
    because a cancelled sale is not experience with the app."""
    from reports import get_owner_transaction_query

    owner_phone = user.phone if not user.parent_id else None
    if owner_phone is None:
        parent = db.query(User).filter(User.id == user.parent_id).first()
        owner_phone = parent.phone if parent else user.phone
    try:
        return get_owner_transaction_query(db, owner_phone).count()
    except Exception:
        _log.exception("campaign transaction count failed")
        return 0


def _days_active(user):
    if not user.created_at:
        return 0
    return max(0, (utcnow() - user.created_at).days)


def _plans_allowed(campaign):
    raw = (campaign.plans or "").strip()
    if not raw:
        return None                      # every plan
    return {p.strip().upper() for p in raw.split(",") if p.strip()}


def _view(db, campaign, user, create=False):
    view = (
        db.query(CampaignView)
        .filter(CampaignView.campaign_id == campaign.id,
                CampaignView.user_phone == user.phone)
        .first()
    )
    if view is None and create:
        view = CampaignView(campaign_id=campaign.id, user_phone=user.phone)
        db.add(view)
    return view


def is_eligible(db, campaign, user, view=None, now=None):
    """Everything that must be true before a card interrupts someone."""
    now = now or utcnow()

    if not campaign.is_active:
        return False
    if campaign.starts_at and now < campaign.starts_at:
        return False
    if campaign.ends_at and now > campaign.ends_at:
        return False

    # Staff are not the ones who speak for the business or pay for it.
    if campaign.owners_only and user.parent_id:
        return False

    allowed = _plans_allowed(campaign)
    if allowed and (user.subscription_plan or "BASIC").upper() not in allowed:
        return False

    if (campaign.min_days_active or 0) > _days_active(user):
        return False
    if (campaign.min_transactions or 0) > 0:
        if _recorded_count(db, user) < campaign.min_transactions:
            return False

    if goal_reached(db, campaign, user):
        return False

    view = view if view is not None else _view(db, campaign, user)
    if view:
        if view.completed_at:
            return False
        if view.snooze_until and now < view.snooze_until:
            return False
        if (campaign.max_shows or 0) > 0 and (view.shown_count or 0) >= campaign.max_shows:
            return False
    return True


def next_for_user(db, user, now=None):
    """The one card to show, or None. Never two at once — an app that stacks
    pop-ups is an app people learn to dismiss without reading."""
    now = now or utcnow()
    candidates = (
        db.query(Campaign)
        .filter(Campaign.is_active == True)        # noqa: E712
        .order_by(Campaign.priority.desc(), Campaign.created_at.asc())
        .all()
    )
    for campaign in candidates:
        try:
            if is_eligible(db, campaign, user, now=now):
                return campaign
        except Exception:
            _log.exception("campaign eligibility failed for %s", campaign.key)
    return None


def mark_shown(db, campaign, user, now=None):
    now = now or utcnow()
    view = _view(db, campaign, user, create=True)
    view.shown_count = (view.shown_count or 0) + 1
    view.first_shown_at = view.first_shown_at or now
    view.last_shown_at = now
    db.commit()
    return view


def mark_clicked(db, campaign, user, now=None):
    now = now or utcnow()
    view = _view(db, campaign, user, create=True)
    view.clicked_at = now
    db.commit()
    return view


def mark_dismissed(db, campaign, user, now=None):
    """Closing it buys quiet for the snooze period, not forever — unless they
    have now seen it as many times as the campaign allows."""
    now = now or utcnow()
    view = _view(db, campaign, user, create=True)
    view.dismissed_at = now
    view.snooze_until = now + timedelta(days=max(0, campaign.snooze_days or 0))
    db.commit()
    return view


def mark_goal_done(db, goal, user, now=None):
    """Called when someone does the thing a campaign asked for.

    Eligibility already stops asking — `goal_reached` sees the review — so this
    exists for the count on the admin screen: a campaign is only worth keeping
    if you can see how many people it actually moved.
    """
    now = now or utcnow()
    done = 0
    try:
        for campaign in db.query(Campaign).filter(Campaign.goal == goal).all():
            view = _view(db, campaign, user, create=True)
            if not view.completed_at:
                view.completed_at = now
                done += 1
        if done:
            db.commit()
    except Exception:
        _log.exception("could not record campaign goal %s", goal)
    return done


def deliver_notifications(db, limit_per_campaign=500, now=None):
    """Put live campaigns into the bell (and push) for the people they target.

    The card alone only reaches someone who opens the dashboard. This is what
    reaches the rest — and what survives a dismissal, because the bell keeps it.
    Each person is told once per campaign: `notified_at` is the guard.

    Returns a count per campaign key, for the scheduler log.
    """
    from feature_flags import whatsapp_live
    from web_common import _add_notification

    now = now or utcnow()
    sent = {}
    wa_live = whatsapp_live(db)

    live = (
        db.query(Campaign)
        .filter(Campaign.is_active == True,                 # noqa: E712
                Campaign.also_notify == True)               # noqa: E712
        .order_by(Campaign.priority.desc())
        .all()
    )
    if not live:
        return sent

    owners = db.query(User).filter(User.parent_id.is_(None),
                                   User.deleted_at.is_(None)).all()

    for campaign in live:
        count = 0
        for user in owners:
            if count >= limit_per_campaign:
                break
            try:
                view = _view(db, campaign, user)
                if view and view.notified_at:
                    continue
                if not is_eligible(db, campaign, user, view=view, now=now):
                    continue

                _add_notification(db, user.phone, "campaign",
                                  campaign.title, campaign.body,
                                  link=campaign.cta_link)
                if campaign.also_whatsapp and wa_live:
                    # Only when Meta has approved the number — otherwise this is
                    # a message that silently never arrives.
                    from whatsapp_client import send_whatsapp_message
                    try:
                        send_whatsapp_message(user.phone, f"*{campaign.title}*\n\n{campaign.body}")
                    except Exception:
                        _log.exception("campaign whatsapp send failed")

                view = _view(db, campaign, user, create=True)
                view.notified_at = now
                db.commit()
                count += 1
            except Exception:
                db.rollback()
                _log.exception("campaign notification failed for %s", campaign.key)
        if count:
            sent[campaign.key or campaign.id] = count
    return sent


def stats(db, campaign):
    """Shown / clicked / dismissed / completed, for the admin screen."""
    from sqlalchemy import func

    row = (
        db.query(
            func.count(CampaignView.id),
            func.coalesce(func.sum(CampaignView.shown_count), 0),
            func.count(CampaignView.clicked_at),
            func.count(CampaignView.dismissed_at),
            func.count(CampaignView.completed_at),
        )
        .filter(CampaignView.campaign_id == campaign.id)
        .one()
    )
    people, shows, clicked, dismissed, completed = row
    return {
        "people": int(people or 0),
        "shows": int(shows or 0),
        "clicked": int(clicked or 0),
        "dismissed": int(dismissed or 0),
        "completed": int(completed or 0),
    }
