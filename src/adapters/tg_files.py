from pathlib import Path

# Telegram bot API allows downloading files up to 20 MB.
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def is_oversized(file_size: int) -> bool:
    return file_size > MAX_DOWNLOAD_BYTES


async def download_to_path(file, dest: Path) -> Path:
    """Wrapper around python-telegram-bot's File.download_to_drive.

    `file` is a telegram.File object obtained via context.bot.get_file().
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    await file.download_to_drive(custom_path=str(dest))
    return dest
