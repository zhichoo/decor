"""Knowledge extraction must preserve usable advice and reject unsupported facts."""
import importlib.util
from decimal import Decimal
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("decor_quality_test_server", ROOT / "backend/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ClaimQualityTests(unittest.TestCase):
    def claim(self, conclusion, quote, **fields):
        return dict(object_name="厨房碗篮", stance="价格建议", original_conclusion=conclusion,
                    original_reasons=[], source_quotes=[quote], **fields)

    def check(self, claim, source):
        return server.sanitize_claims([claim], transcript_text=source, require_evidence=True)

    def test_spoken_price_can_be_written_with_digits(self):
        source = "厨房这套碗篮不到四百块，东西可以一目了然地放好。"
        kept, dropped = self.check(self.claim("厨房碗篮预算可控制在400元以内。", source), source)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_missing_decimal_cannot_be_invented(self):
        source = "玻璃厚度三十五毫米，这是文案明确给出的数字。"
        claim = self.claim("玻璃厚度建议为3.5毫米。", source)
        kept, dropped = self.check(claim, source)
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["reason"], "unsupported_numeric_detail")

    def test_rewritten_quote_is_not_verbatim_evidence(self):
        source = "厨房这套碗篮不到四百块，东西可以一目了然地放好。"
        kept, dropped = self.check(self.claim("建议按预算选择碗篮。", "厨房碗篮只要四百块"), source)
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["reason"], "unsupported_source_evidence")

    def test_clear_brand_advice_does_not_require_numeric_parameters(self):
        source = "热水器推荐海尔和美的，这是作者明确给出的选购建议。"
        claim = dict(object_name="热水器品牌", stance="明确推荐", original_conclusion="可考虑海尔和美的。",
                     original_reasons=[], source_quotes=[source])
        kept, dropped = self.check(claim, source)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_multiple_empty_speech_markers_do_not_become_a_card(self):
        source = "我跟你说家人们，厨房这套碗篮不到四百块。"
        kept, dropped = self.check(self.claim("我跟你说家人们，选碗篮就是这样。", source), source)
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["reason"], "speech_unclear")

    def test_quoted_speech_can_support_a_clean_written_card(self):
        source = "家人们我跟你说，厨房双层碗篮不到四百元，碗筷可以分类放好。"
        kept, dropped = self.check(self.claim("双层碗篮可分类收纳碗筷，案例价格不到四百元。", source), source)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_colloquial_reason_is_rejected_even_if_conclusion_is_clean(self):
        source = "碗篮分类一目了然，这是内行人的选择。"
        claim = self.claim("碗篮便于分类收纳。", source)
        claim["original_reasons"] = ["这是内行人的选择。"]
        kept, dropped = self.check(claim, source)
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["reason"], "colloquial_card_text")

    def test_chinese_numerals_do_not_mix_large_place_values(self):
        self.assertIn(Decimal("120000000"), server.numeric_evidence_values("一亿二千万"))
        self.assertNotIn(Decimal("1000020000000"), server.numeric_evidence_values("一亿二千万"))

    def test_timeout_does_not_submit_the_same_paid_request_again(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), \
             patch.object(server, "call_deepseek_with_curl", return_value=(None, "curl: (28) Operation timed out")) as client, \
             patch.object(server.urllib.request, "urlopen") as fallback:
            result, error = server.call_deepseek("test prompt")
        self.assertIsNone(result)
        self.assertIn("deepseek_timeout", error)
        self.assertEqual(client.call_count, 1)
        fallback.assert_not_called()

    def test_v4_extraction_disables_thinking_by_default(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only", "DEEPSEEK_THINKING": ""}), \
             patch.object(server, "DEEPSEEK_MODEL", "deepseek-v4-pro"), \
             patch.object(server, "call_deepseek_with_curl", return_value=(None, "deepseek_http_401: test")) as client:
            server.call_deepseek("test prompt")
        payload = client.call_args.args[1]
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)
        self.assertGreaterEqual(payload["max_tokens"], 8192)

    def test_v4_thinking_is_explicitly_configurable(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only", "DEEPSEEK_THINKING": "enabled", "DEEPSEEK_REASONING_EFFORT": "low"}), \
             patch.object(server, "DEEPSEEK_MODEL", "deepseek-v4-pro"), \
             patch.object(server, "call_deepseek_with_curl", return_value=(None, "deepseek_http_401: test")) as client:
            server.call_deepseek("test prompt")
        payload = client.call_args.args[1]
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "low")

    def test_authentication_failure_does_not_retry_another_http_client(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), \
             patch.object(server, "call_deepseek_with_curl", return_value=(None, "deepseek_http_401: authentication failed")) as client, \
             patch.object(server.urllib.request, "urlopen") as fallback:
            result, error = server.call_deepseek("test prompt")
        self.assertIsNone(result)
        self.assertIn("deepseek_http_401", error)
        self.assertEqual(client.call_count, 1)
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
