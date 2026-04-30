def message_link(chat_id: int, message_id: int) -> str:
    """Build a t.me link for a private channel message.

    Telegram's private channel chat IDs have format -100<id>; the public link
    drops the -100 prefix.
    """
    chat_str = str(chat_id)
    if chat_str.startswith("-100"):
        chat_str = chat_str[4:]
    return f"https://t.me/c/{chat_str}/{message_id}"
