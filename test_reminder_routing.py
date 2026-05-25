from webhook_early_handlers import is_reminder_automation_text


def test_reminder_automation_text_is_reserved_for_main_router():
    reserved = [
        "reminder automation",
        "run reminder automation",
        "preview reminder automation",
        "reminder queue",
        "edit reminder 1 Please pay today",
        "send reminder 1",
        "skip reminder 1",
        "auto reminders on",
        "reminder time 8am",
    ]

    for text in reserved:
        assert is_reminder_automation_text(text), text


def test_customer_summary_words_do_not_all_become_reminder_automation():
    normal_customer_text = [
        "Amina account",
        "customer summary Amina",
        "send money",
        "edit customer",
    ]

    for text in normal_customer_text:
        assert not is_reminder_automation_text(text), text


if __name__ == "__main__":
    test_reminder_automation_text_is_reserved_for_main_router()
    test_customer_summary_words_do_not_all_become_reminder_automation()
    print("reminder routing smoke tests passed")
