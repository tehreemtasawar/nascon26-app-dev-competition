import os
from typing import Any
import psycopg
from psycopg.types.json import Jsonb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.db import get_db, DATABASE_URL
from app.errors import setup_error_handlers
from app.sports import sports_router
from app.fixtures import fixtures_router
from app.standings import standings_router
from app.events import events_router
from app.store import store_router
from app.rbac import rbac_router
from app.roster import roster_router
from app.sync import sync_router

app = FastAPI(
    title="NaSCon 26 Backend",
    version="1.0.0",
)

# Attach error handlers & body size limit
setup_error_handlers(app)

# Include all module routers
app.include_router(sports_router)
app.include_router(fixtures_router)
app.include_router(standings_router)
app.include_router(events_router)
app.include_router(store_router)
app.include_router(rbac_router)
app.include_router(roster_router)
app.include_router(sync_router)

def create_tables():
    statements = [
        """
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sports (
            sport_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            rules JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS leagues (
            league_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
            name TEXT NOT NULL DEFAULT 'Demo League',
            season TEXT NOT NULL DEFAULT '2026'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS clubs (
            club_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
            name TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS players (
            player_id TEXT PRIMARY KEY,
            club_id TEXT REFERENCES clubs(club_id),
            name TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'apparel'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS variants (
            variant_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL REFERENCES products(product_id),
            size TEXT NOT NULL DEFAULT 'One Size',
            color TEXT NOT NULL DEFAULT 'Default',
            price_minor INTEGER NOT NULL DEFAULT 0 CHECK (price_minor >= 0),
            currency TEXT NOT NULL DEFAULT 'PKR'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS inventory (
            variant_id TEXT PRIMARY KEY REFERENCES variants(variant_id),
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
            reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS discounts (
            code TEXT PRIMARY KEY,
            percent_off INTEGER NOT NULL CHECK (percent_off BETWEEN 0 AND 100)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS demo_users (
            user_id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            tenant_id TEXT REFERENCES tenants(tenant_id),
            club_id TEXT REFERENCES clubs(club_id),
            league_id TEXT REFERENCES leagues(league_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS store_orders (
            order_id TEXT PRIMARY KEY,
            variant_id TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            total_minor INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Pending',
            request_body JSONB,
            response_body JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS match_streams (
            match_id TEXT PRIMARY KEY,
            league_id TEXT,
            sport_id TEXT NOT NULL,
            home_team_id TEXT NOT NULL,
            away_team_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'upcoming'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS match_events (
            sequence BIGINT NOT NULL,
            match_id TEXT NOT NULL,
            event_id TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            payload JSONB NOT NULL,
            signature TEXT NOT NULL,
            raw_body JSONB,
            response_body JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (match_id, sequence)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS leagues_registry (
            league_id TEXT PRIMARY KEY,
            sport_id TEXT NOT NULL,
            teams JSONB NOT NULL,
            fixtures JSONB NOT NULL,
            points JSONB NOT NULL,
            tie_break_order JSONB NOT NULL,
            qualification_spots INTEGER NOT NULL,
            lots_seed INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS roster_scenarios (
            league_id TEXT PRIMARY KEY,
            scenario JSONB NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS roster_audit_entries (
            audit_id TEXT PRIMARY KEY,
            request_id TEXT,
            action TEXT NOT NULL,
            player_id TEXT NOT NULL,
            league_id TEXT NOT NULL,
            from_squad_id TEXT,
            to_squad_id TEXT,
            effective_date DATE,
            state TEXT NOT NULL DEFAULT 'active',
            who TEXT NOT NULL,
            when_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            why TEXT,
            raw_entry JSONB NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS roster_transfer_requests (
            request_id TEXT PRIMARY KEY,
            raw_body JSONB NOT NULL,
            response_body JSONB NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS offline_sync_records (
            device_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            result JSONB NOT NULL,
            PRIMARY KEY (device_id, action_id)
        )
        """
    ]

    with get_db() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)

            cur.execute("ALTER TABLE leagues ADD COLUMN IF NOT EXISTS sport_id TEXT")
            cur.execute("ALTER TABLE leagues ALTER COLUMN sport_id DROP NOT NULL")
            cur.execute("ALTER TABLE discounts ADD COLUMN IF NOT EXISTS percentage INTEGER DEFAULT 10")
            cur.execute("ALTER TABLE discounts ALTER COLUMN percentage DROP NOT NULL")
            cur.execute("ALTER TABLE discounts ADD COLUMN IF NOT EXISTS percent_off INTEGER DEFAULT 10")
            cur.execute("ALTER TABLE discounts ALTER COLUMN percent_off DROP NOT NULL")
            cur.execute("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0)")
            cur.execute("ALTER TABLE sports ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS request_body JSONB")
            cur.execute("ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS response_body JSONB")



