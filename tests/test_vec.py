# tests/test_vec.py
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
