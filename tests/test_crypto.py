import pytest
from app.crypto import canonical, sign, lots_key

def test_vector_1_signature():
    # Test vector 1 (signature). Salt demo-salt, id evt-1, payload {"team_id":"t1","event_type":"goal"}:
    # canonical payload = {"event_type":"goal","team_id":"t1"}
    # signature = 972a8b558690b19121cc5bea84978f85e8eb15a3735018db36616bab1d7ec501
    payload = {"team_id": "t1", "event_type": "goal"}
    canon = canonical(payload)
    assert canon == '{"event_type":"goal","team_id":"t1"}'
    
    sig = sign("demo-salt", "evt-1", payload)
    assert sig == "972a8b558690b19121cc5bea84978f85e8eb15a3735018db36616bab1d7ec501"

def test_vector_2_drawing_of_lots():
    # Test vector 2 (drawing of lots). Seed 42, league lg-1:
    # t1 -> 0613316991ce0ac31e88d6003e3ff4d5e21bb072ac5f81b42c0cdc6598453293
    # t2 -> e3e3a14e22727f936e1f288cf5d02a8a9362b1da13c5432725fc10b2c7955dd9
    # t3 -> c8f28e3c2f1eb6c4f636b4f57050e3362a2b39c07fda9b61742a26dd20397028
    k1 = lots_key(42, "lg-1", "t1")
    k2 = lots_key(42, "lg-1", "t2")
    k3 = lots_key(42, "lg-1", "t3")

    assert k1 == "0613316991ce0ac31e88d6003e3ff4d5e21bb072ac5f81b42c0cdc6598453293"
    assert k2 == "e3e3a14e22727f936e1f288cf5d02a8a9362b1da13c5432725fc10b2c7955dd9"
    assert k3 == "c8f28e3c2f1eb6c4f636b4f57050e3362a2b39c07fda9b61742a26dd20397028"

    # Sorted ascending: t1, t3, t2
    ordered = sorted(["t1", "t2", "t3"], key=lambda t: lots_key(42, "lg-1", t))
    assert ordered == ["t1", "t3", "t2"]
