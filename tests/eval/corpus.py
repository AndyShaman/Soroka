"""Test corpus for the search-quality eval suite.

52 notes covering all kinds the bot ingests: voice transcripts (Russian
with realistic morphology), web articles, YouTube transcripts, plain
text snippets, PDF documents, Telegram posts with embedded URLs, image
OCR. Built specifically to exercise the failure modes we identified:

  * Russian inflection: 'бот' vs 'боте' / 'бота' / 'ботов'
  * Cross-script transliteration: 'bot' vs 'бот'
  * Irregular verb stems: 'идти' vs 'пошёл'
  * Single-token short queries (<= 3 chars)
  * URL-only notes that get web/youtube extraction
  * Posts where text has its own meaning + URLs as references
  * Source-URL near-duplicates for diversification testing

Each entry has a stable `key` used by queries.py to declare expected
hits. The runner maps key -> note_id at insert time.
"""

NOTES = [
    # ====== voice (12) — Deepgram-style transcripts with case inflection ======
    {
        "key": "voice-bot-dative",
        "kind": "voice",
        "title": "Запись с планёрки про боте новые команды",
        "content": (
            "Записываю мысли по боте после планёрки. Обсудили: добавить новые "
            "команды в нашем телеграм-боте, поправить лимиты на длину "
            "сообщений, заодно подключить голосовой ввод. Андрей предлагает "
            "сделать прототип к следующей неделе, я согласился. Нужно ещё "
            "проверить как у нас сейчас обрабатываются форварды из каналов."
        ),
    },
    {
        "key": "voice-rag-meeting",
        "kind": "voice",
        "title": "Планёрка по RAG-проекту",
        "content": (
            "Обсуждали как пилить RAG для внутренней базы знаний компании. "
            "Решили попробовать гибридный поиск: BM25 плюс плотные векторы, "
            "потом реранкер. Лена предлагает взять Jina embeddings, потому "
            "что она мультиязычная и работает с русским. Я за. На след "
            "неделе подготовлю прототип на SQLite с расширением для векторов."
        ),
    },
    {
        "key": "voice-bike-buy",
        "kind": "voice",
        "title": "Хотел купить велосипед бу",
        "content": (
            "Хотел купить велосипед бу, посмотрел на авито и циан. Цены "
            "выросли в полтора раза за последний год, нормальный городской "
            "стоит от тридцати тысяч. Подумал может взять в аренду на сезон "
            "сначала, понять реально ли мне нужен. У соседа есть Trek, "
            "обещал дать прокатиться на выходных."
        ),
    },
    {
        "key": "voice-recipe-pasta",
        "kind": "voice",
        "title": "Записываю рецепт пасты карбонара",
        "content": (
            "Записываю рецепт пасты карбонара пока не забыл. Главное правило "
            "— никаких сливок, только желтки и пекорино. Гуанчале режется "
            "кубиками и обжаривается на собственном жире, без масла. "
            "Спагетти варятся аль денте, потом смешиваются с яично-сырной "
            "смесью на остаточном тепле сковородки. Соль не нужна — пекорино "
            "и гуанчале достаточно солёные."
        ),
    },
    {
        "key": "voice-go-gym",
        "kind": "voice",
        "title": "Пошёл в спортзал забыл полотенце",
        "content": (
            "Пошёл в спортзал, забыл полотенце. Пришлось купить новое в "
            "автомате на рецепции. Тренировку всё равно сделал, ноги "
            "сегодня — присед, жим ногами, выпады. Тренер сказал что я "
            "слишком быстро шёл по программе, надо добавить ещё неделю на "
            "адаптацию. Завтра отдых, послезавтра спина."
        ),
    },
    {
        "key": "voice-trip-georgia",
        "kind": "voice",
        "title": "Поездка в Грузию запланирована",
        "content": (
            "Поездка в Грузию запланирована на конец мая. Билеты до Тбилиси "
            "взял через Pegasus с пересадкой в Стамбуле. Жильё в Старом "
            "городе, сняли через airbnb. Маршрут: Тбилиси, Кахетия, "
            "Боржоми, Батуми. По винам в Кахетии Алексей дал список "
            "проверенных марани. Машину арендуем на месте."
        ),
    },
    {
        "key": "voice-llm-ratelimits",
        "kind": "voice",
        "title": "Обсуждали rate limits Claude API",
        "content": (
            "Обсуждали с командой rate limits на claude API. У нас сейчас "
            "tier 2, лимит на input tokens per minute упирается в потолок "
            "при пиковой нагрузке. Нужно либо переходить на tier 3, либо "
            "внедрять очередь с retry на 429. Костя считает что очередь "
            "проще, я склоняюсь к апгрейду tier — деньги небольшие."
        ),
    },
    {
        "key": "voice-bizdev",
        "kind": "voice",
        "title": "Монетизация канала",
        "content": (
            "Нужно обсудить монетизацию канала, пока подписчиков мало "
            "рекламу никто не даст. Думаю про платный курс по нейросетям, "
            "первый поток продать по предзаказу с большой скидкой. Если "
            "соберём двадцать человек — окупится. Дальше уже на отзывах "
            "поднимем цену."
        ),
    },
    {
        "key": "voice-typescript-async",
        "kind": "voice",
        "title": "Читал про асинхронность TypeScript",
        "content": (
            "Читал про асинхронность в typescript, promise все понятно, "
            "но Promise.all и Promise.allSettled путаются. allSettled "
            "возвращает все результаты включая ошибки, обычный all падает "
            "на первой. Для нашего парсера лучше allSettled, чтобы один "
            "битый источник не валил всю выборку."
        ),
    },
    {
        "key": "voice-grocery",
        "kind": "voice",
        "title": "Купить молоко хлеб кофе",
        "content": (
            "В магазин: молоко, хлеб черный, кофе зерновой, оливковое "
            "масло закончилось, стиральный порошок. Не забыть пакеты для "
            "мусора, маленькие. Если будут хорошие помидоры — взять килограмм "
            "на салат."
        ),
    },
    {
        "key": "voice-meditation",
        "kind": "voice",
        "title": "Медитация утром помогает",
        "content": (
            "Медитация утром реально помогает сосредоточиться, попробую "
            "делать ежедневно по двадцать минут. Использую Calm и "
            "Insight Timer, последний бесплатный и выбор гидов больше. "
            "Главное не пропускать первые две недели — потом войдёт в "
            "привычку."
        ),
    },
    {
        "key": "voice-deepgram-quality",
        "kind": "voice",
        "title": "Качество распознавания Deepgram",
        "content": (
            "Тестировал качество распознавания deepgram на русском. С "
            "длинными монологами справляется неплохо, но имена собственные "
            "ломает регулярно. Deepgram ставит запятые странно, иногда "
            "вообще не ставит. Альтернатива — Whisper large-v3, точнее, но "
            "медленнее в три раза и дороже."
        ),
    },

    # ====== web (11) — articles with title + extracted body ======
    {
        "key": "web-jina-embeddings",
        "kind": "web",
        "title": "Jina Embeddings v3: multilingual retrieval",
        "source_url": "https://jina.ai/news/jina-embeddings-v3",
        "content": (
            "Jina Embeddings v3 is a new multilingual embedding model with "
            "1024 dimensions, supporting 89 languages including Russian. "
            "It outperforms previous Jina models on MTEB benchmarks and "
            "matches OpenAI text-embedding-3-large on retrieval quality. "
            "Free tier offers 1M tokens. The model uses task-specific "
            "instructions: retrieval.passage for documents, retrieval.query "
            "for queries — an asymmetric setup that improves recall."
        ),
    },
    {
        "key": "web-rag-tutorial",
        "kind": "web",
        "title": "Building Production RAG with Hybrid Search",
        "source_url": "https://example.com/rag-production-guide",
        "content": (
            "Production RAG systems combine sparse retrieval (BM25) with "
            "dense retrieval (vector search) using fusion algorithms like "
            "Reciprocal Rank Fusion. RRF with k=60 is the standard default "
            "from the Cormack et al. 2009 paper. After fusion, a "
            "cross-encoder or LLM reranker prunes the top candidates by "
            "actual relevance. Recency bias and source diversification are "
            "common post-processing steps for personal-knowledge use cases."
        ),
    },
    {
        "key": "web-biotech-future",
        "kind": "web",
        "title": "Биотехнологии будущего: что нас ждёт",
        "source_url": "https://example.com/biotech-future-2026",
        "content": (
            "Биотехнологии следующие десять лет будут двигаться в сторону "
            "персонализированной медицины. CRISPR терапии уже одобрены для "
            "лечения серповидноклеточной анемии. Биохакер сообщество "
            "экспериментирует с непрерывными мониторами глюкозы и "
            "генетическими тестами в домашних условиях, хотя клиническая "
            "ценность спорная. Биотехнологические стартапы получили "
            "рекордное финансирование в первом квартале."
        ),
    },
    {
        "key": "web-pasta-carbonara",
        "kind": "web",
        "title": "Карбонара по-римски: пять главных правил",
        "source_url": "https://example.com/carbonara-roman-rules",
        "content": (
            "Настоящая римская карбонара не содержит сливок — только "
            "желтки, пекорино романо, гуанчале, чёрный перец и спагетти. "
            "Ошибка номер один — добавлять сливки или яичные белки. "
            "Гуанчале нельзя заменять беконом, текстура и вкус сильно "
            "отличаются. Пасту смешивают с соусом на остаточном тепле "
            "сковородки, иначе яйца свернутся в омлет."
        ),
    },
    {
        "key": "web-rust-borrow",
        "kind": "web",
        "title": "Understanding the Rust Borrow Checker",
        "source_url": "https://example.com/rust-borrow-checker",
        "content": (
            "The Rust borrow checker enforces three rules: each value has "
            "exactly one owner; references must always be valid; you can "
            "have either one mutable reference or any number of immutable "
            "references, but never both at once. Lifetime annotations let "
            "the compiler verify these rules statically. Common errors: "
            "moved values, dangling references, and mutable aliasing."
        ),
    },
    {
        "key": "web-asyncio-python",
        "kind": "web",
        "title": "Modern asyncio: tasks, gather, semaphores",
        "source_url": "https://example.com/python-asyncio-modern",
        "content": (
            "Modern Python asyncio favors high-level primitives like "
            "asyncio.gather and asyncio.TaskGroup over manual task "
            "creation. Semaphores limit concurrent operations against "
            "external services. Use asyncio.timeout for cancellation. "
            "Common pitfalls: forgetting to await, mixing sync IO into "
            "async paths, and creating tasks without keeping a reference."
        ),
    },
    {
        "key": "web-youtube-seo",
        "kind": "web",
        "title": "YouTube SEO в 2026: что работает",
        "source_url": "https://example.com/youtube-seo-2026",
        "content": (
            "YouTube SEO в 2026 году сильно изменился из-за обновления "
            "алгоритма ранжирования. Теперь главное — удержание зрителя "
            "в первые тридцать секунд и средняя глубина просмотра. "
            "Ключевые слова в названии и описании по-прежнему важны, но "
            "вес меньше. Custom thumbnail с лицом и эмоцией даёт +20% "
            "к CTR. Регулярность публикаций важнее количества."
        ),
    },
    {
        "key": "web-canva-templates",
        "kind": "web",
        "title": "50 бесплатных шаблонов Canva для соцсетей",
        "source_url": "https://example.com/canva-templates-social",
        "content": (
            "Подборка пятидесяти бесплатных шаблонов Canva для постов в "
            "соцсети: Instagram, YouTube, Telegram. Все шаблоны "
            "редактируются на бесплатном тарифе, не требуют Pro. Лучшие "
            "категории: бизнес-цитаты, объявления о вебинарах, обложки "
            "подкастов. Рекомендуем сохранить в избранное и адаптировать "
            "под бренд-цвета."
        ),
    },
    {
        "key": "web-bicycle-review",
        "kind": "web",
        "title": "Обзор городских велосипедов 2026",
        "source_url": "https://example.com/city-bikes-2026",
        "content": (
            "Городские велосипеды 2026 года: топ-10 моделей до пятидесяти "
            "тысяч рублей. Лидер — Trek FX 2 Disc, баланс цены и качества. "
            "Specialized Sirrus подходит тем кто рассматривает легкие "
            "тренировки. Giant Escape — бюджетный вариант с приличной "
            "комплектацией. Электровелосипеды вышли в отдельный сегмент, "
            "цены от ста тысяч и выше."
        ),
    },
    {
        "key": "web-georgia-travel",
        "kind": "web",
        "title": "Гид по Грузии для самостоятельных путешественников",
        "source_url": "https://example.com/georgia-self-travel",
        "content": (
            "Самостоятельная поездка в Грузию: что посмотреть кроме "
            "Тбилиси. Кахетия — главный винодельческий регион, "
            "Сигнаги и Телави обязательны. Боржоми — старый "
            "курорт с минеральными водами. Батуми — субтропики и "
            "море. Сванетия — горы и средневековые башни, требует "
            "подготовки и хотя бы недели."
        ),
    },
    {
        "key": "web-channel-monetization",
        "kind": "web",
        "title": "Монетизация YouTube-канала: семь способов",
        "source_url": "https://example.com/youtube-monetization-7",
        "content": (
            "Монетизация YouTube-канала не ограничивается рекламой. Семь "
            "способов: AdSense, спонсорские интеграции, платные курсы, "
            "членство (channel memberships), товары и мерч, партнёрские "
            "программы, донаты через Super Chat. Лучшая стратегия — "
            "комбинировать три-четыре источника, не полагаясь на один."
        ),
    },

    # ====== web duplicates (2) — same canonical URL after normalization ======
    {
        "key": "web-jina-mirror",
        "kind": "web",
        "title": "Jina Embeddings v3 (mirror)",
        "source_url": "https://jina.ai/news/jina-embeddings-v3?utm_source=twitter",
        "content": (
            "A mirror of the Jina v3 announcement republished on a "
            "newsletter aggregator. Contains the same key facts: 1024-dim "
            "multilingual embeddings, 89 languages, MTEB scores, free "
            "tier of 1M tokens, asymmetric query/passage instruction tasks."
        ),
    },
    {
        "key": "web-jina-mirror-2",
        "kind": "web",
        "title": "Jina v3 — third repost",
        "source_url": "https://jina.ai/news/jina-embeddings-v3/?ref=hn",
        "content": (
            "Third repost of the Jina v3 release notes. Same content "
            "covering 1024 dimensions, 89 languages, MTEB benchmark "
            "results, and the asymmetric retrieval.query / "
            "retrieval.passage task split that improves recall."
        ),
    },

    # ====== youtube (7) — transcripts, mostly English with some Russian ======
    {
        "key": "yt-build-bot-python",
        "kind": "youtube",
        "title": "Building a Telegram bot in Python — full tutorial",
        "source_url": "https://youtu.be/build-tg-bot-python",
        "content": (
            "Today we'll build a chat bot from scratch using python and "
            "the python-telegram-bot library. We'll cover: setting up "
            "BotFather, handling commands, processing text and voice "
            "messages, integrating OpenAI for chat responses, and "
            "deploying to a VPS with docker compose. The full source code "
            "is on github."
        ),
    },
    {
        "key": "yt-claude-api",
        "kind": "youtube",
        "title": "Claude API deep dive: tools, rate limits",
        "source_url": "https://youtu.be/claude-api-deep-dive",
        "content": (
            "In this video we go deep on the Claude API: how tool use "
            "actually works under the hood, how to design tool schemas "
            "that the model will call correctly, and how to handle rate "
            "limits at scale. We compare Anthropic's tier system with "
            "OpenAI and discuss when to use prompt caching."
        ),
    },
    {
        "key": "yt-asyncio-deep",
        "kind": "youtube",
        "title": "Python asyncio в production",
        "source_url": "https://youtu.be/python-asyncio-prod",
        "content": (
            "Разбираем asyncio в продакшене. Когда стоит использовать, "
            "когда лучше threadpool. Как правильно ограничивать "
            "конкурентность через семафоры. Почему gather с return_exceptions "
            "лучше чем allSettled-подобные паттерны. Реальные баги из "
            "продакшена: забытый await, mixing sync IO в корутинах."
        ),
    },
    {
        "key": "yt-rag-anthropic",
        "kind": "youtube",
        "title": "RAG с Claude: hybrid search и rerank",
        "source_url": "https://youtu.be/rag-with-claude",
        "content": (
            "Делаем RAG систему поверх Claude API. Гибридный поиск: BM25 "
            "плюс векторы плюс реранкер. Сравниваем разные стратегии "
            "fusion, разбираем почему RRF работает лучше weighted sum в "
            "большинстве случаев. Финальный реранкер на claude haiku даёт "
            "+15% к recall@5 на нашем датасете."
        ),
    },
    {
        "key": "yt-channel-growth",
        "kind": "youtube",
        "title": "Как я вырастил YouTube-канал до 100к",
        "source_url": "https://youtu.be/channel-growth-100k",
        "content": (
            "Рассказываю как за два года вырастил канал до ста тысяч "
            "подписчиков с нуля. Главное — постоянство публикаций, "
            "анализ удержания, итеративное улучшение обложек. Делюсь "
            "конкретными цифрами: CTR, average view duration, retention "
            "graphs до и после редизайна обложек."
        ),
    },
    {
        "key": "yt-pasta-italy",
        "kind": "youtube",
        "title": "Настоящая карбонара от итальянского повара",
        "source_url": "https://youtu.be/real-italian-carbonara",
        "content": (
            "Итальянский повар показывает как готовить настоящую "
            "карбонару. Никаких сливок, только желтки, пекорино романо, "
            "гуанчале, чёрный перец. Ключевой момент — температура: "
            "соус нельзя готовить на огне, иначе яйца сваряться. "
            "Использует остаточное тепло сковородки и пасты."
        ),
    },
    {
        "key": "yt-bicycle-mechanic",
        "kind": "youtube",
        "title": "Как настроить велосипед самому",
        "source_url": "https://youtu.be/bicycle-self-tune",
        "content": (
            "Базовая настройка велосипеда дома без обращения в "
            "мастерскую. Регулировка тормозов V-brake и дисковых, "
            "настройка переключателей, проверка цепи на износ. Нужны: "
            "набор шестигранников, цепной выжимка, тросовый ключ. "
            "Большинство задач решается за час."
        ),
    },

    # ====== text (7) — short user-typed notes ======
    {
        "key": "text-bot-idea",
        "kind": "text",
        "title": "Идея для телеграм-бота",
        "content": (
            "Идея для телеграм-бота: помощник по дрессировке нейросетей. "
            "Берёт текст промпта, прогоняет через несколько моделей, "
            "сравнивает ответы, советует улучшения. Целевая аудитория — "
            "те кто только начинает работать с LLM."
        ),
    },
    {
        "key": "text-todo-shopping",
        "kind": "text",
        "title": "Хлеб молоко мука яйца",
        "content": "хлеб, молоко, мука, яйца, сахар, масло сливочное",
    },
    {
        "key": "text-meeting-notes",
        "kind": "text",
        "title": "Обсудить с Андреем план запуска",
        "content": (
            "Обсудить с Андреем план запуска: дата релиза, бюджет на "
            "рекламу, кому отдавать на ранний доступ. Решить вопрос с "
            "доменом."
        ),
    },
    {
        "key": "text-bicycle-shortlist",
        "kind": "text",
        "title": "Списать марки велосипедов",
        "content": "велосипеды на рассмотрение: Trek FX 2, Giant Escape, Specialized Sirrus",
    },
    {
        "key": "text-go-gym-list",
        "kind": "text",
        "title": "Качалка жим тяга присед",
        "content": (
            "качалка план: жим лежа 4х8, тяга в наклоне 4х10, присед "
            "5х5, подтягивания 3 подхода до отказа"
        ),
    },
    {
        "key": "text-claude-prompt",
        "kind": "text",
        "title": "Промпт для cleanup'а",
        "content": (
            "промпт для cleanup'а: убрать markdown форматирование, "
            "оставить plain text, сохранить структуру параграфов через "
            "пустые строки"
        ),
    },
    {
        "key": "text-canva-account",
        "kind": "text",
        "title": "Пароль от canva не помню",
        "content": "пароль от canva не помню, восстановить через email",
    },

    # ====== pdf (4) — long documents ======
    {
        "key": "pdf-rag-survey",
        "kind": "pdf",
        "title": "rag-survey-2024.pdf",
        "content": (
            "A comprehensive survey of retrieval-augmented generation "
            "techniques. We cover sparse retrieval (BM25, SPLADE), dense "
            "retrieval with bi-encoders, late-interaction models like "
            "ColBERT, hybrid fusion strategies, and reranking with "
            "cross-encoders or LLMs. Evaluation methodology includes "
            "recall@k, MRR, nDCG, and retrieval-aware metrics that "
            "account for downstream answer quality."
        ),
    },
    {
        "key": "pdf-russian-grammar",
        "kind": "pdf",
        "title": "russian-grammar-rules.pdf",
        "content": (
            "Справочник по русской грамматике. Существительные склоняются "
            "по шести падежам: именительный, родительный, дательный, "
            "винительный, творительный, предложный. Глаголы спрягаются по "
            "лицам и числам, имеют вид (совершенный и несовершенный), "
            "время и наклонение. Неправильные глаголы: идти-шёл-пошёл, "
            "быть-был-буду, мочь-могу-смог."
        ),
    },
    {
        "key": "pdf-cycling-guide",
        "kind": "pdf",
        "title": "urban-cycling-handbook.pdf",
        "content": (
            "Urban cycling safety handbook. Topics covered: helmet "
            "selection and fit, bike lights and visibility, lock "
            "strategies against theft, route planning in mixed traffic, "
            "winter riding gear. Recommended skills: bunny hop, "
            "track stand, emergency braking, scanning behind without "
            "swerving. Practice in empty parking lots before hitting "
            "the street."
        ),
    },
    {
        "key": "pdf-tax-statement",
        "kind": "pdf",
        "title": "tax-statement-2025.pdf",
        "content": (
            "Налоговая декларация за 2025 год. Доходы от трудовой "
            "деятельности, дивиденды, проценты по вкладам. Стандартные "
            "вычеты и инвестиционные. Срок подачи — до тридцатого "
            "апреля. Реквизиты счёта для возврата налога."
        ),
    },

    # ====== post (7) — Telegram posts with embedded URLs ======
    {
        "key": "post-rag-resources",
        "kind": "post",
        "title": "Лучший туториал по RAG что я видел",
        "content": (
            "Лучший туториал по RAG что я видел за последний год: "
            "https://github.com/example/rag-tutorial. Подробное видео-"
            "объяснение на ютубе: https://youtu.be/abc123. Ещё хорошая "
            "статья на хабре: https://habr.com/ru/articles/rag-prod. "
            "Внутри — полный пайплайн от ингеста до реранкинга."
        ),
    },
    {
        "key": "post-embedding-libs",
        "kind": "post",
        "title": "Подборка библиотек для embeddings",
        "content": (
            "Подборка моделей для embeddings которые я тестировал на "
            "русском: jina.ai (мультиязычная, 1024 dim), voyage-multilingual, "
            "openai text-embedding-3-large. Актуальный рейтинг: "
            "https://huggingface.co/spaces/mteb/leaderboard. Для русских "
            "задач Jina и Voyage держат паритет с OpenAI при меньшей цене."
        ),
    },
    {
        "key": "post-soroka-launch",
        "kind": "post",
        "title": "Запустил Soroka на Hetzner",
        "content": (
            "Запустил Soroka — телеграм-бот для личной базы знаний. "
            "Деплой одной командой, инструкция в репо: "
            "https://github.com/AndyShaman/Soroka. Подробности в моём "
            "канале: https://t.me/handler_ai. Использую SQLite + sqlite-vec "
            "плюс Jina embeddings для поиска."
        ),
    },
    {
        "key": "post-canva-templates",
        "kind": "post",
        "title": "Подборка Canva шаблонов для youtube",
        "content": (
            "Делюсь подборкой Canva templates которыми сам пользуюсь "
            "для youtube-обложек: https://canva.com/templates/youtube. "
            "Всё бесплатно, можно адаптировать под бренд-цвета. Лучше "
            "всего работают шаблоны с большим лицом и контрастным фоном."
        ),
    },
    {
        "key": "post-italian-podcast",
        "kind": "post",
        "title": "Слушал подкаст про итальянскую кухню",
        "content": (
            "Слушал подкаст про итальянскую кухню, ведут шеф из Болоньи "
            "и журналист Eater. Разбирают мифы вокруг карбонары, "
            "паппарделле и пиццы. Ссылка: "
            "https://spotify.com/show/italian-food-pod. Очень "
            "рекомендую тем кто интересуется аутентичной кулинарией."
        ),
    },
    {
        "key": "post-typescript-tip",
        "kind": "post",
        "title": "Совет дня: as const для read-only",
        "content": (
            "Совет дня по TypeScript: используйте `as const` для "
            "read-only объектов, чтобы получить узкие литеральные типы "
            "вместо widening до string/number. Подробнее в release "
            "notes: https://typescriptlang.org/docs/handbook/release-notes/"
            "typescript-3-4. Особенно полезно для discriminated unions."
        ),
    },
    {
        "key": "post-claude-cookbook",
        "kind": "post",
        "title": "Anthropic выпустил cookbook",
        "content": (
            "Anthropic выпустил обновлённый cookbook с примерами tool "
            "use, multi-agent patterns, prompt caching: "
            "https://github.com/anthropics/anthropic-cookbook. Особенно "
            "интересны примеры с computer use и тестирование стратегий "
            "промптинга. В каждом ноутбуке — рабочий код."
        ),
    },

    # ====== image (2) — OCR-derived content ======
    {
        "key": "image-receipt",
        "kind": "image",
        "title": "Чек ИП Иванов 12345",
        "content": (
            "ИП Иванов И.И., чек № 12345, дата 03.05.2026, кассир "
            "Петрова, итого 1247 руб. 50 коп., оплата картой VISA"
        ),
    },
    {
        "key": "image-meme-bot",
        "kind": "image",
        "title": "Мем про чат-бот",
        "content": "мем про чат-бот: 'я не настоящий ИИ, я просто if/else'",
    },
]

assert len(NOTES) == 52, f"corpus must have exactly 52 notes, got {len(NOTES)}"
