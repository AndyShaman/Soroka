import re
import sqlite3

from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
from src.core.owners import get_owner, update_owner_field, advance_setup_step

REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")


async def handle_github_step(conn: sqlite3.Connection, owner_id: int, text: str) -> str:
    owner = get_owner(conn, owner_id)
    text = text.strip()

    if not owner.github_mirror_repo:
        if not REPO_PATTERN.match(text):
            return ("Не похоже на имя репозитория. Формат: `username/soroka-data`\n"
                    "Если репо ещё не создан — заведи приватный на github.com/new")
        update_owner_field(conn, owner_id, "github_mirror_repo", text)
        return (f"✓ Репо `{text}` записал.\n\n"
                "Шаг 5b/6 — Personal Access Token.\n"
                "1) Открой github.com/settings/tokens/new\n"
                "2) Поставь галку `repo` (full control of private repositories)\n"
                "3) Сгенерируй и пришли токен сюда (`ghp_...`)")

    if not (text.startswith("ghp_") or text.startswith("github_pat_")):
        return ("Не похоже на GitHub-токен. Должен начинаться с `ghp_` или `github_pat_`.\n"
                "Сгенерируй на github.com/settings/tokens/new и пришли его сюда.")

    mirror = GitHubMirror(token=text, repo=owner.github_mirror_repo)
    try:
        await mirror.validate()
    except GitHubMirrorError as e:
        return f"GitHub отверг настройки: {e}.\nПроверь токен (галка `repo`) или /skip."

    update_owner_field(conn, owner_id, "github_token", text)
    advance_setup_step(conn, owner_id, "channel")
    from src.bot.handlers.setup import PROMPTS
    return "✓ GitHub-зеркало подключено.\n\n" + PROMPTS["channel"]


async def handle_skip_github(conn: sqlite3.Connection, owner_id: int) -> str:
    update_owner_field(conn, owner_id, "github_mirror_repo", None)
    advance_setup_step(conn, owner_id, "channel")
    from src.bot.handlers.setup import PROMPTS
    return ("⚠ Без зеркала /export не сможет отдавать большие архивы.\n"
            "Подключить позже — команда /setgithub.\n\n"
            + PROMPTS["channel"])
