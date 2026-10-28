"""Mock-only browser regressions; never connect to the real API or delete real videos.

Run: .venv/bin/python -m unittest discover -s tests -p test_video_list_ui.py -v
Requires Playwright and Google Chrome.
"""
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
from urllib.parse import parse_qs, urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class VideoListUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT / "web"))
        )
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True, channel="chrome")
        except Exception:
            cls.playwright.stop()
            cls.http.shutdown()
            cls.http.server_close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def setUp(self):
        self.rows = [
            {
                "id": f"v{i:03d}", "title": f"Renovation video {i}",
                "creator": "Creator A" if i < 120 else "Creator B",
                "source_id": "source-a" if i < 120 else "source-b",
                "platform": "douyin", "source_url": f"https://example.com/video/{i}",
                "status": "claims_extracted", "claim_count": 2,
                "has_transcript": True, "transcript_length": 300,
                "created_at": 10000 - i,
            }
            for i in range(180)
        ]
        self.removed = set()
        self.video_requests = []
        self.fail_next_video_request = False
        self.errors = []
        self.login_requests = 0
        self.login_status = {"status": "logged_in", "logged_in": True, "running": False}
        self.authenticated = True
        self.read_only = False
        self.private_view_requests = []
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 950})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        # Keep pagination explicit so tests can assert exact loaded ranges.
        self.page.add_init_script(
            "window.IntersectionObserver = class { observe() {} disconnect() {} };"
        )
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route("**/api/**", self.route_api)
        self.page.goto(f"http://127.0.0.1:{self.http.server_port}/#videos", wait_until="networkidle")
        self.page.locator("#video-grid .video-card").first.wait_for()

    def test_dialog_outside_click_dismisses_without_confirming(self):
        for viewport in ({"width": 1440, "height": 950}, {"width": 390, "height": 844}):
            self.page.set_viewport_size(viewport)
            for selector in ("#video-claims-dialog", "#video-delete-dialog"):
                with self.subTest(viewport=viewport, dialog=selector):
                    dialog = self.page.locator(selector)
                    dialog.evaluate("el => el.showModal()")
                    box = dialog.bounding_box()
                    inside = (box["x"] + 15, box["y"] + 15)
                    self.page.mouse.click(*inside)
                    self.assertTrue(dialog.evaluate("el => el.open"))
                    self.page.mouse.move(*inside)
                    self.page.mouse.down()
                    self.page.mouse.move(2, 2)
                    self.page.mouse.up()
                    self.assertTrue(dialog.evaluate("el => el.open"))
                    self.page.mouse.click(2, 2)
                    self.assertFalse(dialog.evaluate("el => el.open"))
                    self.assertEqual(dialog.evaluate("el => el.returnValue"), "cancel")
        self.assertEqual(self.removed, set())
        self.assertFalse(self.errors)

    def test_long_detail_title_does_not_squeeze_original_video_button(self):
        self.page.evaluate("setView('detail')")
        self.page.locator("#detail-view").wait_for(state="visible")
        for width in (1440, 1024, 768, 390):
            self.page.set_viewport_size({"width": width, "height": 950})
            sizes = []
            for title in ("Short title", "LongRenovationVideoTitle" * 30, "装修视频超长标题" * 50):
                self.page.locator("#detail-heading").evaluate("(el, title) => el.textContent = title", title)
                layout = self.page.locator("#detail-link").evaluate("""el => {
                    const button = el.getBoundingClientRect();
                    const text = el.querySelector('span:last-child').getBoundingClientRect();
                    const heading = document.querySelector('#detail-heading').getBoundingClientRect();
                    return {
                        width: button.width, height: button.height,
                        textInside: text.left >= button.left && text.right <= button.right,
                        fitsViewport: button.right <= innerWidth && heading.right <= innerWidth,
                    };
                }""")
                self.assertTrue(layout["textInside"], (width, layout))
                self.assertTrue(layout["fitsViewport"], (width, layout))
                sizes.append((round(layout["width"], 1), round(layout["height"], 1)))
            self.assertEqual(len(set(sizes)), 1, (width, sizes))
        self.assertFalse(self.errors)

    def test_new_source_platform_is_fixed_to_douyin(self):
        self.page.locator('[data-view="sources"]').click()
        self.page.locator('#open-ingest').click()
        platform = self.page.locator('#ingest-form [name="batch_platform"]')
        self.assertEqual(platform.input_value(), "抖音")
        self.assertTrue(platform.evaluate("el => el.readOnly"))
        self.assertEqual(self.page.locator('#ingest-form select').count(), 0)

        created = []

        def create_source(route):
            created.append(route.request.post_data_json)
            route.fulfill(content_type="application/json", body='{"id":"new-source"}')

        self.page.route("**/api/sources", create_source)
        self.page.route(
            "**/api/sources/new-source/update",
            lambda route: route.fulfill(content_type="application/json", body='{"videos":[]}'),
        )
        self.page.evaluate("""() => batchCollectVideos({
            batch_profile_url: 'https://www.douyin.com/user/new-source',
            batch_platform: '小红书', batch_limit: '5'
        })""")
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["platform"], "抖音")
        self.assertEqual(platform.input_value(), "抖音")
        self.assertFalse(self.errors, self.errors)

    def test_sources_auto_check_login_without_false_logged_out_label(self):
        initial = self.page.evaluate("""() => {
            sources.forEach(source => { source.platform = '抖音'; });
            setView('sources');
            refreshDouyinLoginStatus();
            return document.querySelector('.source-group-summary .status').textContent;
        }""")
        self.assertEqual(initial, '登录检测中')
        self.page.wait_for_function("!douyinLoginChecking")
        self.assertEqual(self.login_requests, 1)
        badge = self.page.locator('.source-group-summary .status')
        self.assertEqual(badge.inner_text(), '登录态已保存')

        self.login_status = {"status": "unknown", "logged_in": False, "running": False}
        self.page.locator('#check-douyin-login').click()
        self.page.wait_for_function("!douyinLoginChecking")
        self.assertEqual(badge.inner_text(), '登录态待确认')

        self.login_status = {"status": "missing", "logged_in": False, "running": False}
        self.page.locator('#check-douyin-login').click()
        self.page.wait_for_function("!douyinLoginChecking")
        self.assertEqual(badge.inner_text(), '抖音未登录')
        self.assertFalse(self.errors)

    def active_rows(self):
        return [row for row in self.rows if row["id"] not in self.removed]

    def facets(self):
        counts = Counter(row["creator"] for row in self.active_rows())
        return {
            "total": len(self.active_rows()),
            "platforms": [{"platform": "douyin", "video_count": len(self.active_rows())}],
            "creators": [
                {"platform": "douyin", "creator": creator, "video_count": count}
                for creator, count in counts.items()
            ],
        }

    def video_page(self, query):
        rows = self.active_rows()
        for key in ("creator", "platform", "source_id"):
            value = query.get(key, [""])[0]
            if value:
                rows = [row for row in rows if row[key] == value]
        offset = int(query.get("offset", [0])[0])
        limit = min(100, int(query.get("limit", [30])[0]))
        return {
            "videos": rows[offset:offset + limit], "total": len(rows),
            "offset": offset, "limit": limit, "has_more": offset + limit < len(rows),
            "facets": self.facets(),
        }

    def bootstrap(self):
        rows = self.active_rows()
        page = self.video_page({})
        return {
            "health": {"ok": True, "db_available": True},
            "videos": page["videos"], "videos_page": page, "video_facets": self.facets(),
            "sources": [
                {
                    "id": source, "name": name, "platform": "douyin", "status": "active",
                    "priority": "P1", "profile_url": "https://example.com/user/" + source,
                    "video_count": sum(row["source_id"] == source for row in rows),
                    "claim_count": 2 * sum(row["source_id"] == source for row in rows),
                    "pending_count": 0,
                }
                for source, name in (("source-a", "Creator A"), ("source-b", "Creator B"))
            ],
            "stats": {
                "source_count": 2, "video_count": len(rows),
                "transcript_count": len(rows), "claim_count": 2 * len(rows),
            },
            "knowledge": {"claims": [], "facets": self.knowledge_facets()},
        }

    def knowledge_facets(self):
        return {"total": 2 * len(self.active_rows()), "stages": {}, "tags": {}, "stances": {}}

    def route_api(self, route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        if request.method == "DELETE" and path.startswith("/api/videos/"):
            self.removed.add(path.rsplit("/", 1)[-1])
            payload = {"status": "deleted", "claims_deleted": True}
        elif request.method == "POST" and path in ("/api/admin/login", "/api/admin/logout"):
            self.authenticated = path.endswith("/login")
            payload = {"authenticated": self.authenticated, "configured": True}
        elif request.method != "GET":
            route.abort()
            return
        elif path == "/api/bootstrap":
            payload = self.bootstrap()
        elif path == "/api/videos":
            query = parse_qs(parsed.query)
            self.video_requests.append(query)
            if self.fail_next_video_request:
                self.fail_next_video_request = False
                route.fulfill(status=503, content_type="application/json", body='{"error":"test failure"}')
                return
            payload = self.video_page(query)
        elif path == "/api/admin/session":
            payload = {"authenticated": self.authenticated and not self.read_only,
                       "configured": True, "read_only": self.read_only}
        elif path in ("/api/admin/deleted", "/api/settings/transcription"):
            self.private_view_requests.append(path)
            payload = {}
        elif path == "/api/douyin/login-status":
            self.login_requests += 1
            payload = self.login_status
        elif path == "/api/knowledge":
            payload = {"claims": [], "total": 0, "facets": self.knowledge_facets()}
        elif path == "/api/progress-summary":
            payload = {"counts": {}}
        elif path == "/api/progress-videos":
            payload = {"videos": [], "total": 0, "has_more": False}
        else:
            payload = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    def delete_at(self, index):
        button = self.page.locator("#video-grid [data-delete-video-id]").nth(index)
        video_id = button.get_attribute("data-delete-video-id")
        button.click()
        before = self.page.evaluate("scrollY")
        self.page.locator(".video-delete-confirm").click()
        self.page.wait_for_function("id => !deletingVideoIds.has(id)", arg=video_id)
        self.assertLess(abs(self.page.evaluate("scrollY") - before), 2)
        self.assertFalse(self.errors, self.errors)
        return video_id

    def test_delete_preserves_large_range_and_pagination_without_gaps(self):
        self.page.evaluate("async () => { for (let i=0; i<4; i++) await loadVideoPage({append:true}); }")
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 150)
        video_id = self.delete_at(100)
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 149)
        self.assertEqual(self.page.evaluate("videoPageState.offset"), 149)
        self.page.evaluate("loadVideoPage({append:true})")
        actual = self.page.locator("#video-grid [data-delete-video-id]").evaluate_all(
            "els => els.map(el => el.dataset.deleteVideoId)"
        )
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual(set(actual), {row["id"] for row in self.rows} - {video_id})

    def test_repeated_filtered_deletions_refresh_all_counts_and_navigation(self):
        self.page.evaluate('async () => {activeVideoCreator="Creator A";await loadVideoPage();await loadVideoPage({append:true});}')
        self.delete_at(40)
        self.delete_at(40)
        self.assertEqual(self.page.locator("#pipeline .pipeline-card strong").all_text_contents(), ["2", "178", "178", "356"])
        self.assertEqual(self.page.evaluate("videoPageState.total"), 118)
        self.assertEqual(self.page.locator('[data-video-creator="Creator A"]').get_attribute("data-video-count"), "118")
        self.assertEqual(self.page.locator('[data-video-creator="Creator B"]').get_attribute("data-video-count"), "60")
        loaded = self.page.locator("#video-grid .video-card").count()
        self.page.locator('[data-view="sources"]').click()
        self.assertIn("178", self.page.locator("#source-summary").inner_text())
        self.assertIn("118", self.page.locator('[data-source-filter-id="source-a"]').inner_text())
        self.page.locator('[data-view="videos"]').click()
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), loaded)
        self.assertEqual(self.page.evaluate("activeVideoCreator"), "Creator A")

    def test_failed_refresh_retains_cards_and_can_retry(self):
        self.page.evaluate("async () => {await loadVideoPage({append:true});await loadVideoPage({append:true});}")
        self.fail_next_video_request = True
        self.delete_at(40)
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 89)
        self.assertEqual(self.page.evaluate("videoPageState.offset"), 89)
        self.assertEqual(self.page.locator("#pipeline .pipeline-card strong").nth(1).inner_text(), "179")
        self.page.locator("#retry-video-page").click()
        self.page.wait_for_function("!videoPageState.loading")
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 89)
        self.assertEqual(self.page.locator("#retry-video-page").count(), 0)
        self.page.evaluate("loadVideoPage({append:true})")
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 119)

    def test_append_cannot_interrupt_a_preserved_refresh(self):
        self.page.evaluate("async () => {for (let i=0;i<4;i++) await loadVideoPage({append:true});}")
        before = len(self.video_requests)
        self.page.evaluate("async () => {const refresh=loadVideoPage({preserveLoaded:true});await loadVideoPage({append:true});await refresh;}")
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 150)
        self.assertEqual(self.page.evaluate("videoPageState.offset"), 150)
        # The two refresh chunks are not superseded by an append request.
        requests = self.video_requests[before:]
        self.assertEqual([int(query["offset"][0]) for query in requests], [0, 100])
        self.assertEqual([int(query["limit"][0]) for query in requests], [100, 50])

    def test_stale_metadata_response_cannot_restore_an_old_count(self):
        result = self.page.evaluate("""async () => {
          const original=fetchApiJson;
          const pending=[];
          fetchApiJson=() => new Promise(resolve => pending.push(resolve));
          try {
            const oldRequest=refreshLibraryMetadata();
            const newRequest=refreshLibraryMetadata();
            pending[1]({stats:{video_count:178}});
            await newRequest;
            pending[0]({stats:{video_count:179}});
            await oldRequest;
            return apiStats.videoCount;
          } finally { fetchApiJson=original; }
        }""")
        self.assertEqual(result, 178)

    def test_partial_creator_list_is_repaired_instead_of_marked_complete(self):
        self.rows = [row for row in self.rows if row["creator"] != "Creator A" or int(row["id"][1:]) < 17]
        self.page.locator('[data-video-creator="Creator A"]').click()
        self.page.wait_for_function("!videoPageState.loading")
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 17)
        self.page.evaluate("() => {videos=videos.slice(0,8);renderVideos();}")
        self.page.wait_for_function("!videoPageState.loading && videos.length===17")
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 17)
        footer = self.page.locator("#video-grid > .video-filter-notice").last.inner_text()
        self.assertIn("17 / 17", footer)
        self.assertNotIn("8 / 17", footer)

    def test_bootstrap_refresh_cannot_replace_a_filtered_loaded_range(self):
        self.page.evaluate('async () => {activeVideoCreator="Creator A";await loadVideoPage();await loadVideoPage({append:true});}')
        self.page.evaluate("loadApiData()")
        self.assertEqual(self.page.evaluate("activeVideoCreator"), "Creator A")
        self.assertEqual(self.page.locator("#video-grid .video-card").count(), 60)
        self.assertEqual(self.page.evaluate("videoPageState.total"), 120)
        self.assertEqual(self.page.evaluate("videoPageState.offset"), 60)
        self.assertTrue(self.page.evaluate("videoPageState.hasMore"))

    def test_source_updates_keep_deleted_video_reasons_visible(self):
        message = (
            "采集完成：新增 0 条，重复 0 条。跳过已删除视频 1 条（此前已删除，不自动恢复）。\n"
            "《测试视频》：此前已删除，本次更新跳过，不自动恢复。原删除原因：推广产品"
        )
        stats = {"received": 1, "saved": 0, "created": 0, "duplicate": 0, "skipped_deleted": 1}
        for all_sources in (False, True):
            with self.subTest(all_sources=all_sources):
                path = "update-all" if all_sources else "source-a/update"
                result = {"status": "completed", "message": message, "stats": stats, "videos": []}
                if all_sources:
                    result.update({
                        "summary": {"total": 1, "completed": 1, "failed": 0, "skipped": 0},
                        "sources": [{"name": "Creator A", "status": "completed", "stats": stats}],
                    })
                self.page.route(
                    "**/api/sources/" + path,
                    lambda route: route.fulfill(status=201, content_type="application/json", body=json.dumps(result)),
                )
                self.page.evaluate("updateAllSources()" if all_sources else "updateSource('source-a')")
                notice = self.page.locator("#source-message")
                self.assertTrue(notice.is_visible())
                self.assertEqual(notice.inner_text(), message)
                self.assertEqual(notice.evaluate("el => getComputedStyle(el).whiteSpace"), "pre-line")
        self.assertFalse(self.errors, self.errors)

    def test_visitors_hide_management_controls_without_hiding_public_content(self):
        self.authenticated = False
        self.page.reload(wait_until="networkidle")
        self.page.locator('[data-view="sources"]').click()
        for selector in (
            '#open-ingest', '#update-all-sources', '[data-update-source-id]',
            '[data-view="deleted"]', '[data-view="settings"]', '.source-card footer',
        ):
            for element in self.page.locator(selector).all():
                self.assertFalse(element.is_visible(), selector)
        self.assertTrue(self.page.locator('[data-source-filter-id="source-a"]').is_visible())
        self.assertTrue(self.page.locator('#admin-login-button').is_visible())
        self.page.locator('[data-view="videos"]').click()
        self.assertGreater(self.page.locator('#video-grid .video-card').count(), 0)
        self.assertEqual(self.page.locator('[data-delete-video-id]').count(), 0)
        self.page.locator('[data-view="progress"]').click()
        self.assertFalse(self.page.locator('#progress-process-pending').is_visible())
        self.assertFalse(self.errors, self.errors)

    def test_login_restores_controls_and_logout_closes_admin_ui(self):
        self.authenticated = False
        self.page.reload(wait_until="networkidle")
        self.page.locator('[data-view="sources"]').click()
        self.page.evaluate("submitAdminLogin('mock-password')")
        for selector in ('#open-ingest', '#update-all-sources', '[data-view="deleted"]', '[data-view="settings"]'):
            self.assertTrue(self.page.locator(selector).is_visible(), selector)
        self.assertTrue(self.page.locator('[data-update-source-id]').first.is_enabled())
        self.page.locator('#open-ingest').click()
        self.assertTrue(self.page.locator('#ingest-panel').is_visible())
        self.page.evaluate('logoutAdmin()')
        self.assertFalse(self.page.locator('#ingest-panel').is_visible())
        self.assertFalse(self.page.locator('#open-ingest').is_visible())
        self.page.evaluate("submitAdminLogin('mock-password')")
        self.page.locator('[data-view="settings"]').click()
        self.assertEqual(self.page.evaluate('activeView'), 'settings')
        self.page.evaluate('logoutAdmin()')
        self.assertEqual(self.page.evaluate('activeView'), 'overview')
        self.assertEqual(self.page.evaluate('location.hash'), '#overview')
        self.assertFalse(self.page.locator('[data-view="settings"]').is_visible())
        self.assertFalse(self.errors, self.errors)

    def test_public_read_only_hides_login_and_prevents_login_modal_on_desktop_and_mobile(self):
        self.read_only = True
        self.authenticated = True  # Stale admin state must not survive a read-only session response.
        for viewport in ({"width": 1440, "height": 950}, {"width": 390, "height": 844}):
            self.page.set_viewport_size(viewport)
            self.page.reload(wait_until="networkidle")
            self.assertFalse(self.page.locator("#admin-panel").is_visible())
            self.assertFalse(self.page.locator("#admin-login-button").is_visible())
            self.assertFalse(self.page.locator('[data-view="settings"]').is_visible())
            self.assertFalse(self.page.locator('[data-view="deleted"]').is_visible())
            self.page.evaluate("openAdminLoginModal()")
            self.assertFalse(self.page.locator("#admin-login-modal").is_visible())
            self.assertFalse(self.page.evaluate("submitAdminLogin('mock-password')"))
            self.page.locator('[data-view="videos"]').click()
            self.assertGreater(self.page.locator('#video-grid .video-card').count(), 0)
            self.page.locator('[data-view="sources"]').click()
            self.assertFalse(self.page.locator('#open-ingest').is_visible())
        self.assertFalse(self.errors, self.errors)

    def test_private_bookmarks_wait_for_session_and_reject_visitors(self):
        for view in ('deleted', 'settings'):
            for authenticated in (False, True):
                with self.subTest(view=view, authenticated=authenticated):
                    self.authenticated = authenticated
                    self.private_view_requests.clear()
                    self.page.goto(
                        f'http://127.0.0.1:{self.http.server_port}/?bookmark={view}&auth={authenticated}#{view}',
                        wait_until='networkidle',
                    )
                    self.assertEqual(self.page.evaluate('activeView'), view if authenticated else 'overview')
                    if not authenticated:
                        self.assertEqual(self.page.evaluate('location.hash'), '#overview')
                        self.assertEqual(self.private_view_requests, [])
        self.assertFalse(self.errors, self.errors)


if __name__ == "__main__":
    unittest.main()
