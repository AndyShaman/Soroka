from src.core.links import message_link

def test_message_link_for_private_channel():
    assert message_link(chat_id=-1001234567890, message_id=42) == \
        "https://t.me/c/1234567890/42"

def test_message_link_for_username():
    # We don't support public usernames yet (private channel only)
    assert message_link(chat_id=-1009999999999, message_id=1) == \
        "https://t.me/c/9999999999/1"
