import re
from typing import Any, Dict, List
from fastapi import APIRouter
from psycopg.types.json import Jsonb
from app.errors import APIError

sports_router = APIRouter()

SPORT_ID_REGEX = re.compile(r"^[a-z0-9_-]{2,40}$")
EVENT_KEY_REGEX = re.compile(r"^[a-z0-9_]{1,40}$")

VALID_OVERTIME_POLICIES = {"none", "extra_time", "shootout", "golden_score", "super_over"}
VALID_TIE_BREAK_CRITERIA = {"h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"}
DEFAULT_TIE_BREAK_ORDER = ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"]

def validate_sport_config(body: Dict[str, Any]):
    fields = []
    
    # sport_id
    sport_id = body.get("sport_id")
    if not isinstance(sport_id, str) or not SPORT_ID_REGEX.match(sport_id):
        fields.append("sport_id")
        
    # name
    name = body.get("name")
    if not isinstance(name, str) or not (1 <= len(name) <= 80):
        fields.append("name")
        
    # scoring_model
    model = body.get("scoring_model")
    if model not in ("event", "innings", "round"):
        fields.append("scoring_model")
        
    # periods
    periods = body.get("periods")
    if not isinstance(periods, dict):
        fields.append("periods")
    else:
        if model == "event":
            count = periods.get("count")
            duration = periods.get("duration_minutes")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                fields.append("periods.count")
            if not isinstance(duration, int) or isinstance(duration, bool) or duration < 1:
                fields.append("periods.duration_minutes")
        elif model == "innings":
            for k in ("innings_per_team", "overs_per_innings", "balls_per_over", "wickets_per_innings"):
                val = periods.get(k)
                if not isinstance(val, int) or isinstance(val, bool) or val < 1:
                    fields.append(f"periods.{k}")
        elif model == "round":
            best_of = periods.get("best_of")
            if not isinstance(best_of, int) or isinstance(best_of, bool) or best_of < 1 or best_of % 2 == 0:
                fields.append("periods.best_of")

    # scoring_events
    events = body.get("scoring_events")
    if not isinstance(events, dict) or len(events) < 1:
        fields.append("scoring_events")
    else:
        for k, v in events.items():
            if not isinstance(k, str) or not EVENT_KEY_REGEX.match(k):
                fields.append(f"scoring_events.{k}")
                continue
            if not isinstance(v, dict):
                fields.append(f"scoring_events.{k}")
                continue
            if model == "event":
                pts = v.get("points")
                if not isinstance(pts, int) or isinstance(pts, bool) or pts < 1:
                    fields.append(f"scoring_events.{k}.points")
            elif model == "innings":
                runs = v.get("runs")
                legal = v.get("legal_ball")
                wicket = v.get("wicket")
                if not isinstance(runs, int) or isinstance(runs, bool) or runs < 0:
                    fields.append(f"scoring_events.{k}.runs")
                if not isinstance(legal, bool):
                    fields.append(f"scoring_events.{k}.legal_ball")
                if not isinstance(wicket, bool):
                    fields.append(f"scoring_events.{k}.wicket")
            elif model == "round":
                rounds = v.get("rounds")
                if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
                    fields.append(f"scoring_events.{k}.rounds")

    # draw_allowed
    draw_allowed = body.get("draw_allowed")
    if not isinstance(draw_allowed, bool):
        fields.append("draw_allowed")

    # overtime
    overtime = body.get("overtime")
    if not isinstance(overtime, dict):
        fields.append("overtime")
    else:
        pol = overtime.get("policy")
        if pol not in VALID_OVERTIME_POLICIES:
            fields.append("overtime.policy")
        dur = overtime.get("duration_minutes")
        if dur is not None and (not isinstance(dur, int) or isinstance(dur, bool) or dur < 0):
            fields.append("overtime.duration_minutes")

    # tie_break_order
    tbo = body.get("tie_break_order")
    if tbo is not None:
        if not isinstance(tbo, list):
            fields.append("tie_break_order")
        else:
            seen = set()
            for item in tbo:
                if item not in VALID_TIE_BREAK_CRITERIA or item in seen:
                    fields.append("tie_break_order")
                    break
                seen.add(item)

    # roster
    roster = body.get("roster")
    if not isinstance(roster, dict):
        fields.append("roster")
    else:
        min_s = roster.get("min_squad_size")
        max_s = roster.get("max_squad_size")
        if not isinstance(min_s, int) or isinstance(min_s, bool) or min_s < 1:
            fields.append("roster.min_squad_size")
        if not isinstance(max_s, int) or isinstance(max_s, bool) or max_s < 1:
            fields.append("roster.max_squad_size")
        if isinstance(min_s, int) and isinstance(max_s, int) and min_s > max_s:
            fields.append("roster.max_squad_size")
            
        req_pos = roster.get("required_positions")
        if not isinstance(req_pos, dict):
            fields.append("roster.required_positions")
        else:
            for pos, count in req_pos.items():
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    fields.append(f"roster.required_positions.{pos}")

    if fields:
        raise APIError(
            status_code=400,
            code="VALIDATION_ERROR",
            message="Sport configuration validation failed",
            details={"fields": list(dict.fromkeys(fields))}
        )

    # normalize tie_break_order
    tbo_final = list(body.get("tie_break_order") or DEFAULT_TIE_BREAK_ORDER)
    if "draw_lots" in tbo_final:
        tbo_final.remove("draw_lots")
    tbo_final.append("draw_lots")
    
    config = dict(body)
    config["tie_break_order"] = tbo_final
    return config

from app.db import get_db

@sports_router.post("/audit/v1/sports", status_code=201)
def create_sport(body: Dict[str, Any]):
    config = validate_sport_config(body)
    sport_id = config["sport_id"]
    name = config["name"]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT sport_id FROM sports WHERE sport_id = %s", (sport_id,))
            if cur.fetchone():
                raise APIError(409, "SPORT_EXISTS", f"Sport {sport_id} already exists")

            cur.execute("""
                INSERT INTO sports (sport_id, name, rules)
                VALUES (%s, %s, %s)
            """, (sport_id, name, Jsonb(config)))
            conn.commit()

    return {
        "sport_id": sport_id,
        "status": "created",
        "config": config
    }

