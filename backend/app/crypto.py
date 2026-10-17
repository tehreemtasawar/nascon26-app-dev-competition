import hmac
import hashlib
import json
from typing import Any

def canonical(obj: Any) -> str:
    """Canonical JSON according to Section 5.3:
    Recursively sorted object keys (ascending by Unicode code point);
    no whitespace (separators , and :); UTF-8; non-ASCII characters not escaped;
    integers without decimal point; true/false/null lowercase. Array order preserved.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sign(salt: str, id_: str, payload_obj: Any) -> str:
    """HMAC-SHA256 lowercase hex of id + '|' + canonical(payload_obj) using salt."""
    msg = (id_ + "|" + canonical(payload_obj)).encode("utf-8")
    return hmac.new(salt.encode("utf-8"), msg, hashlib.sha256).hexdigest()

def lots_key(seed: int, league_id: str, team_id: str) -> str:
    """SHA256 hex of seed + '|' + league_id + '|' + team_id (decimal seed, UTF-8)."""
    return hashlib.sha256(f"{seed}|{league_id}|{team_id}".encode("utf-8")).hexdigest()
