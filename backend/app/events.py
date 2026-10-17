import os
from typing import Dict, Any, List
from fastapi import APIRouter, Response, status
from app.db import get_db
from app.crypto import sign, canonical
from app.errors import APIError

events_router = APIRouter()

def get_salt():
    return os.getenv("DAY1_SALT", "demo-salt")

def compute_score_projection(match_id: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            # Check match stream
            cur.execute("SELECT match_id, league_id, sport_id, home_team_id, away_team_id, status FROM match_streams WHERE match_id = %s", (match_id,))
            match_row = cur.fetchone()
            if not match_row:
                raise APIError(404, "MATCH_NOT_FOUND", f"Match {match_id} does not exist")
            
            _, league_id, sport_id, home_team_id, away_team_id, base_status = match_row

            # Fetch sport rules
            cur.execute("SELECT rules FROM sports WHERE sport_id = %s", (sport_id,))
            sport_row = cur.fetchone()
            rules = sport_row[0] if sport_row else {}

            # Fetch all events in sequence order
            cur.execute("""
                SELECT sequence, event_id, type, payload, signature
                FROM match_events
                WHERE match_id = %s
                ORDER BY sequence ASC
            """, (match_id,))
            event_rows = cur.fetchall()

    scoring_model = rules.get("scoring_model", "event")
    scoring_events_cfg = rules.get("scoring_events", {})
    draw_allowed = rules.get("draw_allowed", True)
    periods_cfg = rules.get("periods", {})
    balls_per_over = periods_cfg.get("balls_per_over", 6)

    # First pass: map compensations
    # compensation event has payload: {"compensates": target_event_id, "reason": ...}
    compensated_map = {} # target_event_id -> compensating_event_id
    for seq, eid, etype, payload, _ in event_rows:
        if etype == "compensation":
            target = payload.get("compensates")
            if target:
                compensated_map[target] = eid

    current_status = base_status or "upcoming"
    home_score = 0
    away_score = 0
    home_fair_play = 0
    away_fair_play = 0
    home_wickets = 0 if scoring_model == "innings" else None
    away_wickets = 0 if scoring_model == "innings" else None
    home_balls = 0 if scoring_model == "innings" else None
    away_balls = 0 if scoring_model == "innings" else None
    tiebreak_winner_id = None

    events_list = []

    for seq, eid, etype, payload, sig in event_rows:
        is_compensated = eid in compensated_map
        comp_by = compensated_map.get(eid)

        events_list.append({
            "sequence": seq,
            "event_id": eid,
            "type": etype,
            "payload": payload,
            "signature": sig,
            "compensated": is_compensated,
            "compensated_by": comp_by
        })

        if etype == "match_init":
            current_status = "upcoming"
            if payload.get("home_team_id"):
                home_team_id = payload["home_team_id"]
            if payload.get("away_team_id"):
                away_team_id = payload["away_team_id"]
            if payload.get("league_id"):
                league_id = payload["league_id"]
        elif etype == "match_start":
            current_status = "in_progress"
        elif etype == "match_end":
            current_status = "completed"

        if is_compensated or etype == "compensation":
            continue

        if etype == "score":
            team = payload.get("team_id")
            ev_type = payload.get("event_type")
            ev_cfg = scoring_events_cfg.get(ev_type, {})
            
            if scoring_model == "event":
                pts = ev_cfg.get("points", 1)
                if team == home_team_id:
                    home_score += pts
                elif team == away_team_id:
                    away_score += pts
            elif scoring_model == "innings":
                runs = ev_cfg.get("runs", 0)
                is_legal = ev_cfg.get("legal_ball", True)
                is_wicket = ev_cfg.get("wicket", False)
                if team == home_team_id:
                    home_score += runs
                    if is_legal:
                        home_balls = (home_balls or 0) + 1
                    if is_wicket:
                        home_wickets = (home_wickets or 0) + 1
                elif team == away_team_id:
                    away_score += runs
                    if is_legal:
                        away_balls = (away_balls or 0) + 1
                    if is_wicket:
                        away_wickets = (away_wickets or 0) + 1
            elif scoring_model == "round":
                rnds = ev_cfg.get("rounds", 1)
                if team == home_team_id:
                    home_score += rnds
                elif team == away_team_id:
                    away_score += rnds

        elif etype == "discipline":
            team = payload.get("team_id")
            pts = payload.get("points", 0)
            if team == home_team_id:
                home_fair_play += pts
            elif team == away_team_id:
                away_fair_play += pts

        elif etype == "tiebreak_winner":
            tiebreak_winner_id = payload.get("team_id")

    # Format overs
    home_overs = None
    away_overs = None
    if scoring_model == "innings":
        if home_balls is not None:
            home_overs = f"{home_balls // balls_per_over}.{home_balls % balls_per_over}"
        if away_balls is not None:
            away_overs = f"{away_balls // balls_per_over}.{away_balls % balls_per_over}"

    # Outcome & winner
    outcome = "pending"
    winner_team_id = None
    if current_status == "completed":
        if home_score > away_score:
            outcome = "home_win"
            winner_team_id = home_team_id
        elif away_score > home_score:
            outcome = "away_win"
            winner_team_id = away_team_id
        else:
            if tiebreak_winner_id:
                winner_team_id = tiebreak_winner_id
                outcome = "home_win" if tiebreak_winner_id == home_team_id else "away_win"
            elif draw_allowed:
                outcome = "draw"
                winner_team_id = None
            else:
                outcome = "undecided"
                winner_team_id = None

    return {
        "match_id": match_id,
        "sport_id": sport_id,
        "league_id": league_id,
        "status": current_status,
        "outcome": outcome,
        "winner_team_id": winner_team_id,
        "tiebreak_winner_team_id": tiebreak_winner_id,
        "home": {
            "team_id": home_team_id,
            "score": home_score,
            "wickets": home_wickets,
            "balls": home_balls,
            "overs": home_overs,
            "fair_play": home_fair_play
        },
        "away": {
            "team_id": away_team_id,
            "score": away_score,
            "wickets": away_wickets,
            "balls": away_balls,
            "overs": away_overs,
            "fair_play": away_fair_play
        },
        "version": len(event_rows),
        "events": events_list
    }

@events_router.get("/audit/v1/score/{match_id}")
def get_score(match_id: str):
    return compute_score_projection(match_id)

@events_router.post("/audit/v1/events", status_code=201)
def append_event(body: Dict[str, Any], response: Response):
    event_id = body.get("event_id")
    match_id = body.get("match_id")
    etype = body.get("type")
    payload = body.get("payload")

    fields = []
    if not isinstance(event_id, str) or not event_id:
        fields.append("event_id")
    if not isinstance(match_id, str) or not match_id:
        fields.append("match_id")
    if not isinstance(etype, str) or not etype:
        fields.append("type")
    if not isinstance(payload, dict):
        fields.append("payload")

    if fields:
        raise APIError(400, "VALIDATION_ERROR", "Event validation failed", {"fields": fields})

    # Idempotency check across all events
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT raw_body, response_body FROM match_events WHERE event_id = %s", (event_id,))
            existing = cur.fetchone()
            if existing:
                stored_req, stored_res = existing[0], existing[1]
                if canonical(stored_req) == canonical(body):
                    response.status_code = status.HTTP_200_OK
                    return stored_res
                else:
                    raise APIError(409, "DUPLICATE_EVENT_ID", f"Event {event_id} already exists with different body")

    if etype == "match_init":
        sport_id = payload.get("sport_id")
        home = payload.get("home_team_id")
        away = payload.get("away_team_id")
        lg_id = payload.get("league_id")

        if not sport_id or not home or not away:
            raise APIError(400, "VALIDATION_ERROR", "match_init missing required payload fields", {"fields": ["sport_id", "home_team_id", "away_team_id"]})

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT sport_id FROM sports WHERE sport_id = %s", (sport_id,))
                if not cur.fetchone():
                    raise APIError(404, "SPORT_NOT_FOUND", f"Sport {sport_id} does not exist")

                cur.execute("SELECT match_id FROM match_streams WHERE match_id = %s", (match_id,))
                if cur.fetchone():
                    raise APIError(409, "MATCH_EXISTS", f"Match stream {match_id} already exists")

                cur.execute("""
                    INSERT INTO match_streams (match_id, league_id, sport_id, home_team_id, away_team_id, status)
                    VALUES (%s, %s, %s, %s, %s, 'upcoming')
                """, (match_id, lg_id, sport_id, home, away))
                conn.commit()

    # Get current match projection
    current = compute_score_projection(match_id)
    sport_id = current["sport_id"]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rules FROM sports WHERE sport_id = %s", (sport_id,))
            sport_rules = cur.fetchone()[0]

    current_status = current["status"]
    scoring_model = sport_rules.get("scoring_model", "event")
    scoring_events = sport_rules.get("scoring_events", {})
    draw_allowed = sport_rules.get("draw_allowed", True)
    periods = sport_rules.get("periods", {})

    if etype == "match_start":
        if current_status != "upcoming":
            raise APIError(409, "ILLEGAL_TRANSITION", f"Cannot start match from status {current_status}")

    elif etype == "score":
        if current_status != "in_progress":
            raise APIError(409, "MATCH_NOT_IN_PROGRESS", f"Match is not in progress (status: {current_status})")
        team = payload.get("team_id")
        if team not in (current["home"]["team_id"], current["away"]["team_id"]):
            raise APIError(400, "VALIDATION_ERROR", f"Team {team} is not playing in match {match_id}", {"fields": ["team_id"]})
        ev_type = payload.get("event_type")
        if ev_type not in scoring_events:
            raise APIError(400, "UNKNOWN_EVENT_TYPE", f"Unknown scoring event type: {ev_type}")

        # Check limits
        if scoring_model == "innings":
            team_stats = current["home"] if team == current["home"]["team_id"] else current["away"]
            ipt = periods.get("innings_per_team", 1)
            opi = periods.get("overs_per_innings", 20)
            bpo = periods.get("balls_per_over", 6)
            wpi = periods.get("wickets_per_innings", 10)
            max_balls = ipt * opi * bpo
            max_wickets = ipt * wpi
            if (team_stats["balls"] or 0) >= max_balls or (team_stats["wickets"] or 0) >= max_wickets:
                raise APIError(409, "INNINGS_COMPLETE", f"Innings complete for team {team}")

        elif scoring_model == "round":
            team_stats = current["home"] if team == current["home"]["team_id"] else current["away"]
            best_of = periods.get("best_of", 3)
            win_threshold = (best_of + 1) // 2
            if current["home"]["score"] >= win_threshold or current["away"]["score"] >= win_threshold:
                raise APIError(409, "SERIES_ALREADY_DECIDED", "Series has already been decided")

    elif etype == "discipline":
        if current_status != "in_progress":
            raise APIError(409, "MATCH_NOT_IN_PROGRESS", f"Match is not in progress (status: {current_status})")

    elif etype == "tiebreak_winner":
        if current_status != "in_progress":
            raise APIError(409, "MATCH_NOT_IN_PROGRESS", f"Match is not in progress (status: {current_status})")

    elif etype == "match_end":
        if current_status != "in_progress":
            raise APIError(409, "ILLEGAL_TRANSITION", f"Cannot end match from status {current_status}")
        if current["home"]["score"] == current["away"]["score"] and not draw_allowed and not current["tiebreak_winner_team_id"]:
            raise APIError(409, "TIE_NOT_ALLOWED", "Match cannot end in a draw without tiebreak winner")

    elif etype == "compensation":
        compensates_id = payload.get("compensates")
        if not compensates_id:
            raise APIError(400, "VALIDATION_ERROR", "compensates field required", {"fields": ["compensates"]})
        
        target_event = None
        for ev in current["events"]:
            if ev["event_id"] == compensates_id:
                target_event = ev
                break

        if not target_event:
            raise APIError(404, "EVENT_NOT_FOUND", f"Event {compensates_id} not found in this match")
        if target_event["type"] not in ("score", "discipline", "tiebreak_winner"):
            raise APIError(409, "INVALID_COMPENSATION", f"Cannot compensate event of type {target_event['type']}")
        if target_event["compensated"]:
            raise APIError(409, "INVALID_COMPENSATION", f"Event {compensates_id} is already compensated")

    salt = get_salt()
    sig = sign(salt, event_id, payload)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM match_events WHERE match_id = %s", (match_id,))
            seq = cur.fetchone()[0] + 1

            result = {
                "event_id": event_id,
                "match_id": match_id,
                "type": etype,
                "sequence": seq,
                "match_version": seq,
                "signature": sig
            }

            cur.execute("""
                INSERT INTO match_events (sequence, match_id, event_id, type, payload, signature, raw_body, response_body)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (seq, match_id, event_id, etype, canonical(payload), sig, canonical(body), canonical(result)))

            # If match_start or match_end, update match_streams
            if etype == "match_start":
                cur.execute("UPDATE match_streams SET status = 'in_progress' WHERE match_id = %s", (match_id,))
            elif etype == "match_end":
                cur.execute("UPDATE match_streams SET status = 'completed' WHERE match_id = %s", (match_id,))

            conn.commit()

    return result
