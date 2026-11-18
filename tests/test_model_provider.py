"""Selected model channels never share credentials or silently fall back."""
import json
import os
from unittest.mock import patch
import unittest

from test_deepseek_transport import server
import test_pipeline_safety as pipeline


class ModelProviderTests(unittest.TestCase):
    def setUp(self):
        settings = patch.dict(os.environ, {
            "COMMAND_CODE_API_KEY": "subscription-test-key",
            "DEEPSEEK_API_KEY": "official-test-key",
            "COMMAND_CODE_TIMEOUT_SECONDS": "180",
            "COMMAND_CODE_CONNECT_TIMEOUT_SECONDS": "8",
            "COMMAND_CODE_MAX_OUTPUT_TOKENS": "32768",
            "DEEPSEEK_TIMEOUT_SECONDS": "90",
        })
        settings.start()
        self.addCleanup(settings.stop)
        for name, value in (("LLM_PROVIDER", "command_code"),
                            ("COMMAND_CODE_MODEL", "deepseek/deepseek-v4.1-flash-fast"),
                            ("COMMAND_CODE_BASE_URL", "https://subscription.test/provider/v1"),
                            ("DEEPSEEK_GROUP", "official-only")):
            setting = patch.object(server, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        self.body = json.dumps({"choices": [{"message": {"content": '{"ok":true}'}}]})

    def test_subscription_uses_its_endpoint_key_and_model_only(self):
        with patch.object(server, "deepseek_request_once", return_value=(self.body, None)) as request:
            body, error = server.call_deepseek("Return JSON")
        self.assertIsNone(error)
        self.assertEqual(server.parse_deepseek_content(body), {"ok": True})
        request.assert_called_once()
        url, payload, key = request.call_args.args
        self.assertEqual(url, "https://subscription.test/provider/v1/chat/completions")
        self.assertEqual(key, "subscription-test-key")
        self.assertEqual(payload["model"], "deepseek/deepseek-v4.1-flash-fast")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("thinking", payload)
        self.assertNotIn("reasoning", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["max_tokens"], 32768)
        self.assertNotIn("group", payload)
        self.assertTrue(server.model_available())

    def test_subscription_failures_do_not_use_official_credit_or_retry(self):
        for error in ("deepseek_http_401: rejected", "deepseek_http_403: upgrade_required",
                      "deepseek_http_429: exhausted", "deepseek_http_503: unavailable",
                      "curl_exit_28: timed out", None):
            with self.subTest(error=error), \
                 patch.object(server, "call_deepseek_with_curl", return_value=(None, error)) as client, \
                 patch.object(server, "call_deepseek_with_urllib") as fallback, \
                 patch.object(server.time, "sleep") as sleep:
                body, message = server.call_deepseek("Return JSON")
                self.assertIsNone(body)
                client.assert_called_once()
                self.assertEqual(client.call_args.args[2], "subscription-test-key")
                self.assertTrue(message.startswith("command_code_"))
                fallback.assert_not_called()
                sleep.assert_not_called()

    def test_missing_subscription_key_cannot_borrow_official_key(self):
        with patch.dict(os.environ, {"COMMAND_CODE_API_KEY": ""}), \
             patch.object(server, "deepseek_request_once") as request:
            self.assertFalse(server.model_available())
            self.assertEqual(server.call_deepseek("test"), (None, "missing_api_key"))
        request.assert_not_called()

    def test_local_magpie_gateway_needs_no_upstream_secret(self):
        with patch.object(server, "COMMAND_CODE_BASE_URL", "http://127.0.0.1:3425/v1"), \
             patch.object(server, "COMMAND_CODE_MODEL", "commandcode/deepseek/deepseek-v4.1-flash-fast"), \
             patch.dict(os.environ, {"COMMAND_CODE_API_KEY": ""}), \
             patch.object(server, "deepseek_request_once", return_value=(self.body, None)) as request:
            self.assertTrue(server.model_available())
            body, error = server.call_deepseek("Return JSON")
        self.assertIsNone(error)
        self.assertEqual(server.parse_deepseek_content(body), {"ok": True})
        url, payload, key = request.call_args.args
        self.assertEqual(url, "http://127.0.0.1:3425/v1/chat/completions")
        self.assertEqual(payload["model"], "commandcode/deepseek/deepseek-v4.1-flash-fast")
        self.assertEqual(key, "")

    def test_no_key_gateway_failure_is_not_corrupted_by_redaction(self):
        with patch.object(server, "COMMAND_CODE_BASE_URL", "http://127.0.0.1:3425/v1"), \
             patch.dict(os.environ, {"COMMAND_CODE_API_KEY": ""}), \
             patch.object(server, "deepseek_request_once", return_value=(None, "deepseek_http_503: unavailable")):
            _, error = server.call_deepseek("test")
        self.assertEqual(error, "command_code_http_503: unavailable")

    def test_unknown_channel_is_rejected_without_a_request(self):
        with patch.object(server, "LLM_PROVIDER", "typo"), \
             patch.object(server, "deepseek_request_once") as request:
            self.assertFalse(server.model_available())
            self.assertEqual(server.call_deepseek("test"), (None, "unsupported_llm_provider"))
        request.assert_not_called()

    def test_subscription_errors_redact_the_key_and_use_its_timeout(self):
        with patch.object(server, "deepseek_request_once", return_value=(None, "deepseek_timeout: subscription-test-key")):
            _, error = server.call_deepseek("test")
        self.assertIn("180 秒", error)
        self.assertNotIn("subscription-test-key", error)
        self.assertIn("[redacted]", error)

    def test_switching_back_to_official_uses_only_official_credentials(self):
        with patch.object(server, "LLM_PROVIDER", "deepseek"), \
             patch.object(server, "deepseek_request_once", return_value=(self.body, None)) as request:
            server.call_deepseek("test")
            self.assertEqual(server.deepseek_timeout_seconds(), 90)
        self.assertEqual(request.call_args.args[2], "official-test-key")
        self.assertEqual(request.call_args.args[1]["model"], server.DEEPSEEK_MODEL)


class ModelProviderPersistenceTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    setUp = pipeline.PipelineSafetyTests.setUp
    video = pipeline.PipelineSafetyTests.video
    claim = pipeline.PipelineSafetyTests.claim
    result = pipeline.PipelineSafetyTests.result

    def test_extraction_history_records_the_selected_model(self):
        model = "deepseek/deepseek-v4.1-flash-fast"
        with patch.object(self.server, "LLM_PROVIDER", "command_code"), \
             patch.object(self.server, "COMMAND_CODE_MODEL", model), \
             patch.object(self.server, "call_deepseek", return_value=(self.result([self.claim("验收时检查插座接线。")]), None)), \
             self.server.connect() as conn:
            result = self.server.extract_claims_for_video(conn, self.server.row_to_video(self.video()))
            record = conn.execute("SELECT model FROM extraction_runs WHERE id=%s", (result["run_id"],)).fetchone()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(record["model"], model)


if __name__ == "__main__":
    unittest.main()
