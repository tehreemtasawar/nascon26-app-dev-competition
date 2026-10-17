import pytest
from app.sports import validate_sport_config
from app.errors import APIError

def test_mystery_sport_event_model():
    req = {
        "sport_id": "kabaddi",
        "name": "Kabaddi",
        "scoring_model": "event",
        "periods": {"count": 2, "duration_minutes": 20},
        "scoring_events": {
            "raid_point": {"points": 1},
            "tackle_point": {"points": 1},
            "all_out": {"points": 2}
        },
        "draw_allowed": False,
        "overtime": {"policy": "golden_score", "duration_minutes": 5},
        "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
        "roster": {
            "min_squad_size": 7,
            "max_squad_size": 12,
            "required_positions": {"raider": 2, "defender": 3}
        }
    }
    config = validate_sport_config(req)
    assert config["sport_id"] == "kabaddi"
    assert config["scoring_model"] == "event"
    assert "draw_lots" in config["tie_break_order"]

def test_mystery_sport_validation_failure():
    bad_req = {
        "sport_id": "Invalid Sport!",
        "name": "",
        "scoring_model": "magic",
        "periods": {},
        "scoring_events": {},
        "draw_allowed": "not_bool",
        "overtime": {},
        "roster": {}
    }
    with pytest.raises(APIError) as exc:
        validate_sport_config(bad_req)
    assert exc.value.code == "VALIDATION_ERROR"
    assert len(exc.value.details["fields"]) > 0
