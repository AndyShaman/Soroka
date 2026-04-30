import re
import tempfile
from pathlib import Path

YT_RE = re.compile(
    r"^https?://(?:www\.|m\.)?(?:youtube\.com/watch\?v=|youtu\.be/)",
    re.IGNORECASE,
)


def is_youtube_url(text: str) -> bool:
    return bool(YT_RE.match(text.strip()))


def extract_youtube(url: str) -> tuple[str | None, str]:
    """Returns (title, transcript_or_description). Uses auto-subs if available."""
    import yt_dlp

    with tempfile.TemporaryDirectory() as td:
        opts = {
            "skip_download": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ru", "en"],
            "subtitlesformat": "vtt",
            "outtmpl": str(Path(td) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title")
            description = info.get("description") or ""
            video_id = info.get("id")

            ydl.process_info(info)

        for ext in ("vtt", "srt"):
            for lang in ("ru", "en"):
                p = Path(td) / f"{video_id}.{lang}.{ext}"
                if p.exists():
                    return title, _vtt_to_text(p.read_text(encoding="utf-8"))

    return title, description


def _vtt_to_text(vtt: str) -> str:
    lines = []
    for line in vtt.splitlines():
        s = line.strip()
        if not s or s.startswith(("WEBVTT", "NOTE")) or "-->" in s:
            continue
        if s.replace(":", "").replace(".", "").isdigit():
            continue
        lines.append(s)
    return "\n".join(lines)
