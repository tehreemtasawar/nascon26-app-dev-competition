from datetime import datetime, timezone, date
from typing import Dict, Any, List
from fastapi import APIRouter, Response, status
from app.db import get_db
from app.crypto import canonical
from app.errors import APIError

roster_router = APIRouter()

@roster_router.post("/audit/v1/roster/setup", status_code=201)
def roster_setup(body: Dict[str, Any]):
    league = body.get("league")
    squads = body.get("squads", [])
    players = body.get("players", [])
    matches_in_progress = body.get("matches_in_progress", [])

    if not isinstance(league, dict) or not league.get("league_id"):
        raise APIError(400, "VALIDATION_ERROR", "Invalid league in roster setup", {"fields": ["league"]})

    league_id = league["league_id"]

    # Calculate squad counts
    squad_counts = {sq["squad_id"]: 0 for sq in squads}
    for p in players:
        sid = p.get("squad_id")
        if sid in squad_counts:
            squad_counts[sid] += 1

    scenario = {
        "league": league,
        "squads": squads,
        "players": players,
        "matches_in_progress": matches_in_progress
    }

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO roster_scenarios (league_id, scenario)
                VALUES (%s, %s)
                ON CONFLICT (league_id) DO UPDATE SET scenario = EXCLUDED.scenario
            """, (league_id, canonical(scenario)))
            conn.commit()

    return {
        "league_id": league_id,
        "status": "configured",
        "squad_counts": squad_counts
    }

@roster_router.post("/audit/v1/roster/transfer", status_code=201)
def roster_transfer(body: Dict[str, Any], response: Response):
    req_id = body.get("request_id")
    league_id = body.get("league_id")
    player_id = body.get("player_id")
    action_type = body.get("type")
    from_sq = body.get("from_squad_id")
    to_sq = body.get("to_squad_id")
    effective_date_str = body.get("effective_date")
    loan_end_date_str = body.get("loan_end_date")
    reason = body.get("reason", "")
    who = body.get("requested_by", "system")

    # Check 1: Schema, dates, loan_end_date > effective_date, to_squad_id present unless release
    fields = []
    if not isinstance(req_id, str) or not req_id: fields.append("request_id")
    if not isinstance(league_id, str) or not league_id: fields.append("league_id")
    if not isinstance(player_id, str) or not player_id: fields.append("player_id")
    if action_type not in ("transfer", "loan", "release"): fields.append("type")
    if action_type != "release" and (not isinstance(to_sq, str) or not to_sq):
        fields.append("to_squad_id")

    eff_d = None
    loan_d = None
    try:
        if effective_date_str:
            eff_d = date.fromisoformat(effective_date_str)
        else:
            fields.append("effective_date")
    except Exception:
        fields.append("effective_date")

    if action_type == "loan":
        try:
            if loan_end_date_str:
                loan_d = date.fromisoformat(loan_end_date_str)
                if eff_d and loan_d <= eff_d:
                    fields.append("loan_end_date")
            else:
                fields.append("loan_end_date")
        except Exception:
            fields.append("loan_end_date")

    if fields:
        raise APIError(400, "VALIDATION_ERROR", "Roster transfer validation failed", {"fields": fields})

    # Idempotency check
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT raw_body, response_body FROM roster_transfer_requests WHERE request_id = %s", (req_id,))
            existing = cur.fetchone()
            if existing:
                stored_req, stored_res = existing[0], existing[1]
                if canonical(stored_req) == canonical(body):
                    response.status_code = status.HTTP_200_OK
                    return stored_res
                else:
                    raise APIError(409, "DUPLICATE_EVENT_ID", f"Request {req_id} already exists with different body")

            # Check 2: League / player / squads exist
            cur.execute("SELECT scenario FROM roster_scenarios WHERE league_id = %s", (league_id,))
            scen_row = cur.fetchone()
            if not scen_row:
                raise APIError(404, "LEAGUE_NOT_FOUND", f"League {league_id} not found")
            
            scenario = scen_row[0]
            league_cfg = scenario.get("league", {})
            squads_list = scenario.get("squads", [])
            players_list = scenario.get("players", [])
            in_prog_matches = scenario.get("matches_in_progress", [])

            squad_map = {sq["squad_id"]: sq for sq in squads_list}
            player_map = {p["player_id"]: p for p in players_list}

            if player_id not in player_map:
                raise APIError(404, "PLAYER_NOT_FOUND", f"Player {player_id} not found")

            if from_sq not in squad_map:
                raise APIError(404, "SQUAD_NOT_FOUND", f"From squad {from_sq} not found")

            if action_type != "release" and to_sq not in squad_map:
                raise APIError(404, "SQUAD_NOT_FOUND", f"To squad {to_sq} not found")

            # Check 3: From and to squads belong to the league's tenant
            league_tenant = league_cfg.get("tenant_id")
            if squad_map[from_sq].get("tenant_id") != league_tenant:
                raise APIError(409, "CROSS_TENANT_TRANSFER", f"From squad {from_sq} does not belong to league tenant")
            if action_type != "release" and squad_map[to_sq].get("tenant_id") != league_tenant:
                raise APIError(409, "CROSS_TENANT_TRANSFER", f"To squad {to_sq} does not belong to league tenant")

            # Check 4: Player's current squad in this league equals from_squad_id
            target_player = player_map[player_id]
            if target_player.get("squad_id") != from_sq:
                raise APIError(409, "NOT_IN_SQUAD", f"Player is in squad {target_player.get('squad_id')}, not {from_sq}")

            # Check 5: transfer/loan: effective_date inside window (inclusive). Release allowed on any date.
            if action_type in ("transfer", "loan"):
                window = league_cfg.get("transfer_window", {})
                w_open = date.fromisoformat(window.get("open", "1970-01-01"))
                w_close = date.fromisoformat(window.get("close", "2099-12-31"))
                if not (w_open <= eff_d <= w_close):
                    raise APIError(409, "TRANSFER_WINDOW_CLOSED", "Transfer window is closed for effective date")

            # Check 6: Player is not currently on loan
            if target_player.get("parent_squad_id") is not None or target_player.get("registration_type") == "loan":
                raise APIError(409, "PLAYER_ON_LOAN", "Player is currently on loan")

            # Check 7: destination squad count + 1 <= max_squad_size
            max_squad_size = league_cfg.get("max_squad_size", 25)
            if action_type in ("transfer", "loan"):
                dest_count = sum(1 for p in players_list if p.get("squad_id") == to_sq)
                if dest_count + 1 > max_squad_size:
                    raise APIError(409, "SQUAD_FULL", f"Destination squad {to_sq} is full")

            # Check 8: After the move, from squad still has >= required count for player's position
            p_pos = target_player.get("position")
            req_positions = league_cfg.get("required_positions", {})
            min_for_pos = req_positions.get(p_pos, 0)
            if min_for_pos > 0:
                from_pos_count = sum(1 for p in players_list if p.get("squad_id") == from_sq and p.get("position") == p_pos and p["player_id"] != player_id)
                if from_pos_count < min_for_pos:
                    raise APIError(409, "MIN_POSITION_VIOLATION", f"From squad would fall below required {min_for_pos} for position {p_pos}")

            # All checks passed! Now apply effects
            # Edge case 6: In-progress match
            blocking_mid = None
            for m in in_prog_matches:
                if m.get("home_squad_id") == from_sq or m.get("away_squad_id") == from_sq:
                    blocking_mid = m.get("match_id")
                    break

            state = "deferred_until_match_end" if blocking_mid else "active"

            # Count previous audit entries for player
            cur.execute("SELECT COUNT(*) FROM roster_audit_entries WHERE player_id = %s", (player_id,))
            audit_seq = cur.fetchone()[0] + 1
            audit_id = f"au-{player_id}-{audit_seq:04d}"

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            audit_entry = {
                "audit_id": audit_id,
                "action": action_type,
                "player_id": player_id,
                "league_id": league_id,
                "from_squad_id": from_sq,
                "to_squad_id": to_sq,
                "effective_date": effective_date_str,
                "state": state,
                "who": who,
                "when": now_iso,
                "why": reason
            }

            reg = None
            if action_type == "transfer":
                reg = {
                    "player_id": player_id,
                    "league_id": league_id,
                    "squad_id": to_sq,
                    "parent_squad_id": None,
                    "registration_type": "transfer",
                    "start_date": effective_date_str,
                    "loan_end_date": None,
                    "role": "substitute"
                }
                target_player["squad_id"] = to_sq
                target_player["role"] = "substitute"
                target_player["registration_type"] = "transfer"
                target_player["parent_squad_id"] = None
                target_player["loan_end_date"] = None
            elif action_type == "loan":
                reg = {
                    "player_id": player_id,
                    "league_id": league_id,
                    "squad_id": to_sq,
                    "parent_squad_id": from_sq,
                    "registration_type": "loan",
                    "start_date": effective_date_str,
                    "loan_end_date": loan_end_date_str,
                    "role": "substitute"
                }
                target_player["squad_id"] = to_sq
                target_player["role"] = "substitute"
                target_player["registration_type"] = "loan"
                target_player["parent_squad_id"] = from_sq
                target_player["loan_end_date"] = loan_end_date_str
            elif action_type == "release":
                reg = None
                target_player["squad_id"] = None
                target_player["role"] = "substitute"
                target_player["registration_type"] = None
                target_player["parent_squad_id"] = None
                target_player["loan_end_date"] = None

            result = {
                "request_id": req_id,
                "status": "accepted",
                "state": state,
                "blocking_match_id": blocking_mid,
                "registration": reg,
                "audit_entry": audit_entry
            }

            # Update scenario and store audit entry
            cur.execute("UPDATE roster_scenarios SET scenario = %s WHERE league_id = %s", (canonical(scenario), league_id))
            cur.execute("""
                INSERT INTO roster_audit_entries (audit_id, request_id, action, player_id, league_id, from_squad_id, to_squad_id, effective_date, state, who, when_ts, why, raw_entry)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (audit_id, req_id, action_type, player_id, league_id, from_sq, to_sq, effective_date_str, state, who, now_iso, reason, canonical(audit_entry)))
            
            cur.execute("""
                INSERT INTO roster_transfer_requests (request_id, raw_body, response_body)
                VALUES (%s, %s, %s)
            """, (req_id, canonical(body), canonical(result)))

            conn.commit()
            return result

