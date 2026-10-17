import os
from contextlib import contextmanager
import psycopg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://nascon:nascon_dev_password@localhost:5432/nascon",
)

@contextmanager
def get_db():
    """Connect to PostgreSQL and close the connection safely."""
    conn = psycopg.connect(DATABASE_URL)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
