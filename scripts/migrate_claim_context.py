#!/usr/bin/env python3
"""Add nullable source-attribution fields without rewriting legacy claims."""
import sys

import psycopg2

from init_db import database_url


def migrate(dsn=None):
    with psycopg2.connect(dsn or database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.claims')")
            if cur.fetchone()[0] is None:
                return
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("ALTER TABLE public.claims ADD COLUMN IF NOT EXISTS author_stance text")
            cur.execute("ALTER TABLE public.claims ADD COLUMN IF NOT EXISTS content_type text")
            cur.execute("ALTER TABLE public.claims ADD COLUMN IF NOT EXISTS source_quotes jsonb")


if __name__ == "__main__":
    try:
        migrate()
    except (psycopg2.Error, RuntimeError, ValueError, OSError):
        print("Claim context migration failed; no claim values were rewritten.", file=sys.stderr)
        raise SystemExit(1)
    print("Claim source fields ready (legacy claims preserved).")
