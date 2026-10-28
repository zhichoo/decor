"""Persistent transcription selection and health gates; no paid or production writes."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_admin_permissions as admin


class TranscriptionSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = admin.server
        cls.httpd = cls.server.ThreadingHTTPServer(('127.0.0.1', 0), admin.QuietHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'transcription-settings.local.json'
        self.addCleanup(patch.stopall)
        patch.object(self.server, 'TRANSCRIPT_SETTINGS_PATH', self.path).start()
        patch.object(self.server, 'TRANSCRIPT_PROVIDER', 'transcriptgenerate').start()
        patch.object(self.server, 'ADMIN_PASSWORD', 'test-only').start()
        self.connect = patch.object(self.server, 'connect', side_effect=AssertionError('no database needed')).start()
        self.health = patch.object(self.server, 'check_local_asr_health', return_value={
            'ready': True, 'status': 'ready', 'message': 'test ready'}).start()

    def request(self, provider=None, check=False, authenticated=True, method='POST'):
        path = '/api/settings/transcription' + ('/check-local' if check else '')
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['Cookie'] = self.server.ADMIN_SESSION_COOKIE + '=' + self.server.make_admin_session_value()
        req = urllib.request.Request(f'http://127.0.0.1:{self.httpd.server_port}' + path,
            data=json.dumps({'provider': provider}).encode() if method == 'POST' else None,
            headers=headers, method=method)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_public_get_only_exposes_provider(self):
        status, body = self.request(authenticated=False, method='GET')
        self.assertEqual((status, body), (200, {'provider': 'transcriptgenerate'}))
        self.health.assert_not_called()
        self.connect.assert_not_called()

    def test_unauthenticated_mutation_or_probe_is_rejected(self):
        for check in (False, True):
            self.assertEqual(self.request('local_asr', check=check, authenticated=False)[0], 401)
        self.health.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_local_selection_requires_successful_probe_and_persists(self):
        status, body = self.request('local_asr')
        self.assertEqual(status, 200)
        self.assertTrue(body['saved'])
        self.health.assert_called_once()
        self.assertEqual(json.loads(self.path.read_text()), {'provider': 'local_asr'})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with patch.object(self.server, 'TRANSCRIPT_PROVIDER', 'transcriptgenerate'):
            self.assertEqual(self.server.get_transcript_provider(), 'local_asr')
        self.assertEqual(self.request(method='GET')[1]['provider'], 'local_asr')
        self.connect.assert_not_called()

    def test_failed_probe_keeps_api_and_does_not_save(self):
        self.health.return_value = {'ready': False, 'status': 'unavailable', 'message': 'model missing'}
        status, body = self.request('local_asr')
        self.assertEqual(status, 503)
        self.assertFalse(body['saved'])
        self.assertEqual(body['provider'], 'transcriptgenerate')
        self.assertFalse(self.path.exists())

    def test_busy_probe_does_not_falsely_enable_local(self):
        self.health.return_value = {'ready': False, 'status': 'busy', 'message': 'worker busy'}
        self.assertEqual(self.request('local_asr')[0], 503)
        self.assertFalse(self.path.exists())

    def test_api_selection_skips_local_probe(self):
        self.path.write_text('{"provider":"local_asr"}')
        status, body = self.request('transcriptgenerate')
        self.assertEqual(status, 200)
        self.assertEqual(body['provider'], 'transcriptgenerate')
        self.health.assert_not_called()

    def test_probe_only_does_not_change_settings(self):
        status, body = self.request(check=True)
        self.assertEqual(status, 200)
        self.assertTrue(body['ready'])
        self.assertFalse(self.path.exists())
        self.assertEqual(self.server.get_transcript_provider(), 'transcriptgenerate')

    def test_unknown_provider_rejected(self):
        for value in ('evil', None, 1, []):
            self.assertEqual(self.request(value)[0], 400)
        self.health.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_failed_probe_preserves_existing_file_byte_for_byte(self):
        self.path.write_text('{"provider":"transcriptgenerate"}\n')
        before = self.path.read_bytes()
        self.health.return_value = {'ready': False, 'status': 'unavailable', 'message': 'failed'}
        self.assertEqual(self.request('local_asr')[0], 503)
        self.assertEqual(self.path.read_bytes(), before)


class LocalHealthProtocolTests(unittest.TestCase):
    def probe(self, response=None, error=None):
        with patch.object(admin.server.subprocess, 'run', return_value=response, side_effect=error):
            return admin.server.check_local_asr_health()

    def test_worker_failed_or_timed_out_returns_safe_error(self):
        failed = subprocess.CompletedProcess([], 1, '', 'private signed url or token')
        result = self.probe(failed)
        self.assertFalse(result['ready'])
        self.assertNotIn('private', result['message'])
        self.assertFalse(self.probe(error=subprocess.TimeoutExpired('probe', 45))['ready'])

    def test_probe_requires_explicit_readiness(self):
        for output in ('[]', 'null', '{}', '{"ready":true}', 'not json', '{"ready":true,"status":"busy"}'):
            self.assertFalse(self.probe(subprocess.CompletedProcess([], 0, output, ''))['ready'])

    def test_worker_success_or_busy(self):
        for ready, status in ((True, 'ready'), (False, 'busy')):
            result = self.probe(subprocess.CompletedProcess([], 0, json.dumps({
                'ready': ready, 'status': status, 'message': 'test'}), ''))
            self.assertEqual(result['ready'], ready)
            self.assertEqual(result['status'], status)
