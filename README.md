# 🐦 Soroka

Telegram-бот, который превращает «Избранное» в персональную базу знаний.
Ты форвардишь в приватный канал что угодно — голос, ссылки, статьи, документы.
Soroka индексирует и хранит. Чтобы найти — пишешь боту в DM.
Возвращает оригинальные ссылки и файлы, не пересказы.

## Что нужно

1. **VPS** — Ubuntu 22.04+, 1GB RAM, EU локация, доступ по SSH-ключу.
2. **Telegram-бот** — создай у [@BotFather](https://t.me/BotFather), сохрани токен.
3. **Свой Telegram ID** — узнай у [@userinfobot](https://t.me/userinfobot).

После установки бот сам спросит ключи (бесплатные/дешёвые):
- [Jina](https://jina.ai/embeddings) — эмбеддинги (free tier 1M токенов)
- [Deepgram](https://deepgram.com) — голос → текст ($200 free)
- [OpenRouter](https://openrouter.ai/keys) — LLM (есть `:free` модели)
- [GitHub Personal Access Token](https://github.com/settings/tokens/new) — для бэкапов

## Установка

```bash
git clone https://github.com/YOUR_USER/soroka.git
cd soroka
./bin/install
```

Скрипт интерактивный — задаст IP VPS, SSH-юзера, токен бота, твой Telegram ID, и
сам развернёт бота на сервере. **Никаких файлов на сервере вручную ты не редактируешь.**

После завершения открой Telegram и отправь своему боту `/start` — мастер
проведёт через 6 шагов настройки в чате.

## Команды бота

- `/start` — мастер настройки (запускается один раз; повтор возобновляет с прерванного шага)
- `/help` — справка
- `/status` — текущие настройки и статистика
- `/setjina`, `/setdeepgram`, `/setkey` — заменить отдельный ключ
- `/models` — выбрать основную/fallback LLM
- `/setgithub` — заменить GitHub-токен и репо-зеркало
- `/setvps` — задать IP/юзера VPS (используется в `/mcp`)
- `/setinbox` — сменить канал-инбокс
- `/export` — выгрузить базу архивом
- `/mcp` — конфиг для Claude Desktop (MCP-сервер по SSH stdio)
- `/cancel` — прервать мастер/диалог

## Архитектура

```
Канал «Избранное 2» ──→ Бот на VPS ──→ SQLite (FTS5 + sqlite-vec)
DM с ботом         ──↗               ↑
                                      │
Claude Desktop через MCP-stdio ──SSH──┘
```

Подробности — `docs/specs/2026-04-30-design.md`.

## Обновление

```bash
./bin/update <vps-ip>
```

## Резервное копирование

При `/export` архив до 50MB бот отдаёт прямо в Telegram. Если больше —
заливает GitHub Release в твой приватный репо `username/soroka-data` и
присылает ссылку.

## Для AI-агентов

См. `AGENTS.md` — там точный протокол развёртывания через флаги.

## Лицензия

MIT.
