# API Notes (shared between backend and mobile)

The grader routes (/audit/v1/*) are defined in the Part I spec, Section 5. The mobile app also needs
production routes. Backend teammates: fill in the real paths and shapes as you build them, so the
mobile app can connect.

## Needed by the mobile app (proposed, confirm or change)

| Purpose | Method and path (proposed) | Owner | Status |
|---|---|---|---|
| Login (email, password) returning token and role | POST /api/v1/auth/login | Teammate 2 | |
| Fixtures list | GET /api/v1/fixtures | Teammate 1 | |
| Match detail with live score and events | GET /api/v1/matches/{match_id} | Teammate 1 | |
| Standings | GET /api/v1/leagues/{league_id}/standings | Teammate 1 | |
| Append score or compensating event | POST /api/v1/events | Teammate 1 | |
| Club profile and roster | GET /api/v1/clubs/{club_id} | Teammate 2 | |
| Roster action (transfer, loan, release) | POST /api/v1/roster/transfer | Teammate 2 | |
| Store catalogue | GET /api/v1/store/products | Teammate 2 | |
| Checkout and receipt | POST /api/v1/store/checkout | Teammate 2 | |
| Offline sync (replay queued actions) | POST /api/v1/offline-sync (or /audit/v1/offline-sync) | Teammate 1 and 2 | |

## Notes
- The spec says /audit/v1/* routes need no Authorization header (except the RBAC probes).
- Offline queue action format is in the spec, Section 5.14.
