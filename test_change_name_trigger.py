"""
"Change business name" launches the re-onboarding wizard for imperative
phrasings, while questions ("how do I…") still route to the how-to answer.
"""
from parser import parse_message


def _is_wizard(t):
    p = parse_message(t)
    return bool(p and p.get("type") == "REONBOARD")


def test_imperatives_launch_wizard():
    for t in [
        "change name", "change business name", "change my business name",
        "i want to change my business name", "update my shop name",
        "rename my business name", "edit business name", "update business name",
    ]:
        assert _is_wizard(t), t


def test_questions_do_not_launch_wizard():
    # These should fall through to the how-to FAQ, not the wizard.
    for t in [
        "how do i change my business name",
        "can i change my business name",
        "what is my business name",
    ]:
        assert not _is_wizard(t), t