@roster_router.get("/audit/v1/roster/history/{player_id}")
def get_roster_history(player_id: str, as_of: str | None = None):
    with get_db() as conn:
        with conn.cursor() as cur:
            # Check player across scenarios
            cur.execute("SELECT league_id, scenario FROM roster_scenarios")
            rows = cur.fetchall()
            found_player = None
            found_league_id = None
            found_scenario = None

            for lid, scen in rows:
                for p in scen.get("players", []):
                    if p["player_id"] == player_id:
                        found_player = p
                        found_league_id = lid
                        found_scenario = scen
                        break
                if found_player:
                    break

            if not found_player:
                raise APIError(404, "PLAYER_NOT_FOUND", f"Player {player_id} not found")

            # Check audit entries
            cur.execute("""
                SELECT raw_entry, action, effective_date, from_squad_id, to_squad_id
                FROM roster_audit_entries
                WHERE player_id = %s
                ORDER BY when_ts ASC, audit_id ASC
            """, (player_id,))
            audit_rows = cur.fetchall()

            history_entries = [r[0] for r in audit_rows]

            # Check if player was on loan and as_of is after loan_end_date
            parent_sq = found_player.get("parent_squad_id")
            loan_end = found_player.get("loan_end_date")
            as_of_date = date.fromisoformat(as_of) if as_of else date.today()

            if parent_sq and loan_end:
                loan_end_d = date.fromisoformat(loan_end)
                if as_of_date > loan_end_d:
                    # Check if loan_return already exists in audit
                    has_return = any(r[1] == "loan_return" for r in audit_rows)
                    if not has_return:
                        return_audit_id = f"au-{player_id}-{len(history_entries)+1:04d}"
                        borrower_sq = found_player.get("squad_id")
                        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        return_entry = {
                            "audit_id": return_audit_id,
                            "action": "loan_return",
                            "player_id": player_id,
                            "league_id": found_league_id,
                            "from_squad_id": borrower_sq,
                            "to_squad_id": parent_sq,
                            "effective_date": str(loan_end_d),
                            "state": "active",
                            "who": "system",
                            "when": now_iso,
                            "why": "Automatic loan return"
                        }
                        cur.execute("""
                            INSERT INTO roster_audit_entries (audit_id, request_id, action, player_id, league_id, from_squad_id, to_squad_id, effective_date, state, who, when_ts, why, raw_entry)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (return_audit_id, f"ret-{player_id}", "loan_return", player_id, found_league_id, borrower_sq, parent_sq, str(loan_end_d), "active", "system", now_iso, "Automatic loan return", canonical(return_entry)))
                        
                        # Return to parent squad
                        found_player["squad_id"] = parent_sq
                        found_player["parent_squad_id"] = None
                        found_player["loan_end_date"] = None
                        found_player["role"] = "substitute"
                        cur.execute("UPDATE roster_scenarios SET scenario = %s WHERE league_id = %s", (canonical(found_scenario), found_league_id))
                        conn.commit()

                        history_entries.append(return_entry)

            # Determine current squad as of date
            curr_squad = found_player.get("squad_id")
            parent_squad = found_player.get("parent_squad_id")

            return {
                "player_id": player_id,
                "as_of": as_of or str(date.today()),
                "league_id": found_league_id,
                "current_squad_id": curr_squad,
                "parent_squad_id": parent_squad,
                "history": history_entries
            }