DEFAULT_STOCK = {
    "var-jersey-001-M": 1,
    "var-jersey-001-L": 5,
}


BASELINE_SPORTS = [
    (
        "football",
        "Football",
        {
            "sport_id": "football",
            "name": "Football",
            "scoring_model": "event",
            "periods": {"count": 2, "duration_minutes": 45},
            "scoring_events": {"goal": {"points": 1}},
            "draw_allowed": True,
            "overtime": {"policy": "none"},
            "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
            "roster": {"min_squad_size": 11, "max_squad_size": 25, "required_positions": {"gk": 1}}
        }
    ),
    (
        "basketball",
        "Basketball",
        {
            "sport_id": "basketball",
            "name": "Basketball",
            "scoring_model": "event",
            "periods": {"count": 4, "duration_minutes": 12},
            "scoring_events": {"free_throw": {"points": 1}, "two_pointer": {"points": 2}, "three_pointer": {"points": 3}},
            "draw_allowed": False,
            "overtime": {"policy": "extra_time", "duration_minutes": 5},
            "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
            "roster": {"min_squad_size": 5, "max_squad_size": 15, "required_positions": {}}
        }
    ),
    (
        "cricket",
        "Cricket",
        {
            "sport_id": "cricket",
            "name": "Cricket",
            "scoring_model": "innings",
            "periods": {"innings_per_team": 1, "overs_per_innings": 20, "balls_per_over": 6, "wickets_per_innings": 10},
            "scoring_events": {
                "dot_ball": {"runs": 0, "legal_ball": True, "wicket": False},
                "single": {"runs": 1, "legal_ball": True, "wicket": False},
                "two": {"runs": 2, "legal_ball": True, "wicket": False},
                "four": {"runs": 4, "legal_ball": True, "wicket": False},
                "six": {"runs": 6, "legal_ball": True, "wicket": False},
                "wide": {"runs": 1, "legal_ball": False, "wicket": False},
                "no_ball": {"runs": 1, "legal_ball": False, "wicket": False},
                "wicket": {"runs": 0, "legal_ball": True, "wicket": True}
            },
            "draw_allowed": True,
            "overtime": {"policy": "super_over"},
            "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
            "roster": {"min_squad_size": 11, "max_squad_size": 18, "required_positions": {"wicketkeeper": 1}}
        }
    ),
    (
        "esports",
        "Esports",
        {
            "sport_id": "esports",
            "name": "Esports",
            "scoring_model": "round",
            "periods": {"best_of": 3},
            "scoring_events": {"round_win": {"rounds": 1}},
            "draw_allowed": False,
            "overtime": {"policy": "none"},
            "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
            "roster": {"min_squad_size": 5, "max_squad_size": 8, "required_positions": {}}
        }
    )
]

