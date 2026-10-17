import math
from typing import Dict, Any, List, Tuple
from fastapi import APIRouter
from app.errors import APIError

fixtures_router = APIRouter()

def get_seed_order(b: int) -> List[int]:
    curr = [1, 2]
    size = 2
    while size < b:
        next_size = size * 2
        next_order = []
        for s in curr:
            next_order.extend([s, next_size + 1 - s])
        curr = next_order
        size = next_size
    return curr

@fixtures_router.post("/audit/v1/fixtures")
def generate_fixtures(body: Dict[str, Any]):
    fmt = body.get("format")
    teams = body.get("teams")
    params = body.get("params") or {}

    if not isinstance(teams, list) or len(teams) != len(set(teams)):
        raise APIError(400, "VALIDATION_ERROR", "Teams must be a unique list", {"fields": ["teams"]})

    n = len(teams)

    if fmt == "round_robin":
        if not (2 <= n <= 40):
            raise APIError(400, "VALIDATION_ERROR", "Round robin team count must be between 2 and 40", {"fields": ["teams"]})
        legs = params.get("legs", 1)
        if legs not in (1, 2):
            raise APIError(400, "VALIDATION_ERROR", "legs must be 1 or 2", {"fields": ["params.legs"]})
        
        withdrawals = params.get("withdrawals", [])
        withdrawal_policy = params.get("withdrawal_policy", "forfeit_remaining")
        if withdrawal_policy not in ("forfeit_remaining", "void_all"):
            raise APIError(400, "VALIDATION_ERROR", "Invalid withdrawal_policy", {"fields": ["params.withdrawal_policy"]})

        team_list = list(teams)
        is_odd = (n % 2 != 0)
        if is_odd:
            team_list.append("__BYE__")
        N = len(team_list)
        rounds_per_leg = N - 1
        total_rounds = rounds_per_leg * legs

        # Validate withdrawals
        withdrawal_map = {}
        for w in withdrawals:
            tid = w.get("team_id")
            ar = w.get("after_round")
            if tid not in teams or not isinstance(ar, int) or isinstance(ar, bool) or not (0 <= ar <= total_rounds):
                raise APIError(400, "VALIDATION_ERROR", "Invalid withdrawal specification", {"fields": ["params.withdrawals"]})
            withdrawal_map[tid] = ar

        # Generate rounds using standard polygon / circle method
        # Fix team_list[0], rotate team_list[1:]
        rounds_data = []
        summary = {"total": 0, "scheduled": 0, "forfeit": 0, "voided": 0}

        # Track home/away per team
        home_count = {t: 0 for t in teams}
        away_count = {t: 0 for t in teams}

        # Generate base pairings for leg 1
        leg1_rounds = []
        ring = team_list[1:]
        for r_idx in range(rounds_per_leg):
            round_teams = [team_list[0]] + ring
            r_pairs = []
            for i in range(N // 2):
                t1 = round_teams[i]
                t2 = round_teams[N - 1 - i]
                r_pairs.append((t1, t2))
            leg1_rounds.append(r_pairs)
            ring = [ring[-1]] + ring[:-1]

        global_round = 1
        for leg in range(1, legs + 1):
            for r_idx in range(rounds_per_leg):
                r_num = global_round
                pairs = leg1_rounds[r_idx]
                r_matches = []
                r_byes = []
                m_idx = 1

                for t1, t2 in pairs:
                    if t1 == "__BYE__":
                        r_byes.append(t2)
                        continue
                    if t2 == "__BYE__":
                        r_byes.append(t1)
                        continue

                    # Decide home / away
                    if leg == 1:
                        # Circle balance: alternate based on round index
                        if (r_idx + (pairs.index((t1, t2)))) % 2 == 0:
                            home, away = t1, t2
                        else:
                            home, away = t2, t1
                    else:
                        # Reverse leg 1
                        # Find corresponding leg 1 home/away
                        leg1_match = rounds_data[r_idx]["matches"][m_idx - 1]
                        home, away = leg1_match["away"], leg1_match["home"]

                    mid = f"RR-L{leg}-R{r_num}-M{m_idx}"
                    m_idx += 1
                    summary["total"] += 1

                    # Check withdrawal
                    w1 = withdrawal_map.get(home)
                    w2 = withdrawal_map.get(away)

                    m_status = "scheduled"
                    awarded_to = None

                    if withdrawal_policy == "void_all":
                        if w1 is not None or w2 is not None:
                            m_status = "voided"
                            summary["voided"] += 1
                        else:
                            summary["scheduled"] += 1
                    else: # forfeit_remaining
                        w1_active = (w1 is not None and r_num > w1)
                        w2_active = (w2 is not None and r_num > w2)
                        if w1_active and w2_active:
                            m_status = "voided"
                            summary["voided"] += 1
                        elif w1_active:
                            m_status = "forfeit"
                            awarded_to = away
                            summary["forfeit"] += 1
                        elif w2_active:
                            m_status = "forfeit"
                            awarded_to = home
                            summary["forfeit"] += 1
                        else:
                            summary["scheduled"] += 1

                    r_matches.append({
                        "match_id": mid,
                        "leg": leg,
                        "home": home,
                        "away": away,
                        "status": m_status,
                        "awarded_to": awarded_to
                    })

                rounds_data.append({
                    "round": r_num,
                    "matches": r_matches,
                    "byes": r_byes
                })
                global_round += 1

        return {
            "format": "round_robin",
            "legs": legs,
            "team_count": n,
            "round_count": total_rounds,
            "rounds": rounds_data,
            "summary": summary
        }

    elif fmt == "single_elim":
        if not (2 <= n <= 128):
            raise APIError(400, "VALIDATION_ERROR", "Single elim team count must be 2-128", {"fields": ["teams"]})
        
        B = 1
        while B < n:
            B *= 2
        num_rounds = int(math.log2(B))
        seed_order = get_seed_order(B)

        third_place = params.get("third_place_match", False)
        results = {r["match_id"]: r["winner"] for r in (params.get("results") or [])}

        # Build round 1 matches
        rounds = []
        matches_by_id = {}

        # Pre-create all match objects across all rounds
        for r in range(1, num_rounds + 1):
            r_match_count = B // (2 ** r)
            r_matches = []
            for i in range(1, r_match_count + 1):
                mid = f"R{r}M{i}"
                winner_to = None
                if r < num_rounds:
                    target_i = math.ceil(i / 2)
                    slot = "home" if i % 2 != 0 else "away"
                    winner_to = {"match_id": f"R{r+1}M{target_i}", "slot": slot}

                m_obj = {
                    "match_id": mid,
                    "bracket": "main",
                    "round": r,
                    "index": i,
                    "home": None,
                    "away": None,
                    "home_seed": None,
                    "away_seed": None,
                    "bye": False,
                    "winner": None,
                    "loser": None,
                    "winner_to": winner_to,
                    "loser_to": None
                }
                r_matches.append(m_obj)
                matches_by_id[mid] = m_obj
            rounds.append({"round": r, "matches": r_matches})

        # Fill Round 1 teams
        for i in range(1, (B // 2) + 1):
            mid = f"R1M{i}"
            m_obj = matches_by_id[mid]
            s1 = seed_order[2 * i - 2]
            s2 = seed_order[2 * i - 1]

            t1 = teams[s1 - 1] if s1 <= n else None
            t2 = teams[s2 - 1] if s2 <= n else None

            m_obj["home"] = t1
            m_obj["home_seed"] = s1
            m_obj["away"] = t2
            m_obj["away_seed"] = s2

            if t2 is None:
                m_obj["bye"] = True
                m_obj["winner"] = t1
                m_obj["loser"] = None
                if m_obj["winner_to"]:
                    target_m = matches_by_id[m_obj["winner_to"]["match_id"]]
                    target_m[m_obj["winner_to"]["slot"]] = t1

        # Handle third place match if requested
        if third_place and num_rounds >= 2:
            tp_match = {
                "match_id": "TP",
                "bracket": "third_place",
                "round": num_rounds,
                "index": 1,
                "home": None,
                "away": None,
                "home_seed": None,
                "away_seed": None,
                "bye": False,
                "winner": None,
                "loser": None,
                "winner_to": None,
                "loser_to": None
            }
            matches_by_id["TP"] = tp_match
            # Semifinals losers point to TP
            semi1 = matches_by_id[f"R{num_rounds - 1}M1"]
            semi2 = matches_by_id[f"R{num_rounds - 1}M2"]
            semi1["loser_to"] = {"match_id": "TP", "slot": "home"}
            semi2["loser_to"] = {"match_id": "TP", "slot": "away"}

        # Propagate results
        for r_item in (params.get("results") or []):
            mid = r_item.get("match_id")
            winner = r_item.get("winner")
            if mid not in matches_by_id:
                raise APIError(400, "VALIDATION_ERROR", f"Unknown match_id {mid}", {"fields": ["params.results"]})
            m_obj = matches_by_id[mid]
            if winner not in (m_obj["home"], m_obj["away"]):
                raise APIError(400, "VALIDATION_ERROR", f"Winner {winner} not in match {mid}", {"fields": ["params.results"]})
            
            m_obj["winner"] = winner
            loser = m_obj["away"] if winner == m_obj["home"] else m_obj["home"]
            m_obj["loser"] = loser

            if m_obj["winner_to"]:
                target_m = matches_by_id[m_obj["winner_to"]["match_id"]]
                target_m[m_obj["winner_to"]["slot"]] = winner
            if m_obj["loser_to"]:
                target_m = matches_by_id[m_obj["loser_to"]["match_id"]]
                target_m[m_obj["loser_to"]["slot"]] = loser

        return {
            "format": "single_elim",
            "bracket_size": B,
            "rounds": rounds
        }

    elif fmt == "double_elim":
        if not (3 <= n <= 128):
            raise APIError(400, "VALIDATION_ERROR", "Double elim team count must be 3-128", {"fields": ["teams"]})
        
        B = 1
        while B < n:
            B *= 2
        k = int(math.log2(B))
        bracket_reset = params.get("bracket_reset", True)

        seed_order = get_seed_order(B)
        matches_by_id = {}

        # Winners bracket
        winners_rounds = []
        for r in range(1, k + 1):
            r_match_count = B // (2 ** r)
            r_matches = []
            for i in range(1, r_match_count + 1):
                mid = f"WR{r}M{i}"
                winner_to = None
                if r < k:
                    target_i = math.ceil(i / 2)
                    slot = "home" if i % 2 != 0 else "away"
                    winner_to = {"match_id": f"WR{r+1}M{target_i}", "slot": slot}
                else:
                    winner_to = {"match_id": "GF1", "slot": "home"}

                m_obj = {
                    "match_id": mid,
                    "bracket": "winners",
                    "round": r,
                    "index": i,
                    "home": None,
                    "away": None,
                    "home_seed": None,
                    "away_seed": None,
                    "bye": False,
                    "winner": None,
                    "loser": None,
                    "winner_to": winner_to,
                    "loser_to": None
                }
                r_matches.append(m_obj)
                matches_by_id[mid] = m_obj
            winners_rounds.append({"round": r, "matches": r_matches})

        # Losers bracket: 2*(k - 1) rounds
        losers_rounds = []
        total_lr_rounds = 2 * (k - 1)
        for r in range(1, total_lr_rounds + 1):
            j = (r + 1) // 2
            lr_match_count = B // (2 ** (j + 1))
            r_matches = []
            for i in range(1, lr_match_count + 1):
                mid = f"LR{r}M{i}"
                winner_to = None
                if r < total_lr_rounds:
                    next_r = r + 1
                    next_j = (next_r + 1) // 2
                    next_match_count = B // (2 ** (next_j + 1))
                    target_i = i if next_match_count == lr_match_count else math.ceil(i / 2)
                    slot = "home" if r % 2 != 0 else ("home" if i % 2 != 0 else "away")
                    winner_to = {"match_id": f"LR{next_r}M{target_i}", "slot": slot}
                else:
                    winner_to = {"match_id": "GF1", "slot": "away"}

                m_obj = {
                    "match_id": mid,
                    "bracket": "losers",
                    "round": r,
                    "index": i,
                    "home": None,
                    "away": None,
                    "home_seed": None,
                    "away_seed": None,
                    "bye": False,
                    "winner": None,
                    "loser": None,
                    "winner_to": winner_to,
                    "loser_to": None
                }
                r_matches.append(m_obj)
                matches_by_id[mid] = m_obj
            losers_rounds.append({"round": r, "matches": r_matches})

        # Grand Final GF1 & GF2
        gf1 = {
            "match_id": "GF1",
            "bracket": "grand_final",
            "round": 1,
            "index": 1,
            "home": None,
            "away": None,
            "home_seed": None,
            "away_seed": None,
            "bye": False,
            "winner": None,
            "loser": None,
            "winner_to": None,
            "loser_to": None
        }
        matches_by_id["GF1"] = gf1
        grand_final = [gf1]

        if bracket_reset:
            gf2 = {
                "match_id": "GF2",
                "bracket": "grand_final",
                "round": 2,
                "index": 1,
                "home": None,
                "away": None,
                "home_seed": None,
                "away_seed": None,
                "bye": False,
                "conditional": True,
                "required": None,
                "winner": None,
                "loser": None,
                "winner_to": None,
                "loser_to": None
            }
            matches_by_id["GF2"] = gf2
            grand_final.append(gf2)

        # Winners bracket drops into losers bracket:
        # WR1 losers meet in LR1
        for i in range(1, (B // 4) + 1):
            lr_m = matches_by_id[f"LR1M{i}"]
            matches_by_id[f"WR1M{2*i - 1}"]["loser_to"] = {"match_id": lr_m["match_id"], "slot": "home"}
            matches_by_id[f"WR1M{2*i}"]["loser_to"] = {"match_id": lr_m["match_id"], "slot": "away"}

        # WRr (r >= 2) drop into LR(2r - 2)
        for r in range(2, k):
            r_match_count = B // (2 ** r)
            for i in range(1, r_match_count + 1):
                target_r = 2 * r - 2
                lr_m = matches_by_id[f"LR{target_r}M{i}"]
                matches_by_id[f"WR{r}M{i}"]["loser_to"] = {"match_id": lr_m["match_id"], "slot": "away"}

        # WR final (WRk) loser drops to LB final (LR{total_lr_rounds}) away slot
        matches_by_id[f"WR{k}M1"]["loser_to"] = {"match_id": f"LR{total_lr_rounds}M1", "slot": "away"}

        # WR1 seeding
        for i in range(1, (B // 2) + 1):
            mid = f"WR1M{i}"
            m_obj = matches_by_id[mid]
            s1 = seed_order[2 * i - 2]
            s2 = seed_order[2 * i - 1]
            t1 = teams[s1 - 1] if s1 <= n else None
            t2 = teams[s2 - 1] if s2 <= n else None
            m_obj["home"] = t1
            m_obj["home_seed"] = s1
            m_obj["away"] = t2
            m_obj["away_seed"] = s2
            if t2 is None:
                m_obj["bye"] = True
                m_obj["winner"] = t1
                if m_obj["winner_to"]:
                    target_m = matches_by_id[m_obj["winner_to"]["match_id"]]
                    target_m[m_obj["winner_to"]["slot"]] = t1

        # Apply results
        for r_item in (params.get("results") or []):
            mid = r_item.get("match_id")
            winner = r_item.get("winner")
            if mid not in matches_by_id:
                raise APIError(400, "VALIDATION_ERROR", f"Unknown match_id {mid}", {"fields": ["params.results"]})
            m_obj = matches_by_id[mid]
            if winner not in (m_obj["home"], m_obj["away"]):
                raise APIError(400, "VALIDATION_ERROR", f"Winner {winner} not in match {mid}", {"fields": ["params.results"]})

            m_obj["winner"] = winner
            loser = m_obj["away"] if winner == m_obj["home"] else m_obj["home"]
            m_obj["loser"] = loser

            if m_obj["winner_to"]:
                target_m = matches_by_id[m_obj["winner_to"]["match_id"]]
                target_m[m_obj["winner_to"]["slot"]] = winner
            if m_obj["loser_to"]:
                target_m = matches_by_id[m_obj["loser_to"]["match_id"]]
                target_m[m_obj["loser_to"]["slot"]] = loser

            if mid == "GF1" and bracket_reset:
                gf2 = matches_by_id["GF2"]
                gf2["home"] = gf1["home"]
                gf2["away"] = gf1["away"]
                # Required if GF1 winner is GF1.away (losers champion)
                if winner == gf1["away"]:
                    gf2["required"] = True
                else:
                    gf2["required"] = False

        return {
            "format": "double_elim",
            "bracket_size": B,
            "bracket_reset": bracket_reset,
            "winners": winners_rounds,
            "losers": losers_rounds,
            "grand_final": grand_final
        }

    elif fmt == "swiss":
        if not (2 <= n <= 64):
            raise APIError(400, "VALIDATION_ERROR", "Swiss team count must be 2-64", {"fields": ["teams"]})
        
        default_tot = math.ceil(math.log2(n))
        total_rounds = params.get("total_rounds", default_tot)
        round_to_pair = params.get("round", 1)
        history = params.get("history", [])

        if len(history) != round_to_pair - 1:
            raise APIError(400, "VALIDATION_ERROR", "History must contain exactly rounds 1..round - 1", {"fields": ["params.history"]})

        # Calculate scores & Buchholz from history
        scores = {t: 0.0 for t in teams}
        met_pairs = set()
        played_opponents = {t: set() for t in teams}
        had_bye = set()

        for h in history:
            b_team = h.get("bye")
            if b_team:
                scores[b_team] += 1.0
                had_bye.add(b_team)
            for m in h.get("matches", []):
                h_team, a_team, res = m["home"], m["away"], m["result"]
                pair = tuple(sorted([h_team, a_team]))
                met_pairs.add(pair)
                played_opponents[h_team].add(a_team)
                played_opponents[a_team].add(h_team)
                if res == "home":
                    scores[h_team] += 1.0
                elif res == "away":
                    scores[a_team] += 1.0
                elif res == "draw":
                    scores[h_team] += 0.5
                    scores[a_team] += 0.5

        buchholz = {
            t: sum(scores[opp] for opp in played_opponents[t])
            for t in teams
        }

        # Standings table before this round
        team_indices = {t: idx for idx, t in enumerate(teams)}
        sorted_teams = sorted(
            teams,
            key=lambda t: (-scores[t], -buchholz[t], team_indices[t])
        )

        standings = [
            {
                "rank": idx + 1,
                "team_id": t,
                "score": scores[t],
                "buchholz": buchholz[t]
            }
            for idx, t in enumerate(sorted_teams)
        ]

        # Round 1 exact matching
        if round_to_pair == 1:
            m = n // 2
            bye_team = sorted_teams[-1] if n % 2 != 0 else None
            pairings = []
            for i in range(m):
                pairings.append({
                    "match_id": f"SW-R1-M{i+1}",
                    "home": sorted_teams[i],
                    "away": sorted_teams[i + m]
                })
            return {
                "format": "swiss",
                "round": 1,
                "total_rounds": total_rounds,
                "pairings": pairings,
                "bye": bye_team,
                "standings": standings
            }

        # Rounds >= 2 with backtracking matching
        # Candidate byes if n odd: lowest-scoring team that has not had a bye, tie -> lowest seed (largest index)
        bye_candidates = [None]
        if n % 2 != 0:
            candidates = [t for t in sorted_teams if t not in had_bye]
            # sort by score asc, then team index desc
            candidates.sort(key=lambda t: (scores[t], -team_indices[t]))
            bye_candidates = candidates

        best_pairings = None
        best_diff = float("inf")
        chosen_bye = None

        for cand_bye in bye_candidates:
            active_teams = [t for t in sorted_teams if t != cand_bye]

            # Backtracking to find rematch-free pairing with minimum score difference
            def backtrack(remaining: List[str], current_pairs: List[Tuple[str, str]], curr_diff: float):
                nonlocal best_pairings, best_diff
                if curr_diff >= best_diff:
                    return
                if not remaining:
                    best_diff = curr_diff
                    best_pairings = list(current_pairs)
                    return

                first = remaining[0]
                rest = remaining[1:]
                for idx, candidate in enumerate(rest):
                    pair = tuple(sorted([first, candidate]))
                    if pair not in met_pairs:
                        diff = abs(scores[first] - scores[candidate])
                        next_remaining = rest[:idx] + rest[idx+1:]
                        backtrack(next_remaining, current_pairs + [(first, candidate)], curr_diff + diff)

            backtrack(active_teams, [], 0.0)
            if best_pairings is not None:
                chosen_bye = cand_bye
                break

        if best_pairings is None:
            raise APIError(409, "NO_VALID_PAIRING", f"No valid pairing exists for round {round_to_pair}", {"round": round_to_pair})

        formatted_pairings = [
            {
                "match_id": f"SW-R{round_to_pair}-M{idx+1}",
                "home": p[0],
                "away": p[1]
            }
            for idx, p in enumerate(best_pairings)
        ]

        return {
            "format": "swiss",
            "round": round_to_pair,
            "total_rounds": total_rounds,
            "pairings": formatted_pairings,
            "bye": chosen_bye,
            "standings": standings
        }

    else:
        raise APIError(400, "VALIDATION_ERROR", f"Unknown format {fmt}", {"fields": ["format"]})
