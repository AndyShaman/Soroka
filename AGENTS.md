# AGENTS.md — Deployment protocol for AI agents

This file is the authoritative protocol for AI agents (Claude Code, Cursor, etc.)
deploying Soroka. Humans should read `README.md`.

## Required values from the user

Ask the user for these (and only these) before doing anything else:

- `VPS`               — `user@host`, e.g. `root@1.2.3.4` (must already accept the user's SSH key without password)
- `TELEGRAM_BOT_TOKEN`— from @BotFather
- `OWNER_TELEGRAM_ID` — from @userinfobot

DO NOT ask the user for any other keys (Jina, Deepgram, OpenRouter, GitHub).
Those are collected later via the bot's `/start` wizard, in Telegram.

If `ssh "$VPS" 'echo ok'` fails with a password prompt or permission denied,
stop and tell the user to run `ssh-copy-id "$VPS"` first.

## Deployment

Run the installer script in non-interactive mode:

```bash
./bin/install \
  --vps "$VPS" \
  --tg-token "$TELEGRAM_BOT_TOKEN" \
  --owner-id "$OWNER_TELEGRAM_ID"
```

Verify success:
```bash
ssh "$VPS" docker ps | grep soroka-bot
```

## Hand-off

After successful deployment, tell the user:

> "Готово. Открой Telegram, найди своего бота и отправь /start.
>  Бот проведёт через 6 шагов: ключи Jina, Deepgram, OpenRouter,
>  выбор моделей, GitHub-зеркало и канал-инбокс."

## Diagnostics

```bash
# Bot logs
ssh "$VPS" docker logs --tail 200 soroka-bot

# Setup wizard state
ssh "$VPS" \
  "sqlite3 /opt/soroka/data/soroka.db 'SELECT setup_step FROM owners'"

# Note count
ssh "$VPS" \
  "sqlite3 /opt/soroka/data/soroka.db 'SELECT count(*) FROM notes'"
```

## Updating

After `git pull` in the local clone:

```bash
./bin/update "$VPS"
```

## Architecture, in 60 seconds

- Single Docker container (`soroka-bot`) running `python -m src.bot.main`.
- SQLite database at `/opt/soroka/data/soroka.db` (FTS5 + sqlite-vec).
- All user secrets except `TELEGRAM_BOT_TOKEN` and `OWNER_TELEGRAM_ID` live in
  the `owners` table, populated through `/start` in Telegram.
- The MCP server (`src/mcp/server.py`) is invoked on demand via
  `docker exec -i soroka-bot python -m src.mcp.server` — wrapped by
  `/usr/local/bin/soroka-mcp` for SSH-stdio access.

## Files you must NOT touch on the VPS

- `/opt/soroka/.env` — installer wrote it, leave it alone
- `/opt/soroka/data/soroka.db` — SQLite database
- `/opt/soroka/data/attachments/` — user files

If `/start` fails, ask the user to run `/cancel` and `/start` again.
