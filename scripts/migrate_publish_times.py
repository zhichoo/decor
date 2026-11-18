#!/usr/bin/env python3
"""Recompute the sort timestamp of publish times stored without an offset.

They were collected on a machine in China Standard Time, so they are Beijing time;
earlier code read them as UTC, which put them 8 hours late in the ordering. The
displayed text (videos.published_at) is not changed. Safe to run repeatedly.
"""
import sys

import psycopg2

from init_db import database_url

NAIVE_TIME = r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?$"


def migrate(dsn=None):
    with psycopg2.connect(dsn or database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.videos')")
            if cur.fetchone()[0] is None:
                return 0
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute(
                """
                UPDATE public.videos
                SET published_at_ts = (btrim(published_at) || '+08')::timestamptz
                WHERE btrim(published_at) ~ %s
                  AND published_at_ts IS DISTINCT FROM (btrim(published_at) || '+08')::timestamptz
                """,
                (NAIVE_TIME,),
            )
            return cur.rowcount


if __name__ == "__main__":
    try:
        changed = migrate()
    except (psycopg2.Error, RuntimeError, ValueError, OSError):
        print("Publish time migration failed; videos unchanged.", file=sys.stderr)
        raise SystemExit(1)
    print(f"Publish time order ready ({changed} videos re-dated as Beijing time).")
