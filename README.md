# NaSCon '26 App Dev, Part I: Multi-Sport League & Club Operations Platform

## Run the backend

```
DAY1_SALT=<your-salt> docker compose up -d --build
```

- API: http://localhost:8080 (health check: GET /health)
- Locally, put `DAY1_SALT=<your-salt>` in a `.env` file (it is git-ignored). Never commit the real salt.

## Run the tests

```
./run_tests.sh
```

## Mobile app

- Source: `mobile/` (Flutter, Android)
- Built app: `mobile/release/app-release.apk`
- The server address can be changed inside the app (settings screen). Emulator: 10.0.2.2:8080. Phone: the laptop's LAN IP, port 8080.

## Demo accounts (password for all: Nascon@26)

| Role | Email |
|---|---|
| Platform Super-Admin | admin@nascon.test |
| League Organizer (owns league-alpha-1) | organizer@nascon.test |
| Club Manager (owns club-alpha-1) | manager@nascon.test |
| Player (player-alpha-1) | player@nascon.test |
| General Viewer | viewer@nascon.test |

## Repository layout

```
backend/    API, scoring engine, workers
mobile/     Flutter app
tests/      unit tests
docs/       API notes
```
