#!/usr/bin/env python3
"""Add nullable task ledger and advertising review columns; existing business values are never rewritten."""
import sys
import psycopg2
from init_db import database_url


def migrate(dsn=None):
    with psycopg2.connect(dsn or database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.videos')")
            if cur.fetchone()[0] is None:
                return  # Empty databases are initialized from db/schema.sql.
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("ALTER TABLE public.videos ADD COLUMN IF NOT EXISTS transcript_job jsonb")
            cur.execute("ALTER TABLE public.videos ADD COLUMN IF NOT EXISTS ad_review jsonb")
            cur.execute("ALTER TABLE public.videos ADD COLUMN IF NOT EXISTS ad_review_override jsonb")


if __name__ == '__main__':
    try:
        migrate()
    except (psycopg2.Error, RuntimeError, ValueError, OSError):
        print('Transcript task migration failed; check local database configuration.', file=sys.stderr)
        raise SystemExit(1)
    print('Transcript ledger and advertising review ready (existing data preserved).')
