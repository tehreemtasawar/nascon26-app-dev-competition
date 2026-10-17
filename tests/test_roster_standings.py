import pytest
from app.fixtures import get_seed_order

def test_seed_order():
    assert get_seed_order(2) == [1, 2]
    assert get_seed_order(4) == [1, 4, 2, 3]
    assert get_seed_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]

def test_draw_lots_ordering():
    from app.crypto import lots_key
    seed = 42
    lg = "lg-1"
    # Verification of ranking
    t1_key = lots_key(seed, lg, "t1")
    t2_key = lots_key(seed, lg, "t2")
    t3_key = lots_key(seed, lg, "t3")
    assert t1_key < t3_key < t2_key
