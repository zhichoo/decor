"""Read-only export/privacy and static-browser regressions; no real model or API calls."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer as _ThreadingHTTPServer

import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest


class ThreadingHTTPServer(_ThreadingHTTPServer):
    # The default listen backlog (5) overflows when a page reload opens many connections;
    # on macOS the extra ones are reset and a stylesheet randomly fails to load.
    request_queue_size = 128


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
    claims[0].update(author_stance="赞成", content_type="个人体验",
                     source_quotes=["控制装修预算，材料施工前明确合同范围。"])
    claims[2]["conditions"] = "仅适用于材料与施工分开签约的情况"
    return sources, videos, claims


def relation_fixture(claims):
    from claim_relations import VERSION, fingerprint
    rows = []
    for index, kind in ((60, "opposite"), (61, "equivalent"), (2, "conditions"), (1, "similar")):
        a, b = claims[0], claims[index]
        rows.append({"claim_a_id": a["id"], "claim_b_id": b["id"], "kind": kind,
                     "reason": {"opposite": "施工范围的建议不同", "equivalent": "均建议提前明确施工与材料范围", "conditions": "第二张卡限定分别签约", "similar": "均建议提前明确施工范围"}[kind],
                     "fingerprint_a": fingerprint(a), "fingerprint_b": fingerprint(b), "version": VERSION,
                     "private_metadata": "private-relation-data"})
    return rows


class PublicExportTests(unittest.TestCase):
    def test_relations_are_bidirectional_and_deleted_or_stale_pairs_are_not_exported(self):
        sources, videos, claims = fixture()
        rows = relation_fixture(claims)
        claims[1]["original_conclusion"] = "内容已改"
        claims[2]["deleted_at"] = 10
        claims[61]["deleted_at"] = 10
        snapshot = exporter.make_snapshot(sources, videos, claims, relation_rows=rows)
        self.assertEqual(len(snapshot["claim_relations"]), 1)
        by_id = {claim["id"]: claim for claim in snapshot["claims"]}
        self.assertEqual(by_id["c000"]["relation_counts"], {"opposite": 1})
        self.assertEqual(by_id["c060"]["relation_counts"], {"opposite": 1})
        self.assertNotIn("private-relation-data", json.dumps(snapshot))
        self.assertNotIn("fingerprint_a", json.dumps(snapshot))

    def test_allowlist_omits_private_fields_deleted_records_and_url_secrets(self):
        sources, videos, claims = fixture()
        sources[0]["source_performance"] = {"private-maintenance-metrics": True}
        videos[-1]["deleted_at"] = 2000
        claims[-1]["deleted_at"] = 2000
        claims[-2]["deleted_at"] = 2000
        videos[0]["last_error"] = "private-api-error-with-key"
        claims[0].update(field_evidence={"private-field-binding": [0]}, source_scope="personal",
                         scope_quote="private-scope-quote", evidence_contract="private-evidence-contract")
        snapshot = exporter.make_snapshot(sources, videos, claims, "2026-10-28T07:00:00+00:00")
        text = json.dumps(snapshot)
        for secret in ("private-maintenance-metrics", "source_performance", "private-password", "private-source-note", "private-review", "private-task",
                       "private-run", "private-admin", "private-api-error-with-key", "private-field-binding",
                       "private-scope-quote", "private-evidence-contract", "secret=", "private=", "v064", "c063"):
            self.assertNotIn(secret, text)
        for field in ("field_evidence", "source_scope", "scope_quote", "evidence_contract"):
            self.assertNotIn(field, snapshot["claims"][0])
        self.assertEqual(snapshot["stats"]["video_count"], 64)
        self.assertEqual(snapshot["stats"]["claim_count"], 63)
        self.assertEqual(snapshot["sources"][0]["claim_count"], 63)
        self.assertEqual(snapshot["knowledge_facets"]["total"], 63)
        self.assertEqual(snapshot["knowledge_facets"]["content_types"]["未分类"], 62)
        self.assertNotIn("旧版未分类", snapshot["knowledge_facets"]["content_types"])
        # Processing progress is admin-only and stays out of the public snapshot.
        self.assertNotIn("progress_counts", snapshot)
        self.assertNotIn("progress_state", snapshot["videos"][0])

    def test_retained_cards_export_a_read_only_source_without_exposing_trash_metadata(self):
        sources, videos, claims = fixture()
        videos[0].update(deleted_at=2000, delete_reason="private-reason", transcript_job={"private": "task"})
        snapshot = exporter.make_snapshot(sources, videos, claims)
        self.assertEqual(snapshot["stats"]["video_count"], 64)
        self.assertEqual(snapshot["stats"]["claim_count"], 65)
        self.assertEqual(snapshot["sources"][0]["claim_count"], 65)
        preview = snapshot["retained_sources"][0]
        self.assertEqual(preview["id"], "v000")
        self.assertTrue(preview["source_read_only"])
        for field in ("deleted_at", "delete_reason", "transcript_job", "last_error"):
            self.assertNotIn(field, preview)
        videos[0]["purged_at"] = 3000
        purged = exporter.make_snapshot(sources, videos, claims)
        self.assertEqual(purged["retained_sources"], [])
        self.assertEqual(purged["stats"]["claim_count"], 64)

    def test_artifact_contains_no_login_edit_delete_or_management_forms(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            snapshot = exporter.make_snapshot(*fixture())
            first = exporter.build_site(snapshot, output)
            document = (output / "index.html").read_text()
            for text in ('id="admin-panel"', 'id="admin-login-modal"', 'id="video-delete-dialog"',
                         'id="video-exclusions-dialog"',
                         'id="promotion-form"', 'id="transcript-edit-form"', "data-admin-required", "data-admin-only",
                         'id="fetch-transcript"', 'id="edit-transcript"', 'id="detail-extract-video"', 'id="claim-review-panel"',
                         'id="quality-view"', 'id="quality-workspace"', 'data-view="quality"', 'quality-review.js', 'quality-review.css'):
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
        values = fixture()
        exporter.build_site(exporter.make_snapshot(*values, relation_rows=relation_fixture(values[2])), cls.output)
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

    def test_relations_cross_pagination_switch_type_and_preserve_reading_position(self):
        self.page.locator('#knowledge-query').fill("预算规划 0")
        self.page.wait_for_function("knowledgePageState.total === 1")
        self.page.locator('[data-claim-relations-id="c000"][data-relation-kind="opposite"]').click()
        dialog = self.page.locator('#claim-relations-dialog')
        dialog.locator('[data-claim-id="c060"]').wait_for()
        # The card being compared stays on the page, so the popover only holds the other one.
        self.assertEqual(dialog.locator('[data-claim-id="c000"]').count(), 0)
        self.assertEqual(dialog.locator('.claim-comparison-current').count(), 0)
        self.assertEqual(dialog.locator('[data-claim-relation-tab]').count(), 2)
        dialog.get_by_role('button', name='下一条关联观点').click()
        dialog.locator('[data-claim-id="c002"]').wait_for()
        self.assertIn("分别签约", dialog.inner_text())
        self.assertEqual(dialog.locator('[data-claim-relation-tab="opposite"]').get_attribute('aria-pressed'), 'true')
        self.assertIn('差异', dialog.locator('.claim-relation-reason').inner_text())
        dialog.locator('[data-claim-relation-tab="similar"]').click()
        dialog.locator('[data-claim-id="c061"]').wait_for()
        dialog.get_by_role('button', name='下一条关联观点').click()
        dialog.locator('[data-claim-id="c001"]').wait_for()
        dialog.locator('[data-claim-relations-id="c001"]').click()
        dialog.locator('.claim-comparison-related [data-claim-id="c000"]').wait_for()
        self.assertTrue(dialog.locator('.claim-comparison-current').is_visible())
        self.page.keyboard.press("Escape")
        self.assertFalse(dialog.is_visible())
        self.assertEqual(self.page.locator('#knowledge-results > .claim-card').count(), 1)
        self.assertEqual(self.page.locator('#knowledge-query').input_value(), "预算规划 0")
        self.assertEqual(self.errors, [])
        self.assertEqual(self.api_requests, [])

    def test_relation_source_navigation_and_mobile_layout(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.locator('[data-claim-relations-id="c000"][data-relation-kind="opposite"]').click()
        dialog = self.page.locator('#claim-relations-dialog')
        dialog.locator('[data-claim-id="c060"]').wait_for()
        self.assertTrue(dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1'))
        bounds = dialog.bounding_box()
        self.assertGreaterEqual(bounds['x'], 0)
        self.assertLessEqual(bounds['x'] + bounds['width'], 390)
        self.assertLessEqual(bounds['y'] + bounds['height'], 844)
        dialog.locator('[data-claim-id="c060"] [data-video-id="v060"]').click()
        self.page.wait_for_function("activeView === 'detail' && selectedVideoId === 'v060' && !detailLoadingId")
        self.assertFalse(dialog.is_visible())
        # The shared renderer also exposes relationships in video details.
        self.page.locator('#video-claims [data-claim-relations-id="c060"]').wait_for()
        self.page.go_back()
        self.page.wait_for_function("activeView === 'knowledge'")
        self.assertEqual(self.errors, [])

    def test_equivalent_views_share_similar_group_without_merging_sources(self):
        buttons = self.page.locator('#knowledge-results [data-claim-id="c000"] [data-relation-kind]')
        self.assertEqual(buttons.count(), 2)
        different = self.page.locator('[data-claim-relations-id="c000"][data-relation-kind="opposite"]')
        button = self.page.locator('[data-claim-relations-id="c000"][data-relation-kind="similar"]')
        self.assertIn("不同观点", different.inner_text())
        self.assertIn("相近观点", button.inner_text())
        self.assertEqual(different.locator('.claim-relation-count').inner_text(), '2')
        self.assertEqual(button.locator('.claim-relation-count').inner_text(), '2')
        self.assertNotEqual(different.locator('svg').inner_html(), button.locator('svg').inner_html())
        self.assertEqual(self.page.locator('[data-relation-kind="equivalent"], [data-relation-kind="conditions"]').count(), 0)
        button.click()
        dialog = self.page.locator('#claim-relations-dialog')
        other = dialog.locator('.claim-comparison-related [data-claim-id="c061"]')
        other.wait_for()
        self.assertIn("装修预算视频 61", other.locator('.claim-comparison-source').inner_text())
        self.assertEqual(dialog.locator('[data-video-id="v000"]').count(), 0)
        self.assertEqual(other.locator('[data-video-id="v061"]').count(), 1)
        # Anchored just below the clicked link instead of centred over the page.
        link_bounds = button.bounding_box()
        dialog_bounds = dialog.bounding_box()
        self.assertLess(abs(dialog_bounds['y'] - (link_bounds['y'] + link_bounds['height'] + 8)), 2)
        self.assertLessEqual(dialog_bounds['width'], 440)
        self.assertEqual(dialog.locator('[data-claim-relation-tab="equivalent"], [data-claim-relation-tab="conditions"]').count(), 0)
        self.assertEqual(dialog.locator('#claim-relations-mark svg').inner_html(), button.locator('svg').inner_html())
        other.locator('[data-claim-relations-id="c061"][data-relation-kind="similar"]').click()
        dialog.locator('.claim-comparison-related [data-claim-id="c000"]').wait_for()
        self.assertTrue(dialog.locator('.claim-comparison-current').is_visible())
        # Following a comparison keeps the popover where it was opened.
        self.assertLess(abs(dialog.bounding_box()['y'] - dialog_bounds['y']), 2)
        self.assertEqual(self.page.evaluate('knowledgePageState.total'), 65)
        self.assertEqual(self.errors, [])
        self.assertEqual(self.api_requests, [])

    def test_comparison_paging_and_long_evidence_stay_inside_dialog(self):
        from claim_relations import fingerprint
        sources, videos, claims = fixture()
        claims[0]['source_quotes'] = ['控制装修预算，材料施工前明确合同范围。' * 120]
        videos[61]['title'] = '装修预算与材料施工前明确合同范围，避免追加费用。' * 40
        rows = relation_fixture(claims)
        same = next(row for row in rows if row['kind'] == 'equivalent')
        rows.extend({**same, 'claim_b_id': claims[index]['id'],
                     'fingerprint_b': fingerprint(claims[index])} for index in (3, 4))
        snapshot = exporter.make_snapshot(sources, videos, claims, relation_rows=rows)
        self.page.route('**/data/*.json', lambda route: route.fulfill(status=200,
            content_type='application/json', body=json.dumps(snapshot)))
        self.page.reload(wait_until='networkidle')
        self.page.wait_for_function("apiLoadState.status === 'ready' && knowledgePageState.total === 65")
        self.page.locator('[data-claim-relations-id="c000"][data-relation-kind="similar"]').click()
        dialog = self.page.locator('#claim-relations-dialog')
        dialog.locator('.claim-comparison-related .claim-card').wait_for()
        self.assertEqual(dialog.locator('.claim-comparison-related .claim-card').count(), 1)
        title = dialog.locator('.claim-comparison-related .claim-comparison-video-title')
        self.assertEqual(title.get_attribute('title'), videos[61]['title'])
        self.assertTrue(title.evaluate('(el) => el.getBoundingClientRect().height <= parseFloat(getComputedStyle(el).lineHeight) * 2 + 1'))
        self.assertIn('1 / 4', dialog.locator('.claim-comparison-pager').inner_text())
        self.assertTrue(dialog.get_by_role('button', name='上一条关联观点').is_disabled())
        first_id = dialog.locator('.claim-comparison-related .claim-card').get_attribute('data-claim-id')
        dialog.get_by_role('button', name='下一条关联观点').click()
        self.assertIn('2 / 4', dialog.locator('.claim-comparison-pager').inner_text())
        self.assertNotEqual(dialog.locator('.claim-comparison-related .claim-card').get_attribute('data-claim-id'), first_id)
        dialog.get_by_role('button', name='上一条关联观点').click()
        self.assertEqual(dialog.locator('.claim-comparison-related .claim-card').get_attribute('data-claim-id'), first_id)
        content = dialog.locator('#claim-relations-content')
        dialog_bounds = dialog.bounding_box()
        self.assertLessEqual(dialog_bounds['y'] + dialog_bounds['height'], 950)
        close_bounds = dialog.get_by_role('button', name='关闭关联观点').bounding_box()
        self.assertGreaterEqual(close_bounds['y'], 0)
        self.assertLess(close_bounds['y'] + close_bounds['height'], 950)
        dialog.locator('[data-claim-relation-tab="opposite"]').click()
        self.assertEqual(content.evaluate('(el) => el.scrollTop'), 0)
        self.assertIn('1 / 2', dialog.locator('.claim-comparison-pager').inner_text())
        dialog.locator('[data-claim-id="c060"]').wait_for()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.api_requests, [])

    def test_outside_click_keeps_underlying_scroll_position(self):
        self.page.evaluate("window.scrollTo(0, 180)")
        button = self.page.locator('[data-claim-relations-id="c000"][data-relation-kind="similar"]')
        button.scroll_into_view_if_needed()
        position = self.page.evaluate("scrollY")
        button.click()
        self.page.locator('#claim-relations-dialog [data-claim-id="c061"]').wait_for()
        self.page.mouse.click(8, 100)
        self.assertFalse(self.page.locator('#claim-relations-dialog').is_visible())
        self.assertLess(abs(self.page.evaluate("scrollY") - position), 2)

    def test_retained_card_opens_its_source_without_showing_management_or_trash_listing(self):
        sources, videos, claims = fixture()
        videos[0]["deleted_at"] = 2000
        snapshot = exporter.make_snapshot(sources, videos, claims)
        self.page.route("**/data/*.json", lambda route: route.fulfill(status=200,
            content_type="application/json", body=json.dumps(snapshot)))
        self.page.reload(wait_until="networkidle")
        self.page.wait_for_function("apiLoadState.status === 'ready' && knowledgeClaims.length > 0")
        self.page.locator('#knowledge-results [data-video-id="v000"]').click()
        self.page.wait_for_function("!detailLoadingId && retainedSourceDetails.has('v000')")
        self.assertIn("控制装修预算", self.page.locator('#transcript-text').inner_text())
        self.assertIn("回收站", self.page.locator('#detail-status').inner_text())
        self.assertEqual(self.page.locator('[data-purge-video-id], [data-delete-video-id], [data-delete-claim-id]').count(), 0)
        self.assertEqual(self.api_requests, [])
        self.assertEqual(self.errors, [])

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

    def test_context_filters_quotes_and_legacy_cards_remain_read_only(self):
        cards = self.page.locator("#knowledge-results .claim-card")
        self.assertIn("作者赞成", cards.first.inner_text())
        self.assertFalse(cards.first.locator(".claim-reasons").is_visible())
        note = self.page.locator("#knowledge-view .claim-library-note")
        self.assertEqual(note.count(), 1)
        self.assertIn("未经事实核验", note.inner_text())
        self.assertIn("未注明条件不代表普遍适用", note.inner_text())
        self.assertEqual(cards.locator(".claim-library-note, .claim-more-hint").count(), 0)
        self.assertEqual(cards.first.locator(".claim-more summary").inner_text(), "展开详情")
        cards.first.locator(".claim-more summary").click()
        self.assertNotIn("原文未说明适用条件", cards.first.inner_text())
        self.assertNotIn("事实核验", cards.first.inner_text())
        self.assertEqual(cards.first.locator(".claim-more summary").inner_text(), "收起详情")
        self.assertEqual(cards.first.locator(".claim-reasons li").inner_text(), "避免追加费用")
        self.assertEqual(cards.first.locator("blockquote").inner_text(), "控制装修预算，材料施工前明确合同范围。")
        cards.nth(1).locator(".claim-more summary").click()
        self.assertEqual(cards.nth(1).locator(".claim-evidence-missing").inner_text(), "暂无引句")
        self.assertNotIn("旧版", cards.nth(1).inner_text())
        self.assertTrue(cards.nth(2).locator(".claim-conditions").is_visible())
        self.page.locator('[data-knowledge-group="按内容类型"]').click()
        self.page.locator('[data-knowledge-category-value="个人体验"]').click()
        self.page.wait_for_function("knowledgePageState.total === 1")
        self.assertEqual(cards.count(), 1)
        self.page.locator('[data-knowledge-category-value="未分类"]').click()
        self.page.wait_for_function("knowledgePageState.total === 64")
        self.assertNotIn("旧版未分类", self.page.locator("#knowledge-view").inner_text())
        self.assertEqual(cards.first.locator(".claim-evidence").count(), 0)
        self.page.locator('[data-knowledge-group="按作者态度"]').click()
        self.page.locator('[data-knowledge-category-value="反对"]').click()
        self.page.wait_for_function("knowledgePageState.total === 0")
        self.page.locator('[data-knowledge-category-value="赞成"]').click()
        self.page.wait_for_function("knowledgePageState.total === 65")
        self.page.evaluate("setView('detail'); loadVideoDetail('v000').then(renderDetail)")
        self.assertEqual(self.page.locator("#video-claims .claim-evidence").count(), 1)
        self.assertEqual(self.page.locator("#detail-view .claim-library-note").inner_text(), note.inner_text())
        self.assertNotIn("事实核验", self.page.locator("#video-claims").inner_text())
        markup = self.page.evaluate("renderClaimCard(normalizeApiClaim({object_name:'测试',stance:'未明确',source_quotes:['<img src=x onerror=alert(1)>']}))")
        self.assertIn("&lt;img", markup)
        self.assertNotIn("<img src=x", markup)
        self.assertNotIn('class="claim-reasons"', markup)
        self.assertNotIn('class="claim-context-meta"', markup)
        self.assertEqual(self.api_requests, [])
        self.assertFalse(self.errors, self.errors)

    def test_unclassified_filter_works_with_an_older_snapshot_and_empty_query(self):
        snapshot = exporter.make_snapshot(*fixture())
        types = snapshot["knowledge_facets"]["content_types"]
        types["旧版未分类"] = types.pop("未分类")
        self.page.route("**/data/library-*.json", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps(snapshot, ensure_ascii=False)))
        self.page.reload(wait_until="networkidle")
        self.page.wait_for_function("apiLoadState.status === 'ready' && knowledgePageState.total === 65")
        self.page.locator('[data-knowledge-group="按内容类型"]').click()
        button = self.page.locator('[data-knowledge-category-value="未分类"]')
        self.assertEqual(button.locator(".category-count").inner_text(), "64")
        button.click()
        self.page.wait_for_function("knowledgePageState.total === 64")
        counts = self.page.evaluate("""async () => {
            const canonical = await fetchApiJson('/knowledge?content_type=' + encodeURIComponent('未分类'));
            const previous = await fetchApiJson('/knowledge?content_type=' + encodeURIComponent('旧版未分类'));
            const empty = await fetchApiJson('/knowledge?content_type=');
            return [canonical.total, previous.total, empty.total];
        }""")
        self.assertEqual(counts, [64, 64, 65])
        self.assertNotIn("旧版未分类", self.page.locator("#knowledge-view").inner_text())
        self.assertEqual(self.api_requests, [])
        self.assertFalse(self.errors, self.errors)

    def test_card_source_round_trip_preserves_filters_loaded_range_and_position(self):
        # Explicit pagination makes the saved range deterministic, even near the sentinel.
        self.page.evaluate("autoLoadObserver?.disconnect()")
        self.page.locator('[data-knowledge-group="按主题"]').click()
        self.page.locator('[data-knowledge-category-value="预算"]').click()
        self.page.locator("#knowledge-query").fill("范围")
        self.page.wait_for_function("!knowledgePageState.loading && knowledgeClaims.length >= 50")
        self.page.wait_for_timeout(350)
        self.page.evaluate("loadKnowledgePage({append:true})")
        self.page.wait_for_function("knowledgeClaims.length === 65")
        card = self.page.locator('#knowledge-results [data-claim-id="c060"]')
        card.locator(".claim-more summary").click()
        card.locator(".claim-source-action").scroll_into_view_if_needed()
        before = self.page.evaluate("scrollY")
        before_videos = self.page.evaluate("videos.map(video => video.id)")
        self.assertGreater(before, 500)
        card.locator(".claim-source-action").click()
        self.page.wait_for_function("activeView === 'detail' && !detailLoadingId")
        self.assertIn("装修预算视频 60", self.page.locator("#detail-heading").inner_text())
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(self.page.evaluate("videos.map(video => video.id)"), before_videos)
        self.assertIn("返回知识库", self.page.locator("#back-to-videos").inner_text())
        self.page.locator("#back-to-videos").click()
        self.page.wait_for_function("activeView === 'knowledge'")
        self.page.wait_for_timeout(100)
        self.assertLess(abs(self.page.evaluate("scrollY") - before), 2)
        self.assertEqual(self.page.locator("#knowledge-query").input_value(), "范围")
        self.assertEqual(self.page.evaluate("activeKnowledgeCategory.value"), "预算")
        self.assertEqual(self.page.evaluate("knowledgeClaims.length"), 65)
        self.assertTrue(card.locator(".claim-more").evaluate("el => el.open"))

        # Forward selects the same source video, and browser Back also restores the list.
        self.page.go_forward()
        self.page.wait_for_function("activeView === 'detail' && !detailLoadingId")
        self.assertIn("装修预算视频 60", self.page.locator("#detail-heading").inner_text())
        self.page.go_back()
        self.page.wait_for_function("activeView === 'knowledge'")
        self.page.wait_for_timeout(100)
        self.assertLess(abs(self.page.evaluate("scrollY") - before), 2)
        self.assertEqual(self.page.locator("#knowledge-results .claim-card").count(), 65)
        self.assertEqual(self.api_requests, [])
        self.assertFalse(self.errors, self.errors)

    def test_compact_cards_keep_conditions_visible_and_fit_mobile(self):
        for width in (1440, 768, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 844})
                card = self.page.locator('#knowledge-results [data-claim-id="c002"]')
                self.assertTrue(card.locator(".claim-conditions").is_visible())
                self.assertFalse(card.locator(".claim-reasons").is_visible())
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                card.locator(".claim-more summary").click()
                self.assertTrue(card.locator(".claim-reasons").is_visible())
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                card.locator(".claim-more summary").click()
        self.assertFalse(self.errors, self.errors)

    def test_mobile_public_views_do_not_offer_management_and_private_bookmarks_fall_back(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        for view in ("overview", "sources", "videos", "knowledge"):
            self.page.evaluate("view=>setView(view)", view)
            self.assertEqual(self.page.evaluate("activeView"), view)
            self.assertEqual(self.page.locator('[data-admin-required], [data-admin-only], #admin-panel').count(), 0)
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 391)
        for view in ("settings", "deleted", "progress"):
            self.page.evaluate("view=>setView(view)", view)
            self.assertEqual(self.page.evaluate("activeView"), "overview")
        self.assertEqual(self.api_requests, [])
        self.assertFalse(self.errors, self.errors)


if __name__ == "__main__":
    unittest.main()
