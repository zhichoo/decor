"""Source/facet regressions against .env PostgreSQL, in a rolled-back private schema.

Run with: .venv/bin/python -m unittest discover -s tests -p test_video_facets.py -v
"""
import importlib.util
import os
from contextlib import nullcontext
from pathlib import Path
import shlex
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import make_dsn

ROOT = Path(__file__).resolve().parents[1]


class TestConnection:
    """Execute application queries without enabling autocommit on the test transaction."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, statement, params=None):
        cursor = self.raw.cursor()
        cursor.execute(statement, params)
        return cursor

    def transaction(self):
        # The entire test already runs inside a disposable, rolled-back transaction.
        return nullcontext(self)


class VideoFacetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Prefer this project's local DSN over environment values left by other test modules.
        values = {}
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                key, separator, value = line.removeprefix("export ").partition("=")
                if separator and not key.strip().startswith("#"):
                    tokens = shlex.split(value, comments=True)
                    values[key.strip()] = tokens[0] if tokens else ""
        cls.dsn = values.get("DATABASE_URL")
        if not cls.dsn and values.get("POSTGRES_PASSWORD"):
            cls.dsn = make_dsn(
                host="127.0.0.1", port=values.get("DECOR_DB_PORT", "15439"),
                dbname="decor", user="decor", password=values["POSTGRES_PASSWORD"],
                sslmode="disable", connect_timeout=5,
            )
        if not cls.dsn:
            raise unittest.SkipTest("Local .env database configuration is required")
        # Import with a temporary environment: do not change other tests' configuration.
        with patch.dict(os.environ, {"DATABASE_URL": cls.dsn}):
            spec = importlib.util.spec_from_file_location(
                "decor_facets_test_server", ROOT / "backend/server.py"
            )
            cls.server = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.server)

    def setUp(self):
        try:
            raw = psycopg2.connect(self.dsn, cursor_factory=RealDictCursor, connect_timeout=5)
        except psycopg2.Error:
            # Never include the DSN or a connection exception that may contain credentials.
            raise RuntimeError("Local PostgreSQL test connection failed") from None
        self.addCleanup(raw.close)
        self.addCleanup(raw.rollback)
        self.conn = TestConnection(raw)
        schema_name = "test_video_facets_" + uuid.uuid4().hex
        identifier = sql.Identifier(schema_name)
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(identifier))
        # No public fallback: any accidental reference to an uncreated table fails safely.
        self.conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(identifier))
        # Reuse actual table definitions/constraints; indexes and extensions are unnecessary here.
        baseline = "\n".join(
            line for line in (ROOT / "db/schema.sql").read_text().splitlines()
            if not line.startswith(("CREATE EXTENSION ", "CREATE INDEX "))
        )
        self.conn.execute(baseline.replace("public.", identifier.as_string(raw) + "."))
        self.seed()

    def seed(self):
        for index, (source_id, priority, status) in enumerate([
            ("alice-source", "P0", "active"),
            ("bob-source", "P1", "active"),
            ("empty-source", "P1", "inactive"),
            ("deleted-source", "P2", "active"),
        ]):
            self.conn.execute(
                """INSERT INTO sources (id, platform, name, priority, status, created_at)
                   VALUES (%s, 'douyin', %s, %s, %s, %s)""",
                (source_id, source_id, priority, status, index),
            )
        for index in range(31):
            self.add_video(
                f"alice-{index:02}", "douyin", "Alice", "alice-source", created_at=100 + index,
                status="transcript_pending" if index < 2 else "created",
            )
        self.add_video("bob", "douyin", "Bob", "bob-source", status="transcript_pending")
        self.add_video("unbound-carol", "bilibili", "Carol")
        self.add_video("unbound-alice", "bilibili", "Alice")
        self.add_video("blank-creator", "douyin", "")
        self.add_video("blank-platform", "", "Unknown platform")
        self.add_video("whitespace", " ", "\t ")
        self.add_video("deleted-alice", "douyin", "Alice", "alice-source", deleted_at=10,
                       status="transcript_pending")
        self.add_video("deleted-only", "deleted-platform", "Deleted creator", "deleted-source",
                       deleted_at=10, status="transcript_pending")
        for index in range(3):
            self.add_claim(f"alice-card-{index}", "alice-00")
        self.add_claim("bob-card", "bob")
        self.add_claim("deleted-card", "alice-00", deleted_at=10)
        # Also exclude active cards attached to a soft-deleted video.
        self.add_claim("card-on-deleted-alice", "deleted-alice")
        self.add_claim("card-on-deleted-only", "deleted-only")

    def add_video(self, video_id, platform, creator, source_id=None, created_at=1,
                  status="created", deleted_at=None):
        self.conn.execute(
            """INSERT INTO videos (id, platform, creator, source_id, title, source_url,
                   created_at, updated_at, status, deleted_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (video_id, platform, creator, source_id, video_id,
             "https://example.invalid/" + video_id, created_at, created_at, status, deleted_at),
        )

    def add_claim(self, claim_id, video_id, deleted_at=None):
        self.conn.execute(
            """INSERT INTO claims (id, video_id, object_name, stance, process_stage,
                   original_conclusion, conditions, price_info, source_video_url, created_at, deleted_at)
               VALUES (%s, %s, '插座', '未明确', '待人工分类', '检查接线',
                   '未提及', '未提及', 'https://example.invalid/', 1, %s)""",
            (claim_id, video_id, deleted_at),
        )

    def expected_facets(self):
        # Stable ordering is by platform, then creator, matching the database query.
        return {
            "total": 37,
            "platforms": [
                {"platform": "bilibili", "video_count": 2},
                {"platform": "douyin", "video_count": 33},
            ],
            "creators": [
                {"platform": "", "creator": "Unknown platform", "video_count": 1},
                {"platform": "bilibili", "creator": "Alice", "video_count": 1},
                {"platform": "bilibili", "creator": "Carol", "video_count": 1},
                {"platform": "douyin", "creator": "Alice", "video_count": 31},
                {"platform": "douyin", "creator": "Bob", "video_count": 1},
            ],
        }

    def test_first_page_keeps_creators_beyond_thirty_videos(self):
        first = self.server.fetch_video_page(self.conn)
        self.assertEqual(first["total"], 37)
        self.assertEqual(first["limit"], 30)
        self.assertEqual(len(first["videos"]), 30)
        self.assertEqual({video["creator"] for video in first["videos"]}, {"Alice"})
        self.assertTrue(first["has_more"])
        self.assertEqual(first["facets"], self.expected_facets())
        second = self.server.fetch_video_page(self.conn, offset=30)
        self.assertEqual(len(second["videos"]), 7)
        self.assertFalse(second["has_more"])
        self.assertEqual(second["facets"], first["facets"])

    def test_all_filters_and_pagination_leave_facets_global(self):
        cases = [
            ({"creator": ["Bob"]}, 1),
            ({"creator": ["Alice"]}, 32),
            ({"platform": ["bilibili"]}, 2),
            ({"source_id": ["empty-source"]}, 0),
            ({"q": ["does-not-exist"]}, 0),
            ({"source_id": ["alice-source"], "platform": ["douyin"],
              "creator": ["Alice"], "q": ["alice-00"]}, 1),
        ]
        for query, total in cases:
            with self.subTest(query=query):
                page = self.server.fetch_video_page(self.conn, query=query, limit=1)
                self.assertEqual(page["total"], total)
                self.assertEqual(page["facets"], self.expected_facets())
                if "creator" in query:
                    self.assertTrue(all(v["creator"] == query["creator"][0] for v in page["videos"]))
        beyond_end = self.server.fetch_video_page(self.conn, limit=1, offset=1000)
        self.assertEqual(beyond_end["videos"], [])
        self.assertEqual(beyond_end["facets"], self.expected_facets())

    def test_facets_include_unbound_videos_and_exclude_blank_options_and_deleted_videos(self):
        facets = self.server.fetch_video_facets(self.conn)
        self.assertEqual(facets, self.expected_facets())
        self.assertTrue(all(item["platform"].strip() for item in facets["platforms"]))
        self.assertTrue(all(item["creator"].strip() for item in facets["creators"]))
        self.assertIs(type(facets["total"]), int)
        for key in ("platforms", "creators"):
            self.assertTrue(all(type(item["video_count"]) is int for item in facets[key]))

    def test_sources_include_zero_video_sources_and_do_not_multiply_counts_by_claims(self):
        sources = self.server.fetch_sources(self.conn)
        by_id = {source["id"]: source for source in sources}
        self.assertEqual(set(by_id), {"alice-source", "bob-source", "empty-source", "deleted-source"})
        expected = {"alice-source": (31, 3, 2), "bob-source": (1, 1, 1),
                    "empty-source": (0, 0, 0), "deleted-source": (0, 0, 0)}
        for source_id, counts in expected.items():
            with self.subTest(source_id=source_id):
                source = by_id[source_id]
                actual = tuple(source[key] for key in ("video_count", "claim_count", "pending_count"))
                self.assertEqual(actual, counts)
                self.assertTrue(all(type(count) is int for count in actual))
        self.assertEqual(by_id["empty-source"]["status"], "inactive")
        self.assertEqual(sources[0]["id"], "alice-source")

    def test_empty_active_library_has_empty_facets_and_zero_source_counts(self):
        self.conn.execute("UPDATE videos SET deleted_at = 10")
        page = self.server.fetch_video_page(self.conn)
        self.assertEqual(page["facets"], {"platforms": [], "creators": [], "total": 0})
        self.assertEqual(page["total"], 0)
        self.assertFalse(page["has_more"])
        sources = self.server.fetch_sources(self.conn)
        self.assertEqual(len(sources), 4)
        self.assertTrue(all(source[key] == 0 for source in sources
                            for key in ("video_count", "claim_count", "pending_count")))

    def get_payload(self, path):
        handler = SimpleNamespace(send_json=lambda payload: payload)
        with patch.object(self.server, "connect", side_effect=lambda: nullcontext(self.conn)), patch.dict(
            self.server.DB_STATUS, {"available": True, "message": "ok"}
        ):
            return self.server.AppHandler.handle_get(handler, urlparse(path))

    def test_collection_invalidates_cached_counts_after_saving(self):
        with patch.object(self.server, "BOOTSTRAP_CACHE", {"payload": None, "timestamp": 0}), patch.object(
            self.server, "BOOTSTRAP_CACHE_TTL_SECONDS", 3600
        ):
            before = self.get_payload("/api/bootstrap")
            self.assertEqual(before["video_facets"]["total"], 37)
            with patch.object(
                self.server, "invalidate_bootstrap_cache", wraps=self.server.invalidate_bootstrap_cache
            ) as invalidate:
                result = self.server.save_collected_videos(
                    self.conn,
                    {"source_id": "empty-source", "platform": "douyin", "creator": "New creator",
                     "profile_url": "https://example.invalid/profile/new", "limit": 2},
                    [{"id": f"new-video-{index}", "source_url": f"https://example.invalid/new-{index}"}
                     for index in range(2)],
                )
                invalidate.assert_called_once_with()
            self.assertEqual(result["stats"]["created"], 2)
            after = self.get_payload("/api/bootstrap")
            self.assertIsNot(after, before)
            self.assertEqual(after["stats"]["video_count"], 39)
            self.assertEqual(after["video_facets"]["total"], 39)
            updated_source = next(source for source in after["sources"] if source["id"] == "empty-source")
            self.assertEqual(updated_source["video_count"], 2)
            self.assertEqual(updated_source["pending_count"], 2)
            self.assertIn(
                {"platform": "douyin", "creator": "New creator", "video_count": 2},
                after["video_facets"]["creators"],
            )

    def test_collection_never_restores_or_modifies_deleted_videos(self):
        self.conn.execute(
            "UPDATE videos SET deleted_by = 'admin', delete_reason = '推广产品，无需保留' WHERE id = 'deleted-alice'"
        )
        before = dict(self.conn.execute("SELECT * FROM videos WHERE id = 'deleted-alice'").fetchone())
        result = self.server.save_collected_videos(
            self.conn,
            {"source_id": "alice-source", "platform": "douyin", "creator": "Alice",
             "profile_url": "https://example.invalid/alice", "limit": 2},
            [{"source_url": before["source_url"], "title": "Must not overwrite deletion"},
             {"source_url": "https://example.invalid/new-after-deletion", "title": "New"}],
        )
        after = dict(self.conn.execute("SELECT * FROM videos WHERE id = 'deleted-alice'").fetchone())
        self.assertEqual(before, after)
        self.assertEqual(result["stats"]["saved"], 1)
        self.assertEqual(result["stats"]["created"], 1)
        self.assertEqual(result["stats"]["skipped_deleted"], 1)
        self.assertEqual(result["videos"][0]["title"], "New")
        self.assertEqual(result["skipped_videos"], [{
            "id": before["id"], "title": before["title"], "source_url": before["source_url"],
            "reason_code": "previously_deleted", "reason": "此前已删除，本次更新跳过，不自动恢复",
            "delete_reason": "推广产品，无需保留",
        }])
        message = self.server.collection_update_message(result)
        self.assertIn("跳过已删除视频 1 条", message)
        self.assertIn("《deleted-alice》", message)
        self.assertIn("原删除原因：推广产品，无需保留", message)

    def test_single_and_all_source_updates_explain_deleted_only_skips(self):
        self.conn.execute("UPDATE sources SET status = 'inactive' WHERE id <> 'alice-source'")
        self.conn.execute("UPDATE sources SET profile_url = 'https://example.invalid/alice' WHERE id = 'alice-source'")
        before = dict(self.conn.execute("SELECT * FROM videos WHERE id = 'deleted-alice'").fetchone())
        for path in ("/api/sources/alice-source/update", "/api/sources/update-all"):
            with self.subTest(path=path):
                handler = SimpleNamespace(
                    send_json=lambda payload, status=200: payload,
                    send_error_json=lambda status, error: self.fail(f"Unexpected error: {status}: {error}"),
                )
                with patch.object(self.server, "connect", side_effect=lambda: nullcontext(self.conn)), patch.dict(
                    self.server.DB_STATUS, {"available": True, "message": "ok"}
                ), patch.object(self.server, "read_json", return_value={"limit": 5}), patch.object(
                    self.server, "require_admin", return_value=True
                ), patch.object(self.server, "collect_douyin_profile", return_value=[{
                    "source_url": before["source_url"], "title": "Do not replace original title",
                }]):
                    result = self.server.AppHandler.handle_post(handler, urlparse(path))
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["stats"]["skipped_deleted"], 1)
                self.assertEqual(result["stats"]["saved"], 0)
                self.assertEqual(result["stats"]["created"], 0)
                self.assertEqual(result["stats"]["duplicate"], 0)
                self.assertIn("跳过已删除视频 1 条", result["message"])
                self.assertIn("《deleted-alice》：此前已删除，本次更新跳过，不自动恢复", result["message"])
                self.assertNotIn("原删除原因", result["message"])
                after = dict(self.conn.execute("SELECT * FROM videos WHERE id = 'deleted-alice'").fetchone())
                self.assertEqual(before, after)
                if "sources" in result:
                    self.assertEqual(result["summary"]["failed"], 0)
                    self.assertEqual(result["sources"][0]["skipped_videos"][0]["id"], before["id"])

    def test_collection_skips_pins_without_using_up_limit(self):
        result = self.server.save_collected_videos(
            self.conn,
            {"source_id": "alice-source", "platform": "douyin", "creator": "Alice",
             "profile_url": "https://example.invalid/alice", "limit": 1},
            [{"source_url": "https://example.invalid/pinned", "is_top": 1},
             {"source_url": "https://example.invalid/pinned"},
             {"source_url": "https://example.invalid/not-pinned", "title": "Normal"}],
        )
        self.assertEqual(result["stats"]["created"], 1)
        self.assertEqual(result["videos"][0]["title"], "Normal")
        self.assertIsNone(self.conn.execute(
            "SELECT id FROM videos WHERE source_url = 'https://example.invalid/pinned'"
        ).fetchone())

    def test_explicit_pin_import_keeps_deleted_videos_excluded(self):
        deleted = dict(self.conn.execute("SELECT * FROM videos WHERE id = 'deleted-alice'").fetchone())
        result = self.server.save_collected_videos(
            self.conn,
            {"source_id": "alice-source", "platform": "douyin", "creator": "Alice",
             "profile_url": "https://example.invalid/alice", "limit": 3, "include_pinned": True},
            [{"source_url": deleted["source_url"], "is_pinned": True},
             {"source_url": "https://example.invalid/explicit-pin", "title": "Pinned", "is_pinned": True},
             {"source_url": "https://example.invalid/normal", "title": "Normal"}],
        )
        self.assertEqual([video["title"] for video in result["videos"]], ["Pinned", "Normal"])
        self.assertEqual(result["stats"]["created"], 2)
        self.assertEqual(result["stats"]["skipped_deleted"], 1)
        after = dict(self.conn.execute("SELECT * FROM videos WHERE id = 'deleted-alice'").fetchone())
        self.assertEqual(deleted, after)

    def test_pin_import_requires_explicit_boolean_opt_in(self):
        for value in (False, "true", "false", 1, None):
            with self.subTest(value=value):
                result = self.server.save_collected_videos(
                    self.conn,
                    {"source_id": "alice-source", "platform": "douyin", "creator": "Alice",
                     "profile_url": "https://example.invalid/alice", "limit": 1, "include_pinned": value},
                    [{"source_url": "https://example.invalid/implicit-pin", "is_top": 1}],
                )
                self.assertEqual(result["stats"]["saved"], 0)

    def test_bootstrap_and_sources_route_share_data_and_reuse_page_facets(self):
        with patch.object(self.server, "BOOTSTRAP_CACHE", {"payload": None, "timestamp": 0}), patch.object(
            self.server, "fetch_video_facets", wraps=self.server.fetch_video_facets
        ) as fetch_facets:
            bootstrap = self.get_payload("/api/bootstrap")
            fetch_facets.assert_called_once_with(self.conn)
        sources_payload = self.get_payload("/api/sources")
        self.assertEqual(bootstrap["sources"], sources_payload["sources"])
        self.assertEqual(bootstrap["stats"]["source_count"], 4)
        self.assertEqual(bootstrap["video_facets"], self.expected_facets())
        self.assertEqual(bootstrap["videos_page"], {
            "total": 37, "limit": 30, "offset": 0, "has_more": True,
        })
        videos_payload = self.get_payload("/api/videos?creator=Bob&limit=1&offset=0")
        self.assertEqual(videos_payload["total"], 1)
        self.assertEqual([video["creator"] for video in videos_payload["videos"]], ["Bob"])
        self.assertEqual(videos_payload["facets"], bootstrap["video_facets"])


if __name__ == "__main__":
    unittest.main()
