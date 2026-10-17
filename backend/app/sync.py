from typing import Dict, Any, List
from fastapi import APIRouter
from app.db import get_db
from app.crypto import canonical
from app.errors import APIError
from app.events import append_event, compute_score_projection
from app.roster import roster_transfer
from starlette.responses import Response

sync_router = APIRouter()

@sync_router.post("/audit/v1/offline-sync")
def offline_sync(body: Dict[str, Any]):
    device_id = body.get("device_id")
    actions = body.get("actions")

    if not isinstance(device_id, str) or not device_id or not isinstance(actions, list) or not (1 <= len(actions) <= 100):
        raise APIError(400, "VALIDATION_ERROR", "Offline sync validation failed", {"fields": ["actions"]})

    with get_db() as conn:
        with conn.cursor() as cur:
            # Check previously processed actions for device
            cur.execute("SELECT action_id, result FROM offline_sync_records WHERE device_id = %s", (device_id,))
            previous_actions = {r[0]: r[1] for r in cur.fetchall()}

    # Pair each action with its original index
    indexed_actions = list(enumerate(actions))
    # Sort by queued_at ascending (ties: original index order)
    sorted_actions = sorted(indexed_actions, key=lambda x: (x[1].get("queued_at", ""), x[0]))

    results_by_index = {}
    summary = {"applied": 0, "rejected": 0, "duplicate": 0}

    for proc_order, (orig_idx, act) in enumerate(sorted_actions, 1):
        action_id = act.get("action_id")
        act_type = act.get("type")
        base_ver = act.get("base_version")
        payload = act.get("payload")

        # Duplicate check
        if action_id in previous_actions:
            res_obj = previous_actions[action_id]
            res_obj["status"] = "duplicate"
            res_obj["resolution"] = "skipped_duplicate"
            res_obj["error_code"] = None
            summary["duplicate"] += 1
            results_by_index[orig_idx] = res_obj
            continue

        if not isinstance(base_ver, int) or base_ver < 0 or not isinstance(payload, dict):
            res_obj = {
                "action_id": action_id,
                "status": "rejected",
                "resolution": "server_wins",
                "error_code": "VALIDATION_ERROR",
                "processed_order": proc_order,
                "server_version": 0,
                "signature": None
            }
            summary["rejected"] += 1
            results_by_index[orig_idx] = res_obj
            continue

        curr_ver = 0
        signature = None

        try:
            if act_type == "score_event":
                mid = payload.get("match_id")
                try:
                    score_info = compute_score_projection(mid)
                    curr_ver = score_info["version"]
                except APIError as e:
                    res_obj = {
                        "action_id": action_id,
                        "status": "rejected",
                        "resolution": "server_wins",
                        "error_code": e.code,
                        "processed_order": proc_order,
                        "server_version": curr_ver,
                        "signature": None
                    }
                    summary["rejected"] += 1
                    results_by_index[orig_idx] = res_obj
                    continue

                if base_ver > curr_ver:
                    res_obj = {
                        "action_id": action_id,
                        "status": "rejected",
                        "resolution": "server_wins",
                        "error_code": "INVALID_BASE_VERSION",
                        "processed_order": proc_order,
                        "server_version": curr_ver,
                        "signature": None
                    }
                    summary["rejected"] += 1
                    results_by_index[orig_idx] = res_obj
                    continue

                # Execute event
                dummy_resp = Response()
                ev_res = append_event(payload, dummy_resp)
                new_ver = ev_res["sequence"]
                signature = ev_res["signature"]

                status_str = "applied"
                res_str = "appended" if base_ver == curr_ver else "rebased_append"
                summary["applied"] += 1

                res_obj = {
                    "action_id": action_id,
                    "status": status_str,
                    "resolution": res_str,
                    "error_code": None,
                    "processed_order": proc_order,
                    "server_version": new_ver,
                    "signature": signature
                }
                results_by_index[orig_idx] = res_obj

            elif act_type == "roster_transfer":
                pid = payload.get("player_id")
                # Count current audit entries for player
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT COUNT(*) FROM roster_audit_entries WHERE player_id = %s", (pid,))
                        curr_ver = cur.fetchone()[0]

                if base_ver > curr_ver:
                    res_obj = {
                        "action_id": action_id,
                        "status": "rejected",
                        "resolution": "server_wins",
                        "error_code": "INVALID_BASE_VERSION",
                        "processed_order": proc_order,
                        "server_version": curr_ver,
                        "signature": None
                    }
                    summary["rejected"] += 1
                    results_by_index[orig_idx] = res_obj
                    continue

                dummy_resp = Response()
                tr_res = roster_transfer(payload, dummy_resp)
                new_ver = curr_ver + 1
                status_str = "applied"
                res_str = "appended" if base_ver == curr_ver else "rebased_append"
                summary["applied"] += 1

                res_obj = {
                    "action_id": action_id,
                    "status": status_str,
                    "resolution": res_str,
                    "error_code": None,
                    "processed_order": proc_order,
                    "server_version": new_ver,
                    "signature": None
                }
                results_by_index[orig_idx] = res_obj
            else:
                res_obj = {
                    "action_id": action_id,
                    "status": "rejected",
                    "resolution": "server_wins",
                    "error_code": "VALIDATION_ERROR",
                    "processed_order": proc_order,
                    "server_version": curr_ver,
                    "signature": None
                }
                summary["rejected"] += 1
                results_by_index[orig_idx] = res_obj

        except APIError as e:
            res_obj = {
                "action_id": action_id,
                "status": "rejected",
                "resolution": "server_wins",
                "error_code": e.code,
                "processed_order": proc_order,
                "server_version": curr_ver,
                "signature": None
            }
            summary["rejected"] += 1
            results_by_index[orig_idx] = res_obj

        # Save action record
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO offline_sync_records (device_id, action_id, result)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (device_id, action_id) DO NOTHING
                """, (device_id, action_id, canonical(res_obj)))
                conn.commit()

    ordered_results = [results_by_index[i] for i in range(len(actions))]

    return {
        "device_id": device_id,
        "results": ordered_results,
        "summary": summary
    }
