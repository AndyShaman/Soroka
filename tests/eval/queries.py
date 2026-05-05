"""Golden queries for the search-quality eval suite.

33 queries each tagged with the failure-mode dimension they probe:

  * easy            — exact full-word matches; baseline must pass
  * morphology      — same root, different Russian inflection
  * morphology-irr  — irregular verb stems (idti vs poshyol)
  * morphology+kind — morphology AND kind filter from intent
  * translit        — cross-script (English latin <-> Russian cyrillic)
  * semantic        — no token overlap; relies on dense vectors
  * typo            — single-character typos
  * empty           — should return nothing (precision check)
  * natural         — natural-language queries the intent parser must clean
  * intent-cleanup  — queries with filler words ('покажи все ...')
  * post-text       — text-content of posts containing URLs
  * post-url-token  — words inside URLs that FTS5 tokenizes as separate tokens

Each entry's `expected` is a list of corpus keys (resolved to note IDs by
the runner). Order does not matter; we measure unordered set overlap for
recall@5 and precision@5, then ranked list for MRR.
"""

QUERIES = [
    # ====== easy (8) — baseline must handle these ======
    {"q": "паста карбонара",
     "expected": ["voice-recipe-pasta", "web-pasta-carbonara", "yt-pasta-italy"],
     "tag": "easy"},
    {"q": "rust borrow checker",
     "expected": ["web-rust-borrow"],
     "tag": "easy"},
    {"q": "youtube seo",
     "expected": ["web-youtube-seo", "yt-channel-growth"],
     "tag": "easy"},
    {"q": "велосипед бу",
     "expected": ["voice-bike-buy"],
     "tag": "easy"},
    {"q": "биохакер",
     "expected": ["web-biotech-future"],
     "tag": "easy"},
    {"q": "claude api",
     "expected": ["voice-llm-ratelimits", "yt-claude-api"],
     "tag": "easy"},
    {"q": "поездка грузия",
     "expected": ["voice-trip-georgia", "web-georgia-travel"],
     "tag": "easy"},
    {"q": "python asyncio",
     "expected": ["web-asyncio-python", "yt-asyncio-deep"],
     "tag": "easy"},

    # ====== morphology (8) — Russian inflection / declension ======
    {"q": "бот",
     "expected": ["voice-bot-dative", "text-bot-idea", "yt-build-bot-python"],
     "tag": "morphology"},
    {"q": "боты",
     "expected": ["voice-bot-dative", "text-bot-idea", "yt-build-bot-python"],
     "tag": "morphology"},
    {"q": "про бот в видео",
     "expected": ["yt-build-bot-python"],
     "tag": "morphology+kind"},
    {"q": "про бот в аудио",
     "expected": ["voice-bot-dative"],
     "tag": "morphology+kind"},
    {"q": "велосипеды",
     "expected": ["voice-bike-buy", "web-bicycle-review", "yt-bicycle-mechanic",
                  "text-bicycle-shortlist", "pdf-cycling-guide"],
     "tag": "morphology"},
    {"q": "идти в спортзал",
     "expected": ["voice-go-gym", "text-go-gym-list"],
     "tag": "morphology-irr"},
    {"q": "пасты рецепт",
     "expected": ["voice-recipe-pasta", "web-pasta-carbonara", "yt-pasta-italy"],
     "tag": "morphology"},
    {"q": "биотех",
     "expected": ["web-biotech-future"],
     "tag": "morphology"},

    # ====== translit (4) — cross-script English<->Russian ======
    {"q": "bot",
     "expected": ["voice-bot-dative", "text-bot-idea", "yt-build-bot-python",
                  "post-claude-cookbook"],
     "tag": "translit"},
    {"q": "OpenAI",
     "expected": ["yt-build-bot-python", "post-embedding-libs"],
     "tag": "translit"},
    {"q": "canva",
     "expected": ["post-canva-templates", "web-canva-templates", "text-canva-account"],
     "tag": "translit"},
    {"q": "telegram",
     "expected": ["voice-bot-dative", "text-bot-idea", "yt-build-bot-python",
                  "post-soroka-launch"],
     "tag": "translit"},

    # ====== semantic (5) — no token overlap, dense-only ======
    {"q": "искусственный интеллект",
     "expected": ["yt-claude-api", "yt-rag-anthropic", "voice-llm-ratelimits",
                  "post-claude-cookbook"],
     "tag": "semantic"},
    {"q": "здоровое питание",
     "expected": ["web-pasta-carbonara", "voice-recipe-pasta"],
     "tag": "semantic"},
    {"q": "веб-разработка",
     "expected": ["web-rust-borrow", "web-asyncio-python", "post-typescript-tip",
                  "voice-typescript-async"],
     "tag": "semantic"},
    {"q": "спорт",
     "expected": ["voice-go-gym", "text-go-gym-list", "web-bicycle-review",
                  "yt-bicycle-mechanic", "pdf-cycling-guide"],
     "tag": "semantic"},
    {"q": "как монетизировать",
     "expected": ["voice-bizdev", "web-channel-monetization", "yt-channel-growth"],
     "tag": "semantic"},

    # ====== typo / noise (3) ======
    {"q": "Боот",
     "expected": ["voice-bot-dative", "text-bot-idea"],
     "tag": "typo"},
    {"q": "yotube",
     "expected": ["web-youtube-seo", "yt-channel-growth"],
     "tag": "typo"},
    {"q": "блаблабла xyz",
     "expected": [],
     "tag": "empty"},

    # ====== natural-language / intent-cleanup (2) ======
    {"q": "найди что я сохранял про бот",
     "expected": ["voice-bot-dative", "text-bot-idea"],
     "tag": "natural"},
    {"q": "покажи все рецепты",
     "expected": ["voice-recipe-pasta", "web-pasta-carbonara", "yt-pasta-italy"],
     "tag": "intent-cleanup"},

    # ====== posts with URLs (3) ======
    {"q": "rag туториал",
     "expected": ["post-rag-resources", "web-rag-tutorial", "pdf-rag-survey",
                  "yt-rag-anthropic"],
     "tag": "post-text"},
    {"q": "подборка embeddings",
     "expected": ["post-embedding-libs", "web-jina-embeddings"],
     "tag": "post-text"},
    {"q": "huggingface leaderboard",
     "expected": ["post-embedding-libs"],
     "tag": "post-url-token"},
]

assert len(QUERIES) == 33, f"queries must have exactly 33 entries, got {len(QUERIES)}"
