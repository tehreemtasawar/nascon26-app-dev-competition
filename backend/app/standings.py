from typing import Dict, Any, List
from fastapi import APIRouter
from app.db import get_db
from app.crypto import lots_key
from app.errors import APIError
from app.events import compute_score_projection

standings_router = APIRouter()

@standings_router.post("/audit/v1/leagues", status_code=201)
def register_league(body: Dict[str, Any]):
    league_id = body.get("league_id")
    sport_id = body.get("sport_id")
    teams = body.get("teams")
    fixtures = body.get("fixtures")
    points_cfg = body.get("points") or {"win": 3, "draw": 1, "loss": 0}
    tie_break_order = body.get("tie_break_order")
    qualification = body.get("qualification")
    lots_seed = body.get("lots_seed", 42)

    fields = []
    if not isinstance(league_id, str) or not league_id:
        fields.append("league_id")
    if not isinstance(sport_id, str) or not sport_id:
        fields.append("sport_id")
    if not isinstance(teams, list) or not (2 <= len(teams) <= 40) or len(teams) != len(set(teams)):
        fields.append("teams")
    if not isinstance(fixtures, list):
        fields.append("fixtures")
    if not isinstance(qualification, dict) or not isinstance(qualification.get("spots"), int):
        fields.append("qualification.spots")

    if fields:
        raise APIError(400, "VALIDATION_ERROR", "League registration validation failed", {"fields": fields})

    spots = qualification["spots"]
    if not (1 <= spots <= len(teams)):
        raise APIError(400, "VALIDATION_ERROR", "Qualification spots out of range", {"fields": ["qualification.spots"]})

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check sport
            cur.execute("SELECT rules FROM sports WHERE sport_id = %s", (sport_id,))
            sport_row = cur.fetchone()
            if not sport_row:
                raise APIError(404, "SPORT_NOT_FOUND", f"Sport {sport_id} does not exist")
            
            sport_rules = sport_row[0]
            if not tie_break_order:
                tie_break_order = sport_rules.get("tie_break_order", ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"])

            # Check league exists
            cur.execute("SELECT league_id FROM leagues_registry WHERE league_id = %s", (league_id,))
            if cur.fetchone():
                raise APIError(409, "LEAGUE_EXISTS", f"League {league_id} already exists")

            # Validate fixtures
            fixture_ids = []
            for f in fixtures:
                mid = f.get("match_id")
                home = f.get("home")
                away = f.get("away")
                if not mid or not home or not away:
                    raise APIError(400, "VALIDATION_ERROR", "Invalid fixture", {"fields": ["fixtures"]})
                if home not in teams or away not in teams or home == away:
                    raise APIError(400, "VALIDATION_ERROR", f"Fixture teams invalid: {home} vs {away}", {"fields": ["fixtures"]})
                fixture_ids.append(mid)

            if len(fixture_ids) != len(set(fixture_ids)):
                raise APIError(400, "VALIDATION_ERROR", "Duplicate fixture match_id", {"fields": ["fixtures"]})

            for mid in fixture_ids:
                cur.execute("SELECT match_id FROM match_streams WHERE match_id = %s", (mid,))
                if cur.fetchone():
                    raise APIError(409, "MATCH_EXISTS", f"Match {mid} already exists")

            # Insert league
            cur.execute("""
                INSERT INTO leagues_registry
                (league_id, sport_id, teams, fixtures, points, tie_break_order, qualification_spots, lots_seed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (league_id, sport_id, list(teams), [f for f in fixtures], points_cfg, list(tie_break_order), spots, lots_seed))

            # Insert match streams
            for f in fixtures:
                cur.execute("""
                    INSERT INTO match_streams (match_id, league_id, sport_id, home_team_id, away_team_id, status)
                    VALUES (%s, %s, %s, %s, %s, 'upcoming')
                """, (f["match_id"], league_id, sport_id, f["home"], f["away"]))

            conn.commit()

    return {
        "league_id": league_id,
        "status": "created",
        "team_count": len(teams),
        "fixture_count": len(fixtures)
    }

@standings_router.get("/audit/v1/standings/{league_id}")
def get_standings(league_id: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sport_id, teams, fixtures, points, tie_break_order, qualification_spots, lots_seed
                FROM leagues_registry
                WHERE league_id = %s
            """, (league_id,))
            league_row = cur.fetchone()
            if not league_row:
                raise APIError(404, "LEAGUE_NOT_FOUND", f"League {league_id} not found")

            sport_id, teams, fixtures, points_cfg, tie_break_order, k_spots, lots_seed = league_row

            cur.execute("SELECT rules FROM sports WHERE sport_id = %s", (sport_id,))
            sport_rules = cur.fetchone()[0]

    scoring_model = sport_rules.get("scoring_model", "event")
    periods_cfg = sport_rules.get("periods", {})
    balls_per_over = periods_cfg.get("balls_per_over", 6)
    overs_per_innings = periods_cfg.get("overs_per_innings", 20)
    wickets_per_innings = periods_cfg.get("wickets_per_innings", 10)

    win_pts = points_cfg.get("win", 3)
    draw_pts = points_cfg.get("draw", 1)
    loss_pts = points_cfg.get("loss", 0)

    # Initial stats per team
    team_stats = {
        t: {
            "team_id": t,
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "scored": 0,
            "conceded": 0,
            "diff": 0.0,
            "points": 0,
            "fair_play": 0,
            "remaining": 0,
            "runs_scored": 0,
            "overs_faced": 0.0,
            "runs_conceded": 0,
            "overs_bowled": 0.0
        }
        for t in teams
    }

    # Head-to-head matrix: h2h[a][b] = {played, points, scored, conceded}
    h2h_matrix = {
        a: {
            b: {"played": 0, "points": 0, "scored": 0, "conceded": 0}
            for b in teams
        }
        for a in teams
    }

    # List of completed matches: (home, away, outcome, home_score, away_score, winner, home_overs, away_overs)
    completed_matches = []

    for f in fixtures:
        mid = f["match_id"]
        proj = compute_score_projection(mid)
        home = proj["home"]["team_id"]
        away = proj["away"]["team_id"]

        if proj["status"] == "completed" and proj["outcome"] != "undecided":
            # Counted as played
            team_stats[home]["played"] += 1
            team_stats[away]["played"] += 1

            h_score = proj["home"]["score"]
            a_score = proj["away"]["score"]

            team_stats[home]["scored"] += h_score
            team_stats[home]["conceded"] += a_score
            team_stats[away]["scored"] += a_score
            team_stats[away]["conceded"] += h_score

            team_stats[home]["fair_play"] += proj["home"]["fair_play"]
            team_stats[away]["fair_play"] += proj["away"]["fair_play"]

            # H2H matrix update
            h2h_matrix[home][away]["played"] += 1
            h2h_matrix[away][home]["played"] += 1
            h2h_matrix[home][away]["scored"] += h_score
            h2h_matrix[home][away]["conceded"] += a_score
            h2h_matrix[away][home]["scored"] += a_score
            h2h_matrix[away][home]["conceded"] += h_score

            # Inning calculations
            h_overs_faced = 0.0
            a_overs_faced = 0.0
            if scoring_model == "innings":
                if (proj["home"]["wickets"] or 0) >= wickets_per_innings:
                    h_overs_faced = float(overs_per_innings)
                else:
                    h_overs_faced = (proj["home"]["balls"] or 0) / balls_per_over

                if (proj["away"]["wickets"] or 0) >= wickets_per_innings:
                    a_overs_faced = float(overs_per_innings)
                else:
                    a_overs_faced = (proj["away"]["balls"] or 0) / balls_per_over

                team_stats[home]["runs_scored"] += h_score
                team_stats[home]["overs_faced"] += h_overs_faced
                team_stats[home]["runs_conceded"] += a_score
                team_stats[home]["overs_bowled"] += a_overs_faced

                team_stats[away]["runs_scored"] += a_score
                team_stats[away]["overs_faced"] += a_overs_faced
                team_stats[away]["runs_conceded"] += h_score
                team_stats[away]["overs_bowled"] += h_overs_faced

            outcome = proj["outcome"]
            if outcome == "home_win":
                team_stats[home]["won"] += 1
                team_stats[home]["points"] += win_pts
                h2h_matrix[home][away]["points"] += win_pts

                team_stats[away]["lost"] += 1
                team_stats[away]["points"] += loss_pts
                h2h_matrix[away][home]["points"] += loss_pts
            elif outcome == "away_win":
                team_stats[away]["won"] += 1
                team_stats[away]["points"] += win_pts
                h2h_matrix[away][home]["points"] += win_pts

                team_stats[home]["lost"] += 1
                team_stats[home]["points"] += loss_pts
                h2h_matrix[home][away]["points"] += loss_pts
            elif outcome == "draw":
                team_stats[home]["drawn"] += 1
                team_stats[home]["points"] += draw_pts
                h2h_matrix[home][away]["points"] += draw_pts

                team_stats[away]["drawn"] += 1
                team_stats[away]["points"] += draw_pts
                h2h_matrix[away][home]["points"] += draw_pts

            completed_matches.append({
                "home": home, "away": away, "outcome": outcome,
                "home_score": h_score, "away_score": a_score,
                "home_overs": h_overs_faced, "away_overs": a_overs_faced
            })
        else:
            team_stats[home]["remaining"] += 1
            team_stats[away]["remaining"] += 1

    # Compute overall diffs
    for t in teams:
        st = team_stats[t]
        if scoring_model in ("event", "round"):
            st["diff"] = st["scored"] - st["conceded"]
        elif scoring_model == "innings":
            nrr = 0.0
            if st["overs_faced"] > 0:
                nrr += st["runs_scored"] / st["overs_faced"]
            if st["overs_bowled"] > 0:
                nrr -= st["runs_conceded"] / st["overs_bowled"]
            st["diff"] = round(nrr, 3)

    # Qualification status
    for t in teams:
        st = team_stats[t]
        pts_t = st["points"]
        max_t = pts_t + win_pts * st["remaining"]
        
        # clinched if fewer than k other teams X satisfy max(X) >= points(T)
        count_max_ge_pts = sum(1 for x in teams if x != t and (team_stats[x]["points"] + win_pts * team_stats[x]["remaining"]) >= pts_t)
        # eliminated if at least k other teams X satisfy points(X) > max(T)
        count_pts_gt_max = sum(1 for x in teams if x != t and team_stats[x]["points"] > max_t)

        if count_max_ge_pts < k_spots:
            st["status"] = "clinched"
        elif count_pts_gt_max >= k_spots:
            st["status"] = "eliminated"
        else:
            st["status"] = "still_possible"

    # Exact Ordering Algorithm
    # Group teams by points
    from collections import defaultdict
    points_map = defaultdict(list)
    for t in teams:
        points_map[team_stats[t]["points"]].append(t)

    sorted_points = sorted(points_map.keys(), reverse=True)
    
    criterion_chain = [c for c in tie_break_order if c != "draw_lots"]
    criterion_chain.append("draw_lots")

    def compute_criterion(crit: str, group: List[str], t: str):
        if crit == "h2h_points":
            pts = 0
            for m in completed_matches:
                if m["home"] in group and m["away"] in group:
                    if m["home"] == t:
                        if m["outcome"] == "home_win": pts += win_pts
                        elif m["outcome"] == "draw": pts += draw_pts
                        else: pts += loss_pts
                    elif m["away"] == t:
                        if m["outcome"] == "away_win": pts += win_pts
                        elif m["outcome"] == "draw": pts += draw_pts
                        else: pts += loss_pts
            return pts
        elif crit == "h2h_diff":
            if scoring_model in ("event", "round"):
                diff = 0
                for m in completed_matches:
                    if m["home"] in group and m["away"] in group:
                        if m["home"] == t:
                            diff += m["home_score"] - m["away_score"]
                        elif m["away"] == t:
                            diff += m["away_score"] - m["home_score"]
                return diff
            elif scoring_model == "innings":
                runs_scored = 0
                overs_faced = 0.0
                runs_conceded = 0
                overs_bowled = 0.0
                for m in completed_matches:
                    if m["home"] in group and m["away"] in group:
                        if m["home"] == t:
                            runs_scored += m["home_score"]
                            overs_faced += m["home_overs"]
                            runs_conceded += m["away_score"]
                            overs_bowled += m["away_overs"]
                        elif m["away"] == t:
                            runs_scored += m["away_score"]
                            overs_faced += m["away_overs"]
                            runs_conceded += m["home_score"]
                            overs_bowled += m["home_overs"]
                nrr = 0.0
                if overs_faced > 0: nrr += runs_scored / overs_faced
                if overs_bowled > 0: nrr -= runs_conceded / overs_bowled
                return round(nrr, 3)
        elif crit == "overall_diff":
            return team_stats[t]["diff"]
        elif crit == "scored":
            return team_stats[t]["scored"]
        elif crit == "fair_play":
            return team_stats[t]["fair_play"]
        elif crit == "draw_lots":
            # ascending by hash! First is best, so return negative hash or sort by hash asc
            return lots_key(lots_seed, league_id, t)
        return 0

    resolved_by_map = {t: None for t in teams}

    def resolve_group(group: List[str]) -> List[str]:
        if len(group) <= 1:
            return group

        for crit in criterion_chain:
            values = {}
            for t in group:
                values[t] = compute_criterion(crit, group, t)

            # Check if all equal
            first_val = next(iter(values.values()))
            all_equal = all(v == first_val for v in values.values())
            if all_equal:
                continue

            # Split into subgroups by value
            val_groups = defaultdict(list)
            for t in group:
                val_groups[values[t]].append(t)

            # Sort subgroups
            if crit == "draw_lots":
                sorted_vals = sorted(val_groups.keys()) # ascending by hex
            else:
                sorted_vals = sorted(val_groups.keys(), reverse=True) # descending for points/diff

            result = []
            for idx, val in enumerate(sorted_vals):
                sub_grp = val_groups[val]
                # Each team in this group was resolved against the teams below it by this criterion
                if idx < len(sorted_vals) - 1:
                    for t in sub_grp:
                        if resolved_by_map[t] is None:
                            resolved_by_map[t] = crit
                
                if len(sub_grp) > 1:
                    resolved_sub = resolve_group(sub_grp)
                    result.extend(resolved_sub)
                else:
                    result.extend(sub_grp)
            return result

        return group

    ordered_teams = []
    for pts in sorted_points:
        grp = points_map[pts]
        if len(grp) == 1:
            ordered_teams.append(grp[0])
        else:
            sorted_sub = resolve_group(grp)
            ordered_teams.extend(sorted_sub)

    table = []
    for rank, t in enumerate(ordered_teams, 1):
        st = team_stats[t]
        table.append({
            "rank": rank,
            "team_id": t,
            "played": st["played"],
            "won": st["won"],
            "drawn": st["drawn"],
            "lost": st["lost"],
            "scored": st["scored"],
            "conceded": st["conceded"],
            "diff": st["diff"],
            "points": st["points"],
            "fair_play": st["fair_play"],
            "status": st["status"],
            "resolved_by": resolved_by_map[t]
        })

    return {
        "league_id": league_id,
        "sport_id": sport_id,
        "qualification_spots": k_spots,
        "table": table,
        "h2h": h2h_matrix
    }
