import pytest
from app.fixtures import generate_fixtures
from app.errors import APIError

def test_round_robin_basic():
    req = {
        "format": "round_robin",
        "teams": ["t1", "t2", "t3", "t4"],
        "params": {"legs": 1}
    }
    res = generate_fixtures(req)
    assert res["format"] == "round_robin"
    assert res["round_count"] == 3
    assert res["team_count"] == 4
    assert res["summary"]["scheduled"] == 6

def test_round_robin_odd_and_withdrawals():
    req = {
        "format": "round_robin",
        "teams": ["t1", "t2", "t3", "t4", "t5"],
        "params": {
            "legs": 1,
            "withdrawals": [{"team_id": "t3", "after_round": 2}],
            "withdrawal_policy": "forfeit_remaining"
        }
    }
    res = generate_fixtures(req)
    assert res["round_count"] == 5
    assert res["summary"]["forfeit"] > 0

def test_round_robin_void_all():
    req = {
        "format": "round_robin",
        "teams": ["t1", "t2", "t3", "t4"],
        "params": {
            "legs": 1,
            "withdrawals": [{"team_id": "t3", "after_round": 1}],
            "withdrawal_policy": "void_all"
        }
    }
    res = generate_fixtures(req)
    assert res["summary"]["voided"] == 3

def test_single_elimination_bracket():
    req = {
        "format": "single_elim",
        "teams": ["t1", "t2", "t3", "t4", "t5", "t6"],
        "params": {
            "third_place_match": True,
            "results": [{"match_id": "R1M2", "winner": "t4"}]
        }
    }
    res = generate_fixtures(req)
    assert res["bracket_size"] == 8
    assert len(res["rounds"]) == 3
    # Check bye for R1M1 (seed 1 vs missing seed 8)
    r1m1 = res["rounds"][0]["matches"][0]
    assert r1m1["home_seed"] == 1
    assert r1m1["away_seed"] == 8
    assert r1m1["bye"] is True
    assert r1m1["winner"] == "t1"

def test_double_elimination_bracket():
    req = {
        "format": "double_elim",
        "teams": ["t1", "t2", "t3", "t4"],
        "params": {
            "bracket_reset": True,
            "results": [{"match_id": "WR1M1", "winner": "t1"}]
        }
    }
    res = generate_fixtures(req)
    assert res["bracket_size"] == 4
    assert len(res["winners"]) == 2
    assert len(res["grand_final"]) == 2
    gf2 = res["grand_final"][1]
    assert gf2["conditional"] is True

def test_swiss_round_1():
    req = {
        "format": "swiss",
        "teams": ["t1", "t2", "t3", "t4", "t5"],
        "params": {"total_rounds": 3, "round": 1}
    }
    res = generate_fixtures(req)
    assert res["round"] == 1
    assert res["bye"] == "t5"
    assert len(res["pairings"]) == 2
    assert res["pairings"][0]["home"] == "t1"
    assert res["pairings"][0]["away"] == "t3"

def test_swiss_round_2_with_history():
    req = {
        "format": "swiss",
        "teams": ["t1", "t2", "t3", "t4", "t5"],
        "params": {
            "total_rounds": 3,
            "round": 2,
            "history": [
                {
                    "round": 1,
                    "bye": "t5",
                    "matches": [
                        {"home": "t1", "away": "t3", "result": "home"},
                        {"home": "t2", "away": "t4", "result": "draw"}
                    ]
                }
            ]
        }
    }
    res = generate_fixtures(req)
    assert res["round"] == 2
    assert len(res["pairings"]) == 2
    assert len(res["standings"]) == 5
