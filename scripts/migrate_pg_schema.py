#!/usr/bin/env python3
import os
import sys
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


JSONB_COLUMNS = {
    "claims": ["space_tags", "topic_tags", "original_reasons", "alternatives"],
    "extraction_runs": ["raw_response_json"],
}


def execute(cur, sql):
    cur.execute(sql)


def constraint_exists(cur, table, name):
    cur.execute(
        """
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public' AND table_name = %s AND constraint_name = %s
        """,
        (table, name),
    )
    return cur.fetchone() is not None


def add_constraint_if_missing(cur, table, name, expression):
    if constraint_exists(cur, table, name):
        return
    execute(cur, f"ALTER TABLE {table} ADD CONSTRAINT {name} {expression}")


def jsonb_expr(column, fallback):
    return f"""
    CASE
      WHEN {column} IS NULL OR btrim({column}) = '' THEN {fallback}::jsonb
      ELSE {column}::jsonb
    END
    """


def migrate_jsonb_column(cur, table, column, fallback):
    if column_type(cur, table, column) == "jsonb":
        return
    tmp = f"{column}_jsonb"
    execute(cur, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {tmp} jsonb")
    execute(cur, f"UPDATE {table} SET {tmp} = {jsonb_expr(column, fallback)} WHERE {tmp} IS NULL")
    execute(cur, f"ALTER TABLE {table} DROP COLUMN {column}")
    execute(cur, f"ALTER TABLE {table} RENAME COLUMN {tmp} TO {column}")


def column_exists(cur, table, column):
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def column_type(cur, table, column):
    cur.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


def add_published_at_ts(cur):
    if not column_exists(cur, "videos", "published_at_ts"):
        execute(cur, "ALTER TABLE videos ADD COLUMN published_at_ts timestamptz")
    execute(
        cur,
        """
        UPDATE videos
        SET published_at_ts = CASE
          WHEN published_at IS NULL OR btrim(published_at) = '' THEN NULL
          WHEN published_at ~ '^\\d{4}-\\d{2}-\\d{2}$' THEN (published_at || ' 00:00:00+00')::timestamptz
          WHEN published_at ~ '^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}$' THEN (published_at || ':00+00')::timestamptz
          WHEN published_at ~ '^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$' THEN (published_at || '+00')::timestamptz
          ELSE NULL
        END
        WHERE published_at_ts IS NULL
        """,
    )


def main():
    dsn = os.environ.get("DATABASE_URL", server.PG_DSN)
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            migrate_jsonb_column(cur, "claims", "space_tags", "'[]'")
            migrate_jsonb_column(cur, "claims", "topic_tags", "'[]'")
            migrate_jsonb_column(cur, "claims", "original_reasons", "'[]'")
            migrate_jsonb_column(cur, "claims", "alternatives", "'[]'")
            migrate_jsonb_column(cur, "extraction_runs", "raw_response_json", "'{}'")
            add_published_at_ts(cur)

            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_source_id ON videos(source_id)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_published_at_ts ON videos(published_at_ts DESC)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_video_id ON claims(video_id)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_process_stage ON claims(process_stage)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_space_tags_gin ON claims USING gin(space_tags)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_topic_tags_gin ON claims USING gin(topic_tags)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_extraction_runs_video_id ON extraction_runs(video_id)")

            add_constraint_if_missing(
                cur,
                "claims",
                "claims_stance_valid",
                "CHECK (stance IN ('明确推荐', '明确不推荐', '有条件', '价格建议', '未明确'))",
            )
            add_constraint_if_missing(
                cur,
                "claims",
                "claims_process_stage_valid",
                """
                CHECK (process_stage IN (
                  '准备阶段', '收房验房', '设计规划', '拆改阶段', '水电阶段', '防水阶段',
                  '瓦工阶段', '木工阶段', '油工阶段', '主材安装', '定制柜安装', '厨卫安装',
                  '灯具开关五金', '家电家具软装', '开荒保洁', '通风除醛', '入住验收', '待人工分类'
                ))
                """,
            )
            add_constraint_if_missing(
                cur,
                "videos",
                "videos_status_valid",
                """
                CHECK (status IS NULL OR status IN (
                  'created', 'transcript_pending', 'transcript_saved', 'claims_extracted',
                  'claims_filtered', 'transcript_failed'
                ))
                """,
            )
            add_constraint_if_missing(
                cur,
                "sources",
                "sources_status_valid",
                "CHECK (status IS NULL OR status IN ('active', 'inactive'))",
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("PostgreSQL schema migration completed.")


if __name__ == "__main__":
    main()
