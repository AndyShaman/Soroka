"""Deterministic Russian-language intent parser for search queries.

Replaced the earlier LLM-based parser: numeric date arithmetic was
unstable, and the bot needs `since_days` / `created_after` / `created_before`
plus a `list_mode` flag for filter-only queries (e.g. «все голосовые»,
«что было в мае») — neither was previously extracted, which is why those
queries returned «Не нашёл ничего релевантного».

Only the patterns the user actually types are covered; unmatched fragments
fall through into `clean_query` and reach hybrid search unchanged.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class IntentResult:
    clean_query: str
    kind: Optional[str]
    since_days: Optional[int]
    created_after: Optional[int]   # epoch UTC, inclusive
    created_before: Optional[int]  # epoch UTC, exclusive
    list_mode: bool


# RU synonyms → canonical kind. Patterns are matched as whole tokens
# (`\b…\b`). Order inside a kind doesn't matter; first kind wins on tie.
KIND_SYNONYMS: dict[str, list[str]] = {
    "voice":   [r"войс\w*", r"голосов\w+", r"голосовух\w*",
                r"аудиозапис\w*", r"аудио", r"расшифровк\w*"],
    "web":     [r"стать\w+", r"ссылк\w+", r"сайт\w*", r"страниц\w*",
                r"урл", r"url", r"линк\w*", r"веб"],
    "post":    [r"пост\w*", r"репост\w*", r"форвард\w*",
                r"пересланн\w+", r"пересылк\w*"],
    "youtube": [r"ютуб\w*", r"ютьюб\w*", r"видео", r"видос\w*", r"ролик\w*"],
    "pdf":     [r"пдф\w*", r"pdf"],
    "docx":    [r"ворд\w*", r"word", r"докс"],
    "xlsx":    [r"эксел\w*", r"excel", r"xls", r"таблиц\w+", r"табличк\w+"],
    "image":   [r"картинк\w+", r"изображени\w+", r"фотк\w+", r"фото",
                r"скрин\w*", r"скриншот\w*", r"ocr"],
    "text":    [r"заметк\w+", r"мысл\w+"],
    "text_file": [r"тхт", r"txt", r"мд", r"md", r"маркдаун\w*", r"markdown"],
}

# Months: nominative / genitive / prepositional (covers «май»/«мая»/«мае»).
MONTHS: dict[int, list[str]] = {
    1:  ["январь",   "января",   "январе"],
    2:  ["февраль",  "февраля",  "феврале"],
    3:  ["март",     "марта",    "марте"],
    4:  ["апрель",   "апреля",   "апреле"],
    5:  ["май",      "мая",      "мае"],
    6:  ["июнь",     "июня",     "июне"],
    7:  ["июль",     "июля",     "июле"],
    8:  ["август",   "августа",  "августе"],
    9:  ["сентябрь", "сентября", "сентябре"],
    10: ["октябрь",  "октября",  "октябре"],
    11: ["ноябрь",   "ноября",   "ноябре"],
    12: ["декабрь",  "декабря",  "декабре"],
}

# Tokens dropped from the residual after temporal/kind extraction so a
# pure filter-only query («все голосовые», «что было в мае») leaves an
# empty `clean_query` and triggers list_mode. Keeping «за»/«на» here is
# safe because the temporal regexes consume the preposition first when
# it carries meaning; what survives is a stray that adds no signal.
STOPWORDS: set[str] = {
    "что", "было", "покажи", "найди", "найти", "мне",
    "все", "всё", "вся", "про", "о", "об", "за", "на",
    "утром", "вечером", "днём", "днем", "ночью",
}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _day_bounds(now_local: datetime, day_offset: int) -> tuple[int, int]:
    """[start, end) of the local day at `now - day_offset`."""
    target = (now_local - timedelta(days=day_offset)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return _epoch(target), _epoch(target + timedelta(days=1))


def _month_bounds(year: int, month: int, tz: ZoneInfo) -> tuple[int, int]:
    start = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        end = datetime(year, month + 1, 1, tzinfo=tz)
    return _epoch(start), _epoch(end)


def _week_bounds(now_local: datetime, weeks_back: int) -> tuple[int, int]:
    """ISO week (Mon 00:00 → next Mon 00:00) at `now - weeks_back`."""
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    monday_this_week = today - timedelta(days=today.weekday())
    start = monday_this_week - timedelta(weeks=weeks_back)
    return _epoch(start), _epoch(start + timedelta(weeks=1))


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Return (year, month) shifted by `delta` months, normalising overflow."""
    total = (year * 12 + (month - 1)) + delta
    return total // 12, (total % 12) + 1


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    s, e = span
    return any(not (e <= ss or s >= ee) for ss, ee in spans)


