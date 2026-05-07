"""Deterministic intent parser — RU temporal + kind extraction.

We freeze `now` to 2026-05-07 12:00 Europe/Moscow so calendar-relative
phrases («в мае» / «в апреле 2025» / «3 дня назад») produce a stable
expected window across runs and timezones.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.core.intent import parse_intent

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 5, 7, 12, 0, tzinfo=TZ)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def test_yesterday_triggers_list_mode_with_day_window():
    out = parse_intent("что было вчера", tz=TZ, now=NOW)
    assert out.list_mode is True
    assert out.clean_query == ""
    start = datetime(2026, 5, 6, 0, 0, tzinfo=TZ)
    end = datetime(2026, 5, 7, 0, 0, tzinfo=TZ)
    assert out.created_after == _epoch(start)
    assert out.created_before == _epoch(end)


def test_before_yesterday_yields_two_day_offset():
    out = parse_intent("что было позавчера", tz=TZ, now=NOW)
    start = datetime(2026, 5, 5, 0, 0, tzinfo=TZ)
    end = datetime(2026, 5, 6, 0, 0, tzinfo=TZ)
    assert out.created_after == _epoch(start)
    assert out.created_before == _epoch(end)
    assert out.list_mode is True


def test_in_may_uses_current_year_when_not_yet_passed():
    # NOW is 7 May, so "в мае" still refers to May 2026 (not last year).
    out = parse_intent("что было в мае", tz=TZ, now=NOW)
    assert out.list_mode is True
    assert out.created_after == _epoch(datetime(2026, 5, 1, tzinfo=TZ))
    assert out.created_before == _epoch(datetime(2026, 6, 1, tzinfo=TZ))


def test_in_future_month_falls_back_to_previous_year():
    # December 2026 is in the future relative to May 2026 → previous year.
    out = parse_intent("в декабре", tz=TZ, now=NOW)
    assert out.created_after == _epoch(datetime(2025, 12, 1, tzinfo=TZ))
    assert out.created_before == _epoch(datetime(2026, 1, 1, tzinfo=TZ))


def test_explicit_year_pins_month():
    out = parse_intent("в апреле 2025", tz=TZ, now=NOW)
    assert out.created_after == _epoch(datetime(2025, 4, 1, tzinfo=TZ))
    assert out.created_before == _epoch(datetime(2025, 5, 1, tzinfo=TZ))


def test_voice_kind_with_filter_only_query():
    out = parse_intent("все голосовые", tz=TZ, now=NOW)
    assert out.kind == "voice"
    assert out.clean_query == ""
    assert out.list_mode is True


def test_kind_plus_topic_keeps_clean_query():
    out = parse_intent("статьи про React за прошлую неделю", tz=TZ, now=NOW)
    assert out.kind == "web"
    assert out.list_mode is False
    assert "react" in out.clean_query
    # Prior ISO week: 27 Apr (Mon) → 4 May (Mon).
    assert out.created_after == _epoch(datetime(2026, 4, 27, tzinfo=TZ))
    assert out.created_before == _epoch(datetime(2026, 5, 4, tzinfo=TZ))


def test_rolling_week_sets_since_days():
    out = parse_intent("голосовые за неделю", tz=TZ, now=NOW)
    assert out.kind == "voice"
    assert out.since_days == 7
    assert out.created_after is None
    assert out.list_mode is True


def test_n_days_ago_targets_specific_day():
    out = parse_intent("3 дня назад", tz=TZ, now=NOW)
    assert out.created_after == _epoch(datetime(2026, 5, 4, tzinfo=TZ))
    assert out.created_before == _epoch(datetime(2026, 5, 5, tzinfo=TZ))


def test_topical_query_passes_through_unchanged():
    out = parse_intent("паста рецепт", tz=TZ, now=NOW)
    assert out.kind is None
    assert out.since_days is None
    assert out.created_after is None
    assert out.list_mode is False
    assert "паста" in out.clean_query
    assert "рецепт" in out.clean_query


def test_bare_month_name_without_preposition_stays_keyword():
    # «май» without a preposition is more often a topic than a date.
    out = parse_intent("событие май", tz=TZ, now=NOW)
    assert out.created_after is None
    assert "май" in out.clean_query


def test_empty_query_yields_empty_result():
    out = parse_intent("", tz=TZ, now=NOW)
    assert out.list_mode is False
    assert out.clean_query == ""
