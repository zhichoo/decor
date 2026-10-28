import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import server


class DeepSeekTransportTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            'DEEPSEEK_API_KEY': 'private-test-key',
            'DEEPSEEK_TIMEOUT_SECONDS': '300',
            'DEEPSEEK_CONNECT_TIMEOUT_SECONDS': '15',
            'DEEPSEEK_MAX_RETRIES': '1',
            'DEEPSEEK_THINKING': 'disabled',
        })
        env.start()
        self.addCleanup(env.stop)
        for name, value in [('DEEPSEEK_MODEL', 'deepseek-v4-pro'), ('DEEPSEEK_BASE_URL', 'https://model.test'), ('DEEPSEEK_GROUP', '')]:
            p = patch.object(server, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.body = json.dumps({'choices': [{'message': {'content': '{"claims": []}'}}]})

    def test_configured_timeouts_and_secret_cleanup(self):
        paths = []
        def run(command, **kwargs):
            self.assertEqual(command[command.index('--max-time') + 1], '300')
            self.assertEqual(command[command.index('--connect-timeout') + 1], '15')
            self.assertEqual(kwargs['timeout'], 310)
            self.assertNotIn('private-test-key', ' '.join(command))
            headers = Path(command[command.index('--config') + 1])
            payload = Path(command[command.index('--data-binary') + 1][1:])
            paths.extend([headers, payload])
            self.assertIn('Bearer private-test-key', headers.read_text())
            self.assertEqual(headers.stat().st_mode & 0o777, 0o600)
            self.assertEqual(payload.stat().st_mode & 0o777, 0o600)
            return subprocess.CompletedProcess(command, 0, self.body + '\n200', '')
        with patch.object(server.subprocess, 'run', side_effect=run):
            body, error = server.call_deepseek_with_curl('https://model.test/chat/completions', {'model': 'deepseek-v4-pro'}, 'private-test-key')
        self.assertEqual(body, self.body)
        self.assertIsNone(error)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_temporary_http_failure_retries_once_and_succeeds(self):
        with patch.object(server, 'call_deepseek_with_curl', side_effect=[(None, 'deepseek_http_503: overloaded'), (self.body, None)]) as curl, patch.object(server.time, 'sleep') as sleep:
            body, error = server.call_deepseek('test prompt')
        self.assertEqual(body, self.body)
        self.assertIsNone(error)
        self.assertEqual(curl.call_count, 2)
        sleep.assert_called_once_with(2)
        self.assertEqual(curl.call_args.args[1]['thinking'], {'type': 'disabled'})

    def test_official_flash_uses_official_url_and_non_thinking_json(self):
        with patch.object(server, 'DEEPSEEK_MODEL', 'deepseek-flash'), \
             patch.object(server, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com'), \
             patch.object(server, 'DEEPSEEK_GROUP', 'relay-only'), \
             patch.object(server, 'deepseek_request_once', return_value=(self.body, None)) as request:
            body, error = server.call_deepseek('test prompt')
        self.assertEqual(body, self.body)
        self.assertIsNone(error)
        url, payload, key = request.call_args.args
        self.assertEqual(url, 'https://api.deepseek.com/chat/completions')
        self.assertEqual(key, 'private-test-key')
        self.assertEqual(payload['model'], 'deepseek-flash')
        self.assertEqual(payload['thinking'], {'type': 'disabled'})
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertEqual(payload['max_tokens'], 8192)
        self.assertNotIn('group', payload)

    def test_official_failure_never_falls_back_to_relay(self):
        with patch.object(server, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com'), \
             patch.object(server, 'deepseek_request_once', return_value=(None, 'deepseek_http_503: busy')) as request, \
             patch.object(server.time, 'sleep'):
            body, error = server.call_deepseek('test prompt')
        self.assertIsNone(body)
        self.assertIn('deepseek_http_503', error)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(call.args[0] == 'https://api.deepseek.com/chat/completions'
                            for call in request.call_args_list))

    def test_timeout_is_explained_and_not_resubmitted(self):
        with patch.object(server, 'call_deepseek_with_curl', return_value=(None, 'curl_exit_28: Operation timed out')) as curl, patch.object(server.time, 'sleep') as sleep, patch.object(server.urllib.request, 'urlopen') as python:
            body, error = server.call_deepseek('test prompt')
        self.assertIsNone(body)
        self.assertTrue(error.startswith('deepseek_timeout:'))
        self.assertIn('300 秒', error)
        self.assertIn('共尝试 1 次', error)
        self.assertIn('文案和已有知识卡已保留', error)
        self.assertEqual(curl.call_count, 1)
        python.assert_not_called()
        sleep.assert_not_called()

    def test_auth_and_payment_errors_are_not_retried(self):
        for status in (400, 401, 402, 422):
            with self.subTest(status=status), patch.object(server, 'call_deepseek_with_curl', return_value=(None, f'deepseek_http_{status}: rejected')) as curl, patch.object(server.time, 'sleep') as sleep:
                _, error = server.call_deepseek('test prompt')
                self.assertIn(f'deepseek_http_{status}', error)
                self.assertEqual(curl.call_count, 1)
                sleep.assert_not_called()

    def test_busy_retries_but_empty_keepalive_response_does_not(self):
        for transient in ('deepseek_http_429: busy', 'deepseek_http_503: overloaded', 'deepseek_http_500: unavailable', None):
            with self.subTest(error=transient), patch.object(server, 'call_deepseek_with_curl', side_effect=[(' \n' if transient is None else None, transient), (self.body, None)]) as curl, patch.object(server.time, 'sleep'):
                body, error = server.call_deepseek('test prompt')
                if transient is not None:
                    self.assertEqual(body, self.body)
                    self.assertIsNone(error)
                    self.assertEqual(curl.call_count, 2)
                else:
                    self.assertIsNone(body)
                    self.assertEqual(error, 'deepseek_empty_response')
                    self.assertEqual(curl.call_count, 1)

    def test_v1_fallback_is_retained_on_retry(self):
        with patch.object(server, 'call_deepseek_with_curl', side_effect=[(None, 'deepseek_http_404: missing'), (None, 'deepseek_http_503: busy'), (self.body, None)]) as curl, patch.object(server.time, 'sleep'):
            body, error = server.call_deepseek('test prompt')
        self.assertIsNone(error)
        self.assertEqual(body, self.body)
        self.assertEqual([item.args[0] for item in curl.call_args_list], ['https://model.test/chat/completions', 'https://model.test/v1/chat/completions', 'https://model.test/v1/chat/completions'])

    def test_retry_can_be_disabled(self):
        with patch.dict(os.environ, {'DEEPSEEK_MAX_RETRIES': '0'}), patch.object(server, 'call_deepseek_with_curl', return_value=(None, 'deepseek_http_503: overloaded')) as curl, patch.object(server.time, 'sleep') as sleep:
            _, error = server.call_deepseek('test prompt')
        self.assertIn('deepseek_http_503', error)
        self.assertEqual(curl.call_count, 1)
        sleep.assert_not_called()

    def test_subprocess_timeout_is_sanitized(self):
        paths = []
        def run(command, **kwargs):
            paths.append(Path(command[command.index('--config') + 1]))
            raise subprocess.TimeoutExpired(['curl', '-H', 'Authorization: Bearer private-test-key'], kwargs['timeout'])
        with patch.object(server.subprocess, 'run', side_effect=run):
            body, error = server.call_deepseek_with_curl('https://model.test/chat/completions', {}, 'private-test-key')
        self.assertIsNone(body)
        self.assertIn('curl_process_timeout', error)
        self.assertNotIn('private-test-key', error)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_missing_curl_uses_python_with_same_timeout(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = self.body.encode()
        with patch.object(server, 'call_deepseek_with_curl', return_value=(None, 'curl_unavailable: cannot execute curl')), patch.object(server.urllib.request, 'urlopen', return_value=response) as python:
            body, error = server.call_deepseek('test prompt')
        self.assertEqual(body, self.body)
        self.assertIsNone(error)
        self.assertEqual(python.call_args.kwargs['timeout'], 300)

    def test_python_timeout_and_http_errors_follow_retry_policy(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = self.body.encode()
        with patch.object(server, 'call_deepseek_with_curl', return_value=(None, 'curl_unavailable: cannot execute curl')), patch.object(server.urllib.request, 'urlopen', side_effect=[TimeoutError('timed out'), response]) as python, patch.object(server.time, 'sleep'):
            body, error = server.call_deepseek('test prompt')
        self.assertIsNone(body)
        self.assertIn('deepseek_timeout', error)
        self.assertEqual(python.call_count, 1)
        rejected = urllib.error.HTTPError('https://model.test', 401, 'Unauthorized', {}, io.BytesIO(b'rejected'))
        with patch.object(server, 'call_deepseek_with_curl', return_value=(None, 'curl_unavailable: cannot execute curl')), patch.object(server.urllib.request, 'urlopen', side_effect=rejected) as python, patch.object(server.time, 'sleep') as sleep:
            _, error = server.call_deepseek('test prompt')
        self.assertIn('deepseek_http_401', error)
        self.assertEqual(python.call_count, 1)
        sleep.assert_not_called()

    def test_config_validation_and_clamping(self):
        for value, expected in [('garbage', 300), ('0', 30), ('900', 600), ('180', 180)]:
            with self.subTest(value=value), patch.dict(os.environ, {'DEEPSEEK_TIMEOUT_SECONDS': value}):
                self.assertEqual(server.deepseek_timeout_seconds(), expected)


if __name__ == '__main__':
    unittest.main()
