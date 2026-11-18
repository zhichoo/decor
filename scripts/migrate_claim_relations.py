#!/usr/bin/env python3
"""Add relation navigation tables without touching existing cards."""
from pathlib import Path
import sys
import psycopg2
from init_db import database_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import claim_relations


def migrate(dsn=None):
    with psycopg2.connect(dsn or database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.claims')")
            if cur.fetchone()[0] is None:
                return
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL search_path = public")
            claim_relations.migrate_schema(cur)


if __name__ == "__main__":
    try:
        migrate()
    except (psycopg2.Error, RuntimeError, ValueError, OSError):
        print("Claim relation migration failed; existing cards preserved.", file=sys.stderr)
        raise SystemExit(1)
    print("Claim relation tables ready (existing cards preserved).")
