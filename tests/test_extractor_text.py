"""Plain-text source files (.txt / .md / .markdown).

Three things matter: the extractor must surface the body verbatim for
search to hit it, must survive non-utf8 encodings (legacy Russian txt),
and must not blow the embedding budget on a runaway file.
"""

from src.adapters.extractors.text import extract_text_file, _MAX_BYTES


def test_extract_text_file_reads_utf8(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("# Заголовок\n\nТело заметки.", encoding="utf-8")
    out = extract_text_file(p)
    assert "Заголовок" in out
    assert "Тело заметки." in out


def test_extract_text_file_strips_surrounding_whitespace(tmp_path):
    p = tmp_path / "n.txt"
    p.write_text("\n\n  hello world  \n\n", encoding="utf-8")
    assert extract_text_file(p) == "hello world"


def test_extract_text_file_handles_cp1251(tmp_path):
    """Legacy Russian text exported from older Windows tools: cp1251 has
    bytes that are invalid utf-8, so a naive utf-8 decode would raise.
    """
    p = tmp_path / "legacy.txt"
    p.write_bytes("Привет, мир!".encode("cp1251"))
    out = extract_text_file(p)
    assert out == "Привет, мир!"


def test_extract_text_file_empty_returns_empty_string(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_bytes(b"")
    assert extract_text_file(p) == ""


def test_extract_text_file_caps_huge_input(tmp_path):
    """A pathological 5 MB file must be truncated to _MAX_BYTES so the
    embedding step never sees an unbounded body."""
    p = tmp_path / "big.txt"
    p.write_bytes(b"a" * (5 * _MAX_BYTES))
    out = extract_text_file(p)
    assert len(out) <= _MAX_BYTES


def test_extract_text_file_falls_back_on_undecodable_bytes(tmp_path):
    """A file with bytes valid in neither utf-8 nor cp1251 still returns
    something — the replacement fallback prevents the bot from losing
    the whole document over a single bad byte. Uses 0x98, which is
    *undefined* in Python's cp1251 codec and so raises in strict mode,
    forcing the third fallback branch."""
    p = tmp_path / "broken.txt"
    # 0xC0 starts a utf-8 2-byte sequence (illegal alone) → utf-8 raises.
    # 0x98 is undefined in cp1251 → cp1251 raises. Last branch wins.
    p.write_bytes(b"\xc0\x98 text after")
    out = extract_text_file(p)
    assert "text after" in out
