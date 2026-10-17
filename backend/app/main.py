
import os
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# ============================================================
# CONFIGURATION
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://nascon:nascon_dev_password@localhost:5432/nascon",
)

app = FastAPI(
    title="NaSCon 26 Backend",
    version="1.0.0",
)


# ============================================================
# DATABASE CONNECTION
# ============================================================

@contextmanager
def get_db():
    """Connect to PostgreSQL and close the connection safely."""
    conn = psycopg.connect(DATABASE_URL)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# ============================================================
# DATABASE TABLES AND MIGRATIONS
# ============================================================

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
            price_minor INTEGER NOT NULL DEFAULT 0
                CHECK (price_minor >= 0),
            currency TEXT NOT NULL DEFAULT 'PKR'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS inventory (
            variant_id TEXT PRIMARY KEY REFERENCES variants(variant_id),
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS discounts (
            code TEXT PRIMARY KEY,
            percent_off INTEGER NOT NULL
                CHECK (percent_off BETWEEN 0 AND 100)
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
        CREATE TABLE IF NOT EXISTS roster_squads (
            squad_id TEXT PRIMARY KEY,
            league_id TEXT NOT NULL REFERENCES leagues(league_id),
            club_id TEXT NOT NULL REFERENCES clubs(club_id),
            max_size INTEGER NOT NULL DEFAULT 25
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS roster_registrations (
            registration_id BIGSERIAL PRIMARY KEY,
            player_id TEXT NOT NULL REFERENCES players(player_id),
            squad_id TEXT NOT NULL REFERENCES roster_squads(squad_id),
            role TEXT NOT NULL DEFAULT 'Substitute',
            status TEXT NOT NULL DEFAULT 'active',
            start_date DATE,
            end_date DATE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS roster_requests (
            request_id BIGSERIAL PRIMARY KEY,
            player_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS roster_audit (
            audit_id BIGSERIAL PRIMARY KEY,
            player_id TEXT NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS store_orders (
            order_id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL REFERENCES variants(variant_id),
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            total_minor INTEGER NOT NULL CHECK (total_minor >= 0),
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]

    with get_db() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)

            # Migrate databases created by the older starter code.
            cur.execute("""
                ALTER TABLE sports
                ADD COLUMN IF NOT EXISTS rules JSONB
                NOT NULL DEFAULT '{}'::jsonb
            """)

            cur.execute("""
                ALTER TABLE leagues
                ADD COLUMN IF NOT EXISTS name TEXT
                NOT NULL DEFAULT 'Demo League'
            """)

            cur.execute("""
                ALTER TABLE leagues
                ADD COLUMN IF NOT EXISTS season TEXT
                NOT NULL DEFAULT '2026'
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS category TEXT
                NOT NULL DEFAULT 'apparel'
            """)

            cur.execute("""
                ALTER TABLE variants
                ADD COLUMN IF NOT EXISTS size TEXT
                NOT NULL DEFAULT 'One Size'
            """)

            cur.execute("""
                ALTER TABLE variants
                ADD COLUMN IF NOT EXISTS color TEXT
                NOT NULL DEFAULT 'Default'
            """)

            cur.execute("""
                ALTER TABLE variants
                ADD COLUMN IF NOT EXISTS currency TEXT
                NOT NULL DEFAULT 'PKR'
            """)


# ============================================================
# BASELINE DATA
# ============================================================

DEFAULT_STOCK = {
    "var-jersey-001-M": 1,
    "var-jersey-001-L": 5,
}


def seed_baseline(
    stock_overrides: dict[str, int] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    stock = DEFAULT_STOCK.copy()

    if stock_overrides is not None:
        unknown_ids = set(stock_overrides) - set(DEFAULT_STOCK)
        if unknown_ids:
            raise ValueError(
                f"Unknown variant IDs: {', '.join(sorted(unknown_ids))}"
            )
        stock.update(stock_overrides)

    for variant_id, quantity in stock.items():
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 0
        ):
            raise ValueError(
                f"Stock for {variant_id} must be a non-negative integer"
            )

    tenants = [
        ("tenant-alpha", "Alpha Sports"),
        ("tenant-beta", "Beta Athletics"),
    ]

    sports = [
        ("football", {"model": "event"}),
        ("basketball", {"model": "event"}),
        ("cricket", {"model": "innings"}),
        ("esports", {"model": "event"}),
    ]

    leagues = [
        ("league-alpha-1", "tenant-alpha", "Alpha League 1", "2026"),
        ("league-alpha-2", "tenant-alpha", "Alpha League 2", "2026"),
        ("league-beta-1", "tenant-beta", "Beta League 1", "2026"),
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
            # Clear old demo data in dependency order.
            cur.execute("""
                TRUNCATE TABLE
                    store_orders,
                    roster_audit,
                    roster_requests,
                    roster_registrations,
                    roster_squads,
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

            cur.executemany(
                "INSERT INTO tenants (tenant_id, name) VALUES (%s, %s)",
                tenants,
            )

            cur.executemany(
                "INSERT INTO sports (sport_id, rules) VALUES (%s, %s)",
                [
                    (sport_id, Jsonb(rules))
                    for sport_id, rules in sports
                ],
            )

            cur.executemany(
                """
                INSERT INTO leagues
                    (league_id, tenant_id, name, season)
                VALUES (%s, %s, %s, %s)
                """,
                leagues,
            )

            cur.executemany(
                """
                INSERT INTO clubs (club_id, tenant_id, name)
                VALUES (%s, %s, %s)
                """,
                clubs,
            )

            cur.executemany(
                """
                INSERT INTO players (player_id, club_id, name)
                VALUES (%s, %s, %s)
                """,
                players,
            )

            cur.execute(
                """
                INSERT INTO products
                    (product_id, tenant_id, name, category)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    "prod-jersey-001",
                    "tenant-alpha",
                    "Alpha Sports Jersey",
                    "apparel",
                ),
            )

            variants = [
                (
                    "var-jersey-001-M",
                    "prod-jersey-001",
                    "M",
                    "Blue",
                    450000,
                    "PKR",
                ),
                (
                    "var-jersey-001-L",
                    "prod-jersey-001",
                    "L",
                    "Blue",
                    450000,
                    "PKR",
                ),
            ]

            cur.executemany(
                """
                INSERT INTO variants
                    (variant_id, product_id, size, color,
                     price_minor, currency)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                variants,
            )

            cur.executemany(
                """
                INSERT INTO inventory (variant_id, stock)
                VALUES (%s, %s)
                """,
                list(stock.items()),
            )

            cur.execute(
                """
                INSERT INTO discounts (code, percent_off)
                VALUES (%s, %s)
                """,
                ("WELCOME10", 10),
            )

            users = [
                (
                    "user-super-admin",
                    "super_admin",
                    None,
                    None,
                    None,
                ),
                (
                    "user-organizer-alpha",
                    "league_organizer",
                    "tenant-alpha",
                    None,
                    "league-alpha-1",
                ),
                (
                    "user-manager-alpha",
                    "club_manager",
                    "tenant-alpha",
                    "club-alpha-1",
                    None,
                ),
                (
                    "user-player-alpha",
                    "player",
                    "tenant-alpha",
                    "club-alpha-1",
                    None,
                ),
                (
                    "user-viewer-alpha",
                    "viewer",
                    "tenant-alpha",
                    None,
                    None,
                ),
            ]

            cur.executemany(
                """
                INSERT INTO demo_users
                    (user_id, role, tenant_id, club_id, league_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                users,
            )

    return {
        "status": "reset_complete",
        "seed": seed,
        "sports": [item[0] for item in sports],
        "tenants": [item[0] for item in tenants],
        "stock": stock,
    }


# ============================================================
# REQUEST MODEL
# ============================================================

class ResetRequest(BaseModel):
    seed: int = 42
    stock: dict[str, int] = Field(
        default_factory=lambda: DEFAULT_STOCK.copy()
    )


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup():
    create_tables()

    # Seed if the baseline is missing, not just when tenants are absent.
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tenants")
            tenant_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM sports")
            sport_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM products")
            product_count = cur.fetchone()[0]

    if tenant_count < 2 or sport_count < 4 or product_count < 1:
        seed_baseline()


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM tenants")
                tenant_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM sports")
                sport_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM products")
                product_count = cur.fetchone()[0]

        if (
            tenant_count < 2
            or sport_count < 4
            or product_count < 1
        ):
            raise HTTPException(
                status_code=503,
                detail="Baseline data is missing",
            )

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable",
        ) from exc


# ============================================================
# RESET BASELINE
# ============================================================

@app.post("/audit/v1/reset")
def reset(request: ResetRequest | None = None):
    if request is None:
        request = ResetRequest()

    try:
        return seed_baseline(
            stock_overrides=request.stock,
            seed=request.seed,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Reset failed",
        ) from exc


# ============================================================
# CLUB PROFILE
# ============================================================

@app.get("/api/v1/clubs/{club_id}")
def get_club(club_id: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT club_id, tenant_id, name
                FROM clubs
                WHERE club_id = %s
                """,
                (club_id,),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Club not found",
        )

    return {
        "club_id": row[0],
        "tenant_id": row[1],
        "name": row[2],
    }


# ============================================================
# PRODUCT CATALOGUE
# ============================================================

@app.get("/api/v1/store/products")
def list_products():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.product_id,
                    p.name,
                    p.category,
                    v.variant_id,
                    v.size,
                    v.color,
                    v.price_minor,
                    v.currency,
                    i.stock
                FROM products AS p
                JOIN variants AS v
                    ON v.product_id = p.product_id
                JOIN inventory AS i
                    ON i.variant_id = v.variant_id
                ORDER BY p.product_id, v.variant_id
                """
            )
            rows = cur.fetchall()

    return {
        "products": [
            {
                "product_id": row[0],
                "name": row[1],
                "category": row[2],
                "variant_id": row[3],
                "size": row[4],
                "color": row[5],
                "price_minor": row[6],
                "currency": row[7],
                "stock": row[8],
            }
            for row in rows
        ]
    }
