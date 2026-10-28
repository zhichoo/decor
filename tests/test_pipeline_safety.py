"""Isolated pipeline regression tests; requires Docker and postgres:18-alpine."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch

import psycopg2

ROOT = Path(__file__).resolve().parents[1]


class PipelineSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = subprocess.check_output([
            "docker", "run", "--rm", "-d", "--tmpfs", "/var/lib/postgresql",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-p", "127.0.0.1::5432",
            "postgres:18-alpine",
        ], text=True).strip()
        try:
            port = subprocess.check_output([
                "docker", "port", cls.container, "5432/tcp"
            ], text=True).strip().rsplit(":", 1)[1]
            cls.dsn = f"postgresql://postgres@127.0.0.1:{port}/postgres"
            for _ in range(60):
                try:
                    with psycopg2.connect(cls.dsn) as raw:
                        with raw.cursor() as cursor:
                            cursor.execute((ROOT / "db/schema.sql").read_text())
                    break
                except psycopg2.OperationalError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("isolated PostgreSQL did not become ready")
            # Import only after overriding any environment/local configuration with this disposable DSN.
            os.environ["DATABASE_URL"] = cls.dsn
            spec = importlib.util.spec_from_file_location("decor_pipeline_test_server", ROOT / "backend/server.py")
            cls.server = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.server)
            # Legacy provider fakes must not depend on the developer's local ASR config.
            cls.server.TRANSCRIPT_PROVIDER = "transcriptgenerate"
            cls.server.TRANSCRIPT_SETTINGS_PATH = ROOT / '.runtime' / ('test-settings-' + cls.container + '.json')
            assert cls.server.PG_DSN == cls.dsn
        except BaseException:
            subprocess.run(["docker", "rm", "-f", cls.container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            raise

    @classmethod
    def tearDownClass(cls):
        if cls.server._pool is not None:
            cls.server._pool.closeall()
        subprocess.run(["docker", "rm", "-f", cls.container], check=True, stdout=subprocess.DEVNULL)

    def setUp(self):
        # These fixtures isolate extraction/ASR; advertising has its own tests.
        ad_review = patch.object(self.server, "review_video_advertising", return_value={"decision": "not_ad"})
        ad_review.start()
        self.addCleanup(ad_review.stop)
        self.video_id = "isolated-video"
        self.old_text = "旧文案：" + "装修验收时检查每个插座的接线是否安全。" * 9
        with self.server.connect() as conn:
            conn.execute("TRUNCATE claims, extraction_runs, videos CASCADE")
            conn.execute("""INSERT INTO videos (id, platform, creator, title, source_url, transcript_text,
                transcript_source, transcript_created_at, has_transcript, transcript_length, status, created_at, updated_at)
                VALUES (%s, 'test', 'test', 'test', 'https://example.invalid/video', %s,
                'original', 77, true, %s, 'claims_extracted', 77, 77)""",
                (self.video_id, self.old_text, len(self.old_text)))
            conn.execute("""INSERT INTO claims (id, video_id, object_name, stance, process_stage, space_tags,
                topic_tags, original_conclusion, original_reasons, conditions, alternatives, price_info,
                source_video_url, created_at) VALUES ('old', %s, '插座', '未明确', '待人工分类', '[]',
                '[]', '旧观点', '[]', '未提及', '[]', '未提及', 'https://example.invalid/video', 77)""", (self.video_id,))

    def video(self):
        with self.server.connect() as conn:
            return dict(conn.execute("SELECT * FROM videos WHERE id = %s", (self.video_id,)).fetchone())

    def claims(self):
        with self.server.connect() as conn:
            return conn.execute("SELECT id, deleted_at, original_conclusion FROM claims ORDER BY original_conclusion").fetchall()

    def active(self):
        return [row for row in self.claims() if row["deleted_at"] is None]

    def result(self, claims, reason="none"):
        return json.dumps({"choices": [{"message": {"content": json.dumps({
            "claims": claims, "filter_reason": reason, "filter_message": ""
        })}}]})

    def claim(self, conclusion, quote=None):
        if quote is None:
            quote = "装修验收时检查每个插座的接线是否安全"
        return {"object_name": "插座", "original_conclusion": conclusion,
                "original_reasons": ["验收时检查接线是否牢固"], "process_stage": "待人工分类",
                "source_quotes": [quote]}

    def extract_with(self, response, error=None):
        with patch.object(self.server, "call_deepseek", return_value=(response, error)):
            with self.server.connect() as conn:
                return self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()))

    def test_retry_transcript_failure_keeps_original_metadata_and_cards(self):
        before = self.video()
        with patch.object(self.server, "fetch_transcript_from_transcriptgenerate", side_effect=RuntimeError("upstream failed")):
            with self.assertRaisesRegex(RuntimeError, "upstream failed"):
                self.server.retry_video_from_transcript(self.video_id)
        after = self.video()
        for key in ("transcript_text", "transcript_source", "transcript_created_at", "has_transcript",
                    "transcript_length", "status"):
            self.assertEqual(before[key], after[key], key)
        self.assertEqual([row["id"] for row in self.active()], ["old"])

    def test_video_delete_option_preserves_knowledge_or_deletes_claims(self):
        for delete_claims in (False, True):
            with self.subTest(delete_claims=delete_claims):
                self.setUp()
                with self.server.connect() as conn:
                    self.assertTrue(self.server.delete_video_and_claims(
                        conn, self.video_id, 101, "test", delete_claims=delete_claims
                    ))
                    self.assertEqual(self.video()["deleted_at"], 101)
                    page = self.server.fetch_knowledge_page(conn)
                    self.assertEqual(page["total"], 0 if delete_claims else 1)
                    self.assertEqual(page["facets"]["total"], 0 if delete_claims else 1)
                    self.assertEqual(len(self.active()), 0 if delete_claims else 1)
                    self.assertFalse(self.server.delete_video_and_claims(
                        conn, self.video_id, 102, "repeat", delete_claims=True
                    ))
                    self.assertEqual(len(self.active()), 0 if delete_claims else 1)

    def test_video_delete_http_option_validation_and_default(self):
        server = self.server

        class QuietHandler(server.AppHandler):
            def log_message(self, _format, *args):
                pass

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.object(server, "ADMIN_PASSWORD", "test-delete-only"), \
                 patch.dict(server.DB_STATUS, {"available": True, "message": "ok"}):
                cookie = server.make_admin_session_value()
                for query, authenticated, expected_status, deleted in (
                    ("?delete_claims=false", False, 401, None),
                    ("?delete_claims=invalid", True, 400, None),
                    ("?delete_claims=", True, 400, None),
                    ("?delete_claims=true&delete_claims=false", True, 400, None),
                    ("?delete_claims=false", True, 200, False),
                    ("?delete_claims=true", True, 200, True),
                    ("", True, 200, True),
                ):
                    with self.subTest(query=query, authenticated=authenticated):
                        self.setUp()
                        headers = {"Cookie": f"{server.ADMIN_SESSION_COOKIE}={cookie}"} if authenticated else {}
                        request = urllib.request.Request(
                            f"http://127.0.0.1:{httpd.server_port}/api/videos/{self.video_id}{query}",
                            headers=headers, method="DELETE",
                        )
                        try:
                            response = urllib.request.urlopen(request, timeout=3)
                        except urllib.error.HTTPError as exc:
                            response = exc
                        with response:
                            self.assertEqual(response.status, expected_status)
                            body = json.load(response)
                        if deleted is None:
                            self.assertIsNone(self.video()["deleted_at"])
                            self.assertEqual(len(self.active()), 1)
                        else:
                            self.assertEqual(body["claims_deleted"], deleted)
                            self.assertIsNotNone(self.video()["deleted_at"])
                            self.assertEqual(len(self.active()), 0 if deleted else 1)
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=3)
            server.invalidate_bootstrap_cache()

    def test_second_insert_failure_rolls_back_all_claims_and_status(self):
        real_insert = self.server.new_id
        count = 0

        def fail_second(prefix):
            nonlocal count
            if prefix == "claim":
                count += 1
                if count == 2:
                    return "old"  # Primary key violation after first new claim was inserted.
            return real_insert(prefix)

        with patch.object(self.server, "new_id", side_effect=fail_second):
            with self.assertRaises(psycopg2.errors.UniqueViolation):
                self.extract_with(self.result([self.claim("新观点一"), self.claim("新观点二")]))
        self.assertEqual([row["id"] for row in self.claims()], ["old"])
        self.assertEqual(self.video()["status"], "claims_extracted")
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT status FROM extraction_runs").fetchone()["status"], "insert_failed")

    def test_model_parse_and_untrusted_empty_keep_old_cards(self):
        result = self.extract_with(None, "model_unavailable")
        self.assertEqual(result["status"], "model_unavailable")
        for response in ("not json", self.result([], "none"), self.result([], "unexpected")):
            with self.assertRaises(ValueError):
                self.extract_with(response)
            self.assertEqual([row["id"] for row in self.active()], ["old"])
            self.assertEqual(self.video()["status"], "claims_extracted")

    def test_explicit_filter_and_empty_text_clear_active_cards(self):
        result = self.extract_with(self.result([], "promotion_only"))
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(self.active(), [])
        self.assertEqual(self.video()["status"], "claims_filtered")
        with self.server.connect() as conn:
            summary = self.server.fetch_progress_summary(conn)
            self.assertEqual(summary["已完成"], 1)
            self.assertEqual(summary["失败"], 0)
            conn.execute("UPDATE claims SET deleted_at = NULL WHERE id = 'old'")
            conn.execute("UPDATE videos SET transcript_text = '', transcript_length = 0 WHERE id = %s", (self.video_id,))
            result = self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()))
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(self.active(), [])
        self.assertEqual(self.video()["status"], "claims_filtered")

    def test_retry_short_transcript_filters_without_model_call(self):
        with patch.object(self.server, "fetch_transcript_from_transcriptgenerate", return_value={
            "transcript_text": "太短", "task_id": "mock-task"
        }), patch.object(self.server, "call_deepseek") as model:
            result = self.server.retry_video_from_transcript(self.video_id)
        self.assertEqual(result["status"], "filtered")
        self.assertEqual(self.video()["status"], "claims_filtered")
        self.assertEqual(self.video()["transcript_text"], "太短")
        self.assertEqual(self.active(), [])
        model.assert_not_called()

    def test_retry_model_failure_retains_cards_after_saving_new_transcript(self):
        new_text = "重试新文案：" + "水电验收需要检查接线。" * 12
        with patch.object(self.server, "fetch_transcript_from_transcriptgenerate", return_value={
            "transcript_text": new_text, "task_id": "mock-task"
        }), patch.object(self.server, "call_deepseek", return_value=(None, "model_unavailable")):
            with self.assertRaisesRegex(RuntimeError, "model_unavailable"):
                self.server.retry_video_from_transcript(self.video_id)
        self.assertEqual(self.video()["transcript_text"], new_text)
        self.assertEqual(self.video()["status"], "claims_extracted")
        self.assertEqual([row["id"] for row in self.active()], ["old"])

    def test_stale_or_deleted_video_cannot_replace_cards(self):
        response = self.result([self.claim("新观点")])

        def change_transcript(_prompt):
            with self.server.connect() as conn:
                conn.execute("UPDATE videos SET transcript_text = '并发更新的文案' WHERE id = %s", (self.video_id,))
            return response, None

        with patch.object(self.server, "call_deepseek", side_effect=change_transcript):
            with self.server.connect() as conn:
                with self.assertRaisesRegex(ValueError, "transcript changed"):
                    self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()))
        self.assertEqual([row["id"] for row in self.active()], ["old"])
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET deleted_at = 100 WHERE id = %s", (self.video_id,))
        with self.assertRaisesRegex(ValueError, "video not found"):
            self.extract_with(response)
        self.assertEqual([row["id"] for row in self.active()], ["old"])

    def test_missing_or_fabricated_evidence_and_empty_conclusion_keep_old_cards(self):
        cases = [
            ({key: value for key, value in self.claim("新观点").items() if key != "source_quotes"}, "missing_source_evidence"),
            (self.claim("新观点", "原文里根本没有这样的做法和结论"), "unsupported_source_evidence"),
            (self.claim(""), "empty_conclusion"),
        ]
        for expected_count, (claim, reason) in enumerate(cases, start=1):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, "quality_check_failed"):
                    self.extract_with(self.result([claim]))
                self.assertEqual([row["id"] for row in self.active()], ["old"])
                self.assertEqual(self.video()["status"], "claims_extracted")
                with self.server.connect() as conn:
                    count = conn.execute(
                        "SELECT COUNT(*) AS count FROM extraction_runs WHERE status = 'quality_check_failed'"
                    ).fetchone()["count"]
                self.assertEqual(count, expected_count)

    def test_partial_quality_success_replaces_only_supported_claim(self):
        bad_claim = self.claim("无来源引用")
        bad_claim.pop("source_quotes")
        result = self.extract_with(self.result([bad_claim, self.claim("验收时检查插座接线")]))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["claims"]), 1)
        self.assertEqual([item["reason"] for item in result["dropped_claims"]], ["missing_source_evidence"])
        self.assertEqual([row["original_conclusion"] for row in self.active()], ["验收时检查插座接线"])
        self.assertEqual(self.video()["status"], "claims_extracted")

    def test_video_deletion_waits_for_claim_replacement_then_clears_all(self):
        started = threading.Event()
        outcome = []

        def delete_in_thread():
            started.set()
            try:
                with self.server.connect() as conn:
                    outcome.append(self.server.delete_video_and_claims(conn, self.video_id, 101, "test"))
            except Exception as exc:
                outcome.append(exc)

        with self.server.connect() as conn:
            with conn.transaction():
                conn.execute("SELECT id FROM videos WHERE id = %s FOR UPDATE", (self.video_id,))
                thread = threading.Thread(target=delete_in_thread)
                thread.start()
                self.assertTrue(started.wait(timeout=2))
                time.sleep(0.1)
                self.assertTrue(thread.is_alive(), "deletion must wait on the video row lock")
                self.server.insert_claims(conn, self.server.row_to_video(self.video()), None, [self.claim("验收时检查插座接线")])
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [True])
        self.assertEqual(self.video()["deleted_at"], 101)
        self.assertEqual(self.active(), [])
        self.assertEqual(len(self.claims()), 2)

    def test_quick_ingest_http_saves_manual_transcript_and_cards(self):
        server = self.server
        previous_db_status = dict(server.DB_STATUS)
        server.check_database()
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        payload = {
            "share_url": "https://example.invalid/video/manual-ingest", "transcript_text": self.old_text,
            "creator": "Test", "title": "人工文案入库", "extract": True,
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_port}/api/videos/quick-ingest",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with patch.object(server, "ADMIN_PASSWORD", "pipeline-test-password"), patch.object(
                server, "ADMIN_SESSION_SECRET", "pipeline-test-session-secret"
            ), patch.object(server, "call_deepseek", return_value=(self.result([self.claim("验收时检查插座接线")]), None)):
                request.add_header("Cookie", f"{server.ADMIN_SESSION_COOKIE}={server.make_admin_session_value()}")
                with urllib.request.urlopen(request, timeout=10) as response:
                    self.assertEqual(response.status, 201)
                    result = json.load(response)
            self.assertEqual(result["extraction"]["status"], "completed")
            self.assertEqual(result["video"]["transcript_text"], self.old_text)
            with server.connect() as conn:
                saved = conn.execute("SELECT * FROM videos WHERE id=%s", (result["video"]["id"],)).fetchone()
                count = conn.execute("SELECT count(*) AS n FROM claims WHERE video_id=%s AND deleted_at IS NULL", (saved["id"],)).fetchone()["n"]
                self.assertEqual(saved["status"], "claims_extracted")
                self.assertEqual(count, 1)
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=5)
            server.DB_STATUS.update(previous_db_status)
            server.invalidate_bootstrap_cache()

    def test_queue_transcribes_extracts_and_finishes_job(self):
        server = self.server
        previous_job = server.queue_snapshot()
        with server.connect() as conn:
            conn.execute("UPDATE videos SET transcript_text=NULL,has_transcript=false,transcript_length=0,status='created',retry_count=0 WHERE id=%s", (self.video_id,))
        transcript_result = {"task_id": "test-transcript-task", "transcript_text": self.old_text, "raw_result": {}}
        try:
            with patch.object(server, "fetch_transcript_from_transcriptgenerate", return_value=transcript_result), patch.object(
                server, "call_deepseek", return_value=(self.result([self.claim("验收时检查插座接线")]), None)
            ):
                job_id = server.reserve_queue_job()
                self.assertTrue(job_id)
                server.run_queue_job(limit=1, delay_seconds=0, job_id=job_id)
            snapshot = server.queue_snapshot()
            self.assertFalse(snapshot["running"])
            self.assertEqual(len(snapshot["processed"]), 1)
            self.assertEqual(snapshot["failed"], [])
            self.assertEqual(snapshot["processed"][0]["stage"], "completed")
            self.assertIsNotNone(snapshot["finished_at"])
            video = self.video()
            self.assertEqual(video["transcript_text"], self.old_text)
            self.assertEqual(video["status"], "claims_extracted")
            self.assertEqual(video["retry_count"], 1)
            self.assertEqual(len(self.active()), 1)
            self.assertNotEqual(self.active()[0]["id"], "old")
        finally:
            with server.QUEUE_JOB_LOCK:
                server.QUEUE_JOB.update(previous_job)

    def test_health_detects_missing_business_schema(self):
        self.assertEqual(self.server.database_readiness(), (True, ""))
        with self.server.connect() as conn:
            conn.execute("ALTER TABLE claims RENAME TO claims_temporarily_unavailable")
        try:
            available, message = self.server.database_readiness()
            self.assertFalse(available)
            self.assertTrue(message)
        finally:
            with self.server.connect() as conn:
                conn.execute("ALTER TABLE claims_temporarily_unavailable RENAME TO claims")
        self.assertEqual(self.server.database_readiness(), (True, ""))

    def test_successful_retry_replaces_cards_and_saves_transcript(self):
        new_text = "新文案：" + "水电完成后检查所有插座的接线。" * 10
        with patch.object(self.server, "fetch_transcript_from_transcriptgenerate", return_value={
            "transcript_text": new_text, "task_id": "mock-task"
        }), patch.object(self.server, "call_deepseek", return_value=(self.result([
            self.claim("新观点", "水电完成后检查所有插座的接线")
        ]), None)):
            result = self.server.retry_video_from_transcript(self.video_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.video()["transcript_text"], new_text)
        self.assertEqual(self.video()["status"], "claims_extracted")
        self.assertEqual([row["original_conclusion"] for row in self.active()], ["新观点"])
        self.assertIsNotNone(next(row for row in self.claims() if row["id"] == "old")["deleted_at"])


if __name__ == "__main__":
    unittest.main()
