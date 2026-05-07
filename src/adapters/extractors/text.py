"""Plain-text source files (.txt / .md / .markdown).

The body is read verbatim — no Markdown rendering, no front-matter
stripping. Search hits the raw text the user wrote, which matches how
they think about the file. We bound the read so a deceptively-named
binary or a runaway log file can't blow up the embedding budget.
"""

from pathlib import Path

# 1 MB matches what we'd realistically embed: Jina sees only the first
# 8 KB of the body anyway (see _save_or_update_note), and anything
# beyond a megabyte of plain text is almost certainly auto-generated.
_MAX_BYTES = 1_000_000

# cp1251 covers legacy Russian text files exported from older Windows
# tools. utf-8 is the modern default; we try it first.
_ENCODINGS = ("utf-8", "cp1251")


def extract_text_file(path: Path) -> str:
    # Bounded read — never load the whole file. A pathological multi-GB
    # file or a symlink pointing at /dev/zero would otherwise hang or
    # OOM the process before a post-read slice could trim it.
    with path.open("rb") as f:
        raw = f.read(_MAX_BYTES)
    if not raw:
        return ""
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    # Fallback: never lose the whole document over a single bad byte.
    return raw.decode("utf-8", errors="replace").strip()
