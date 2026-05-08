# AGENTS.md — Deployment protocol for AI agents

This file is the authoritative protocol for AI agents (Claude Code, Cursor, etc.)
deploying Soroka. Humans should read `README.md`.

## Required values from the user

Ask the user for these (and only these) before doing anything else:

- `VPS`               — `user@host`, e.g. `root@1.2.3.4` or an SSH alias
- `TELEGRAM_BOT_TOKEN`— from @BotFather
- `OWNER_TELEGRAM_ID` — from @userinfobot

DO NOT ask the user for any other keys (Jina, Deepgram, OpenRouter, GitHub).
Those are collected later via the bot's `/start` wizard, in Telegram.

If `ssh "$VPS" 'echo ok'` fails (password prompt or permission denied), stop
and tell the user to set up an SSH key first — either `ssh-copy-id "$VPS"` or
the [vps-setup-skill](https://github.com/AndyShaman/vps-setup-skill) (server
hardening flow that creates a non-root user with a key).

## Deployment

The installer runs **on the VPS itself** (not from the local machine). Drive it
through SSH with the non-interactive flags:

```bash
ssh "$VPS" "git clone https://github.com/AndyShaman/Soroka.git soroka \
  && cd soroka \
  && ./bin/install --tg-token '$TELEGRAM_BOT_TOKEN' --owner-id '$OWNER_TELEGRAM_ID'"
```

If the repo already exists from a previous attempt:

```bash
ssh "$VPS" "cd soroka && git pull --ff-only \
  && ./bin/install --tg-token '$TELEGRAM_BOT_TOKEN' --owner-id '$OWNER_TELEGRAM_ID'"
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

# Setup wizard state — DB lives inside the repo dir, not /opt/soroka
ssh "$VPS" "cd soroka && sqlite3 data/soroka.db 'SELECT setup_step FROM owners'"

# Note count
ssh "$VPS" "cd soroka && sqlite3 data/soroka.db 'SELECT count(*) FROM notes'"
```

## Updating

```bash
ssh "$VPS" "cd soroka && ./bin/update"
```

`bin/update` runs `git pull --ff-only` and `docker compose up -d --build` on the
VPS — no local rsync, no flags.

## Architecture, in 60 seconds

- Single Docker container (`soroka-bot`) running `python -m src.bot.main`.
- SQLite database at `<repo>/data/soroka.db` (FTS5 + sqlite-vec). Repo lives
  wherever the user did `git clone` — typically `~/soroka` or `/root/soroka`.
- All user secrets except `TELEGRAM_BOT_TOKEN` and `OWNER_TELEGRAM_ID` live in
  the `owners` table, populated through `/start` in Telegram.
- The MCP server (`src/mcp/server.py`) is invoked on demand via
  `docker exec -i soroka-bot python -m src.mcp.server` — wrapped by
  `/usr/local/bin/soroka-mcp` for SSH-stdio access.

## Files you must NOT touch on the VPS

- `<repo>/.env` — installer wrote it, leave it alone
- `<repo>/data/soroka.db` — SQLite database
- `<repo>/data/attachments/` — user files

If `/start` fails, ask the user to run `/cancel` and `/start` again.
