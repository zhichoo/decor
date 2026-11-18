"""Isolated browser checks for theme rollback; no real API or data writes."""
import unittest

import test_video_list_ui as ui


@unittest.skipIf(ui.sync_playwright is None, "Playwright is not installed")
class ThemeSwitchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ui.VideoListUITests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        ui.VideoListUITests.tearDownClass()

    def setUp(self):
        self.app = ui.VideoListUITests("test_claim_delete_preserves_scroll_and_loaded_knowledge_range")
        self.addCleanup(self.app.doCleanups)
        self.app.setUp()
        self.page = self.app.page
        self.page.evaluate("DecorThemes.ready")

    def appearance(self):
        return self.page.evaluate("""() => ({
            background: getComputedStyle(document.body).background,
            font: getComputedStyle(document.body).fontFamily,
            sidebar: document.querySelector('.sidebar').getBoundingClientRect().width,
            icon: getComputedStyle(document.querySelector('.nav-icon img')).visibility,
        })""")

    def test_round_trip_preserves_business_dom_form_and_dialog(self):
        original = self.appearance()
        self.page.evaluate("""() => {
            window.savedVideoNode = document.querySelector('#video-grid .video-card');
            document.querySelector('#knowledge-query').value = '防水';
            document.querySelector('#video-claims-dialog').showModal();
        }""")
        self.assertTrue(self.page.evaluate("DecorThemes.set('studio')")['applied'])
        self.assertEqual(self.page.evaluate("DecorThemes.current"), "studio")
        self.assertGreater(self.appearance()['sidebar'], original['sidebar'])
        self.assertEqual(self.appearance()['icon'], 'hidden')
        self.assertTrue(self.page.evaluate("DecorThemes.set('original')")['applied'])
        self.assertEqual(self.appearance(), original)
        self.assertTrue(self.page.evaluate("savedVideoNode === document.querySelector('#video-grid .video-card')"))
        self.assertEqual(self.page.locator('#knowledge-query').input_value(), '防水')
        self.assertTrue(self.page.locator('#video-claims-dialog').evaluate('el => el.open'))
        self.assertEqual(self.page.locator('[data-decor-theme-sheet]').count(), 0)
        self.assertEqual(self.app.errors, [])

    def test_unselected_studio_css_cannot_change_original(self):
        original = self.appearance()
        self.page.add_style_tag(url=f"http://127.0.0.1:{self.app.http.server_port}/assets/themes/studio/theme.css")
        self.assertEqual(self.appearance(), original)

    def test_switch_keeps_visible_knowledge_card_at_its_reading_position(self):
        self.page.evaluate("""() => {
            knowledgeClaims = Array.from({length: 60}, (_, index) => normalizeKnowledgeClaim({
                id: `theme-card-${index}`, video_id: 'v000', object_name: `施工检查 ${index}`,
                original_conclusion: '施工前明确材料和验收要求。', author_stance: '中性陈述',
                content_type: '施工做法', process_stage: '准备阶段', space_tags: ['全屋'],
                topic_tags: [], original_reasons: [], source_quotes: [], conditions: '未提及',
            }));
            knowledgePageState = {total:60,limit:60,offset:60,hasMore:false,loading:false,error:''};
            setView('knowledge');
        }""")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        self.page.evaluate("""() => {
            scrollTo(0, 1500);
            window.readingCard = [...document.querySelectorAll('#knowledge-results article')]
                .find(el => el.getBoundingClientRect().top >= 0);
            window.readingTop = readingCard.getBoundingClientRect().top;
        }""")
        self.page.evaluate("DecorThemes.set('studio')")
        self.assertLess(abs(self.page.evaluate('readingCard.getBoundingClientRect().top - readingTop')), 2)
        self.page.evaluate("DecorThemes.set('original')")
        self.assertLess(abs(self.page.evaluate('readingCard.getBoundingClientRect().top - readingTop')), 2)
        self.assertTrue(self.page.evaluate('readingCard.isConnected'))
        self.assertEqual(self.app.errors, [])

    def test_load_failure_and_rapid_cancellation_keep_current_theme(self):
        original = self.appearance()
        self.page.route('**/studio/theme.css?*', lambda route: route.abort())
        failed = self.page.evaluate("DecorThemes.set('studio')")
        self.assertEqual(failed['reason'], 'load_failed')
        self.assertEqual(self.appearance(), original)
        self.page.unroute('**/studio/theme.css?*')
        results = self.page.evaluate("Promise.all([DecorThemes.set('studio'), DecorThemes.set('original')])")
        self.assertEqual(results[0]['reason'], 'superseded')
        self.assertTrue(results[1]['applied'])
        self.assertEqual(self.appearance(), original)
        self.assertEqual(self.page.locator('[data-decor-theme-sheet]').count(), 0)
        invalid = self.page.evaluate("DecorThemes.set('missing')")
        self.assertEqual(invalid['reason'], 'unknown_theme')
        self.assertEqual(self.app.errors, [])

    def test_settings_buttons_persist_and_url_override_can_restore_original(self):
        self.page.locator('[data-view="settings"]').click()
        self.page.locator('[data-theme-select="studio"]').click()
        self.page.wait_for_function("DecorThemes.current === 'studio'")
        self.assertEqual(self.page.locator('[data-theme-select="studio"]').get_attribute('aria-pressed'), 'true')
        self.page.reload(wait_until='networkidle')
        self.page.wait_for_function("DecorThemes.current === 'studio'")
        self.page.goto(f"http://127.0.0.1:{self.app.http.server_port}/?theme=original#videos", wait_until='networkidle')
        self.assertEqual(self.page.evaluate('DecorThemes.current'), 'original')
        self.assertEqual(self.page.evaluate("localStorage.getItem('decor.theme.v1')"), 'studio')
        self.page.evaluate("DecorThemes.set('original')")
        self.assertEqual(self.page.evaluate("localStorage.getItem('decor.theme.v1')"), 'original')
        self.assertEqual(self.app.errors, [])
