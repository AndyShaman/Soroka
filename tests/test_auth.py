from src.bot.auth import is_owner

def test_is_owner_match():
    assert is_owner(user_id=42, owner_id=42)

def test_is_owner_mismatch():
    assert not is_owner(user_id=43, owner_id=42)
