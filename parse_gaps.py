"""
What people asked tiTi that tiTi could not answer.

Two tables have been collecting the answer to "what should we teach it next"
and nothing has ever read them. `failed_parses` holds every message tiTi did
not understand; `parse_logs` holds what it thought a message meant **and what
the user corrected it to** — the second is rarer and worth more, because the
right answer is written next to the wrong one.

A list of five thousand raw messages is not useful. What is useful is "forty
people asked this same thing in two different ways", so messages are grouped by
what they are asking rather than by their exact wording, counted by how many
separate businesses hit them, and sorted by how much teaching one fix would buy.

No language model. Normalising, grouping, counting.
"""
import re
from collections import defaultdict
from datetime import timedelta

from models import FailedParse, ParseLog, utcnow

# Words that say nothing about what is being asked. Dropping them lets "how
# much do I pay for rice" and "what do I pay for rice" land in one group.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am", "do", "does",
    "did", "doing", "have", "has", "had", "i", "me", "my", "we", "our", "you",
    "your", "it", "its", "this", "that", "these", "those", "to", "of", "for",
    "in", "on", "at", "by", "with", "and", "or", "but", "so", "if", "then",
    "please", "abeg", "pls", "plz", "hello", "hi", "hey", "titi", "tell", "show",
    "give", "want", "need", "can", "could", "would", "should", "will", "just",
    "now", "today", "again", "ok", "okay", "thanks", "thank", "sir", "ma",
    "na", "dey", "wetin", "abi",
    # Question words say what *kind* of message this is, not what it is about —
    # and that is already recorded as its shape. Leaving them in splits one
    # question into several: "how much do I pay for rice" and "what do I pay for
    # rice" are the same gap.
    "how", "what", "when", "where", "which", "who", "why", "much", "many",
}

# Shapes that say what kind of message it was, so the biggest group is not just
# "things with numbers in them".
_QUESTION_WORDS = re.compile(
    r"\b(how|what|when|where|which|who|why|is|are|can|do|does|did|should)\b", re.I)
_MONEY = re.compile(r"\b\d{3,}\b|\bk\b|₦|naira", re.I)
_TRANSACTION_HINT = re.compile(
    r"\b(sold|sell|bought|buy|paid|pay|received|add|stock|credit|balance|owe)\b", re.I)


