import sqlite3

from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
from src.core.owners import update_owner_field, advance_setup_step


async def handle_github_step(conn: sqlite3.Connection, owner_id: int, text: str) -> str:
    parts = text.strip().split()
    if len(parts) != 2 or "/" not in parts[1]:
        return ("Не понял. Пришли одной строкой: `<token> <user>/<repo>`\n"
                "Например: `ghp_xxxx me/soroka-data`")
    token, repo = parts
    mirror = GitHubMirror(token=token, repo=repo)
    try:
        await mirror.validate()
    except GitHubMirrorError as e:
        return f"GitHub отверг настройки: {e}. Попробуй ещё раз."

    update_owner_field(conn, owner_id, "github_token", token)
    update_owner_field(conn, owner_id, "github_mirror_repo", repo)
    advance_setup_step(conn, owner_id, "channel")
    from src.bot.handlers.setup import PROMPTS
    return "✓ GitHub-зеркало подключено.\n\n" + PROMPTS["channel"]


async def handle_skip_github(conn: sqlite3.Connection, owner_id: int) -> str:
    advance_setup_step(conn, owner_id, "channel")
    from src.bot.handlers.setup import PROMPTS
    return ("⚠ Без зеркала /export не сможет отдавать большие архивы.\n\n"
            + PROMPTS["channel"])
