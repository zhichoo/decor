"""Mock-only browser regressions; never connect to the real API or delete real videos.

Run: .venv/bin/python -m unittest discover -s tests -p test_video_list_ui.py -v
Requires Playwright and Google Chrome.
"""
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer as _ThreadingHTTPServer

import json
from pathlib import Path
import threading
import unittest
from urllib.parse import parse_qs, urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class ThreadingHTTPServer(_ThreadingHTTPServer):
    # The default listen backlog (5) overflows when a page reload opens many connections;
    # on macOS the extra ones are reset and a stylesheet randomly fails to load.
    request_queue_size = 128


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
        self.resource_errors = []
        self.script_responses = []
        self.login_requests = 0
        self.login_status = {"status": "logged_in", "logged_in": True, "running": False}
        self.authenticated = True
        self.read_only = False
        self.private_view_requests = []
        self.performance_requests = 0
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 950})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        # Keep pagination explicit so tests can assert exact loaded ranges.
        self.page.add_init_script(
            "window.IntersectionObserver = class { observe() {} disconnect() {} };"
        )
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", lambda message: self.resource_errors.append(message.text) if message.type == "error" else None)
        self.page.on("requestfailed", lambda request: self.resource_errors.append(f"{urlparse(request.url).path}: {request.failure}"))
        self.page.on("response", lambda response: self.script_responses.append({"status": response.status,
            "headers": response.headers}) if urlparse(response.url).path == "/app.js" else None)
        self.page.route("**/api/**", self.route_api)
        self.page.goto(f"http://127.0.0.1:{self.http.server_port}/#videos", wait_until="networkidle")
        try:
            self.page.locator("#video-grid .video-card").first.wait_for()
        except Exception as error:
            diagnostics = self.page.evaluate("""() => ({
                url: location.href, active: document.querySelector('.view.active')?.id,
                cards: document.querySelectorAll('#video-grid .video-card').length,
                scripts: [...document.scripts].map(script => script.src),
                body: document.body.innerText.slice(-1500),
            })""")
            raise AssertionError({"page_errors": self.errors, "resource_errors": self.resource_errors,
                                  "script_responses": self.script_responses, "initialization": diagnostics}) from error

    def test_already_attempted_extraction_is_a_skip_not_a_frontend_error(self):
        self.page.route("**/api/queue/extract-next", lambda route: route.fulfill(
            status=202, content_type="application/json", body=json.dumps({
                "status": "skipped_existing_extraction", "claims": [], "video": self.rows[0],
                "message": "这份文案已尝试提取，不再自动重试",
            }, ensure_ascii=False)))
        result = self.page.evaluate("async () => (await extractNextQueuedVideo()).status")
        self.assertEqual(result, "skipped_existing_extraction")
        self.assertIn("不再自动重试", self.page.locator("#queue-message").inner_text())
        text = self.page.evaluate("getQueueResultText({job_id:'test',processed:[{stage:'skipped_existing_extraction'}]})")
        self.assertIn("跳过自动重试", text)
        self.assertEqual(self.errors, [])

    def test_detail_delete_returns_to_video_list_and_does_not_display_another_video(self):
        self.page.route("**/api/videos/v020", lambda route: route.fallback() if route.request.method != "GET"
            else route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "video": {**self.rows[20], "transcript_text": "完整测试文案"}, "claims": []})))
        button = self.page.locator('#video-grid [data-video-id="v020"]').first
        button.scroll_into_view_if_needed()
        position = self.page.evaluate("scrollY")
        button.click()
        self.page.wait_for_function("activeView === 'detail' && !detailLoadingId")
        self.page.locator('[data-detail-delete-video]').click()
        self.page.locator('.video-delete-confirm').click()
        self.page.wait_for_function("!deletingVideoIds.has('v020') && activeView === 'videos'")
        self.assertEqual(self.removed, {"v020"})
        self.assertEqual(self.page.evaluate("location.hash"), "#videos")
        self.assertIsNone(self.page.evaluate("history.state.videoId"))
        self.assertEqual(self.page.locator('#video-grid [data-video-id="v020"]').count(), 0)
        self.assertLess(abs(self.page.evaluate("scrollY") - position), 3)
        self.assertEqual(self.errors, [])

    def test_claim_delete_preserves_scroll_and_loaded_knowledge_range(self):
        claims = [{
            "id": f"card-{index:03d}", "video_id": f"v{index:03d}", "object_name": f"知识观点 {index}",
            "original_conclusion": f"保留当前位置的装修判断 {index}", "author_stance": "中性陈述",
            "content_type": "施工做法", "process_stage": "准备阶段", "space_tags": ["全屋"],
            "topic_tags": ["预算"], "source_quotes": [], "original_reasons": [],
            "conditions": "未提及", "alternatives": [], "price_info": "未提及",
        } for index in range(75)]
        deleted = set()
        offsets = []

        def knowledge_api(route):
            parsed = urlparse(route.request.url)
            offset = int(parse_qs(parsed.query).get("offset", [0])[0])
            offsets.append(offset)
            active = [claim for claim in claims if claim["id"] not in deleted]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "claims": active[offset:offset + 50], "total": len(active), "offset": offset,
                "limit": 50, "has_more": offset + 50 < len(active),
                "facets": {"total": len(active), "stages": {"准备阶段": len(active)},
                           "tags": {"预算": len(active)}, "stances": {}, "author_stances": {},
                           "content_types": {"施工做法": len(active)}},
            }, ensure_ascii=False))

        def claim_api(route):
            claim_id = urlparse(route.request.url).path.rsplit("/", 1)[-1]
            deleted.add(claim_id)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "status": "deleted", "claim_id": claim_id,
                "video_id": next(claim["video_id"] for claim in claims if claim["id"] == claim_id),
            }))

        self.page.route("**/api/knowledge?**", knowledge_api)
        self.page.route("**/api/claims/**", claim_api)
        self.page.evaluate("""({claims}) => {
            knowledgeClaims=claims.slice(0, 50).map(normalizeKnowledgeClaim);
            knowledgePageState={total:75,limit:50,offset:50,hasMore:true,loading:false,error:''};
            setView('knowledge');
        }""", {"claims": claims})
        self.page.evaluate("loadKnowledgePage({append:true})")
        self.page.wait_for_function("knowledgeClaims.length === 75 && !knowledgePageState.loading")
        button = self.page.locator('[data-delete-claim-id="card-060"]')
        button.scroll_into_view_if_needed()
        position = self.page.evaluate("scrollY")
        self.page.evaluate("window.confirm = () => true")
        button.click()
        self.page.wait_for_function("knowledgeClaims.length === 74 && !knowledgePageState.loading")
        self.assertEqual(self.page.evaluate("scrollY"), position)
        self.assertEqual(self.page.locator("#knowledge-results .claim-card").count(), 74)
        self.assertEqual(self.page.locator('[data-claim-id="card-060"]').count(), 0)
        self.assertEqual(offsets[-2:], [0, 50])
        self.assertEqual(self.errors, [])

    def test_claim_delete_from_detail_preserves_loaded_list_and_scroll(self):
        claims = [{
            "id": f"detail-card-{index:03d}", "video_id": "v000",
            "object_name": f"详情观点 {index}",
            "original_conclusion": f"删除后不跳回页面顶部 {index}", "author_stance": "中性陈述",
            "content_type": "施工做法", "process_stage": "准备阶段", "space_tags": ["全屋"],
            "topic_tags": ["预算"], "source_quotes": [], "original_reasons": [],
            "conditions": "未提及", "alternatives": [], "price_info": "未提及",
        } for index in range(75)]
        deleted = set()

        def knowledge_api(route):
            parsed = urlparse(route.request.url)
            offset = int(parse_qs(parsed.query).get("offset", [0])[0])
            active = [claim for claim in claims if claim["id"] not in deleted]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "claims": active[offset:offset + 50], "total": len(active), "offset": offset,
                "limit": 50, "has_more": offset + 50 < len(active),
                "facets": {"total": len(active), "stages": {"准备阶段": len(active)},
                           "tags": {"预算": len(active)}, "stances": {}, "author_stances": {},
                           "content_types": {"施工做法": len(active)}},
            }, ensure_ascii=False))

        def claim_api(route):
            if route.request.method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "video": self.rows[0], "claims": [claim for claim in claims if claim["id"] not in deleted],
                }, ensure_ascii=False))
                return
            claim_id = urlparse(route.request.url).path.rsplit("/", 1)[-1]
            deleted.add(claim_id)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "status": "deleted", "claim_id": claim_id, "video_id": "v000",
            }))

        self.page.route("**/api/knowledge?**", knowledge_api)
        self.page.route("**/api/claims/**", claim_api)
        self.page.route("**/api/videos/v000", claim_api)
        self.page.evaluate("""({claims}) => {
            knowledgeClaims=claims.map(normalizeKnowledgeClaim);
            knowledgePageState={total:75,limit:50,offset:75,hasMore:false,loading:false,error:''};
            selectedVideoId='v000';
            detailedVideos.set('v000', normalizeApiVideo({id:'v000', title:'详情删除测试',
                creator:'Creator A', platform:'douyin', status:'claims_extracted', claim_count:claims.length,
                claims:claims, has_transcript:true, transcript_text:'详情文案'}));
            setView('detail');
        }""", {"claims": claims})
        button = self.page.locator('[data-delete-claim-id="detail-card-060"]')
        button.scroll_into_view_if_needed()
        position = self.page.evaluate("scrollY")
        self.page.evaluate("window.confirm = () => true")
        button.click()
        self.page.wait_for_function("detailedVideos.get('v000')?.claims.length === 74 && !knowledgePageState.loading")
        self.assertEqual(self.page.evaluate("scrollY"), position)
        self.assertEqual(self.page.locator("#video-claims .claim-card").count(), 74)
        self.assertEqual(self.page.locator('[data-claim-id="detail-card-060"]').count(), 0)
        self.assertEqual(self.page.evaluate("knowledgeClaims.length"), 74)
        self.assertEqual(self.errors, [])

    def test_retained_card_source_is_read_only_and_returns_to_knowledge(self):
        self.page.route("**/api/videos/trashed-source", lambda route: route.fulfill(status=404,
            content_type="application/json", body='{"error":"video not found"}'))
        self.page.route("**/api/knowledge/sources/trashed-source", lambda route: route.fulfill(status=200,
            content_type="application/json", body=json.dumps({"video": {
                "id": "trashed-source", "title": "保留卡片来源", "transcript_text": "回收站来源的保存文案",
                "source_url": "https://example.com/video/retained", "source_read_only": True}, "claims": []})))
        self.page.evaluate("""() => {
            knowledgeClaims=[{id:'retained-card',videoId:'trashed-source',object:'材料',conclusion:'核对材料范围',
                sourceQuotes:[],authorStance:'中性陈述',tags:[]}];setView('knowledge');
        }""")
        self.page.locator('#knowledge-results [data-video-id="trashed-source"]').click()
        self.page.wait_for_function("!detailLoadingId && retainedSourceDetails.size === 1")
        self.assertEqual(self.page.locator('#detail-heading').inner_text(), "保留卡片来源")
        self.assertIn("保存文案", self.page.locator('#transcript-text').inner_text())
        self.assertEqual(self.page.locator('#detail-view [data-admin-required]:visible').count(), 0)
        self.assertEqual(self.page.locator('[data-detail-delete-video]').count(), 0)
        self.assertTrue(self.page.locator('#promotion-editor').is_hidden())
        self.assertFalse(self.page.evaluate("detailedVideos.has('trashed-source')"))
        self.page.locator('#back-to-videos').click()
        self.page.wait_for_function("activeView === 'knowledge'")
        self.assertEqual(self.errors, [])

    def test_trash_permanent_delete_confirms_cascade_and_clears_both_tabs(self):
        purged = []
        def trash_api(route):
            if route.request.method == "DELETE":
                purged.append(route.request.url)
                self.page.evaluate("knowledgeClaims=[]")
                payload = {"status": "purged", "video_id": "trashed-source", "claims_deleted": 2}
            else:
                payload = {"videos": [] if purged else [{"id": "trashed-source", "title": "回收站测试视频"}],
                           "claims": [] if purged else [{"id": "trashed-card", "video_id": "trashed-source",
                               "video_deleted_at": 123}], "video_total": 0 if purged else 1,
                           "claim_total": 0 if purged else 1}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
        self.page.route("**/api/admin/deleted**", trash_api)
        self.page.evaluate("setView('deleted')")
        self.page.wait_for_function("!deletedItems.loading && deletedItems.videoTotal === 1")
        self.assertEqual(self.page.locator('#page-title').inner_text(), "回收站")
        self.page.locator('[data-purge-video-id]').click()
        self.assertIn("无法恢复", self.page.locator('#video-delete-desc').inner_text())
        self.assertIn("全部关联知识卡", self.page.locator('#video-delete-desc').inner_text())
        self.assertTrue(self.page.locator('.video-delete-option').is_hidden())
        self.page.locator('#video-delete-dialog [value="cancel"]').click()
        self.page.wait_for_function("purgingVideoIds.size === 0")
        self.assertEqual(purged, [])
        self.page.locator('[data-purge-video-id]').click()
        self.page.locator('.video-delete-confirm').click()
        self.page.wait_for_function("purgingVideoIds.size === 0 && deletedItems.videoTotal === 0")
        self.assertEqual(len(purged), 1)
        self.assertEqual(self.page.evaluate("deletedItems.claims.length"), 0)
        self.assertEqual(self.page.evaluate("activeView"), "deleted")
        self.assertEqual(self.errors, [])

    def test_trash_permanent_delete_preserves_loaded_range_and_position(self):
        rows = [{"id": f"gone-{index}", "title": f"回收站视频 {index}"} for index in range(120)]
        offsets = []
        def trash_api(route):
            parsed = urlparse(route.request.url)
            if route.request.method == "DELETE":
                rows[:] = [row for row in rows if row["id"] != parsed.path.rsplit("/", 1)[-1]]
                payload = {"status": "purged"}
            else:
                offset = int(parse_qs(parsed.query).get("offset", [0])[0])
                offsets.append(offset)
                payload = {"videos": rows[offset:offset + 50], "claims": [],
                           "video_total": len(rows), "claim_total": 0}
            route.fulfill(content_type="application/json", body=json.dumps(payload))
        self.page.route("**/api/admin/deleted**", trash_api)
        self.page.evaluate("setView('deleted')")
        self.page.wait_for_function("!deletedItems.loading && deletedItems.videoTotal === 120")
        self.page.locator("[data-load-more-deleted]").click()
        self.page.wait_for_function("!deletedItems.loading && deletedItems.videos.length === 100")
        button = self.page.locator('[data-purge-video-id="gone-90"]')
        button.scroll_into_view_if_needed()
        position = self.page.evaluate("scrollY")
        button.click()
        self.page.locator(".video-delete-confirm").click()
        self.page.wait_for_function("purgingVideoIds.size === 0 && deletedItems.videoTotal === 119")
        self.assertEqual(self.page.locator("#deleted-list .video-card").count(), 100)
        self.assertEqual(self.page.locator('[data-purge-video-id="gone-90"]').count(), 0)
        self.assertEqual(offsets, [0, 50, 0, 50])
        self.assertLess(abs(self.page.evaluate("scrollY") - position), 3)
        self.assertEqual(self.errors, [])

    def test_dialog_outside_click_dismisses_without_confirming(self):
        for viewport in ({"width": 1440, "height": 950}, {"width": 390, "height": 844}):
            self.page.set_viewport_size(viewport)
            for selector in ("#video-claims-dialog", "#video-delete-dialog", "#video-exclusions-dialog"):
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

    def test_switching_mobile_category_groups_reveals_first_selected_option(self):
        self.page.evaluate("setView('knowledge')")
        for width in (390, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 844})
                self.page.locator('[data-knowledge-group="按主题"]').click()
                self.page.wait_for_function("!knowledgePageState.loading")
                self.page.locator('[data-knowledge-category-value="家电"]').click()
                self.page.wait_for_function("!knowledgePageState.loading && activeKnowledgeCategory.value === '家电'")
                self.assertGreater(self.page.locator('#knowledge-stage-list').evaluate('el => el.scrollLeft'), 0)
                self.page.locator('[data-knowledge-group="按内容类型"]').click()
                self.page.wait_for_function("!knowledgePageState.loading && activeKnowledgeCategory.value === '选购建议'")
                geometry = self.page.locator('[data-knowledge-category-value="选购建议"]').evaluate("""el => {
                    const row = el.parentElement.getBoundingClientRect(), box = el.getBoundingClientRect();
                    return {left:box.left, right:box.right, rowLeft:row.left, rowRight:row.right};
                }""")
                self.assertGreaterEqual(geometry['left'], geometry['rowLeft'] - 1)
                self.assertLessEqual(geometry['right'], geometry['rowRight'] + 1)
                self.assertEqual(self.page.locator('[data-knowledge-category-value="选购建议"]').get_attribute('aria-pressed'), 'true')
        self.assertFalse(self.errors, self.errors)

    def prepare_exclusion_card(self):
        self.page.evaluate("""() => {
            videos[0].excludedClaimCount = 8;
            videos[0].adReview = {decision: 'advertising', reason: '关联产品推广'};
            renderVideos();
        }""")

    def test_claim_promotion_notice_hover_click_and_keyboard_across_views(self):
        claims = [{"id": f"promotion-{index}", "video_id": "v000", "object_name": "木纹砖选购",
                   "original_conclusion": "按实际采光选择颜色。", "author_stance": "未明确",
                   "source_video_is_promotional": index == 0} for index in range(2)]
        self.page.route("**/api/videos/v000", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps({"video": self.rows[0], "claims": claims})))
        self.page.evaluate("""({video, claims}) => {
            knowledgeClaims = claims.map(normalizeKnowledgeClaim);
            knowledgePageState = {...knowledgePageState, total: claims.length, hasMore: false};
            const detail = normalizeApiVideo({...video, claims});
            detailedVideos.set(detail.id, detail); selectedVideoId = detail.id;
        }""", {"video": self.rows[0], "claims": claims})
        for width in (1440, 320):
            self.page.set_viewport_size({"width": width, "height": 950})
            for view, selector in (("knowledge", "#knowledge-results"), ("detail", "#video-claims"),
                                   ("dialog", "#video-claims-dialog")):
                with self.subTest(width=width, view=view):
                    if view == "dialog":
                        self.page.evaluate("openVideoClaims('v000')")
                    else:
                        self.page.evaluate("view => setView(view)", view)
                    container = self.page.locator(selector)
                    button = container.locator(".claim-promotion-toggle")
                    button.wait_for(state="visible")
                    self.assertEqual(button.count(), 1)
                    tooltip = container.locator(".claim-promotion-tooltip")
                    self.assertFalse(tooltip.is_visible())
                    button.evaluate("el => el.scrollIntoView({block:'end'})")
                    button.hover()
                    self.assertEqual(tooltip.inner_text(), "来源视频标记为推广")
                    self.assertTrue(tooltip.is_visible())
                    bounds = tooltip.bounding_box()
                    self.assertGreaterEqual(bounds["y"], 0)
                    self.assertLessEqual(bounds["y"] + bounds["height"], 950)
                    self.assertTrue(tooltip.evaluate("""el => {
                        const box = el.getBoundingClientRect();
                        return el.contains(document.elementFromPoint(box.left + 4, box.top + 4));
                    }"""))
                    button.click()
                    container.locator("h3").first.hover()
                    self.assertTrue(tooltip.is_visible())  # Click keeps it open after leaving the icon.
                    self.page.keyboard.press("Escape")
                    self.assertFalse(tooltip.is_visible())
                    self.assertEqual(button.get_attribute("aria-expanded"), "false")
                    button.focus()
                    self.page.keyboard.press("Enter")
                    self.assertTrue(tooltip.is_visible())
                    self.page.keyboard.press("Space")
                    self.assertFalse(tooltip.is_visible())
                    button.click()
                    container.locator("h3").first.click()
                    self.assertFalse(tooltip.is_visible())
                    self.assertEqual(self.page.evaluate("activeView"), "detail" if view == "dialog" else view)
                    self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
                    if view == "dialog":
                        self.assertTrue(container.evaluate("el => el.open"))
                        self.page.keyboard.press("Escape")
        self.assertFalse(self.errors, self.errors)

    def test_deleted_tabs_paginate_and_sources_return_to_same_tab_and_position(self):
        deleted_videos = [{"id": f"gone-{index}", "title": f"已删除视频 {index}", "creator": "博主",
                           "platform": "douyin", "source_url": "https://www.douyin.com/video/test",
                           "deleted_at": 1000, "delete_reason": "推广"} for index in range(55)]
        deleted_claims = [{"id": f"gone-card-{index}", "object_name": f"已删除卡片 {index}",
                           "original_conclusion": "按实际采光选择颜色。", "deleted_at": 1000,
                           "video_id": "gone-0" if index % 2 == 0 else "v001",
                           "video_title": "来源视频", "video_deleted_at": 1000 if index % 2 == 0 else None}
                          for index in range(70)]
        requests = []
        def deleted_api(route):
            parsed = urlparse(route.request.url)
            requests.append(parsed.path)
            if "/videos/" in parsed.path:
                video_id = parsed.path.rsplit("/", 1)[-1]
                payload = {"video": {**deleted_videos[int(video_id.split("-")[-1])],
                                     "transcript_text": "已删除来源的完整文案"}, "claims": []}
            else:
                offset = int(parse_qs(parsed.query).get("offset", [0])[0])
                payload = {"videos": deleted_videos[offset:offset + 50], "claims": deleted_claims[offset:offset + 50],
                           "video_total": 55, "claim_total": 70}
            route.fulfill(content_type="application/json", body=json.dumps(payload, ensure_ascii=False))
        self.page.route("**/api/admin/deleted**", deleted_api)
        self.page.route("**/api/videos/v001", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps({"video": {**self.rows[1],
                        "transcript_text": "正常来源文案"}, "claims": []})))
        for width in (1440, 390, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 950})
                self.page.evaluate("activeDeletedTab='videos';setView('deleted')")
                self.page.wait_for_function("!deletedItems.loading && deletedItems.videoTotal === 55")
                self.assertEqual(self.page.locator("#deleted-list .video-card").count(), 50)
                self.assertEqual(self.page.locator("#deleted-list .claim-card").count(), 0)
                self.assertIn("55", self.page.locator("#deleted-videos-tab").inner_text())
                self.page.locator("#deleted-claims-tab").click()
                self.assertEqual(self.page.locator("#deleted-list .claim-card").count(), 50)
                self.assertEqual(self.page.locator("#deleted-list .video-card").count(), 0)
                self.page.locator("[data-load-more-deleted]").click()
                self.page.wait_for_function("!deletedItems.loading && deletedItems.claims.length === 70")
                for index, deleted in ((60, True), (61, False)):
                    card = self.page.locator(f'[data-deleted-item-id="gone-card-{index}"]')
                    self.assertEqual(card.locator("[data-restore-claim-id]").is_disabled(), deleted)
                    source = card.locator("[data-video-id]")
                    source.scroll_into_view_if_needed()
                    before = self.page.evaluate("scrollY")
                    source.click()
                    self.page.wait_for_function("activeView === 'detail' && !detailLoadingId")
                    self.assertEqual(self.page.locator("#back-to-videos").inner_text().strip(), "返回回收站")
                    self.assertIn("已删除来源的完整文案" if deleted else "正常来源文案",
                                  self.page.locator("#transcript-text").inner_text())
                    self.assertEqual(self.page.locator("#detail-view [data-admin-required]:visible").count() == 0, deleted)
                    self.assertEqual(self.page.locator("[data-detail-delete-video]").count() == 0, deleted)
                    self.assertEqual(self.page.locator("#promotion-editor").is_hidden(), deleted)
                    self.assertEqual(len(self.context.pages), 1)
                    self.page.locator("#back-to-videos").click()
                    self.page.wait_for_function("activeView === 'deleted'")
                    self.assertEqual(self.page.locator("#deleted-claims-tab").get_attribute("aria-selected"), "true")
                    self.assertEqual(self.page.locator("#deleted-list .claim-card").count(), 70)
                    self.assertLess(abs(self.page.evaluate("scrollY") - before), 2)
                self.page.locator("#deleted-videos-tab").click()
                self.assertEqual(self.page.locator("#deleted-list .video-card").count(), 55)
                self.page.locator('[data-deleted-item-id="gone-54"] [data-video-id]').click()
                self.page.wait_for_function("activeView === 'detail' && !detailLoadingId")
                self.assertEqual(self.page.locator("#detail-heading").inner_text(), "已删除视频 54")
                self.page.locator("#back-to-videos").click()
                self.page.wait_for_function("activeView === 'deleted'")
                self.page.locator("#deleted-videos-tab").focus()
                self.page.keyboard.press("ArrowRight")
                self.assertEqual(self.page.evaluate("activeDeletedTab"), "claims")
                self.assertTrue(self.page.locator("#deleted-claims-tab").evaluate("el => el === document.activeElement"))
                self.assertEqual(self.page.locator('#deleted-list a[target="_blank"]').count(), 0)
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
        self.assertIn("/api/admin/deleted/videos/gone-0", requests)
        self.assertFalse(self.errors, self.errors)

    def test_deleted_private_content_clears_on_logout_and_late_responses_are_ignored(self):
        pending = []
        self.page.route("**/api/admin/deleted**", lambda route: pending.append(route))
        self.page.evaluate("setView('deleted')")
        self.page.wait_for_function("deletedItems.loading")
        self.page.evaluate("adminSession.authenticated=false;renderAdminSession()")
        pending.pop().fulfill(content_type="application/json", body=json.dumps({
            "videos": [{"id": "private-gone", "title": "private-deleted-title"}], "video_total": 1}))
        self.page.wait_for_timeout(50)
        self.assertEqual(self.page.evaluate("deletedItems.videos.length"), 0)
        self.assertNotIn("private-deleted-title", self.page.locator("#deleted-view").text_content())
        self.page.evaluate("""() => {
            adminSession.authenticated=true;renderAdminSession();
            deletedItems={videos:[{id:'private-gone',title:'private-deleted-title'}],claims:[],videoTotal:1,claimTotal:0,loaded:true};
            activeDeletedTab='videos';setView('deleted',{load:false});
        }""")
        self.page.locator('#deleted-list [data-video-id="private-gone"]').click()
        self.page.wait_for_function("Boolean(detailLoadingId)")
        self.page.evaluate("adminSession.authenticated=false;renderAdminSession()")
        pending.pop().fulfill(content_type="application/json", body=json.dumps({
            "video": {"id": "private-gone", "title": "private-deleted-title", "transcript_text": "private-late-transcript"},
            "claims": []}))
        self.page.wait_for_function("!detailLoadingId")
        self.assertEqual(self.page.evaluate("deletedVideoDetails.size"), 0)
        self.assertNotIn("private-late-transcript", self.page.locator("body").text_content())
        self.assertNotIn("private-deleted-title", self.page.evaluate("JSON.stringify({...sessionStorage})"))
        self.assertEqual(self.page.evaluate("activeView"), "overview")
        self.assertFalse(self.errors, self.errors)

    def test_deleted_detail_reload_stays_private_and_logout_removes_loaded_content(self):
        payload = {"video": {"id": "private-gone", "title": "private-deleted-title",
                             "transcript_text": "private-saved-transcript"}, "claims": []}
        self.page.route("**/api/admin/deleted/videos/private-gone", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps(payload)))
        self.page.evaluate("""() => {
            selectedVideoId='private-gone';setView('detail',{returnView:'deleted',deletedVideo:true});
            loadSelectedVideoDetail();
        }""")
        self.page.wait_for_function("!detailLoadingId && deletedVideoDetails.size === 1")
        self.assertIn("private-saved-transcript", self.page.locator("#transcript-text").inner_text())
        self.page.reload(wait_until="networkidle")
        self.page.wait_for_function("adminSession.authenticated && deletedVideoDetails.size === 1 && !detailLoadingId")
        self.assertEqual(self.page.locator("#detail-heading").inner_text(), "private-deleted-title")
        self.assertEqual(self.page.locator("#detail-view [data-admin-required]:visible").count(), 0)
        self.assertNotIn("private-saved-transcript", self.page.evaluate("JSON.stringify({...sessionStorage})"))
        self.page.evaluate("adminSession.authenticated=false;renderAdminSession()")
        self.assertEqual(self.page.evaluate("deletedVideoDetails.size"), 0)
        self.assertNotIn("private-saved-transcript", self.page.locator("body").text_content())
        self.assertNotIn("private-deleted-title", self.page.locator("body").text_content())
        self.assertEqual(self.page.evaluate("activeView"), "overview")
        self.assertFalse(self.errors, self.errors)

    def test_svg_statuses_keep_promotion_inline_and_exclusions_show_saved_evidence(self):
        self.prepare_exclusion_card()
        items = [{"object": "衣柜", "action": "字段省略" if index == 0 else "未收录",
                  "reasons": ["价格信息：数值缺少原文依据" if index == 0 else "对象指代不清"],
                  "quotes": ["原文片段 <img src=x onerror=alert(1)>" if index == 0 else "这个做法不合适"]}
                 for index in range(8)]
        self.page.route("**/api/admin/videos/v000/exclusions", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps({"video": {"id": "v000", "title": "Test video"},
                                                             "total": 8, "items": items})))
        first = self.page.locator("#video-grid .video-card").first
        for width in (1440, 768, 390, 320):
            self.page.set_viewport_size({"width": width, "height": 950})
            self.assertEqual(first.locator(".video-content-status > .video-state-badge").count(), 3)
            self.assertEqual(first.locator(".video-promotion-badge").inner_text(), "推广")
            self.assertEqual(first.locator(".video-content-status > .video-state-badge > svg").count(), 3)
            geometry = first.locator(".video-content-status").evaluate("""el => {
                const boxes = [...el.children].map(child => child.getBoundingClientRect());
                return {tops: boxes.map(box => box.top), right: boxes.at(-1).right, limit: el.getBoundingClientRect().right};
            }""")
            self.assertLess(max(geometry["tops"]) - min(geometry["tops"]), 1)
            self.assertLessEqual(geometry["right"], geometry["limit"] + 1)
            first.locator("[data-video-exclusions-id]").click()
            self.page.wait_for_function("document.querySelector('#video-exclusions-count').textContent === '8 条'")
            dialog = self.page.locator("#video-exclusions-dialog")
            self.assertEqual(dialog.locator(".video-exclusion-list > li").count(), 8)
            self.assertEqual(dialog.locator(".exclusion-action[data-action='field']").count(), 1)
            self.assertIn("原文片段 <img", dialog.locator("blockquote").first.inner_text())
            self.assertEqual(dialog.locator("img").count(), 0)
            self.assertEqual(dialog.locator("[data-admin-required], [data-delete-claim-id]").count(), 0)
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
            self.page.keyboard.press("Escape")
            self.page.wait_for_function("document.querySelector('#video-exclusions-dialog-content').textContent === ''")
        cache = self.page.evaluate("JSON.stringify(sessionStorage)")
        self.assertNotIn("原文片段", cache)
        self.assertFalse(self.errors, self.errors)

    def test_exclusion_dialog_drops_late_responses_and_clears_private_content_on_logout(self):
        self.prepare_exclusion_card()
        pending = []
        self.page.route("**/api/admin/videos/v000/exclusions", lambda route: pending.append(route))
        trigger = self.page.locator('[data-video-exclusions-id="v000"]')
        trigger.click()
        self.page.wait_for_function("document.querySelector('#video-exclusions-dialog').open")
        self.page.evaluate("adminSession.authenticated = false; renderAdminSession()")
        self.assertFalse(self.page.locator("#video-exclusions-dialog").evaluate("el => el.open"))
        self.assertEqual(trigger.count(), 0)
        self.page.evaluate("adminSession.authenticated = true; renderAdminSession()")
        trigger.click()
        self.page.wait_for_timeout(50)
        self.assertEqual(len(pending), 2)
        old = {"video": {"id": "v000", "title": "late-private-title"}, "total": 1,
               "items": [{"object": "late-private-content", "action": "未收录", "quotes": [], "reasons": ["old"]}]}
        pending[0].fulfill(content_type="application/json", body=json.dumps(old))
        self.page.wait_for_timeout(50)
        self.assertNotIn("late-private", self.page.locator("#video-exclusions-dialog").inner_text())
        pending[1].fulfill(content_type="application/json", body=json.dumps({**old, "total": 0, "items": []}))
        self.page.wait_for_function("document.querySelector('#video-exclusions-count').textContent === '0 条'")
        self.page.evaluate("adminSession.authenticated = false; renderAdminSession()")
        self.assertNotIn("late-private", self.page.locator("#video-exclusions-dialog").text_content())
        self.assertEqual(self.page.locator("#video-exclusions-dialog-content").text_content(), "")
        self.assertFalse(self.errors, self.errors)

    def test_expired_exclusion_session_removes_private_entry_and_dialog(self):
        self.prepare_exclusion_card()
        self.page.route("**/api/admin/videos/v000/exclusions", lambda route: route.fulfill(
            status=401, content_type="application/json", body='{"error":"admin login required"}'))
        self.page.locator('[data-video-exclusions-id="v000"]').click()
        self.page.wait_for_function("!adminSession.authenticated")
        self.assertFalse(self.page.locator("#video-exclusions-dialog").evaluate("el => el.open"))
        self.assertEqual(self.page.locator("[data-video-exclusions-id]").count(), 0)
        self.assertEqual(self.page.locator("#video-exclusions-dialog-content").text_content(), "")
        self.assertFalse(self.errors, self.errors)

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

    def test_detail_promotion_controls_do_not_navigate_and_save_only_on_submit(self):
        transcript = "明确施工范围，再确定材料。"
        self.rows[0].update(transcript_text=transcript, ad_review={
            "decision": "not_ad", "reason": "仅作材料比较", "evidence": ["明确施工范围"],
        })
        self.page.route("**/api/videos/v000", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps({"video": self.rows[0], "claims": []})))
        saved = []

        def save_promotion(route):
            saved.append(route.request.post_data_json)
            self.rows[0]["ad_review"] = {"decision": "advertising", "source": "manual"}
            route.fulfill(content_type="application/json", body='{"status":"saved"}')

        self.page.route("**/api/videos/v000/promotion", save_promotion)
        self.page.locator('#video-grid footer [data-video-id="v000"]').click()
        self.page.wait_for_function("activeView === 'detail' && !detailLoadingId")
        self.assertEqual(self.page.locator("#transcript-text").inner_text(), transcript)
        self.page.locator("#detail-source-info > summary").click()
        self.assertTrue(self.page.locator("#detail-source-info").evaluate("el => el.open"))
        self.page.locator("#promotion-editor > summary").click()
        self.page.locator("#promotion-form").wait_for(state="visible")
        self.page.locator("#promotion-decision").select_option("advertising")
        self.assertEqual(self.page.locator("#promotion-current").inner_text(), "普通内容")
        self.assertEqual(saved, [])
        self.assertEqual(self.page.evaluate("activeView"), "detail")
        self.assertEqual(self.page.evaluate("selectedVideoId"), "v000")
        self.page.locator("#save-promotion").click()
        self.page.wait_for_function("promotionEdits.has('v000') && !promotionEdits.get('v000').saving")
        self.assertEqual(saved, [{"decision": "advertising"}])
        self.assertEqual(self.page.locator("#promotion-current").inner_text(), "推广")
        self.assertFalse(self.page.locator("#promotion-editor").evaluate("el => el.open"))
        self.assertEqual(self.page.locator("#transcript-text").inner_text(), transcript)
        self.assertFalse(self.errors, self.errors)

    def test_missing_card_source_can_retry_and_return_without_showing_another_video(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.route("**/api/videos/missing-source", lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"error":"unavailable"}'))
        self.page.evaluate("""() => {
            knowledgeClaims = Array.from({length: 24}, (_, index) => normalizeKnowledgeClaim({
                id: `test-${index}`, video_id: 'missing-source', object_name: `测试观点 ${index}`,
                original_conclusion: '签约前明确材料范围，避免施工过程中追加费用。',
                original_reasons: ['避免争议'], conditions: '仅适用于分开签约',
                author_stance: '赞成', process_stage: '准备阶段', source_quotes: ['明确材料范围'],
            }));
            knowledgePageState = {...knowledgePageState, total: 24, hasMore: false};
            setView('knowledge');
        }""")
        card = self.page.locator('#knowledge-results [data-claim-id="test-15"]')
        card.locator('.claim-source-action').scroll_into_view_if_needed()
        before = self.page.evaluate("scrollY")
        card.locator('.claim-source-action').click()
        self.page.wait_for_function("Boolean(detailLoadError)")
        self.assertEqual(self.page.locator('#detail-heading').inner_text(), '来源视频暂不可用')
        self.assertNotIn('Renovation video', self.page.locator('#detail-view').inner_text())
        self.page.route("**/api/videos/missing-source", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps({
                "video": {**self.rows[0], "id": "missing-source", "title": "Recovered source",
                          "transcript_text": "明确材料范围"}, "claims": []})))
        self.page.locator('[data-retry-detail]').click()
        self.page.wait_for_function("!detailLoadingId && !detailLoadError")
        self.assertEqual(self.page.locator('#detail-heading').inner_text(), 'Recovered source')
        self.page.locator('#back-to-videos').click()
        self.page.wait_for_function("activeView === 'knowledge'")
        self.page.wait_for_timeout(100)
        self.assertLess(abs(self.page.evaluate('scrollY') - before), 2)
        self.assertEqual(self.page.locator('#knowledge-results .claim-card').count(), 24)
        self.assertFalse(self.errors, self.errors)

    def test_late_knowledge_search_preserves_expanded_card_on_return(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        claims = [{"id": f"reading-{i}", "video_id": "v000", "object_name": f"观点 {i}",
                   "original_conclusion": "签约前明确材料范围。", "source_quotes": ["签约前明确材料范围。"],
                   "author_stance": "赞成", "content_type": "施工做法"} for i in range(24)]
        self.page.evaluate("""(claims) => {
            knowledgeClaims = claims.map(normalizeKnowledgeClaim);
            knowledgePageState = {...knowledgePageState,total:24,hasMore:false};
            setView('knowledge');
        }""", claims)
        card = self.page.locator('#knowledge-results [data-claim-id="reading-15"]')
        card.locator('summary').click()
        card.locator('.claim-source-action').scroll_into_view_if_needed()
        before = self.page.evaluate('scrollY')
        card.locator('.claim-source-action').click()
        self.page.wait_for_function("activeView === 'detail' && !detailLoadingId")
        pending = []
        self.page.route('**/api/knowledge?**', lambda route: pending.append(route))
        self.page.evaluate('void (window.delayedKnowledge = loadKnowledgePage())')
        self.page.wait_for_function('knowledgePageState.loading')
        self.page.locator('#back-to-videos').click()
        self.page.wait_for_function("activeView === 'knowledge'")
        self.assertTrue(pending)
        pending[0].fulfill(content_type='application/json', body=json.dumps({
            "claims": claims, "total": 24, "has_more": False, "facets": {"total": 24}}))
        self.page.wait_for_function('!knowledgePageState.loading')
        self.assertTrue(card.locator('.claim-more').evaluate('(el)=>el.open'))
        self.assertLess(abs(self.page.evaluate('scrollY') - before), 2)
        # An ordinary rerender must not collapse the same card either.
        self.page.evaluate('renderKnowledge()')
        self.assertTrue(card.locator('.claim-more').evaluate('(el)=>el.open'))
        self.assertFalse(self.errors, self.errors)

    def test_quick_view_source_closes_dialog_and_late_detail_does_not_change_selection(self):
        pending = []
        self.page.route("**/api/videos/v001", lambda route: pending.append(route))
        self.page.route("**/api/videos/v002", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps({"video": self.rows[2], "claims": []})))
        self.page.evaluate("""() => {
            const dialog = document.querySelector('#video-claims-dialog');
            dialog.querySelector('#video-claims-dialog-content').innerHTML = renderClaimCard({
                id: 'quick-card', videoId: 'v001', object: '预算', conclusion: '明确范围', tags: [],
            }, {allowDelete: false});
            dialog.showModal();
        }""")
        self.page.locator('#video-claims-dialog .claim-source-action').click()
        self.page.wait_for_function("activeView === 'detail'")
        self.assertFalse(self.page.locator('#video-claims-dialog').evaluate('el => el.open'))
        self.assertEqual(len(pending), 1)
        self.page.locator('#back-to-videos').click()
        self.page.wait_for_function("activeView === 'videos'")
        self.page.locator('#video-grid [data-video-id="v002"]').click()
        self.page.wait_for_function("selectedVideoId === 'v002' && !detailLoadingId")
        pending[0].fulfill(content_type="application/json", body=json.dumps({
            "video": self.rows[1], "claims": []}))
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate('selectedVideoId'), 'v002')
        self.assertEqual(self.page.locator('#detail-heading').inner_text(), 'Renovation video 2')
        self.assertFalse(self.errors, self.errors)

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

        self.login_status = {"status": "busy", "logged_in": True, "running": False}
        self.page.locator('#check-douyin-login').click()
        self.page.wait_for_function("!douyinLoginChecking")
        self.assertEqual(badge.inner_text(), '浏览器正忙')

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
        elif path == "/api/admin/source-performance":
            self.performance_requests += 1
            payload = {"prompt_version": "test-current", "reason_labels": {"parameter": "参数不清"}, "sources": [{
                "source_id": "source-a", "sample_count": 2, "deleted_videos": 1,
                "published_from": "2026-10-01T00:00:00+00:00", "published_to": "2026-11-01T00:00:00+00:00",
                "videos_with_cards": 1, "retained_cards": 2, "technical_videos": 1, "current_completed": 1,
                "content_counts": {"not_ad": 1, "error": 1}, "card_versions": {"current": 1, "legacy": 1},
                "deletions": {"replacement": 2, "other": 1}, "exclusions": {"parameter": 1},
                "videos": [{"id": "v000", "title": "Maintenance sample", "published_at": "2026-11-01T00:00:00Z",
                            "content_label": "普通", "decision_source": "automatic", "outcome_label": "已完成提取",
                            "retained_cards": 2, "run_version": "current"},
                           {"id": "removed", "title": "Deleted sample", "deleted": True, "content_label": "未判定",
                            "outcome_label": "文案获取失败", "retained_cards": 0}],
            }]}
        elif path in ("/api/admin/deleted", "/api/settings/transcription"):
            self.private_view_requests.append(path)
            payload = {}
        elif path == "/api/douyin/login-status":
            self.login_requests += 1
            payload = self.login_status
        elif path == "/api/knowledge":
            payload = {"claims": [], "total": 0, "facets": self.knowledge_facets()}
        elif path == "/api/progress-summary":
            self.private_view_requests.append(path)
            payload = {"counts": {}}
        elif path == "/api/progress-videos":
            self.private_view_requests.append(path)
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

    def test_publish_times_are_shown_in_one_format(self):
        result = self.page.evaluate("""() => [
          formatPublishTime("2026-11-07T08:16:28+00:00"),
          formatPublishTime("2026-11-04 16:54:54"),
          formatPublishTime("2026-08-21T23:00:00Z"),
          formatPublishTime("2025-01-02"),
          formatPublishTime("未提及"),
        ]""")
        self.assertEqual(result, ["2026-11-07 16:16", "2026-11-04 16:54", "2026-08-22 07:00", "2025-01-02", ""])

    def test_creator_filter_shows_top_creators_with_search_and_more(self):
        rows = [{"platform": "抖音", "creator": f"博主{i:02d}", "video_count": 40 - i} for i in range(20)]
        self.page.evaluate("""rows => {
          videoFacets = {...(videoFacets || {}), total: 590, platforms: [{platform: "抖音", video_count: 590}], creators: rows};
          renderVideoFilters();
        }""", rows)
        visible = lambda: self.page.locator("[data-video-creator]:visible").count()
        self.assertEqual(visible(), 13)  # 全部 + the 12 busiest creators
        self.assertTrue(self.page.locator('[data-video-creator="博主00"]').is_visible())
        self.assertFalse(self.page.locator('[data-video-creator="博主19"]').is_visible())
        more = self.page.locator("[data-video-creator-more]")
        self.assertEqual(more.inner_text(), "更多博主 8 位")
        more.click()
        self.assertEqual(visible(), 21)
        more.click()
        search = self.page.locator("[data-video-creator-search]")
        search.fill("博主19")
        self.assertEqual(visible(), 2)
        self.assertTrue(self.page.locator('[data-video-creator="博主19"]').is_visible())
        search.fill("没有这个人")
        self.assertTrue(self.page.locator("[data-video-creator-empty]").is_visible())
        self.assertFalse(self.errors, self.errors)

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
            '[data-view="deleted"]', '[data-view="settings"]', '[data-view="progress"]', '.source-card footer',
        ):
            for element in self.page.locator(selector).all():
                self.assertFalse(element.is_visible(), selector)
        self.assertTrue(self.page.locator('[data-source-filter-id="source-a"]').is_visible())
        self.assertEqual(self.page.locator('[data-source-performance]').count(), 0)
        self.assertEqual(self.performance_requests, 0)
        self.assertTrue(self.page.locator('#admin-login-button').is_visible())
        self.page.locator('[data-view="videos"]').click()
        self.assertGreater(self.page.locator('#video-grid .video-card').count(), 0)
        self.assertEqual(self.page.locator('[data-delete-video-id]').count(), 0)
        # Processing progress is admin-only: a bookmarked #progress falls back to the overview.
        self.page.evaluate("setView('progress')")
        self.assertEqual(self.page.evaluate("activeView"), "overview")
        self.assertFalse(self.errors, self.errors)

    def test_source_performance_expands_without_navigation_and_preserves_state(self):
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_function("sourcePerformance.status === 'ready'")
        details = self.page.locator('.source-performance[data-source-performance="source-a"]')
        self.assertIn("2 / 10", details.locator(':scope > summary').inner_text())
        self.assertIn("1 条有卡 · 2 张知识卡", details.locator(':scope > summary').inner_text())
        details.locator(':scope > summary').click()
        self.assertTrue(details.evaluate("el => el.open"))
        self.assertEqual(self.page.evaluate('activeView'), 'sources')
        self.assertNotIn("旧版", details.text_content())
        self.assertEqual(details.locator('.source-performance-key-metrics > div').count(), 2)
        self.assertEqual(details.locator('.source-performance-ring').get_attribute('aria-label'), "有卡视频 1 / 2 条")
        self.assertEqual(details.locator('.performance-ring-value').get_attribute('stroke-dasharray'), "50 100")
        self.assertEqual(details.locator('.source-performance-bar').get_attribute('aria-label'), "内容判定：普通 1 条，判定失败 1 条")
        self.assertEqual(details.locator('[data-performance-section="videos"]').count(), 0)
        self.assertEqual(details.locator('details').count(), 0)
        self.assertEqual(details.locator('.source-performance-note').count(), 0)
        self.assertEqual(details.locator('.source-performance-videos').count(), 0)
        self.assertNotIn("查看 2 条视频", details.text_content())
        self.assertEqual(details.locator('.source-performance-version').count(), 0)
        self.assertNotIn("版本替换", details.inner_text())
        self.assertEqual(details.locator('[data-performance-video-id="removed"]').count(), 0)
        self.page.evaluate('renderSources()')
        self.assertTrue(details.evaluate("el => el.open"))
        details.locator(':scope > summary').focus()
        self.page.keyboard.press('Enter')
        self.assertFalse(details.evaluate("el => el.open"))
        self.assertEqual(self.page.evaluate('activeView'), 'sources')
        self.page.keyboard.press('Space')
        self.assertTrue(details.evaluate("el => el.open"))
        for width in (1440, 768, 390, 320):
            self.page.set_viewport_size({"width": width, "height": 950})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
            self.assertLess(details.locator('.source-performance-body').bounding_box()['height'], 240)
        self.assertNotIn("统计说明", details.inner_text())
        for removed in ("旧版", "版本", "当前提示", "test-current", "文案已变"):
            self.assertNotIn(removed, details.text_content())
        self.page.evaluate('renderSources()')
        self.assertEqual(details.locator('.source-performance-note').count(), 0)
        self.assertEqual(self.page.evaluate('activeView'), 'sources')
        # Text and title supplied by the endpoint must remain plain text.
        self.page.evaluate("""() => {
            sourcePerformance.sources.get('source-a').videos[0].title='<img src=x onerror=alert(1)>';
            renderSources();
        }""")
        self.assertEqual(details.locator('img').count(), 0)
        self.assertFalse(self.errors, self.errors)

    def test_source_card_opens_filtered_video_list_and_keeps_chart_expanded_on_return(self):
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_function("sourcePerformance.status === 'ready'")
        details = self.page.locator('.source-performance[data-source-performance="source-a"]')
        details.locator(':scope > summary').click()
        self.page.evaluate('renderSources()')
        self.assertTrue(details.evaluate('el => el.open'))
        self.page.locator('[data-source-filter-id="source-a"] h3').click()
        self.page.wait_for_function("activeView === 'videos' && !videoPageState.loading")
        self.assertEqual(self.page.evaluate('activeSourceFilter.id'), 'source-a')
        self.assertEqual(self.page.locator('#video-grid .video-card').count(), 30)
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_function("activeView === 'sources' && sourcePerformance.status === 'ready'")
        self.assertTrue(details.evaluate('el => el.open'))
        self.assertFalse(self.errors, self.errors)

    def test_source_chart_uses_actual_sample_and_keeps_unknown_separate_from_ordinary(self):
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_function("sourcePerformance.status === 'ready'")
        details = self.page.locator('.source-performance[data-source-performance="source-a"]')
        details.locator(':scope > summary').click()
        for sample, with_cards, content, label, share in (
            (0, 0, {}, "暂无视频样本", "0 100"),
            (3, 3, {"unknown": 3}, "有卡视频 3 / 3 条", "100 100"),
            (5, 0, {"advertising": 2, "uncertain": 1, "error": 2}, "有卡视频 0 / 5 条", "0 100"),
        ):
            with self.subTest(sample=sample):
                self.page.evaluate("""values => {
                    Object.assign(sourcePerformance.sources.get('source-a'), values);
                    renderSources();
                }""", {"sample_count": sample, "videos_with_cards": with_cards, "content_counts": content})
                self.assertEqual(details.locator('.source-performance-ring').get_attribute('aria-label'), label)
                self.assertEqual(details.locator('.performance-ring-value').get_attribute('stroke-dasharray'), share)
                actual = details.locator('.performance-content-segment').evaluate_all(
                    "els => Object.fromEntries(els.map(el => [el.dataset.content, Number(el.getAttribute('width'))]))")
                self.assertEqual(set(actual), set(content))
                self.assertAlmostEqual(sum(actual.values()), 100 if sample else 0)
                self.assertEqual(details.locator('.performance-ring-number').text_content(), '—' if not sample else f'{with_cards}/{sample}')
                self.assertNotIn('NaN', details.inner_html())
                self.assertNotIn('Infinity', details.inner_html())
        self.assertFalse(self.errors, self.errors)

    def test_performance_private_state_is_not_cached_and_logout_clears_hidden_dom(self):
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_function("sourcePerformance.status === 'ready'")
        self.page.evaluate('writeApiCache()')
        cache = self.page.evaluate('JSON.stringify({...localStorage})')
        self.assertNotIn('Maintenance sample', cache)
        self.assertNotIn('card_versions', cache)
        self.page.locator('[data-view="videos"]').click()
        self.page.evaluate('logoutAdmin()')
        self.assertEqual(self.page.locator('[data-source-performance]').count(), 0)
        self.assertEqual(self.page.evaluate('sourcePerformance.sources.size'), 0)
        self.assertEqual(self.page.evaluate('expandedSourcePerformance.size'), 0)
        count = self.performance_requests
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_timeout(100)
        self.assertEqual(self.performance_requests, count)
        self.assertFalse(self.errors, self.errors)

    def test_late_private_performance_cannot_reappear_after_logout_and_relogin(self):
        pending = []
        self.page.route('**/api/admin/source-performance', lambda route: pending.append(route))
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_function("sourcePerformance.status === 'loading'")
        self.assertTrue(pending)
        self.page.evaluate('logoutAdmin()')
        self.page.wait_for_function('!adminSession.authenticated')
        self.page.evaluate("submitAdminLogin('mock-password')")
        self.page.wait_for_function("adminSession.authenticated && sourcePerformance.status === 'loading'")
        pending[0].fulfill(content_type='application/json', body=json.dumps({"sources": [{"source_id": "leaked"}]}))
        self.page.wait_for_timeout(50)
        self.assertEqual(self.page.evaluate('sourcePerformance.sources.size'), 0)
        self.assertEqual(len(pending), 2)
        pending[1].fulfill(content_type='application/json', body='{"sources": []}')
        self.page.wait_for_function("sourcePerformance.status === 'ready'")
        self.assertFalse(self.errors, self.errors)

    def test_performance_expired_session_clears_all_private_source_nodes(self):
        self.page.route('**/api/admin/source-performance', lambda route: route.fulfill(
            status=401, content_type='application/json', body='{"error":"admin login required"}'))
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_function('!adminSession.authenticated')
        self.assertEqual(self.page.locator('[data-source-performance]').count(), 0)
        self.assertEqual(self.page.evaluate('sourcePerformance.sources.size'), 0)
        self.assertFalse(self.errors, self.errors)

    def test_source_performance_failure_can_retry_without_navigating_source_card(self):
        self.page.route('**/api/admin/source-performance', lambda route: route.fulfill(
            status=503, content_type='application/json', body='{"error":"unavailable"}'))
        self.page.locator('[data-view="sources"]').click()
        self.page.wait_for_function("sourcePerformance.status === 'error'")
        self.assertEqual(self.page.evaluate('activeView'), 'sources')
        self.page.unroute('**/api/admin/source-performance')
        self.page.locator('[data-retry-source-performance]').first.click()
        self.page.wait_for_function("sourcePerformance.status === 'ready'")
        self.assertEqual(self.page.evaluate('activeView'), 'sources')
        self.assertEqual(self.page.locator('.source-performance').count(), 1)
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
        for view in ('deleted', 'settings', 'progress'):
            for authenticated in (False, True):
                with self.subTest(view=view, authenticated=authenticated):
                    self.authenticated = authenticated
                    self.private_view_requests.clear()
                    self.page.goto(
                        f'http://127.0.0.1:{self.http.server_port}/?bookmark={view}&auth={authenticated}#{view}',
                        wait_until='networkidle',
                    )
                    try:
                        self.page.wait_for_function("typeof activeView !== 'undefined' && adminSessionLoaded")
                    except Exception as error:
                        diagnostics = self.page.evaluate("""() => ({
                            url: location.href, active: document.querySelector('.view.active')?.id,
                            appStarted: typeof activeView !== 'undefined',
                            sessionLoaded: typeof adminSessionLoaded !== 'undefined' && adminSessionLoaded,
                            scripts: [...document.scripts].map(script => script.src),
                            resources: performance.getEntriesByType('resource').filter(item => /app.js|admin.session/.test(item.name))
                                .map(item => ({name: item.name, transferred: item.transferSize, duration: item.duration})),
                        })""")
                        raise AssertionError({"page_errors": self.errors, "resource_errors": self.resource_errors,
                                              "script_responses": self.script_responses, "bookmark": diagnostics}) from error
                    self.assertEqual(self.page.evaluate('activeView'), view if authenticated else 'overview')
                    if not authenticated:
                        self.assertEqual(self.page.evaluate('location.hash'), '#overview')
                        self.assertEqual(self.private_view_requests, [])
                    elif view == 'progress':
                        self.page.wait_for_function("document.querySelector('#progress-tabs').children.length > 0")
                        self.assertIn('/api/progress-videos', self.private_view_requests)
        self.assertFalse(self.errors, self.errors)

    def test_secondary_review_is_removed_from_navigation_detail_and_requests(self):
        requested = []
        self.page.on("request", lambda request: requested.append(urlparse(request.url).path))
        self.page.goto(f"http://127.0.0.1:{self.http.server_port}/#quality", wait_until="networkidle")
        self.page.wait_for_function("typeof activeView !== 'undefined' && adminSessionLoaded")
        self.assertEqual(self.page.evaluate("activeView"), "overview")
        self.assertEqual(self.page.locator('[data-view="quality"], #quality-view').count(), 0)
        self.page.route("**/api/videos/v000", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"video": self.rows[0], "claims": []})))
        self.page.evaluate("async () => { await loadVideoDetail('v000'); setView('detail'); }")
        self.assertEqual(self.page.locator("#claim-review-panel, [data-review-action]").count(), 0)
        self.assertFalse(any("/reviews" in path or path == "/api/admin/quality" or "quality-review." in path for path in requested))
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 391)
        self.assertFalse(self.errors, self.errors)


if __name__ == "__main__":
    unittest.main()