def parse_intent(query: str, *, tz: ZoneInfo,
                 now: Optional[datetime] = None) -> IntentResult:
    """Extract `kind`, temporal filters and a residual `clean_query`.

    `now` is injectable for deterministic tests; in production we read
    `datetime.now(tz)` lazily so each call sees a fresh wall-clock.
    """
    text = (query or "").lower().strip()
    if not text:
        return IntentResult("", None, None, None, None, list_mode=False)

    now_local = now if now is not None else datetime.now(tz)

    kind: Optional[str] = None
    since_days: Optional[int] = None
    created_after: Optional[int] = None
    created_before: Optional[int] = None
    matched: list[tuple[int, int]] = []

    # 1. «N дней/недель/месяцев назад» — exact day/week/month bound for N.
    m = re.search(r"\b(\d+)\s+(день|дня|дней)\s+назад\b", text)
    if m:
        created_after, created_before = _day_bounds(now_local, int(m.group(1)))
        matched.append(m.span())
    if created_after is None:
        m = re.search(r"\b(\d+)\s+(неделю|недели|недель|неделя)\s+назад\b", text)
        if m:
            created_after, created_before = _week_bounds(now_local, int(m.group(1)))
            matched.append(m.span())
    if created_after is None:
        m = re.search(r"\b(\d+)\s+(месяц|месяца|месяцев)\s+назад\b", text)
        if m:
            y, mo = _shift_month(now_local.year, now_local.month, -int(m.group(1)))
            created_after, created_before = _month_bounds(y, mo, tz)
            matched.append(m.span())

    # 2. Today / yesterday / before-yesterday.
    if created_after is None:
        for word, off in (("позавчера", 2), ("вчера", 1), ("сегодня", 0)):
            m = re.search(rf"\b{word}\b", text)
            if m:
                created_after, created_before = _day_bounds(now_local, off)
                matched.append(m.span())
                break

    # 3. Calendar week: «прошлая/эта неделя».
    if created_after is None:
        m = re.search(
            r"\b(за\s+прошлую\s+неделю|на\s+прошлой\s+неделе|прошлую\s+неделю)\b",
            text,
        )
        if m:
            created_after, created_before = _week_bounds(now_local, 1)
            matched.append(m.span())
        else:
            m = re.search(r"\b(на\s+этой\s+неделе|за\s+эту\s+неделю)\b", text)
            if m:
                created_after, created_before = _week_bounds(now_local, 0)
                matched.append(m.span())

    # 4. Calendar month: «прошлый месяц».
    if created_after is None:
        m = re.search(
            r"\b(за\s+прошлый\s+месяц|в\s+прошлом\s+месяце|прошлый\s+месяц)\b",
            text,
        )
        if m:
            y, mo = _shift_month(now_local.year, now_local.month, -1)
            created_after, created_before = _month_bounds(y, mo, tz)
            matched.append(m.span())

    # 5. Rolling windows: «за неделю / за месяц / за N дней».
    if since_days is None and created_after is None:
        m = (re.search(r"\bза\s+(последн\w+\s+)?недел\w+\b", text)
             or re.search(r"\bза\s+7\s+дней\b", text))
        if m:
            since_days = 7
            matched.append(m.span())
        else:
            m = (re.search(r"\bза\s+(последн\w+\s+)?месяц\w*\b", text)
                 or re.search(r"\bза\s+30\s+дней\b", text))
            if m:
                since_days = 30
                matched.append(m.span())
            else:
                m = re.search(r"\bза\s+(\d+)\s+(день|дня|дней)\b", text)
                if m:
                    since_days = int(m.group(1))
                    matched.append(m.span())

    # 6a. Specific calendar date: «5 мая», «6 мая 2025», «10 апреля
    #     2024». Single-day window. Runs BEFORE the month-only rule so
    #     «5 мая» picks the day, not the whole month. Ambiguous bare
    #     dates (no year) default to the current year, falling back to
    #     last year if the resulting date would be in the future.
    if created_after is None:
        for mo, forms in MONTHS.items():
            joined = "|".join(forms)
            pat = rf"\b(\d{{1,2}})\s+(?:{joined})(?:\s+(\d{{4}}))?\b"
            m = re.search(pat, text)
            if not m:
                continue
            day = int(m.group(1))
            if not 1 <= day <= 31:
                continue
            year_str = m.group(2)
            if year_str:
                y = int(year_str)
            else:
                y = now_local.year
                try:
                    if datetime(y, mo, day, tzinfo=tz) > now_local:
                        y -= 1
                except ValueError:
                    continue
            try:
                start = datetime(y, mo, day, tzinfo=tz)
            except ValueError:
                continue
            end = start + timedelta(days=1)
            created_after, created_before = _epoch(start), _epoch(end)
            matched.append(m.span())
            break

    # 6b. Month name: «в мае [2025]» / «за апрель 2024» / «мая 2025».
    #    Bare «май» without preposition or year stays a keyword (codex
    #    advice: avoids stealing words from real topic queries).
    if created_after is None:
        for mo, forms in MONTHS.items():
            joined = "|".join(forms)
            pat_with_prep = rf"\b(в|за)\s+(?:{joined})(?:\s+(\d{{4}}))?\b"
            pat_with_year = rf"\b(?:{joined})\s+(\d{{4}})\b"
            m = re.search(pat_with_prep, text)
            year_str = m.group(2) if m else None
            if not m:
                m = re.search(pat_with_year, text)
                year_str = m.group(1) if m else None
            if not m:
                continue
            if year_str:
                y = int(year_str)
            else:
                y = now_local.year
                # Future month in the current year → treat as previous year.
                if datetime(y, mo, 1, tzinfo=tz) > now_local:
                    y -= 1
            created_after, created_before = _month_bounds(y, mo, tz)
            matched.append(m.span())
            break

    # 7. Kind synonym (skipped if it would overlap an already-matched
    #    temporal span — keeps «месяц назад» from triggering a kind).
    for k, patterns in KIND_SYNONYMS.items():
        if kind is not None:
            break
        for pat in patterns:
            m = re.search(rf"\b{pat}\b", text)
            if m and not _overlaps(m.span(), matched):
                kind = k
                matched.append(m.span())
                break

    # Residual clean_query: blank out matched spans, drop stop-words.
    chars = list(text)
    for s, e in matched:
        for i in range(s, e):
            chars[i] = " "
    tokens = [t for t in re.split(r"\s+", "".join(chars)) if t and t not in STOPWORDS]
    clean_query = " ".join(tokens)

    has_filter = kind is not None or since_days is not None or created_after is not None
    list_mode = clean_query == "" and has_filter

    return IntentResult(
        clean_query=clean_query,
        kind=kind,
        since_days=since_days,
        created_after=created_after,
        created_before=created_before,
        list_mode=list_mode,
    )
