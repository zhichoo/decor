#!/usr/bin/env python3
"""Initialize a fresh PostgreSQL database, or validate and leave it untouched."""
import json
import os
import re
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "db" / "schema.sql"
TABLES = ("sources", "videos", "extraction_runs", "claims")
# Shared with the optional seed command. Serializes cooperating initializers/seeds.
LOCK_ID = 0x4445434F52


def database_url():
    """Environment wins; never fall back to a hard-coded server or credentials."""
    if "DATABASE_URL" in os.environ:
        dsn = os.environ["DATABASE_URL"].strip()
    else:
        path = ROOT / "backend" / "config.local.json"
        config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        dsn = str(config.get("DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("Set DATABASE_URL or backend/config.local.json DATABASE_URL")
    return dsn


def normalized_sql(value):
    return " ".join(value.strip().rstrip(";").split())


def expected_structure(schema_sql):
    """Read the deliberately simple, pg_dump-shaped baseline (no second schema)."""
    columns = {}
    constraints = {}
    for table, body in re.findall(
        r"CREATE TABLE public\.(\w+) \(\n(.*?)\n\);", schema_sql, re.S
    ):
        for line in body.splitlines():
            definition = line.strip().rstrip(",")
            if definition.startswith("CONSTRAINT "):
                name, expression = definition[len("CONSTRAINT "):].split(" ", 1)
                constraints[table, name] = normalized_sql(expression)
                continue
            match = re.fullmatch(
                r"(\w+) (timestamp with time zone|text|bigint|integer|boolean|jsonb)"
                r"(?: DEFAULT (.*?))?( NOT NULL)?", definition
            )
            if not match:
                raise RuntimeError("Unrecognized baseline column definition")
            name, datatype, default, not_null = match.groups()
            columns[table, name] = (datatype, bool(not_null), default)
    for table, name, definition in re.findall(
        r"ALTER TABLE ONLY public\.(\w+)\s+ADD CONSTRAINT (\w+) ([^;]+);",
        schema_sql,
    ):
        constraints[table, name] = normalized_sql(definition)
    indexes = {
        name: normalized_sql(definition)
        for definition, name in re.findall(
            r"(CREATE INDEX (\w+) ON public\.\w+ [^;]+);", schema_sql
        )
    }
    if {table for table, _ in columns} != set(TABLES) or not indexes or not constraints:
        raise RuntimeError("Incomplete baseline definition")
    return columns, constraints, indexes


def validate_schema(cur, schema_sql):
    """Require baseline columns, defaults, constraints and valid index definitions.

    Additional columns/indexes are allowed. This checks catalogs only: it never
    migrates, resets, seeds, or scans application rows in an existing database.
    """
    expected_columns, expected_constraints, expected_indexes = expected_structure(schema_sql)
    cur.execute("SELECT extnamespace::regnamespace::text FROM pg_extension WHERE extname = 'pg_trgm'")
    if cur.fetchone() != ("public",):
        raise RuntimeError("Existing schema requires pg_trgm in public; no changes made")
    cur.execute(
        """
        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
               a.attnotnull, pg_get_expr(d.adbin, d.adrelid)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid
        LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = 'public' AND c.relname = ANY(%s)
          AND a.attnum > 0 AND NOT a.attisdropped
        """, (list(TABLES),)
    )
    columns = {(table, name): (datatype, not_null, default)
               for table, name, datatype, not_null, default in cur.fetchall()}
    cur.execute(
        """
        SELECT t.relname, c.conname, pg_get_constraintdef(c.oid), c.convalidated
        FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public' AND t.relname = ANY(%s)
        """, (list(TABLES),)
    )
    constraints = {(table, name): (normalized_sql(definition), valid)
                   for table, name, definition, valid in cur.fetchall()}
    cur.execute(
        """
        SELECT i.relname, pg_get_indexdef(x.indexrelid), x.indisvalid, x.indisready
        FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_class t ON t.oid = x.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public' AND t.relname = ANY(%s)
        """, (list(TABLES),)
    )
    indexes = {name: (normalized_sql(definition), valid and ready)
               for name, definition, valid, ready in cur.fetchall()}
    problems = []
    for key, expected in expected_columns.items():
        if columns.get(key) != expected:
            problems.append("column " + ".".join(key))
    for key, expected in expected_constraints.items():
        if constraints.get(key) != (expected, True):
            problems.append("constraint " + ".".join(key))
    for name, expected in expected_indexes.items():
        if indexes.get(name) != (expected, True):
            problems.append("index " + name)
    if problems:
        raise RuntimeError("Existing schema differs from baseline: " + ", ".join(problems)
                           + "; no changes made")


def init_db(dsn=None):
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = psycopg2.connect(dsn or database_url())
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL search_path = ''")
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
                cur.execute(
                    """SELECT c.relname, c.relkind FROM pg_class c
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = 'public' AND c.relname = ANY(%s)""",
                    (list(TABLES),),
                )
                existing = dict(cur.fetchall())
                if existing:
                    if set(existing) != set(TABLES) or any(kind != "r" for kind in existing.values()):
                        raise RuntimeError("Partial/conflicting business schema; no changes made. "
                                           "Found: " + ", ".join(sorted(existing)))
                    validate_schema(cur, schema_sql)
                    return False
                # An empty business namespace is insufficient: do not initialize
                # an unrelated application database by accident.
                cur.execute(
                    """SELECT n.nspname, c.relname FROM pg_class c
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                         AND n.nspname <> 'information_schema'
                         AND n.nspname !~ '^pg_'
                         AND NOT EXISTS (
                           SELECT 1 FROM pg_depend d
                           WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                             AND d.deptype = 'e')"""
                )
                if cur.fetchone():
                    raise RuntimeError("Database is not empty; no changes made")
                cur.execute(schema_sql)
                validate_schema(cur, schema_sql)
        return True
    finally:
        conn.close()


def main():
    try:
        created = init_db()
    except (RuntimeError, ValueError, OSError, psycopg2.Error) as exc:
        # Driver errors can include connection details. Never echo a DSN.
        message = str(exc) if not isinstance(exc, psycopg2.Error) else "PostgreSQL initialization failed (SQLSTATE: " + (exc.pgcode or "connection error") + ")"
        print(message, file=sys.stderr)
        return 1
    print("Initialized empty business schema" if created else "Validated existing business schema; skipped initialization")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