def seed_baseline(
    stock_overrides: dict[str, int] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    stock = DEFAULT_STOCK.copy()

    if stock_overrides is not None:
        stock.update(stock_overrides)

    tenants = [
        ("tenant-alpha", "Alpha Sports"),
        ("tenant-beta", "Beta Athletics"),
    ]

    leagues = [
        ("league-alpha-1", "tenant-alpha", "football", "Alpha League 1", "2026"),
        ("league-alpha-2", "tenant-alpha", "football", "Alpha League 2", "2026"),
        ("league-beta-1", "tenant-beta", "football", "Beta League 1", "2026"),
    ]


    clubs = [
        ("club-alpha-1", "tenant-alpha", "Alpha Club 1"),
        ("club-alpha-2", "tenant-alpha", "Alpha Club 2"),
        ("club-beta-1", "tenant-beta", "Beta Club 1"),
    ]

    players = [
        ("player-alpha-1", "club-alpha-1", "Alpha Player 1"),
        ("player-alpha-2", "club-alpha-2", "Alpha Player 2"),
        ("player-beta-1", "club-beta-1", "Beta Player 1"),
    ]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                TRUNCATE TABLE
                    offline_sync_records,
                    roster_transfer_requests,
                    roster_audit_entries,
                    roster_scenarios,
                    match_events,
                    match_streams,
                    leagues_registry,
                    store_orders,
                    inventory,
                    variants,
                    discounts,
                    products,
                    demo_users,
                    players,
                    clubs,
                    leagues,
                    sports,
                    tenants
                RESTART IDENTITY CASCADE
            """)

            cur.executemany("INSERT INTO tenants (tenant_id, name) VALUES (%s, %s)", tenants)

            cur.executemany(
                "INSERT INTO sports (sport_id, name, rules) VALUES (%s, %s, %s)",
                [(sid, name, Jsonb(cfg)) for sid, name, cfg in BASELINE_SPORTS]
            )

            cur.executemany(
                "INSERT INTO leagues (league_id, tenant_id, sport_id, name, season) VALUES (%s, %s, %s, %s, %s)",
                leagues
            )


            cur.executemany(
                "INSERT INTO clubs (club_id, tenant_id, name) VALUES (%s, %s, %s)",
                clubs
            )

            cur.executemany(
                "INSERT INTO players (player_id, club_id, name) VALUES (%s, %s, %s)",
                players
            )

            cur.execute(
                "INSERT INTO products (product_id, tenant_id, name, category) VALUES (%s, %s, %s, %s)",
                ("prod-jersey-001", "tenant-alpha", "Alpha Sports Jersey", "apparel")
            )

            variants = [
                ("var-jersey-001-M", "prod-jersey-001", "M", "Blue", 450000, "PKR"),
                ("var-jersey-001-L", "prod-jersey-001", "L", "Blue", 450000, "PKR"),
            ]

            cur.executemany(
                "INSERT INTO variants (variant_id, product_id, size, color, price_minor, currency) VALUES (%s, %s, %s, %s, %s, %s)",
                variants
            )

            cur.executemany(
                "INSERT INTO inventory (variant_id, stock, reserved) VALUES (%s, %s, 0)",
                list(stock.items())
            )

            cur.execute("INSERT INTO discounts (code, percentage, percent_off) VALUES (%s, %s, %s)", ("WELCOME10", 10, 10))


            users = [
                ("user-super-admin", "super_admin", None, None, None),
                ("user-organizer-alpha", "league_organizer", "tenant-alpha", None, "league-alpha-1"),
                ("user-manager-alpha", "club_manager", "tenant-alpha", "club-alpha-1", None),
                ("user-player-alpha", "player", "tenant-alpha", "club-alpha-1", None),
                ("user-viewer-alpha", "viewer", "tenant-alpha", None, None),
            ]

            cur.executemany(
                "INSERT INTO demo_users (user_id, role, tenant_id, club_id, league_id) VALUES (%s, %s, %s, %s, %s)",
                users
            )
            conn.commit()

    return {
        "status": "reset_complete",
        "seed": seed,
        "sports": [item[0] for item in BASELINE_SPORTS],
        "tenants": [item[0] for item in tenants],
        "stock": stock,
    }

class ResetRequest(BaseModel):
    seed: int = 42
    stock: dict[str, int] = Field(
        default_factory=lambda: DEFAULT_STOCK.copy()
    )

@app.on_event("startup")
def startup():
    create_tables()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tenants")
            t_count = cur.fetchone()[0]
    if t_count < 2:
        seed_baseline()

@app.get("/health")
def health():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM tenants")
                if cur.fetchone()[0] < 2:
                    raise HTTPException(status_code=503, detail="Baseline missing")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

@app.post("/audit/v1/reset")
def reset(request: ResetRequest | None = None):
    if request is None:
        request = ResetRequest()
    return seed_baseline(stock_overrides=request.stock, seed=request.seed)

@app.get("/api/v1/clubs/{club_id}")
def get_club(club_id: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT club_id, tenant_id, name FROM clubs WHERE club_id = %s", (club_id,))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Club not found")
    return {"club_id": row[0], "tenant_id": row[1], "name": row[2]}

@app.get("/api/v1/store/products")
def list_products():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.product_id, p.name, p.category, v.variant_id, v.size, v.color, v.price_minor, v.currency, i.stock
                FROM products AS p
                JOIN variants AS v ON v.product_id = p.product_id
                JOIN inventory AS i ON i.variant_id = v.variant_id
                ORDER BY p.product_id, v.variant_id
            """)
            rows = cur.fetchall()
    return {
        "products": [
            {
                "product_id": r[0],
                "name": r[1],
                "category": r[2],
                "variant_id": r[3],
                "size": r[4],
                "color": r[5],
                "price_minor": r[6],
                "currency": r[7],
                "stock": r[8],
            }
            for r in rows
        ]
    }
