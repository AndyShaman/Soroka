from telegram import Bot, ReactionTypeEmoji

PROCESSING = "🔄"
SUCCESS = "✅"
FAILURE = "❌"
OVERSIZED = "⚠️"


async def set_reaction(bot: Bot, chat_id: int, message_id: int, emoji: str) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        # Reactions are best-effort; never fail ingestion because of them.
        pass


async def clear_reaction(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id, message_id=message_id, reaction=[],
        )
    except Exception:
        pass
