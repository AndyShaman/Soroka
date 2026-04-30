import pytest
from src.adapters.tg_files import is_oversized, MAX_DOWNLOAD_BYTES

def test_is_oversized_threshold():
    assert is_oversized(MAX_DOWNLOAD_BYTES + 1)
    assert not is_oversized(MAX_DOWNLOAD_BYTES)
    assert not is_oversized(0)