def _normalise(text):
    """Strip everything that varies between two people asking the same thing."""
    text = (text or "").lower().strip()
    text = re.sub(r"[₦$]|\bngn\b", " ", text)
    text = re.sub(r"\b\d[\d,.]*\s*k?\b", " <num> ", text)   # amounts and quantities
    text = re.sub(r"[^\w\s<>]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text):
    return {w for w in _normalise(text).split()
            if w not in _STOPWORDS and (len(w) > 2 or w == "<num>")}


def _signature(text, shared=None):
    """What the message is about, with the wording thrown away.

    `shared` is the set of words that appear in more than one message in the
    batch. Filtering to those drops the names: "ade collect 2 bag rice" and
    "tunde collect 1 bag rice" are one gap in the parser, and the only thing
    separating them is a customer. A message with nothing in common with any
    other keeps all its own words rather than becoming an empty group.
    """
    words = _tokens(text)
    if shared is not None:
        common = words & shared
        if common:
            words = common
    return " ".join(sorted(words)[:8])


def _shared_words(texts):
    """Words that show up in more than one message — the topic, not the people."""
    seen, repeated = set(), set()
    for text in texts:
        for word in _tokens(text):
            if word in seen:
                repeated.add(word)
            else:
                seen.add(word)
    return repeated


def _shape(text):
    """Roughly what the person was trying to do — a question, a transaction, or
    something we cannot place. It decides who should fix it: a question is a
    fact to register, a transaction is a parser rule."""
    has_question = bool(_QUESTION_WORDS.search(text or ""))
    has_money = bool(_MONEY.search(text or ""))
    has_action = bool(_TRANSACTION_HINT.search(text or ""))
    if has_question and not (has_money and has_action):
        return "question"
    if has_action and has_money:
        return "transaction"
    if has_question:
        return "question"
    return "unclear"


def unanswered(db, days=90, limit=40, min_count=1):
    """The questions tiTi could not answer, grouped and ranked.

    Ranked by how many separate businesses hit each group, not by raw count —
    one person sending the same thing twenty times is a support conversation,
    twenty people sending it once is a feature.
    """
    since = utcnow() - timedelta(days=max(1, days))
    rows = (db.query(FailedParse)
            .filter(FailedParse.created_at >= since)
            .order_by(FailedParse.created_at.desc())
            .limit(20_000).all())

    shared = _shared_words([(r.text or "") for r in rows])
    groups = defaultdict(lambda: {"count": 0, "businesses": set(), "examples": [],
                                  "last_seen": None, "shape": "unclear"})
    for row in rows:
        text = (row.text or "").strip()
        if not text:
            continue
        signature = _signature(text, shared)
        if not signature:
            continue
        group = groups[signature]
        group["count"] += 1
        group["businesses"].add(row.owner_phone or row.phone)
        group["shape"] = _shape(text)
        if len(group["examples"]) < 3 and text not in group["examples"]:
            group["examples"].append(text)
        if group["last_seen"] is None or (row.created_at and row.created_at > group["last_seen"]):
            group["last_seen"] = row.created_at

    out = []
    for signature, group in groups.items():
        if group["count"] < min_count:
            continue
        out.append({
            "signature": signature,
            "shape": group["shape"],
            "count": group["count"],
            "businesses": len(group["businesses"]),
            "examples": group["examples"],
            "last_seen": group["last_seen"].isoformat() if group["last_seen"] else None,
        })
    out.sort(key=lambda g: (g["businesses"], g["count"]), reverse=True)
    return out[:limit]


def misreadings(db, days=90, limit=40):
    """Where tiTi understood something and the user corrected it.

    The most valuable rows we hold: the wrong reading and the right one, side
    by side, written by the person who knew.
    """
    since = utcnow() - timedelta(days=max(1, days))
    rows = (db.query(ParseLog)
            .filter(ParseLog.created_at >= since,
                    ParseLog.was_confirmed == False,          # noqa: E712
                    ParseLog.correction_input.isnot(None))
            .order_by(ParseLog.created_at.desc())
            .limit(5_000).all())

    shared = _shared_words([(r.raw_input or "") for r in rows])
    groups = defaultdict(lambda: {"count": 0, "businesses": set(), "pairs": [],
                                  "parsed_type": None})
    for row in rows:
        original = (row.raw_input or "").strip()
        corrected = (row.correction_input or "").strip()
        if not original or not corrected:
            continue
        signature = _signature(original, shared)
        if not signature:
            continue
        group = groups[signature]
        group["count"] += 1
        group["businesses"].add(row.owner_phone or row.phone)
        group["parsed_type"] = row.parsed_type
        if len(group["pairs"]) < 3:
            group["pairs"].append({"said": original, "meant": corrected})

    out = [{
        "signature": signature,
        "count": group["count"],
        "businesses": len(group["businesses"]),
        "parsed_type": group["parsed_type"],
        "pairs": group["pairs"],
    } for signature, group in groups.items()]
    out.sort(key=lambda g: (g["businesses"], g["count"]), reverse=True)
    return out[:limit]


def summary(db, days=90):
    """The headline: how often tiTi is failing, and on what."""
    since = utcnow() - timedelta(days=max(1, days))
    total = db.query(FailedParse).filter(FailedParse.created_at >= since).count()
    groups = unanswered(db, days=days, limit=1_000)
    by_shape = defaultdict(int)
    for group in groups:
        by_shape[group["shape"]] += group["count"]
    return {
        "days": days,
        "messages": total,
        "distinct_questions": len(groups),
        "questions": by_shape.get("question", 0),
        "transactions": by_shape.get("transaction", 0),
        "unclear": by_shape.get("unclear", 0),
        "businesses_affected": len({
            r[0] for r in db.query(FailedParse.owner_phone)
            .filter(FailedParse.created_at >= since).all() if r[0]
        }),
    }
