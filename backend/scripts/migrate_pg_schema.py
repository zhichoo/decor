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


def add_transcript_meta(cur):
    if not column_exists(cur, "videos", "has_transcript"):
        execute(cur, "ALTER TABLE videos ADD COLUMN has_transcript boolean")
    if not column_exists(cur, "videos", "transcript_length"):
        execute(cur, "ALTER TABLE videos ADD COLUMN transcript_length integer")
    execute(
        cur,
        """
        UPDATE videos
        SET
          transcript_length = length(btrim(COALESCE(transcript_text, ''))),
          has_transcript = length(btrim(COALESCE(transcript_text, ''))) > 0
        WHERE transcript_length IS NULL OR has_transcript IS NULL
        """,
    )
    execute(cur, "ALTER TABLE videos ALTER COLUMN has_transcript SET DEFAULT false")
    execute(cur, "ALTER TABLE videos ALTER COLUMN transcript_length SET DEFAULT 0")


def add_soft_delete_columns(cur):
    for table in ("videos", "claims"):
        if not column_exists(cur, table, "deleted_at"):
            execute(cur, f"ALTER TABLE {table} ADD COLUMN deleted_at integer")
        if not column_exists(cur, table, "deleted_by"):
            execute(cur, f"ALTER TABLE {table} ADD COLUMN deleted_by text")
        if not column_exists(cur, table, "delete_reason"):
            execute(cur, f"ALTER TABLE {table} ADD COLUMN delete_reason text")


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
            add_transcript_meta(cur)
            execute(cur, "ALTER TABLE videos ADD COLUMN IF NOT EXISTS transcript_job jsonb")
            execute(cur, "ALTER TABLE videos ADD COLUMN IF NOT EXISTS ad_review jsonb")
            execute(cur, "ALTER TABLE videos ADD COLUMN IF NOT EXISTS ad_review_override jsonb")
            execute(cur, "ALTER TABLE claims ADD COLUMN IF NOT EXISTS author_stance text")
            execute(cur, "ALTER TABLE claims ADD COLUMN IF NOT EXISTS content_type text")
            execute(cur, "ALTER TABLE claims ADD COLUMN IF NOT EXISTS source_quotes jsonb")
            add_soft_delete_columns(cur)

            execute(cur, "CREATE EXTENSION IF NOT EXISTS pg_trgm")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_source_id ON videos(source_id)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_published_at_ts ON videos(published_at_ts DESC)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_page_order ON videos(published_at_ts DESC, created_at DESC, id DESC)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_progress_order ON videos(status, has_transcript, published_at_ts DESC, created_at DESC, id DESC)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_video_id ON claims(video_id)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_process_stage ON claims(process_stage)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_page_order ON claims(created_at DESC, id DESC)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_space_tags_gin ON claims USING gin(space_tags)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_topic_tags_gin ON claims USING gin(topic_tags)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_extraction_runs_video_id ON extraction_runs(video_id)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_active_page_order ON videos(deleted_at, published_at_ts DESC, created_at DESC, id DESC)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_active_progress_order ON videos(deleted_at, status, has_transcript, published_at_ts DESC, created_at DESC, id DESC)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_active_video_id ON claims(deleted_at, video_id)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_active_stage_order ON claims(deleted_at, process_stage, created_at DESC, id DESC)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_search_trgm ON videos USING gin ((COALESCE(title, '') || ' ' || COALESCE(creator, '') || ' ' || COALESCE(platform, '')) gin_trgm_ops)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_search_trgm ON claims USING gin ((COALESCE(object_name, '') || ' ' || COALESCE(original_conclusion, '') || ' ' || COALESCE(conditions, '') || ' ' || COALESCE(original_reasons::text, '')) gin_trgm_ops)")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_active_page_order_partial ON videos(published_at_ts DESC, created_at DESC, id DESC) WHERE deleted_at IS NULL")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_active_progress_order_partial ON videos(status, has_transcript, published_at_ts DESC, created_at DESC, id DESC) WHERE deleted_at IS NULL")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_active_video_id_partial ON claims(video_id) WHERE deleted_at IS NULL")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_active_stage_order_partial ON claims(process_stage, created_at DESC, id DESC) WHERE deleted_at IS NULL")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_videos_active_search_trgm ON videos USING gin ((COALESCE(title, '') || ' ' || COALESCE(creator, '') || ' ' || COALESCE(platform, '')) gin_trgm_ops) WHERE deleted_at IS NULL")
            execute(cur, "CREATE INDEX IF NOT EXISTS idx_claims_active_search_trgm ON claims USING gin ((COALESCE(object_name, '') || ' ' || COALESCE(original_conclusion, '') || ' ' || COALESCE(conditions, '') || ' ' || COALESCE(original_reasons::text, '')) gin_trgm_ops) WHERE deleted_at IS NULL")
            execute(cur, "ANALYZE videos")
            execute(cur, "ANALYZE claims")

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
