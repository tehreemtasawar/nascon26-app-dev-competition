import pytest
from app.rbac import get_rbac_matrix, verify_token, check_permission, create_token
from app.errors import APIError

def test_rbac_matrix_structure():
    matrix = get_rbac_matrix()
    assert "tokens" in matrix
    assert "context" in matrix
    tokens = matrix["tokens"]
    for role in ("super_admin", "league_organizer", "club_manager", "player", "viewer"):
        assert role in tokens
        payload = verify_token("Bearer " + tokens[role])
        assert payload["role"] == role

def test_rbac_probes_super_admin():
    matrix = get_rbac_matrix()
    admin_token = matrix["tokens"]["super_admin"]
    admin_payload = verify_token("Bearer " + admin_token)
    for probe in ("P1", "P2", "P3", "P4", "P5", "P6", "P7"):
        assert check_permission(admin_payload, probe, "any_id") is True

def test_rbac_probes_roles_matrix():
    matrix = get_rbac_matrix()
    org_payload = verify_token("Bearer " + matrix["tokens"]["league_organizer"])
    assert check_permission(org_payload, "P2", "league-alpha-1") is True
    assert check_permission(org_payload, "P2", "league-alpha-2") is False
    assert check_permission(org_payload, "P1") is False

    mgr_payload = verify_token("Bearer " + matrix["tokens"]["club_manager"])
    assert check_permission(mgr_payload, "P3", "club-alpha-1") is True
    assert check_permission(mgr_payload, "P3", "club-alpha-2") is False
    assert check_permission(mgr_payload, "P5", "player-alpha-1") is True
    assert check_permission(mgr_payload, "P5", "player-alpha-2") is False

    player_payload = verify_token("Bearer " + matrix["tokens"]["player"])
    assert check_permission(player_payload, "P5", "player-alpha-1") is True
    assert check_permission(player_payload, "P5", "player-alpha-2") is False
    assert check_permission(player_payload, "P4", "club-alpha-1") is False

    viewer_payload = verify_token("Bearer " + matrix["tokens"]["viewer"])
    assert check_permission(viewer_payload, "P6", "club-alpha-1") is True
    assert check_permission(viewer_payload, "P6", "club-beta-1") is False
    assert check_permission(viewer_payload, "P1") is False
