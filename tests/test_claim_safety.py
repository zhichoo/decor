"""Concrete P1 counterexamples, including preservation of valid short/source-scoped claims."""
import copy
import unittest
from unittest.mock import Mock, patch

import test_claim_contract as contract

server = contract.server
safety = server.claim_safety


class ClaimSafetyTests(unittest.TestCase):
    def payload(self, quote, conclusion, **fields):
        return {"extraction_contract": "v12", "promotion_context": {"has_promotion": False, "subjects": []},
                "filter_reason": "none", "ambiguities": [], "claims": [{
                    "object_name": "装修做法", "author_stance": "赞成", "content_type": "施工做法",
                    "source_scope": "general", "scope_quote": "", "promotion_relation": "independent",
                    "statement": {"text": conclusion, "quote": quote}, "condition": None, "price": None,
                    "reasons": [], "alternatives": [], **fields}]}

    def partition(self, payload, transcript):
        return server._partition_claims(server.claim_wire.normalize_legacy(payload, transcript), transcript, require_contract=True)

    def test_missing_explicit_condition_is_excluded(self):
        text = "只有层高超过2.7米且愿意吊顶时，才建议考虑无主灯设计。"
        payload = self.payload(text, "所有住宅都适合无主灯设计。")
        clean, _, excluded = self.partition(payload, text)
        self.assertFalse(clean)
        self.assertIn("explicit_condition_not_preserved", str(excluded))

    def test_descriptive_conditional_cannot_become_unconditional_cause(self):
        text = "如果没有这一层胶浆，那么下边的半干砂浆。\n就会吸走粘接剂里的水分，影响凝固。"
        payload = self.payload(text, "半干砂浆会吸走粘接剂里的水分，影响凝固。")
        clean, _, excluded = self.partition(payload, text)
        self.assertFalse(clean)
        self.assertIn("explicit_condition_not_preserved", str(excluded))
        payload["claims"][0]["condition"] = {"text": "没有这一层胶浆", "quote": text}
        clean, dropped, _ = self.partition(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_descriptive_condition_guard_does_not_import_other_sentence(self):
        text = "施工前应检查线路。如果预算不足，那么需要调整采购计划。"
        payload = self.payload("施工前应检查线路。", "施工前应检查线路。")
        clean, dropped, _ = self.partition(payload, text)
        self.assertEqual(len(clean), 1, dropped)

    def test_condition_can_be_in_conclusion_or_separate_field(self):
        text = "只有层高超过2.7米且愿意吊顶，才建议考虑无主灯设计。"
        for in_conclusion in (True, False):
            payload = self.payload(text, "层高大于270厘米且愿意吊顶时，可以考虑无主灯。" if in_conclusion else "可以考虑无主灯。")
            if not in_conclusion:
                payload["claims"][0]["condition"] = {"text": "层高超过2.7米且愿意吊顶", "quote": text}
            clean, dropped, excluded = self.partition(payload, text)
            self.assertEqual(len(clean), 1, (dropped, excluded))

    def test_reversed_condition_not_accepted(self):
        text = "只有层高超过2.7米且愿意吊顶，才建议考虑无主灯设计。"
        payload = self.payload(text, "层高低于2.7米且愿意吊顶时，可以考虑无主灯。")
        clean, _, excluded = self.partition(payload, text)
        self.assertFalse(clean)
        self.assertIn("explicit_condition_not_preserved", str(excluded))

    def test_citing_only_consequence_cannot_hide_antecedent(self):
        text = "如果预算有限，就建议保留原来的灯具。"
        clean, _, excluded = self.partition(self.payload("就建议保留原来的灯具。", "建议保留原来的灯具。"), text)
        self.assertFalse(clean)
        self.assertIn("explicit_condition_not_preserved", str(excluded))

    def test_unrelated_neighbor_condition_does_not_delete_clear_card(self):
        quote = "铺贴前应清理基层的浮灰。"
        text = quote + "如果预算有限，就建议保留原来的灯具。"
        clean, dropped, excluded = self.partition(self.payload(quote, "铺贴前应清理基层浮灰。"), text)
        self.assertEqual(len(clean), 1, (dropped, excluded))

    def test_missing_background_is_not_a_condition_error(self):
        text = "我家在南方，这次安装了定制柜。"
        clean, dropped, excluded = self.partition(self.payload(text, "该案例安装了定制柜。",
            source_scope="case", scope_quote=text), text)
        self.assertEqual(len(clean), 1, (dropped, excluded))

    def test_quantity_units_roles_and_rates_cannot_be_swapped(self):
        pairs = [("石膏板厚度9毫米。", "石膏板厚度9厘米。"),
                 ("木板宽度9毫米，厚度3毫米。", "木板厚度9毫米。"),
                 ("防水需要刷3遍。", "防水需要刷3层。"),
                 ("施工单价300元/平。", "施工总价300元。"),
                 ("吸水率为10%。", "吸水率为10成。")]
        for quote, conclusion in pairs:
            with self.subTest(quote=quote, conclusion=conclusion):
                clean, _, excluded = self.partition(self.payload(quote, conclusion), quote)
                self.assertFalse(clean)
                self.assertIn("unsupported_quantity", str(excluded))

    def test_exact_unit_conversions_and_chinese_numbers_are_supported(self):
        pairs = [("板材厚度三十毫米。", "板材厚度3厘米。"),
                 ("实际预算一万元。", "预算10000元。"),
                 ("需要等待两小时。", "需要等待120分钟。"),
                 ("吸水率为百分之十。", "吸水率为10%。"),
                 ("材料价格三百元/平方米。", "材料价格300元/平。"),
                 ("房屋面积90平方米。", "房屋面积90㎡。")]
        pairs += [("板材采用9毫米厚的规格。", "板材厚度9毫米。"),
                  ("材料每平方米三百元。", "材料单价300元/平。"),
                  ("材料单价300元/平方米。", "材料价格300元一平。"),
                  ("保养后还能使用三五年。", "保养后还能使用三五年。")]
        for quote, conclusion in pairs:
            with self.subTest(quote=quote, conclusion=conclusion):
                clean, dropped, excluded = self.partition(self.payload(quote, conclusion), quote)
                self.assertEqual(len(clean), 1, (dropped, excluded))

    def test_verbatim_dimension_without_unit_is_excluded_not_guessed(self):
        for quote in ("贴砖留缝必须2.5，后期做美缝才不掉。", "板材厚度是9。", "吊顶间距控制在40左右。"):
            with self.subTest(quote=quote):
                clean, _, excluded = self.partition(self.payload(quote, quote), quote)
                self.assertFalse(clean)
                self.assertIn("missing_measurement_unit", str(excluded))

    def test_dimension_with_unit_range_and_nonmeasurement_numbers_stay_valid(self):
        for quote in ("贴砖留缝必须2.5毫米。", "板材厚度9毫米。", "留缝2到3毫米。", "宽度20-25厘米。", "施工步骤分为3步。"):
            with self.subTest(quote=quote):
                self.assertEqual(safety.numeric_errors(quote, quote, server.numeric_evidence_values), [])

    def test_approximate_chinese_range_must_not_be_interpreted_as_exact_value(self):
        quote = "保养后还能使用三五年。"
        clean, _, excluded = self.partition(self.payload(quote, "保养后还能使用35年。"), quote)
        self.assertFalse(clean)
        self.assertIn("unsupported_quantity", str(excluded))

    def test_counterfactual_reason_is_not_automatically_an_applicability_requirement(self):
        quote = "要是刮大白完事了之后，再开槽就需要返工，所以应提前确认主灯位置。"
        clean, dropped, excluded = self.partition(self.payload(quote, "应提前确认主灯位置，避免后期开槽返工。"), quote)
        self.assertEqual(len(clean), 1, (dropped, excluded))

    def test_question_and_redundant_scope_phrasing_do_not_create_false_missing_conditions(self):
        pairs = [("先做木工，前提是什么呢？拆改不能太多。", "拆改不能太多时先做木工。"),
                 ("如果有特殊的需求，可以装磁控百叶帘。", "有特殊需求时可装磁控百叶帘。"),
                 ("只适用一个地方，就是悬浮铺贴的木地板。", "只适用于悬浮铺贴的木地板。")]
        for quote, conclusion in pairs:
            with self.subTest(quote=quote):
                clean, dropped, excluded = self.partition(self.payload(quote, conclusion), quote)
                self.assertEqual(len(clean), 1, (dropped, excluded))

    def test_optional_quantity_error_is_pruned_but_core_survives(self):
        quote = "板材厚度9毫米，基层需要清理浮灰。"
        payload = self.payload(quote, "基层需要清理浮灰。", reasons=[{"text": "板材厚度9厘米", "quote": quote}])
        clean, dropped, _ = self.partition(payload, quote)
        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["original_reasons"], [])
        self.assertIn("unsupported_optional_field", str(dropped))

    def test_short_scope_issue_links_without_blocked_terms_and_keeps_neighbor(self):
        quote = "厨房可考虑开放式布局，但这里说的是示范间，不是所有住宅。"
        neighbor = "铺贴前需要清理基层浮灰。"
        payload = self.payload(quote, "厨房都应采用开放式布局。")
        payload["claims"] += self.payload(neighbor, "铺贴前需要清理基层浮灰。", object_name="清理基层")["claims"]
        payload["ambiguities"] = [{"type": "scope", "quote": "这里说的是示范间", "reason": "范围不清",
                                   "blocked_terms": []}]
        clean, _, excluded = self.partition(payload, quote + neighbor)
        self.assertEqual([item["object_name"] for item in clean], ["清理基层"])
        self.assertTrue(excluded)

    def test_term_ambiguity_in_long_quote_does_not_erase_independent_clear_scheme(self):
        quote = "装修预算分成轻工辅料、主材、定制、家具家电四份，各占25%。主材里面有铝库板、地脚线等等。"
        payload = self.payload(quote, "装修预算分成轻工辅料、主材、定制、家具家电四份，各占25%。")
        payload["ambiguities"] = [{"type": "transcription", "quote": "主材里面有铝库板、地脚线等等。",
                                   "reason": "材料名无法确认", "blocked_terms": ["铝库板"]}]
        clean, dropped, _ = self.partition(payload, quote)
        self.assertEqual(len(clean), 1, dropped)

    def test_no_input_never_calls_model_or_replaces_existing_cards(self):
        for text in (None, "", "太短", "......"):
            with self.subTest(text=text), patch.object(server, "call_deepseek") as model, \
                    patch.object(server, "replace_claims_and_status") as replace:
                with self.assertRaisesRegex(ValueError, "insufficient_transcript_evidence"):
                    server.extract_claims_for_video_locked(None, {"id": "test", "transcript_text": text})
                model.assert_not_called()
                replace.assert_not_called()

    def test_clear_short_input_reaches_model_without_early_replacement(self):
        text = "吸水率高的瓷砖，铺贴前需要泡水两小时。"
        conn = Mock()
        with patch.object(server, "call_deepseek", side_effect=RuntimeError("reached_model")) as model, \
                patch.object(server, "replace_claims_and_status") as replace:
            with self.assertRaisesRegex(RuntimeError, "reached_model"):
                server.extract_claims_for_video_locked(conn, {"id": "test", "title": "测试", "creator": "测试",
                    "platform": "test", "source_url": "https://example.invalid", "transcript_text": text})
            model.assert_called_once()
            replace.assert_not_called()
