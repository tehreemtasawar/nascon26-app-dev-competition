# NaSCon 26 App Dev - Part I

## Run

```sh
DAY1_SALT=replace-with-your-team-salt docker compose up -d --build
```

The API is available on `http://localhost:8080`. The salt is read only at
startup and is never committed to the repository.

The backend provides the audit contract for:

- data-driven sports and signed event-sourced scoring;
- round-robin, Swiss, single-elimination, and double-elimination fixture output;
- league creation and recomputed standings with head-to-head matrices;
- roster setup, transfers, loans, releases, and immutable audit history;
- atomic mock-gateway checkout, signed receipts, inventory, and PDF receipts;
- offline action replay and authenticated demo login/ping routes.

The Android source project is in [mobile](./mobile). It includes configurable
API access, encrypted token storage, cached responses, and a persistent pending
action queue. A signed APK must be produced on a machine with Android SDK and
Gradle installed and placed at `mobile/release/app-release.apk`; this workspace
does not contain an Android SDK, so a binary APK is not generated here.

The Docker Compose stack includes PostgreSQL 16, Redis 7, RabbitMQ, and MinIO
alongside the API. The current domain state is kept in-process for deterministic
audit reset behavior; the service URLs are exposed to the API for the queue,
cache, database, and object-store integration boundary.

The five demo accounts use password `Nascon@26`:
`admin@nascon.test`, `organizer@nascon.test`, `manager@nascon.test`,
`player@nascon.test`, and `viewer@nascon.test`.

Run the included smoke command after starting the service:

```sh
sh run_tests.sh
```
