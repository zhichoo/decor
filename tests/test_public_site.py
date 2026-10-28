"""Read-only export/privacy and static-browser regressions; no real model or API calls."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("decor_public_export", ROOT / "scripts/export_public.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def fixture():
    sources = [{"id": "s1", "platform": "抖音", "name": "示例博主", "status": "active",
                "profile_url": "https://www.douyin.com/user/test?private=secret", "created_at": 1,
                "notes": "private-source-note", "ADMIN_PASSWORD": "private-password"}]
    videos = [{"id": f"v{index:03d}", "source_id": "s1", "platform": "抖音", "creator": "示例博主",
               "title": f"装修预算视频 {index}", "source_url": f"https://www.douyin.com/video/{10000+index}?secret=private",
               "transcript_text": "控制装修预算，材料施工前明确合同范围。" * 10, "status": "claims_extracted",
               "published_at": f"2026-10-{28-index%20:02d} 12:00:00", "created_at": 1000-index,
               "updated_at": 1000, "ad_review_override": {"decision": "not_ad", "private": "private-review"},
               "transcript_job": {"task_id": "private-task"}, "last_error": None, "deleted_at": None}
              for index in range(65)]
    claims = [{"id": f"c{index:03d}", "video_id": f"v{index:03d}", "object_name": f"预算规划 {index}",
               "stance": "明确推荐", "process_stage": "准备阶段", "space_tags": ["全屋"], "topic_tags": ["预算"],
               "original_conclusion": f"提前明确施工与材料范围 {index}", "original_reasons": ["避免追加费用"],
               "conditions": "未提及", "alternatives": [], "price_info": "未提及", "created_at": 1000-index,
               "extraction_run_id": "private-run", "deleted_by": "private-admin", "deleted_at": None}
              for index in range(65)]
    return sources, videos, claims


class PublicExportTests(unittest.TestCase):
    def test_allowlist_omits_private_fields_deleted_records_and_url_secrets(self):
        sources, videos, claims = fixture()
        videos[-1]["deleted_at"] = 2000
        claims[-2]["deleted_at"] = 2000
        videos[0]["last_error"] = "private-api-error-with-key"
        snapshot = exporter.make_snapshot(sources, videos, claims, "2026-10-28T07:00:00+00:00")
        text = json.dumps(snapshot)
        for secret in ("private-password", "private-source-note", "private-review", "private-task",
                       "private-run", "private-admin", "private-api-error-with-key", "secret=", "private=", "v064", "c063"):
            self.assertNotIn(secret, text)
        self.assertEqual(snapshot["stats"]["video_count"], 64)
        self.assertEqual(snapshot["stats"]["claim_count"], 63)
        self.assertEqual(snapshot["sources"][0]["claim_count"], 63)
        self.assertEqual(snapshot["knowledge_facets"]["total"], 63)
        self.assertEqual(snapshot["progress_counts"]["全部"], 64)

    def test_artifact_contains_no_login_edit_delete_or_management_forms(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            snapshot = exporter.make_snapshot(*fixture())
            first = exporter.build_site(snapshot, output)
            document = (output / "index.html").read_text()
            for text in ('id="admin-panel"', 'id="admin-login-modal"', 'id="video-delete-dialog"',
                         'id="promotion-form"', 'id="transcript-edit-form"', "data-admin-required", "data-admin-only",
                         'id="fetch-transcript"', 'id="edit-transcript"', 'id="detail-extract-video"'):
                self.assertNotIn(text, document)
            self.assertIn("公开预览 · 仅供浏览", document)
            self.assertIn("data-snapshot=", document)
            second = exporter.build_site(snapshot, output)
            self.assertEqual(first["version"], second["version"])
            self.assertEqual(len(list((output / "data").glob("*.json"))), 1)
            headers = (output / "_headers").read_text()
            self.assertIn("connect-src 'self'", headers)
            self.assertIn("form-action 'none'", headers)
            with self.assertRaises(RuntimeError):
                exporter.build_site(snapshot, Path(directory))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class PublicSiteBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.directory = tempfile.TemporaryDirectory(prefix="decor-public-ui-")
        cls.output = Path(cls.directory.name) / "site"
        exporter.build_site(exporter.make_snapshot(*fixture()), cls.output)
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(cls.output)))
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        cls.directory.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 950})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.requests = []
        self.api_requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.requests.append(request.url))
        self.page.route("**/api/**", lambda route: (self.api_requests.append(route.request.url), route.abort()))
        self.page.goto(f"http://127.0.0.1:{self.http.server_port}/?api=https://untrusted.invalid#knowledge", wait_until="networkidle")
        self.page.wait_for_function("apiLoadState.status === 'ready' && knowledgePageState.total === 65")

    def test_search_filter_pagination_details_and_no_write_controls_or_api_requests(self):
        self.assertEqual(self.page.locator("#admin-panel, #admin-login-modal, #video-delete-dialog").count(), 0)
        self.assertFalse(self.page.evaluate("adminSession.authenticated"))
        self.page.locator("#knowledge-query").fill("追加费用")
        self.page.wait_for_timeout(350)
        self.assertEqual(self.page.evaluate("knowledgePageState.total"), 65)
        self.page.locator("#knowledge-query").fill("范围 64")
        self.page.wait_for_function("knowledgePageState.total === 1")
        self.page.locator("#knowledge-query").fill("")
        self.page.wait_for_function("knowledgePageState.total === 65")
        self.page.evaluate("loadKnowledgePage({append: true})")
        self.page.wait_for_function("knowledgeClaims.length === 65")
        self.page.locator('[data-view="sources"]').click()
        self.assertEqual(self.page.locator('[data-source-filter-id="s1"]').count(), 1)
        self.page.locator('[data-source-filter-id="s1"]').click()
        self.page.wait_for_function("videoPageState.total === 65")
        self.page.evaluate("loadVideoPage({append:true})")
        self.assertGreater(self.page.evaluate("videos.length"), 30)
        self.page.evaluate("selectedVideoId='v064'; setView('detail'); loadVideoDetail('v064').then(renderDetail)")
        self.page.wait_for_function("findDetailVideo('v064')?.detailLoaded")
        self.assertIn("装修预算视频 64", self.page.locator("#detail-heading").inner_text())
        self.assertIn("控制装修预算", self.page.locator("#transcript-text").inner_text())
        self.assertEqual(self.page.locator("#promotion-form, #transcript-editor, #detail-extract-video").count(), 0)
        self.assertEqual(self.page.locator('[data-delete-video-id], [data-delete-claim-id], [data-progress-retry-video-id], [data-update-source-id]').count(), 0)
        self.assertTrue(self.page.evaluate("postJson('/api/videos',{}).then(()=>false,()=>true)"))
        self.assertTrue(self.page.evaluate("deleteJson('/api/videos/v000').then(()=>false,()=>true)"))
        self.assertTrue(self.page.evaluate("fetchApiJson('/admin/deleted').then(()=>false,()=>true)"))
        self.assertEqual(self.api_requests, [])
        self.assertTrue(all(url.startswith(f"http://127.0.0.1:{self.http.server_port}/") for url in self.requests))
        self.assertFalse(self.errors, self.errors)

    def test_mobile_public_views_do_not_offer_management_and_private_bookmarks_fall_back(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        for view in ("overview", "sources", "videos", "knowledge", "progress"):
            self.page.evaluate("view=>setView(view)", view)
            self.assertEqual(self.page.evaluate("activeView"), view)
            self.assertEqual(self.page.locator('[data-admin-required], [data-admin-only], #admin-panel').count(), 0)
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 391)
        for view in ("settings", "deleted"):
            self.page.evaluate("view=>setView(view)", view)
            self.assertEqual(self.page.evaluate("activeView"), "overview")
        self.assertEqual(self.api_requests, [])
        self.assertFalse(self.errors, self.errors)


if __name__ == "__main__":
    unittest.main()
