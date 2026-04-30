# tests/test_vec.py
import pytest
import struct
from src.core.db import open_db, init_schema
from src.core.vec import upsert_embedding, search_similar

def _vec(values):
    return struct.pack(f"{len(values)}f", *values)

def test_upsert_and_search(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    e1 = [1.0] + [0.0] * 1023
    e2 = [0.0, 1.0] + [0.0] * 1022
    upsert_embedding(conn, note_id=1, embedding=e1)
    upsert_embedding(conn, note_id=2, embedding=e2)
    results = search_similar(conn, query_embedding=e1, limit=2)
    assert results[0][0] == 1
    assert len(results) == 2


def test_serialize_rejects_wrong_dims(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    with pytest.raises(ValueError, match="expected 1024 dims"):
        upsert_embedding(conn, note_id=1, embedding=[0.0] * 512)


def test_search_similar_on_empty_table(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    e = [1.0] + [0.0] * 1023
    assert search_similar(conn, query_embedding=e, limit=5) == []


def test_upsert_overwrites_existing(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    e1 = [1.0] + [0.0] * 1023
    e2 = [0.0, 1.0] + [0.0] * 1022
    upsert_embedding(conn, note_id=1, embedding=e1)
    upsert_embedding(conn, note_id=1, embedding=e2)  # overwrite
    rows = conn.execute("SELECT count(*) FROM notes_vec WHERE note_id = 1").fetchone()
    assert rows[0] == 1
