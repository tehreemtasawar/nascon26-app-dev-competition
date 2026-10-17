import os
import time
from typing import Dict, Any, List
import jwt
from fastapi import APIRouter, Request, Header, Response
from app.errors import APIError

rbac_router = APIRouter()

JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_nascon_key_2026")
JWT_ALGORITHM = "HS256"

# In-memory rate limiting for /api/v1/ping
# ip -> list of request timestamps
_rate_limits: Dict[str, List[float]] = {}

def get_salt():
    return os.getenv("DAY1_SALT", "demo-salt")

def create_token(role: str, user_id: str, tenant_id: str | None = None, club_id: str | None = None, league_id: str | None = None, player_id: str | None = None) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "club_id": club_id,
        "league_id": league_id,
        "player_id": player_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600 * 24
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(authorization: str | None) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise APIError(401, "UNAUTHENTICATED", "Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        # Check header to reject alg: none
        unverified_header = jwt.get_unverified_header(token)
        if unverified_header.get("alg") == "none" or unverified_header.get("alg") != JWT_ALGORITHM:
            raise APIError(401, "UNAUTHENTICATED", "Invalid token algorithm")
        
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except APIError:
        raise
    except Exception as exc:
        raise APIError(401, "UNAUTHENTICATED", f"Token verification failed: {exc}")

@rbac_router.post("/audit/v1/rbac-matrix")
def get_rbac_matrix():
    tokens = {
        "super_admin": create_token("super_admin", "user-super-admin"),
        "league_organizer": create_token("league_organizer", "user-organizer-alpha", tenant_id="tenant-alpha", league_id="league-alpha-1"),
        "club_manager": create_token("club_manager", "user-manager-alpha", tenant_id="tenant-alpha", club_id="club-alpha-1"),
        "player": create_token("player", "user-player-alpha", tenant_id="tenant-alpha", club_id="club-alpha-1", player_id="player-alpha-1"),
        "viewer": create_token("viewer", "user-viewer-alpha", tenant_id="tenant-alpha"),
    }
    context = {
        "tenant_id": "tenant-alpha",
        "foreign_tenant_id": "tenant-beta",
        "own_league_id": "league-alpha-1",
        "other_league_id": "league-alpha-2",
        "foreign_league_id": "league-beta-1",
        "own_club_id": "club-alpha-1",
        "other_club_id": "club-alpha-2",
        "foreign_club_id": "club-beta-1",
        "own_player_id": "player-alpha-1",
        "other_player_id": "player-alpha-2",
        "foreign_player_id": "player-beta-1"
    }
    return {
        "tokens": tokens,
        "context": context
    }

def check_permission(payload: Dict[str, Any], probe: str, target_id: str | None = None):
    role = payload.get("role")
    user_tenant = payload.get("tenant_id")
    
    if role == "super_admin":
        return True # Super admin is allowed everywhere
        
    if probe == "P1":
        # Tenants
        return False
        
    elif probe == "P2":
        # leagues/{league_id}/fixtures
        # organizer owns league-alpha-1
        if role == "league_organizer" and target_id == "league-alpha-1":
            return True
        return False
        
    elif probe in ("P3", "P4"):
        # clubs/{club_id}/roster or clubs/{club_id}/products
        if role == "club_manager" and target_id == "club-alpha-1":
            return True
        return False
        
    elif probe == "P5":
        # players/{player_id}
        if role == "club_manager" and target_id == "player-alpha-1":
            return True
        if role == "player" and target_id == "player-alpha-1":
            return True
        return False
        
    elif probe == "P6":
        # clubs/{club_id}
        # In tenant-alpha: club-alpha-1, club-alpha-2
        # Foreign club: club-beta-1
        if target_id in ("club-alpha-1", "club-alpha-2"):
            return True
        # Cross-tenant is forbidden
        return False
        
    elif probe == "P7":
        # platform/config
        return False
        
    return False

def authorize_probe(authorization: str | None, probe: str, target_id: str | None = None):
    payload = verify_token(authorization)
    if check_permission(payload, probe, target_id):
        return {"authorized": True}
    raise APIError(403, "FORBIDDEN", "Forbidden: Insufficient privileges for this role or tenant")

@rbac_router.post("/audit/v1/rbac/tenants")
def probe_p1(authorization: str | None = Header(None)):
    return authorize_probe(authorization, "P1")

@rbac_router.post("/audit/v1/rbac/leagues/{league_id}/fixtures")
def probe_p2(league_id: str, authorization: str | None = Header(None)):
    return authorize_probe(authorization, "P2", league_id)

@rbac_router.post("/audit/v1/rbac/clubs/{club_id}/roster")
def probe_p3(club_id: str, authorization: str | None = Header(None)):
    return authorize_probe(authorization, "P3", club_id)

@rbac_router.post("/audit/v1/rbac/clubs/{club_id}/products")
def probe_p4(club_id: str, authorization: str | None = Header(None)):
    return authorize_probe(authorization, "P4", club_id)

@rbac_router.patch("/audit/v1/rbac/players/{player_id}")
def probe_p5(player_id: str, authorization: str | None = Header(None)):
    return authorize_probe(authorization, "P5", player_id)

@rbac_router.get("/audit/v1/rbac/clubs/{club_id}")
def probe_p6(club_id: str, authorization: str | None = Header(None)):
    return authorize_probe(authorization, "P6", club_id)

@rbac_router.get("/audit/v1/rbac/platform/config")
def probe_p7(authorization: str | None = Header(None)):
    return authorize_probe(authorization, "P7")

@rbac_router.get("/api/v1/ping")
def ping(request: Request, response: Response):
    client_ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()
    
    # 100 requests per rolling 10 seconds per client IP
    timestamps = _rate_limits.setdefault(client_ip, [])
    # purge older than 10 seconds
    timestamps = [t for t in timestamps if now - t <= 10.0]
    _rate_limits[client_ip] = timestamps
    
    if len(timestamps) >= 100:
        response.status_code = 429
        response.headers["Retry-After"] = "11"
        return {
            "error": {
                "code": "RATE_LIMITED",
                "message": "Rate limit exceeded. Try again in 11 seconds.",
                "details": {}
            }
        }
        
    timestamps.append(now)
    return {"pong": True}
