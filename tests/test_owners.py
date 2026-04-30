import pytest
from src.core.db import open_db, init_schema
from src.core.owners import (
    create_or_get_owner, get_owner, update_owner_field, advance_setup_step,
)

def test_create_or_get_owner_inserts_once(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    o1 = create_or_get_owner(conn, telegram_id=42)
    o2 = create_or_get_owner(conn, telegram_id=42)
    assert o1.telegram_id == o2.telegram_id == 42
    rows = conn.execute("SELECT count(*) FROM owners").fetchone()
    assert rows[0] == 1

def test_update_owner_field_round_trip(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    update_owner_field(conn, 42, "jina_api_key", "abc")
    o = get_owner(conn, 42)
    assert o.jina_api_key == "abc"

def test_advance_setup_step_writes_step(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "jina")
    assert get_owner(conn, 42).setup_step == "jina"

def test_update_owner_field_rejects_unknown_field(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    with pytest.raises(ValueError, match="unknown field"):
        update_owner_field(conn, 42, "telegram_id", 99)

def test_get_owner_returns_none_for_missing(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    assert get_owner(conn, 9999) is None
