"""HTTP permission checks with a disposable server and no real database or upstream calls."""
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
with patch.dict(os.environ, {
    "ADMIN_PASSWORD": "test-password-only",
    "ADMIN_SESSION_SECRET": "test-signing-key-only",
    "DATABASE_URL": "postgresql://localhost/unused_test_db",
}):
    spec = importlib.util.spec_from_file_location("decor_admin_permission_server", ROOT / "backend/server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)


class QuietHandler(server.AppHandler):
    def log_message(self, _format, *args):
        pass


class AdminPermissionTests(unittest.TestCase):
    protected = (
        ("/api/sources", {"platform": "douyin", "name": "New creator"}),
        ("/api/sources", {"id": "src-1", "platform": "douyin", "name": "Changed creator"}),
        ("/api/videos", {"platform": "douyin", "creator": "Test", "title": "New video",
                         "source_url": "https://example.invalid/video"}),
        ("/api/videos", {"platform": "douyin", "creator": "Test", "title": "Manual import",
                         "source_url": "https://example.invalid/video", "transcript_text": "manual"}),
        ("/api/videos/vid-1/share", {"share_url": "https://example.invalid/changed"}),
        ("/api/videos/vid-1/restore", {}),
        ("/api/claims/claim-1/restore", {}),
        ("/api/videos/vid-1/promotion", {"decision": "advertising"}),
        ("/api/settings/transcription", {"provider": "local_asr"}),
        ("/api/settings/transcription/check-local", {}),
        ("/api/sources/src-1/update", {}),
        ("/api/sources/update-all", {}),
        ("/api/videos/vid-1/transcript", {"transcript_text": "手动文案"}),
        ("/api/videos/vid-1/transcript", {"transcript_text": None}),
        ("/api/videos/vid-1/transcript/retry", {}),
        ("/api/videos/vid-1/retry-full/start", {}),
        ("/api/videos/vid-1/extract", {}),
        ("/api/videos/batch-collect", {}),
        ("/api/queue/extract-next", {}),
        ("/api/queue/process-pending", {}),
        ("/api/queue/start", {}),
        ("/api/queue/cancel", {}),
        ("/api/douyin/login/start", {}),
        ("/api/videos/quick-ingest", {"share_url": "https://example.invalid/v"}),
        ("/api/videos/quick-ingest", {"transcript_text": "manual", "extract": True}),
        ("/api/videos/quick-ingest", {"share_url": "https://example.invalid/video", "transcript_text": "manual"}),
        ("/api/videos/quick-ingest", {"share_url": "https://example.invalid/video", "transcript_text": "manual", "extract": False}),
        ("/api/videos/quick-ingest", {"transcript_text": "manual"}),
        ("/api/future-write-operation", {}),
    )

    @classmethod
    def setUpClass(cls):
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=2)

    def setUp(self):
        ad_review = patch.object(server, "review_video_advertising", return_value={"decision": "not_ad"})
        ad_review.start()
        self.addCleanup(ad_review.stop)
        self.password = patch.object(server, "ADMIN_PASSWORD", "test-password-only")
        self.password.start()
        self.addCleanup(self.password.stop)
        self.status = patch.dict(server.DB_STATUS, {"available": True, "message": "ok"})
        self.status.start()
        self.addCleanup(self.status.stop)

    def request(self, path, payload=None, cookie=None, method="POST"):
        headers = {"Content-Type": "application/json"}
        if cookie is not None:
            headers["Cookie"] = f"{server.ADMIN_SESSION_COOKIE}={cookie}"
        body = json.dumps(payload if payload is not None else {}).encode() if method == "POST" else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_port}{path}", data=body, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response), response.headers

    def test_rejected_sessions_cannot_access_db_or_start_side_effects(self):
        expired_at = server.now() - server.ADMIN_SESSION_MAX_AGE_SECONDS - 1
        expired_payload = f"{expired_at}.nonce"
        expired_cookie = f"{expired_payload}.{server.sign_admin_session(expired_payload)}"
        bad_cookie = server.make_admin_session_value() + "tampered"
        for configured, cookie, expected in (
            (True, None, 401),
            (True, bad_cookie, 401),
            (True, expired_cookie, 401),
            (False, server.make_admin_session_value(), 503),
        ):
            with self.subTest(configured=configured, cookie_type=str(cookie is not None)):
                with patch.object(server, "ADMIN_PASSWORD", "test-password-only" if configured else ""):
                    with patch.object(server, "connect") as connect, \
                         patch.object(server, "invalidate_bootstrap_cache") as invalidate, \
                         patch.object(server, "collect_douyin_profile") as collect, \
                         patch.object(server, "fetch_transcript_from_transcriptgenerate") as transcript, \
                         patch.object(server, "extract_claims_for_video") as extract, \
                         patch.object(server, "request_queue_cancel") as cancel, \
                         patch.object(server, "process_pending_queue") as pending, \
                         patch.object(server, "run_douyin_login_job") as login, \
                         patch.object(server, "reserve_queue_job") as reserve, \
                         patch.object(server, "read_json", wraps=server.read_json) as read, \
                         patch.object(server, "call_deepseek") as model, \
                         patch.object(server, "save_transcript_for_video") as save_transcript:
                        for path, payload in self.protected:
                            with self.subTest(path=path, payload=payload):
                                status, body, _ = self.request(path, payload, cookie)
                                self.assertEqual(status, expected, body)
                        connect.assert_not_called()
                        invalidate.assert_not_called()
                        collect.assert_not_called()
                        transcript.assert_not_called()
                        extract.assert_not_called()
                        cancel.assert_not_called()
                        pending.assert_not_called()
                        login.assert_not_called()
                        reserve.assert_not_called()
                        read.assert_not_called()
                        model.assert_not_called()
                        save_transcript.assert_not_called()
                        server.review_video_advertising.assert_not_called()

    def test_authentication_login_and_public_session_read(self):
        with patch.object(server, "connect") as connect:
            status, body, _ = self.request("/api/admin/login", {"password": "wrong"})
            self.assertEqual((status, body["error"]), (401, "invalid admin password"))
            status, body, headers = self.request("/api/admin/login", {"password": "test-password-only"})
            self.assertEqual(status, 200)
            self.assertTrue(body["authenticated"])
            cookie = headers.get("Set-Cookie").split(";", 1)[0].split("=", 1)[1]
            self.assertTrue(server.validate_admin_session_value(cookie))
            status, body, _ = self.request("/api/admin/session", method="GET", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertTrue(body["authenticated"])
            status, body, _ = self.request("/api/admin/logout", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertFalse(body["authenticated"])
            connect.assert_not_called()

    def test_read_only_rejects_writes_even_with_valid_admin_cookie_before_body_or_db(self):
        cookie = server.make_admin_session_value()
        with patch.object(server, "PUBLIC_READ_ONLY", True), \
             patch.object(server, "connect") as connect, \
             patch.object(server, "read_json") as read, \
             patch.object(server, "call_deepseek") as model:
            for path, payload in self.protected + (("/api/admin/login", {"password": "test-password-only"}),
                                                     ("/api/admin/logout", {})):
                for session in (None, cookie):
                    status, body, headers = self.request(path, payload, session)
                    self.assertEqual((status, body["error"]), (403, "public instance is read-only"))
                    self.assertIsNone(headers.get("Set-Cookie"))
            for path in ("/api/videos/vid-1", "/api/claims/claim-1"):
                status, _, _ = self.request(path, cookie=cookie, method="DELETE")
                self.assertEqual(status, 403)
            connect.assert_not_called()
            read.assert_not_called()
            model.assert_not_called()

    def test_read_only_session_cannot_authenticate_and_private_gets_are_blocked(self):
        with patch.object(server, "PUBLIC_READ_ONLY", True), patch.object(server, "connect") as connect, \
             patch.object(server, "get_douyin_login_status") as browser:
            status, body, _ = self.request("/api/admin/session", method="GET", cookie=server.make_admin_session_value())
            self.assertEqual(status, 200)
            self.assertTrue(body["read_only"])
            self.assertFalse(body["authenticated"])
            for path in ("/api/admin/deleted", "/api/settings/transcription", "/api/queue/status",
                         "/api/douyin/login-status", "/api/queue/next", "/api/future-private-read",
                         "/api/videos/vid-1?include_runs=1"):
                status, _, _ = self.request(path, method="GET", cookie=server.make_admin_session_value())
                self.assertEqual(status, 403, path)
            connect.assert_not_called()
            browser.assert_not_called()

    def test_read_only_keeps_public_library_reads_and_does_not_grant_cross_origin_access(self):
        db = MagicMock()
        with patch.object(server, "PUBLIC_READ_ONLY", True), \
             patch.object(server, "connect", return_value=db), \
             patch.object(server, "fetch_sources", return_value=[]), \
             patch.object(server, "fetch_video_page", return_value={"videos": [], "total": 0}), \
             patch.object(server, "fetch_knowledge_page", return_value={"claims": [], "total": 0}):
            for path in ("/api/sources", "/api/videos", "/api/knowledge"):
                status, _, headers = self.request(path, method="GET")
                self.assertEqual(status, 200)
                self.assertIsNone(headers.get("Access-Control-Allow-Credentials"))
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.httpd.server_port}/api/admin/session",
                headers={"Origin": "https://untrusted.invalid"},
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_public_library_reads_remain_available_without_session(self):
        db = MagicMock()
        with patch.object(server, "connect", return_value=db), \
             patch.object(server, "require_admin") as guard, \
             patch.object(server, "fetch_sources", return_value=[]), \
             patch.object(server, "fetch_video_page", return_value={"videos": [], "total": 0}), \
             patch.object(server, "fetch_knowledge_page", return_value={"claims": [], "total": 0}):
            for path in ("/api/sources", "/api/videos", "/api/knowledge"):
                with self.subTest(path=path):
                    status, _, _ = self.request(path, method="GET")
                    self.assertEqual(status, 200)
            guard.assert_not_called()

    def test_authenticated_source_update_reaches_collector(self):
        cookie = server.make_admin_session_value()
        source = {"id": "src-1", "platform": "douyin", "profile_url": "https://example.invalid/profile",
                  "name": "Test", "priority": "P1", "notes": ""}
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = source
        conn.execute.return_value.fetchall.return_value = [source]
        db = MagicMock()
        db.__enter__.return_value = conn
        saved = {"stats": {"received": 1, "saved": 1, "created": 1, "duplicate": 0}}
        with patch.object(server, "connect", return_value=db) as connect, \
             patch.object(server, "collect_douyin_profile", return_value=[{"id": "v"}]) as collect, \
             patch.object(server, "save_collected_videos", return_value=saved.copy()) as save:
            status, body, _ = self.request("/api/sources/src-1/update", {"limit": 1}, cookie)
            self.assertEqual((status, body["status"]), (201, "completed"))
            status, body, _ = self.request("/api/sources/update-all", {"limit": 1}, cookie)
            self.assertEqual((status, body["summary"]["completed"]), (200, 1))
            self.assertEqual(connect.call_count, 2)
            self.assertEqual(collect.call_count, 2)
            self.assertEqual(save.call_count, 2)

    def test_authenticated_retry_extract_and_queue_reach_handlers(self):
        cookie = server.make_admin_session_value()
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"id": "vid-1", "retry_count": 0}
        db = MagicMock()
        db.__enter__.return_value = conn
        transcript_result = {"task_id": "mock", "transcript_text": "text", "raw_result": {}}
        with patch.object(server, "connect", return_value=db), \
             patch.object(server, "save_transcript_for_video", return_value=({"id": "vid-1"}, transcript_result)) as retry, \
             patch.object(server, "row_to_video", return_value={"id": "vid-1"}), \
             patch.object(server, "extract_claims_for_video", return_value={"status": "completed"}) as extract, \
             patch.object(server, "reserve_queue_job", return_value=None) as reserve:
            status, body, _ = self.request("/api/videos/vid-1/transcript/retry", cookie=cookie)
            self.assertEqual(status, 200)
            retry.assert_called_once()
            status, body, _ = self.request("/api/videos/vid-1/extract", cookie=cookie)
            self.assertEqual((status, body["status"]), (200, "completed"))
            extract.assert_called_once()
            status, _, _ = self.request("/api/videos/vid-1/retry-full/start", cookie=cookie)
            self.assertEqual(status, 409)
            status, _, _ = self.request("/api/queue/start", cookie=cookie)
            self.assertEqual(status, 409)
            self.assertEqual(reserve.call_count, 2)

    def test_authenticated_quick_ingest_keeps_validation_and_upstream_behavior(self):
        conn = MagicMock()
        db = MagicMock()
        db.__enter__.return_value = conn
        with patch.object(server, "connect", return_value=db) as connect, \
             patch.object(server, "save_transcript_for_video", side_effect=RuntimeError("stub upstream")) as fetch:
            cookie = server.make_admin_session_value()
            status, _, _ = self.request("/api/videos/quick-ingest", {"transcript_text": "manual"}, cookie)
            self.assertEqual(status, 400)
            self.assertEqual(connect.call_count, 1)
            fetch.assert_not_called()
            status, body, _ = self.request(
                "/api/videos/quick-ingest", {"share_url": "https://example.invalid/video"},
                server.make_admin_session_value(),
            )
            self.assertEqual((status, body["error"]), (502, "stub upstream"))
            self.assertEqual(connect.call_count, 2)
            fetch.assert_called_once()

    def test_authenticated_source_and_manual_imports_remain_available(self):
        cookie = server.make_admin_session_value()
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {
            "id": "vid-1", "source_id": "src-1", "published_at": None, "has_transcript": True,
            "platform": "douyin", "creator": "Test", "title": "Manual import",
        }
        db = MagicMock()
        db.__enter__.return_value = conn
        with patch.object(server, "connect", return_value=db) as connect, \
             patch.object(server, "row_to_video", return_value={"id": "vid-1"}), \
             patch.object(server, "save_transcript_for_video") as fetch:
            for payload in (
                {"platform": "douyin", "name": "New creator"},
                {"id": "src-1", "platform": "douyin", "name": "Changed creator"},
            ):
                status, _, _ = self.request("/api/sources", payload, cookie)
                self.assertEqual(status, 201)
            status, body, _ = self.request("/api/videos", {
                "platform": "douyin", "creator": "Test", "title": "Manual import",
                "source_url": "https://example.invalid/video", "transcript_text": "manual",
            }, cookie)
            self.assertEqual((status, body["video"]["id"]), (201, "vid-1"))
            status, body, _ = self.request("/api/videos/quick-ingest", {
                "share_url": "https://example.invalid/video", "transcript_text": "manual", "extract": False,
            }, cookie)
            self.assertEqual((status, body["video"]["id"]), (201, "vid-1"))
            self.assertEqual(connect.call_count, 4)
            fetch.assert_not_called()
            self.assertEqual(server.review_video_advertising.call_count, 2)

    def test_authenticated_login_start_dispatches_worker(self):
        cookie = server.make_admin_session_value()
        launched = threading.Event()
        with patch.object(server, "connect") as connect, \
             patch.object(server, "run_douyin_login_job", side_effect=lambda *_: launched.set()) as login_job:
            status, _, _ = self.request("/api/douyin/login/start", cookie=cookie)
            self.assertEqual(status, 202)
            self.assertTrue(launched.wait(1))
            login_job.assert_called_once()
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
