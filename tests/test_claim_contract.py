"""First-pass source boundaries; no extra model call or approval workflow."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("decor_contract_server", ROOT / "backend/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ClaimContractTests(unittest.TestCase):
    text = "白漆先刷漆再装定制柜，彩色乳胶漆先装柜再刷漆。案例中的水电人工加辅料六千元。胶浆做法不明。今天这款净水器进群抢。"

    def claim(self, **fields):
        claim = {"claim_id": "c1", "source_scope": "general", "scope_quote": "",
                "promotion_relation": "independent", "object_name": "定制柜施工顺序",
                "author_stance": "赞成", "content_type": "施工做法",
                "original_conclusion": "白漆先刷漆再装定制柜，彩色乳胶漆先装柜再刷漆。",
                "original_reasons": [], "conditions": "按白漆和彩色乳胶漆分别处理",
                "source_quotes": ["白漆先刷漆再装定制柜，彩色乳胶漆先装柜再刷漆。"], **fields}
        claim.setdefault("field_evidence", {name: list(range(len(claim["source_quotes"])))
            for name in server.claim_contract.field_values(claim)} if isinstance(claim.get("source_quotes"), list) else {})
        return claim

    def payload(self, *claims, **fields):
        fields = copy.deepcopy(fields)
        for issue in fields.get("ambiguities", []):
            issue.setdefault("blocked_terms", [])
        return {"extraction_contract": "v11", "promotion_context": {"has_promotion": False, "subjects": []},
                "claims": list(claims), "ambiguities": [], **fields}

    def run_payload(self, payload, **kwargs):
        return server._partition_claims(payload, self.text, require_contract=True, **kwargs)

    def test_grounded_construction_without_keyword_is_preserved(self):
        clean, dropped, excluded = self.run_payload(self.payload(self.claim()))
        self.assertEqual(len(clean), 1)
        self.assertEqual((dropped, excluded), ([], []))

    def test_missing_contract_and_boundary_fields_fail_closed(self):
        for field in ("extraction_contract", "promotion_context"):
            payload = self.payload(self.claim())
            del payload[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_payload(payload)
        for field in ("claim_id", "source_scope", "scope_quote", "promotion_relation", "author_stance"):
            claim = self.claim()
            del claim[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_payload(self.payload(claim))

    def test_forged_scope_and_promotion_evidence_rejected(self):
        with self.assertRaisesRegex(ValueError, "scope_evidence"):
            self.run_payload(self.payload(self.claim(source_scope="case", scope_quote="伪造的案例证据")))
        with self.assertRaisesRegex(ValueError, "promotion_evidence"):
            self.run_payload(self.payload(promotion_context={"has_promotion": True,
                "subjects": [{"name": "净水器", "quote": "伪造的推广证据文案"}]}))

    def test_top_issue_blocks_linked_claim_not_clear_neighbor(self):
        issue = {"type": "transcription", "quote": "胶浆做法不明。", "reason": "核心做法不明", "affected_claim_ids": ["c2"]}
        uncertain = self.claim(claim_id="c2", object_name="胶浆", original_conclusion="必须做胶浆。",
                               source_quotes=[self.text])
        clean, _, excluded = self.run_payload(self.payload(self.claim(), uncertain, ambiguities=[issue]))
        self.assertEqual([item["claim_id"] for item in clean], ["c1"])
        self.assertEqual(len(excluded), 1)

    def test_unknown_ambiguity_reference_rejected(self):
        issue = {"type": "scope", "quote": "胶浆做法不明。", "reason": "不明", "affected_claim_ids": ["c9"]}
        with self.assertRaisesRegex(ValueError, "claim_reference"):
            self.run_payload(self.payload(self.claim(), ambiguities=[issue]))

    def test_unlinked_exact_quote_still_excludes_affected_card(self):
        quote = self.claim()["source_quotes"][0]
        issue = {"type": "scope", "quote": quote, "reason": "主张范围不清", "affected_claim_ids": []}
        clean, _, excluded = self.run_payload(self.payload(self.claim(), ambiguities=[issue]))
        self.assertEqual(clean, [])
        self.assertTrue(excluded)

    def test_duplicate_claim_ids_are_contract_failure(self):
        with self.assertRaisesRegex(ValueError, "duplicate_claim_id"):
            self.run_payload(self.payload(self.claim(), self.claim()))

    def test_brand_mention_alone_is_not_promotion(self):
        text = "作者建议热水器可考虑海尔和美的。"
        claim = self.claim(object_name="热水器", content_type="选购建议", original_conclusion=text,
                           conditions="未提及", source_quotes=[text])
        clean, dropped, excluded = server._partition_claims(self.payload(claim), text, require_contract=True)
        self.assertEqual(len(clean), 1)
        self.assertEqual((dropped, excluded), ([], []))

    def test_product_relation_excluded_even_without_brand_name(self):
        context = {"has_promotion": True, "subjects": [{"name": "净水器", "quote": "今天这款净水器进群抢。"}]}
        for relation in ("related", "uncertain"):
            product = self.claim(claim_id="c2", object_name="加热技术", promotion_relation=relation)
            clean, _, excluded = self.run_payload(self.payload(self.claim(), product, promotion_context=context))
            self.assertEqual([item["claim_id"] for item in clean], ["c1"])
            self.assertEqual(excluded[0]["reason"], "promotion_related_content")

    def test_known_ad_cannot_deny_promotion_context(self):
        with self.assertRaisesRegex(ValueError, "promotion_context_conflict"):
            self.run_payload(self.payload(self.claim()), video={"ad_review_override": {"decision": "advertising"}})

    def test_case_price_keeps_case_attribution_without_invented_area(self):
        quote = "案例中的水电人工加辅料六千元。"
        claim = self.claim(object_name="水电报价", original_conclusion="水电人工加辅料六千元。",
                           content_type="价格信息", source_scope="case", scope_quote=quote,
                           source_quotes=[quote], conditions="未提及", price_info="六千元")
        clean, _, _ = self.run_payload(self.payload(claim))
        self.assertTrue(clean[0]["original_conclusion"].startswith("该视频案例中"))
        self.assertNotIn("120", str(clean))
        self.assertEqual(clean[0]["source_quotes"], [quote])

    def test_vague_praise_is_not_grounded_knowledge(self):
        claim = self.claim(object_name="定制柜", original_conclusion="定制柜很好用。", conditions="未提及")
        clean, dropped, _ = self.run_payload(self.payload(claim))
        self.assertEqual(clean, [])
        self.assertEqual(dropped[0]["reason"], "no_actionable_information")

    def test_exact_duplicate_dedup_but_conditions_and_stance_survive(self):
        first = self.claim()
        duplicate = self.claim(claim_id="c2", object_name="刷漆顺序")
        different = self.claim(claim_id="c3", conditions="仅白漆")
        opposite = self.claim(claim_id="c4", author_stance="反对")
        payload = self.payload(first, duplicate, different, opposite)
        before = copy.deepcopy(payload)
        clean, dropped, _ = self.run_payload(payload)
        self.assertEqual([item["claim_id"] for item in clean], ["c1", "c3", "c4"])
        self.assertEqual(dropped[0]["reason"], "duplicate_claim")
        self.assertEqual(before["claims"][0]["source_quotes"], payload["claims"][0]["source_quotes"])

    def test_dedup_does_not_erase_decimal_or_ratio_differences(self):
        for left, right in (("厚度3.5毫米", "厚度35毫米"), ("比例1/2", "比例12"), ("范围1-2", "范围12")):
            self.assertNotEqual(server.claim_contract.duplicate_key(self.claim(original_conclusion=left)),
                                server.claim_contract.duplicate_key(self.claim(original_conclusion=right)))

    def test_malformed_quote_container_is_rejected_without_type_error(self):
        with self.assertRaisesRegex(ValueError, "quality_check_failed"):
            self.run_payload(self.payload(self.claim(source_quotes=7)))

    def test_previous_response_contract_cannot_bypass_new_dependencies(self):
        payload = self.payload(self.claim())
        payload["extraction_contract"] = "v10"
        with self.assertRaisesRegex(ValueError, "missing_extraction_contract_v11"):
            self.run_payload(payload)

    def test_every_nonempty_field_needs_its_own_binding(self):
        for field in ("object_name", "original_conclusion", "conditions", "original_reasons.0", "price_info", "alternatives.0"):
            claim = self.claim(original_reasons=["按漆的颜色处理顺序"], price_info="六千元", alternatives=["先刷漆"])
            del claim["field_evidence"][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "incomplete_field_evidence"):
                self.run_payload(self.payload(claim))

    def test_invalid_binding_indices_fail_closed(self):
        for indices in ([3], [-1], [True], [0.0], [], [0, 0], [[0]]):
            claim = self.claim()
            claim["field_evidence"]["original_conclusion"] = indices
            with self.subTest(indices=indices), self.assertRaisesRegex(ValueError, "invalid_field_evidence_reference"):
                self.run_payload(self.payload(claim))

    def test_field_cannot_borrow_number_from_other_field_quote(self):
        text = "防水涂刷二遍即可。龙骨之间间距三十公分。"
        claim = self.claim(object_name="防水", original_conclusion="防水高度三十公分。", conditions="未提及",
                           original_reasons=["龙骨间距三十公分"], source_quotes=["防水涂刷二遍即可。", "龙骨之间间距三十公分。"],
                           field_evidence={"object_name": [0], "original_conclusion": [0], "original_reasons.0": [1]})
        clean, dropped, excluded = server._partition_claims(self.payload(claim), text, require_contract=True)
        self.assertEqual(clean, [])
        self.assertIn("unsupported_field_numeric_detail:original_conclusion", str(dropped))
        self.assertTrue(excluded)

    def test_location_in_conclusion_must_be_in_its_bound_quote(self):
        text = "客厅可先打好水平线再固定型材。卧室可以采用其他做法。"
        claim = self.claim(object_name="吊顶", original_conclusion="客厅和卧室可固定型材。", conditions="未提及",
                           source_quotes=["客厅可先打好水平线再固定型材。"])
        clean, dropped, _ = server._partition_claims(self.payload(claim), text, require_contract=True)
        self.assertEqual(clean, [])
        self.assertIn("unsupported_field_location", str(dropped))

    def test_ambiguous_term_propagates_from_other_card_even_if_ids_omitted(self):
        text = "胶浆怎么做未说明。保水性特别好，失水会影响凝固。白漆先刷漆再装定制柜，彩色乳胶漆先装柜再刷漆。"
        uncertain = self.claim(claim_id="c2", object_name="胶浆做法", original_conclusion="胶浆处理后施工。",
                               conditions="未提及", source_quotes=["胶浆怎么做未说明。"], review_issues=[
                                   {"type": "transcription", "quote": "胶浆怎么做未说明。", "reason": "工艺不明确", "blocked_terms": ["胶浆"]}])
        reasoning = self.claim(claim_id="c3", object_name="脱壳原因", original_conclusion="不做胶浆处理会影响凝固。",
                              conditions="未提及", source_quotes=["保水性特别好，失水会影响凝固。"])
        clean, dropped, _ = server._partition_claims(self.payload(self.claim(), uncertain, reasoning), text, require_contract=True)
        self.assertEqual([claim["claim_id"] for claim in clean], ["c1"])
        self.assertIn("dependency", str(dropped))

    def test_forged_ambiguity_term_fails_not_global_blacklist(self):
        issue = {"type": "transcription", "quote": "胶浆做法不明。", "reason": "不明", "affected_claim_ids": [],
                 "blocked_terms": ["定制柜"]}
        with self.assertRaisesRegex(ValueError, "blocked_terms"):
            self.run_payload(self.payload(self.claim(), ambiguities=[issue]))
        self.assertEqual(len(self.run_payload(self.payload(self.claim()))[0]), 1)

    def test_material_dimension_needs_meaning_even_without_model_issue(self):
        for value in ("2", "二"):
            text = f"先固定一圈{value}公分的欧松板，然后固定型材。"
            claim = self.claim(object_name="欧松板固定", original_conclusion="固定一圈2公分的欧松板。",
                               conditions="未提及", source_quotes=[text])
            clean, _, excluded = server._partition_claims(self.payload(claim), text, require_contract=True)
            self.assertEqual(clean, [])
            self.assertIn("参数含义", str(excluded))

    def test_explicit_material_dimension_or_omitted_measurement_can_survive(self):
        for text, conclusion in (("先固定厚度2公分的欧松板，然后固定型材。", "固定厚度2公分的欧松板。"),
                                 ("先固定一圈2公分的欧松板，然后固定型材。", "固定型材。")):
            claim = self.claim(object_name="吊顶固定", original_conclusion=conclusion,
                               conditions="未提及", source_quotes=[text])
            clean, dropped, _ = server._partition_claims(self.payload(claim), text, require_contract=True)
            self.assertEqual(len(clean), 1, str(dropped))

    def test_truncated_json_or_stream_cannot_be_successful_empty(self):
        payload = {"choices": [{"finish_reason": "length", "message": {"content": '{"claims":[]}'}}]}
        stream = "data: " + json.dumps({"choices": [{"delta": {"content": '{"claims":[]}'}}]}) + "\n"
        stream += 'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\ndata: [DONE]\n'
        for raw in (json.dumps(payload), stream):
            with self.assertRaisesRegex(ValueError, "deepseek_incomplete_response"):
                server.parse_deepseek_content(raw)

    def test_bad_optional_price_does_not_discard_clear_budget_scheme(self):
        text = "整体预算分成四份，各占25%。这个金额不明的报价案例请勿照搬。"
        claim = self.claim(object_name="预算分配", original_conclusion="整体预算分成四份，各占25%。",
                           conditions="未提及", price_info="总价10000元、定制2500元",
                           source_quotes=["整体预算分成四份，各占25%。", "这个金额不明的报价案例请勿照搬。"],
                           field_evidence={"object_name": [0], "original_conclusion": [0], "price_info": [1]})
        before = copy.deepcopy(claim)
        clean, dropped, excluded = server._partition_claims(self.payload(claim), text, require_contract=True)
        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["price_info"], "未提及")
        self.assertEqual(clean[0]["original_conclusion"], before["original_conclusion"])
        self.assertEqual(clean[0]["source_quotes"], before["source_quotes"][:1])
        self.assertEqual(claim, before)
        self.assertEqual(excluded[0]["reason"], "unsupported_optional_field")
        self.assertIn("price_info", str(dropped))

    def test_bad_optional_reason_reindexes_only_remaining_evidence(self):
        text = "先刷白漆再装定制柜。此处没有提供施工报价。白漆顺序可调整。"
        claim = self.claim(object_name="白漆施工", original_conclusion="先刷白漆再装定制柜。", conditions="未提及",
                           original_reasons=["报价300元", "白漆顺序可调整。"],
                           source_quotes=["先刷白漆再装定制柜。", "此处没有提供施工报价。", "白漆顺序可调整。"],
                           field_evidence={"object_name": [0], "original_conclusion": [0],
                                           "original_reasons.0": [1], "original_reasons.1": [2]})
        clean, _, _ = server._partition_claims(self.payload(claim), text, require_contract=True)
        self.assertEqual(clean[0]["original_reasons"], ["白漆顺序可调整。"])
        self.assertEqual(clean[0]["field_evidence"]["original_reasons.0"], [1])
        self.assertEqual(clean[0]["source_quotes"], [text.split("。")[0] + "。", "白漆顺序可调整。"])

    def test_bad_conclusion_or_condition_cannot_be_saved_by_stripping_scope(self):
        text = "先刷白漆再装定制柜。"
        for fields in ({"conditions": "预算300元时"}, {"original_conclusion": "施工报价300元。"}):
            claim = self.claim(**{"object_name": "白漆施工", "original_conclusion": "先刷白漆再装定制柜。",
                                  "conditions": "未提及", "source_quotes": [text], **fields})
            clean, _, excluded = server._partition_claims(self.payload(claim), text, require_contract=True)
            self.assertEqual(clean, [])
            self.assertTrue(excluded)


if __name__ == "__main__":
    unittest.main()
