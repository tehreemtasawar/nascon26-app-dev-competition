# Traceability

| ID | Source | Verification |
|---|---|---|
| FR-1.1 | `backend/server.js`: sport validation, event log, HMAC signatures, score projection | `run_tests.sh` |
| FR-1.2 | `backend/server.js`: `POST /audit/v1/leagues` | `run_tests.sh` |
| FR-1.3 | `backend/server.js`: `POST /audit/v1/fixtures` | `run_tests.sh` |
| FR-1.4 | `backend/server.js`: `GET /audit/v1/standings/:id` | `run_tests.sh` |
| FR-2.1 | `backend/server.js`: reset baseline tenants and authenticated demo users | `run_tests.sh` |
| FR-2.2 | `backend/server.js`: roster setup, transfer, and history routes | `run_tests.sh` |
| FR-2.3 | `backend/server.js`: checkout, inventory, stock reservation, and receipts | `run_tests.sh` |
| NFR-3 | `backend/server.js`: atomic in-process stock decrement before payment capture | `run_tests.sh` |
| NFR-4 | `backend/server.js`: offline-sync action replay and idempotency | `run_tests.sh` |
| NFR-7 | `docker-compose.yml`, `backend/Dockerfile`, `backend/server.js` | Docker build and `/health` |
| NFR-4 / mobile | `mobile/app/src/main/java/test/nascon/mobile/MainActivity.kt` | Android build on SDK-enabled machine |
| RBAC / security | `backend/server.js`: signed tokens, tenant ownership probes, rate limiter, malformed-body handling | RBAC matrix smoke test |
| Realtime | `backend/server.js`: `/audit/v1/stream/:id` SSE endpoint | Event stream smoke test |
