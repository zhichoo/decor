"""Trash lifecycle regressions against disposable PostgreSQL; no external services."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_pipeline_safety as pipeline


class VideoTrashTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    video = pipeline.PipelineSafetyTests.video
    claims = pipeline.PipelineSafetyTests.claims
    active = pipeline.PipelineSafetyTests.active
    claim = pipeline.PipelineSafetyTests.claim
    result = pipeline.PipelineSafetyTests.result
    extract_with = pipeline.PipelineSafetyTests.extract_with

    def setUp(self):
        pipeline.PipelineSafetyTests.setUp(self)
        self.server.DB_STATUS["available"] = True
        self.password = patch.object(self.server, "ADMIN_PASSWORD", "trash-only-test-password")
        self.password.start()
        self.addCleanup(self.password.stop)
        self.http = self.server.ThreadingHTTPServer(("127.0.0.1", 0), self.server.AppHandler)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_http)

    def stop_http(self):
        self.http.shutdown()
        self.http.server_close()
        self.worker.join(timeout=3)

    def request(self, path, method="GET", authenticated=True, payload=None):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Cookie"] = self.server.ADMIN_SESSION_COOKIE + "=" + self.server.make_admin_session_value()
        request = urllib.request.Request(f"http://127.0.0.1:{self.http.server_port}" + path,
            data=json.dumps(payload or {}).encode() if method == "POST" else None, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def trash(self, delete_claims=False):
        with self.server.connect() as conn:
            self.assertTrue(self.server.delete_video_and_claims(conn, self.video_id, 123, "test", delete_claims))

    def test_only_retained_cards_allow_public_read_only_source_preview(self):
        self.trash()
        path = "/api/knowledge/sources/" + self.video_id
        self.assertEqual(self.request("/api/videos/" + self.video_id, authenticated=False)[0], 404)
        with patch.object(self.server, "call_deepseek") as model:
            for readonly in (False, True):
                with patch.object(self.server, "PUBLIC_READ_ONLY", readonly):
                    status, body = self.request(path, authenticated=False)
                    self.assertEqual(status, 200)
                    self.assertTrue(body["video"]["source_read_only"])
                    self.assertEqual(body["video"]["transcript_text"], self.old_text)
                    self.assertEqual([card["id"] for card in body["claims"]], ["old"])
                    for private in ("transcript_job", "last_error", "delete_reason", "ad_review_override"):
                        self.assertNotIn(private, body["video"])
            model.assert_not_called()
        self.assertEqual(self.request("/api/admin/deleted/videos/" + self.video_id, authenticated=False)[0], 401)
        with self.server.connect() as conn:
            conn.execute("UPDATE claims SET deleted_at=123")
        self.assertEqual(self.request(path, authenticated=False)[0], 404)

    def test_permanent_delete_clears_all_cards_runs_and_content_but_keeps_url_skip_marker(self):
        self.extract_with(self.result([self.claim("检查插座接线。")]))
        self.trash()
        path = "/api/admin/deleted/videos/" + self.video_id
        self.assertEqual(self.request(path, method="DELETE", authenticated=False)[0], 401)
        with patch.object(self.server, "PUBLIC_READ_ONLY", True):
            self.assertEqual(self.request(path, method="DELETE")[0], 403)
        status, body = self.request(path, method="DELETE")
        self.assertEqual((status, body["status"], body["claims_deleted"], body["runs_deleted"]), (200, "purged", 2, 1))
        video = self.video()
        self.assertIsNotNone(video["purged_at"])
        self.assertEqual(video["source_url"], "https://example.invalid/video")
        self.assertEqual((video["title"], video["creator"], video["platform"]), ("", "", ""))
        for key in ("transcript_text", "transcript_job", "ad_review", "share_text"):
            self.assertIsNone(video[key])
        with self.server.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM extraction_runs").fetchone()["n"], 0)
        self.assertEqual(self.claims(), [])
        self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request(path, method="DELETE")[0], 404)
        self.assertEqual(self.request("/api/knowledge/sources/" + self.video_id)[0], 404)
        self.assertEqual(self.request("/api/videos/" + self.video_id + "/restore", method="POST")[0], 404)
        self.assertEqual(self.request("/api/admin/deleted")[1]["video_total"], 0)
        with self.server.connect() as conn:
            result = self.server.save_collected_videos(conn,
                {"platform": "test", "creator": "test", "profile_url": "https://example.invalid/creator"},
                [{"source_url": video["source_url"], "title": "must not recreate"}])
        self.assertEqual(result["stats"]["skipped_deleted"], 1)
        self.assertIn("永久删除", result["skipped_videos"][0]["delete_reason"])
        with patch.object(self.server, "call_deepseek") as model:
            for route, payload in (("/api/videos/quick-ingest", {"share_url": video["source_url"]}),
                                   ("/api/videos", {"platform": "test", "creator": "test", "title": "test",
                                                    "source_url": video["source_url"]})):
                self.assertEqual(self.request(route, method="POST", payload=payload)[0], 409)
            model.assert_not_called()

    def test_active_video_cannot_be_purged_and_failed_purge_rolls_back_everything(self):
        with self.server.connect() as conn:
            self.assertIsNone(self.server.purge_video_and_claims(conn, self.video_id))
        self.trash()
        before = self.video()
        with self.server.connect() as conn:
            execute = conn.execute
            def fail(statement, params=None):
                if "UPDATE videos SET purged_at" in statement:
                    raise RuntimeError("simulated storage failure")
                return execute(statement, params)
            with patch.object(conn, "execute", side_effect=fail), self.assertRaisesRegex(RuntimeError, "storage failure"):
                self.server.purge_video_and_claims(conn, self.video_id)
        self.assertEqual(self.video(), before)
        self.assertEqual([card["id"] for card in self.active()], ["old"])


if __name__ == "__main__":
    unittest.main()
