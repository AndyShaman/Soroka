# tests/test_extractor_youtube.py
from unittest.mock import patch, MagicMock

from src.adapters.extractors.youtube import (
    is_youtube_url, _extract_video_id, extract_youtube,
    _description_from_initial, _title_from_initial,
)


def test_is_youtube_url_variations():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert is_youtube_url("https://m.youtube.com/watch?v=abc")
    assert is_youtube_url("https://www.youtube.com/shorts/abc")
    assert not is_youtube_url("https://example.com/watch?v=abc")


def test_extract_video_id_variants():
    assert _extract_video_id("https://www.youtube.com/watch?v=4Xz4-SIRD80") == "4Xz4-SIRD80"
    assert _extract_video_id("https://youtu.be/4Xz4-SIRD80?si=x") == "4Xz4-SIRD80"
    assert _extract_video_id("https://www.youtube.com/shorts/4Xz4-SIRD80") == "4Xz4-SIRD80"
    assert _extract_video_id("https://example.com/x") is None


def _fake_initial_with_description(text: str) -> dict:
    """Build the minimal ytInitialData shape that yt-dlp #14078 walks."""
    return {
        "engagementPanels": [
            {
                "engagementPanelSectionListRenderer": {
                    "content": {
                        "structuredDescriptionContentRenderer": {
                            "items": [
                                {
                                    "expandableVideoDescriptionBodyRenderer": {
                                        "attributedDescriptionBodyText": {
                                            "content": text,
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        ]
    }


def test_description_walker_finds_text_in_engagement_panel():
    initial = _fake_initial_with_description("Авторский рецепт чиабатты")
    assert _description_from_initial(initial) == "Авторский рецепт чиабатты"


def test_description_walker_returns_empty_when_panel_missing():
    """Some videos (live streams, age-restricted) have no engagement
    panel at all — we must return '' rather than crash."""
    assert _description_from_initial({}) == ""
    assert _description_from_initial({"engagementPanels": []}) == ""
    assert _description_from_initial({"engagementPanels": [{"foo": "bar"}]}) == ""


def test_title_walker_picks_up_video_primary_info_runs():
    initial = {
        "contents": {
            "twoColumnWatchNextResults": {
                "results": {
                    "results": {
                        "contents": [
                            {"videoPrimaryInfoRenderer": {
                                "title": {"runs": [
                                    {"text": "Чиабатта "},
                                    {"text": "без замеса"},
                                ]}
                            }}
                        ]
                    }
                }
            }
        }
    }
    assert _title_from_initial(initial) == "Чиабатта без замеса"


def test_extract_youtube_combines_oembed_and_initial_data():
    initial = _fake_initial_with_description("Полный текст описания видео.")
    with patch("src.adapters.extractors.youtube._fetch_oembed",
               return_value=("Чиабатта", "Oksana Levi")):
        with patch("src.adapters.extractors.youtube._fetch_watch_initial_data",
                   return_value=initial):
            title, body = extract_youtube(
                "https://www.youtube.com/watch?v=4Xz4-SIRD80"
            )

    assert title == "Чиабатта"
    assert "Канал: Oksana Levi" in body
    assert "Полный текст описания видео." in body


def test_extract_youtube_falls_back_to_initial_title_when_oembed_fails():
    initial = {
        "engagementPanels": [{
            "engagementPanelSectionListRenderer": {"content": {
                "structuredDescriptionContentRenderer": {"items": [{
                    "expandableVideoDescriptionBodyRenderer": {
                        "attributedDescriptionBodyText": {"content": "Описание"}
                    }
                }]}
            }}
        }],
        "contents": {"twoColumnWatchNextResults": {"results": {"results": {"contents": [
            {"videoPrimaryInfoRenderer": {"title": {"runs": [{"text": "Title from initial"}]}}},
        ]}}}}
    }
    with patch("src.adapters.extractors.youtube._fetch_oembed",
               return_value=(None, None)):
        with patch("src.adapters.extractors.youtube._fetch_watch_initial_data",
                   return_value=initial):
            title, body = extract_youtube(
                "https://www.youtube.com/watch?v=abc12345678"
            )

    assert title == "Title from initial"
    assert "Описание" in body


def test_extract_youtube_returns_empty_when_all_sources_fail():
    with patch("src.adapters.extractors.youtube._fetch_oembed",
               return_value=(None, None)):
        with patch("src.adapters.extractors.youtube._fetch_watch_initial_data",
                   return_value=None):
            title, body = extract_youtube(
                "https://www.youtube.com/watch?v=abc12345678"
            )

    assert title is None
    assert body == ""


def test_fetch_oembed_swallows_network_errors():
    from src.adapters.extractors.youtube import _fetch_oembed
    with patch("httpx.get", side_effect=Exception("DNS failure")):
        title, author = _fetch_oembed("https://youtu.be/x")
    assert (title, author) == (None, None)


def test_fetch_watch_initial_data_swallows_errors():
    from src.adapters.extractors.youtube import _fetch_watch_initial_data
    with patch("httpx.get", side_effect=Exception("connection refused")):
        result = _fetch_watch_initial_data("abc12345678")
    assert result is None


def test_fetch_watch_initial_data_parses_embedded_json():
    """Real watch responses look like ...var ytInitialData = {...};</script>...
    The regex must pick the JSON between var and ;</script>."""
    from src.adapters.extractors.youtube import _fetch_watch_initial_data

    fake = MagicMock()
    fake.status_code = 200
    fake.text = (
        "<html><head></head><body>"
        '<script>var ytInitialData = {"engagementPanels": [{"x": 1}]};</script>'
        "</body></html>"
    )
    with patch("httpx.get", return_value=fake):
        result = _fetch_watch_initial_data("abc12345678")
    assert result == {"engagementPanels": [{"x": 1}]}
