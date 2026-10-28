"""Real HTTP transcript edits in a private PostgreSQL schema, rolled back per test.

Run with: .venv/bin/python -m unittest discover -s tests -p test_transcript_edit.py -v
"""
import importlib.util
import json
import os
from contextlib import ExitStack, nullcontext
from pathlib import Path
import shlex
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]


class TestConnection:
    """Keep application queries inside the isolated, uncommitted test transaction."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, statement, params=None):
        cursor = self.raw.cursor()
        cursor.execute(statement, params)
        return cursor


class TranscriptEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Match the facet tests: only use this project's local database configuration.
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
        with patch.dict(os.environ, {
            "DATABASE_URL": cls.dsn,
            "ADMIN_PASSWORD": "transcript-test-password",
            "ADMIN_SESSION_SECRET": "transcript-test-secret",
        }):
            spec = importlib.util.spec_from_file_location(
                "decor_transcript_edit_test_server", ROOT / "backend/server.py"
            )
            cls.server = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.server)

    def setUp(self):
        ad_review = patch.object(self.server, "review_video_advertising", return_value={})
        ad_review.start()
        self.addCleanup(ad_review.stop)
        try:
            raw = psycopg2.connect(self.dsn, cursor_factory=RealDictCursor, connect_timeout=5)
        except psycopg2.Error:
            raise RuntimeError("Local PostgreSQL test connection failed") from None
        self.addCleanup(raw.close)
        self.addCleanup(raw.rollback)
        self.conn = TestConnection(raw)
        identifier = sql.Identifier("test_transcript_edit_" + uuid.uuid4().hex)
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(identifier))
        # No public fallback, so an uncreated table can never reach business data.
        self.conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(identifier))
        baseline = "\n".join(
            line for line in (ROOT / "db/schema.sql").read_text().splitlines()
            if not line.startswith(("CREATE EXTENSION ", "CREATE INDEX "))
        )
        self.conn.execute(baseline.replace("public.", identifier.as_string(raw) + "."))
        self.seed()

        server = self.server
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(server, "connect", side_effect=lambda: nullcontext(self.conn)))
        stack.enter_context(patch.dict(server.DB_STATUS, {"available": True, "message": "ok"}))
        stack.enter_context(patch.object(server, "BOOTSTRAP_CACHE", {"payload": None, "timestamp": 0}))
        stack.enter_context(patch.object(server, "BOOTSTRAP_CACHE_TTL_SECONDS", 3600))
        # Fail closed if manual edits ever start transcription, extraction, or a model request.
        self.upstreams = {}
        for name in (
            "fetch_transcript_from_transcriptgenerate", "save_transcript_for_video",
            "retry_video_from_transcript", "extract_claims_for_video", "call_deepseek",
            "transcript_request", "transcript_request_once",
        ):
            self.upstreams[name] = stack.enter_context(patch.object(
                server, name, side_effect=AssertionError("manual edit must not call " + name)
            ))
        self.addCleanup(self.assert_no_upstreams)

        class QuietHandler(server.AppHandler):
            def log_message(self, _format, *args):
                pass

        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_http)
        self.cookie = None
        status, body, headers = self.request(
            "/api/admin/login", {"password": "transcript-test-password"}, authenticated=False
        )
        self.assertEqual(status, 200, body)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]

    def seed(self):
        self.video_id = "editable-video"
        self.old_text = "原文案：检查插座接线。"
        self.conn.execute(
            """INSERT INTO videos (id, platform, creator, title, source_url, transcript_text,
                   transcript_source, transcript_created_at, has_transcript, transcript_length,
                   status, last_error, created_at, updated_at)
               VALUES (%s, 'test', 'test', '待编辑', 'https://example.invalid/edit', %s,
                   'original', 77, true, %s, 'claims_extracted', 'old extraction error', 77, 77)""",
            (self.video_id, self.old_text, len(self.old_text)),
        )
        for video_id, deleted_at in (("no-transcript", None), ("deleted-video", 100)):
            self.conn.execute(
                """INSERT INTO videos (id, platform, creator, title, source_url, status,
                       created_at, updated_at, deleted_at)
                   VALUES (%s, 'test', 'test', %s, %s, 'transcript_pending', 77, 77, %s)""",
                (video_id, video_id, "https://example.invalid/" + video_id, deleted_at),
            )
        self.conn.execute(
            """INSERT INTO extraction_runs (id, video_id, model, prompt_version, input_hash,
                   prompt_text, status, created_at, raw_response_json)
               VALUES ('old-run', %s, 'test-model', 'old-version', 'old-hash',
                   'old prompt', 'completed', 77, '{"claims": []}')""",
            (self.video_id,),
        )
        for claim_id, deleted_at in (("active-card", None), ("deleted-card", 100)):
            self.conn.execute(
                """INSERT INTO claims (id, video_id, extraction_run_id, object_name, stance,
                       process_stage, original_conclusion, conditions, price_info, source_video_url,
                       created_at, deleted_at)
                   VALUES (%s, %s, 'old-run', '插座', '未明确', '待人工分类', '保留旧观点',
                       '未提及', '未提及', 'https://example.invalid/edit', 77, %s)""",
                (claim_id, self.video_id, deleted_at),
            )

    def stop_http(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.assertFalse(self.worker.is_alive())

    def assert_no_upstreams(self):
        for name, mock in self.upstreams.items():
            with self.subTest(upstream=name):
                mock.assert_not_called()

    def request(self, path=None, payload=None, authenticated=True, method="POST", raw_body=None):
        if path is None:
            path = f"/api/videos/{self.video_id}/transcript"
        headers = {"Content-Type": "application/json"}
        if authenticated and self.cookie:
            headers["Cookie"] = self.cookie
        body = None
        if method == "POST":
            body = raw_body if raw_body is not None else json.dumps(
                payload if payload is not None else {}, ensure_ascii=False
            ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_port}{path}",
            data=body, headers=headers, method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response), response.headers

    def video(self, video_id=None):
        return dict(self.conn.execute(
            "SELECT * FROM videos WHERE id = %s", (video_id or self.video_id,)
        ).fetchone())

    def snapshot(self):
        return {
            table: self.conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            for table in ("videos", "claims", "extraction_runs")
        }

    def test_authentication_precedes_json_parsing_database_and_cache_access(self):
        before = self.snapshot()
        with patch.object(self.server, "connect") as connect, patch.object(
            self.server, "invalidate_bootstrap_cache"
        ) as invalidate:
            for body in (b'{"transcript_text": "new"}', b"invalid json"):
                status, result, _ = self.request(authenticated=False, raw_body=body)
                self.assertEqual((status, result["error"]), (401, "admin login required"))
            connect.assert_not_called()
            invalidate.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_logged_in_multiline_save_updates_metadata_and_preserves_cards_and_runs(self):
        before = self.video()
        relations = self.snapshot()
        text = "  第一行：检查接线。\n第二行：验收插座。\n "
        saved_at = self.server.now() + 10
        with patch.object(self.server, "now", return_value=saved_at):
            status, result, _ = self.request(payload={"transcript_text": text})
        self.assertEqual(status, 200, result)
        updated = self.video()
        self.assertEqual(result, {"video": self.server.row_to_video(updated)})
        self.assertEqual(updated["transcript_text"], text)
        self.assertTrue(updated["has_transcript"])
        self.assertEqual(updated["transcript_length"], len(text.strip()))
        self.assertEqual(updated["transcript_source"], "manual")
        self.assertEqual(updated["transcript_created_at"], saved_at)
        self.assertEqual(updated["updated_at"], saved_at)
        self.assertEqual(updated["status"], "transcript_saved")
        self.assertIsNone(updated["last_error"])
        changed = {"transcript_text", "has_transcript", "transcript_length", "transcript_source",
                   "transcript_created_at", "updated_at", "status", "last_error"}
        self.assertEqual({k: v for k, v in updated.items() if k not in changed},
                         {k: v for k, v in before.items() if k not in changed})
        after = self.snapshot()
        self.assertEqual(after["claims"], relations["claims"])
        self.assertEqual(after["extraction_runs"], relations["extraction_runs"])

    def test_short_text_and_custom_source_are_saved_without_extraction(self):
        before = self.snapshot()
        saved_at = self.server.now() + 10
        with patch.object(self.server, "now", return_value=saved_at):
            status, result, _ = self.request(payload={
                "transcript_text": "好", "transcript_source": "existing-client/editor",
                "extract": True,  # This route must never dispatch extraction, even if requested.
            })
        self.assertEqual(status, 200, result)
        video = result["video"]
        self.assertEqual(video["transcript_text"], "好")
        self.assertEqual(video["transcript_length"], 1)
        self.assertTrue(video["has_transcript"])
        self.assertEqual(video["transcript_source"], "existing-client/editor")
        self.assertEqual(video["status"], "transcript_saved")
        self.assertEqual(video["transcript_created_at"], saved_at)
        self.assertEqual(video["updated_at"], saved_at)
        after = self.snapshot()
        self.assertEqual(after["claims"], before["claims"])
        self.assertEqual(after["extraction_runs"], before["extraction_runs"])

    def test_blank_missing_and_non_string_text_return_400_without_writes(self):
        before = self.snapshot()
        payloads = [{}, *({"transcript_text": value} for value in (
            "", " \n\r\t\u3000", None, False, True, 0, 42, 1.5, [], ["text"], {}, {"text": "text"},
        ))]
        execute = self.conn.execute
        with patch.object(self.conn, "execute", wraps=execute) as queries:
            for payload in payloads:
                with self.subTest(payload=payload):
                    status, result, _ = self.request(payload=payload)
                    self.assertEqual(status, 400, result)
                    self.assertEqual(self.snapshot(), before)
            self.assertTrue(all(call.args[0].lstrip().startswith("SELECT")
                                for call in queries.call_args_list))

    def test_deleted_and_missing_videos_return_404_without_changes(self):
        before = self.snapshot()
        for video_id in ("deleted-video", "missing-video"):
            with self.subTest(video_id=video_id):
                status, result, _ = self.request(
                    f"/api/videos/{video_id}/transcript", {"transcript_text": "新文案"}
                )
                self.assertEqual((status, result["error"]), (404, "video not found"))
                self.assertEqual(self.snapshot(), before)

    def test_success_clears_cache_after_write_and_refreshes_lengths_and_global_stats(self):
        status, before, _ = self.request("/api/bootstrap", method="GET")
        self.assertEqual(status, 200, before)
        self.assertEqual(before["stats"]["transcript_count"], 1)
        self.assertIsNotNone(self.server.BOOTSTRAP_CACHE["payload"])
        execute = self.conn.execute
        refilled = []

        def execute_with_cache_refill(statement, params=None):
            if statement.lstrip().startswith("UPDATE videos"):
                # Simulate a GET filling the cache between POST's generic invalidation and write.
                refilled.append(self.server.get_cached_bootstrap_payload(self.conn))
            return execute(statement, params)

        with patch.object(self.conn, "execute", side_effect=execute_with_cache_refill):
            status, result, _ = self.request(
                "/api/videos/no-transcript/transcript", {"transcript_text": "短文案"}
            )
        self.assertEqual(status, 200, result)
        self.assertEqual(len(refilled), 1)
        self.assertEqual(refilled[0]["stats"]["transcript_count"], 1)
        self.assertIsNone(self.server.BOOTSTRAP_CACHE["payload"])
        self.assertEqual(self.server.BOOTSTRAP_CACHE["timestamp"], 0)
        status, after, _ = self.request("/api/bootstrap", method="GET")
        self.assertEqual(status, 200, after)
        self.assertEqual(after["stats"]["transcript_count"], 2)
        self.assertEqual(after["stats"]["claim_count"], before["stats"]["claim_count"])
        video = next(v for v in after["videos"] if v["id"] == "no-transcript")
        self.assertEqual(video["transcript_length"], 3)
        self.assertTrue(video["has_transcript"])


if __name__ == "__main__":
    unittest.main()
