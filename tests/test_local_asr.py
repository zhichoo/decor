"""Local ASR routing and data safety against disposable PostgreSQL."""
import concurrent.futures
import time
import importlib.util
import json
import os
import threading
import urllib.request
import urllib.error
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import test_pipeline_safety as pipeline

REAL_RUN = subprocess.run
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('local_asr_test_module', ROOT / 'backend/local_asr.py')
asr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(asr)


class MediaSafetyTests(unittest.TestCase):
    def test_allowlist(self):
        self.assertTrue(asr.media_url_allowed('https://v3.douyinvod.com/video/tos/test'))
        for url in ('http://v3.douyinvod.com/x', 'https://douyinvod.com.evil.test/x',
                    'https://127.0.0.1/x', 'https://evil.test/x', 'https://user@douyinvod.com/x'):
            self.assertFalse(asr.media_url_allowed(url))

    def test_media_belongs_to_requested_video(self):
        payload = [{'aweme_id': '123', 'video': {'play_addr': {'url_list': ['https://v3.douyinvod.com/a']}}},
                   {'aweme_id': '456', 'video': {'play_addr': {'url_list': ['https://v3.douyinvod.com/b']}}}]
        self.assertEqual(asr.find_media(payload, '123'), ['https://v3.douyinvod.com/a'])
        self.assertEqual(asr.find_media(payload, '999'), [])

    def test_private_video_reports_access_failure_not_login_failure(self):
        error = asr.video_access_error({
            'status_code': 0, 'aweme_detail': None,
            'filter_detail': {'aweme_id': '123', 'filter_reason': 'status_self_see',
                              'detail_msg': '因作品权限或已被删除，无法观看'},
        }, '123')
        self.assertIn('local_asr_video_unavailable', error)
        self.assertIn('status_self_see', error)
        self.assertIn('权限', error)
        self.assertNotIn('check Douyin login', error)

    def test_access_failure_ignores_other_videos_and_success(self):
        rejection = {'filter_detail': {'aweme_id': '456', 'filter_reason': 'status_self_see'}}
        self.assertIsNone(asr.video_access_error(rejection, '123'))
        self.assertIsNone(asr.video_access_error({}, '123'))
        self.assertIsNone(asr.video_access_error(None, '123'))
        self.assertIsNone(asr.video_access_error({**rejection, 'aweme_detail': {'aweme_id': '456'}}, '456'))

    def test_access_error_does_not_echo_platform_secrets(self):
        error = asr.video_access_error({'filter_detail': {
            'aweme_id': '123', 'filter_reason': 'https://example.invalid/signed-secret',
            'detail_msg': 'private-session-secret',
        }}, '123')
        self.assertIn('access_restricted', error)
        self.assertNotIn('secret', error)

    def test_downloader_exits_on_matching_platform_access_rejection(self):
        context = MagicMock()
        page = context.new_page.return_value
        response = MagicMock()
        response.url = 'https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=123'
        response.headers = {'content-type': 'application/json'}
        response.json.return_value = {'aweme_detail': None, 'filter_detail': {
            'aweme_id': '123', 'filter_reason': 'status_self_see',
        }}
        callbacks = {}
        page.on.side_effect = lambda event, callback: callbacks.update({event: callback})
        page.goto.side_effect = lambda *_args, **_kwargs: callbacks['response'](response)
        collector = SimpleNamespace(launch_context=MagicMock(return_value=context))
        with patch.dict(sys.modules, {'collector_douyin': collector}), \
                patch('playwright.sync_api.sync_playwright'), \
                patch.object(asr.urllib.request, 'build_opener') as download:
            with self.assertRaisesRegex(RuntimeError, 'local_asr_video_unavailable.*status_self_see'):
                asr.download_video('https://www.douyin.com/video/123', '/tmp/not-used')
        context.close.assert_called_once()
        page.wait_for_timeout.assert_not_called()
        download.assert_not_called()

    def test_non_douyin_input_rejected_before_browser(self):
        with self.assertRaisesRegex(RuntimeError, 'canonical_douyin'):
            asr.download_video('http://127.0.0.1/private', '/tmp/not-used')

    def test_script_read_retries_after_navigation(self):
        from playwright.sync_api import Error
        page = MagicMock()
        page.locator.return_value.all_text_contents.side_effect = [
            Error('Execution context was destroyed, most likely because of a navigation'), ['{}']]
        self.assertEqual(asr.read_page_scripts(page), [])
        self.assertEqual(asr.read_page_scripts(page), ['{}'])

    def test_unrelated_browser_error_is_not_swallowed(self):
        from playwright.sync_api import Error
        page = MagicMock()
        page.locator.return_value.all_text_contents.side_effect = Error('Target page has been closed')
        with self.assertRaisesRegex(Error, 'closed'):
            asr.read_page_scripts(page)


class LocalASRTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    video = pipeline.PipelineSafetyTests.video
    active = pipeline.PipelineSafetyTests.active
    claims = pipeline.PipelineSafetyTests.claims

    def setUp(self):
        pipeline.PipelineSafetyTests.setUp(self)
        self.addCleanup(patch.stopall)
        patch.object(self.server, 'TRANSCRIPT_PROVIDER', 'local_asr').start()
        self.remote = patch.object(self.server, 'fetch_transcript_from_transcriptgenerate',
                                  side_effect=AssertionError('no remote ASR')).start()
        self.extract = patch.object(self.server, 'call_deepseek', side_effect=AssertionError('no LLM')).start()
        self.text = '这是本地语音识别的完整文字。' * 15
        self.worker = patch.object(self.server.subprocess, 'run', return_value=subprocess.CompletedProcess(
            [], 0, json.dumps({'transcript_text': self.text, 'model': 'SenseVoiceSmall-int8',
                              'audio_seconds': 30, 'elapsed_seconds': 4}), '')).start()

    def empty(self):
        with self.server.connect() as conn:
            conn.execute("UPDATE videos SET transcript_text=NULL,has_transcript=false,transcript_length=0,source_url='https://www.douyin.com/video/123'")

    def save(self):
        with self.server.connect() as conn:
            return self.server.save_transcript_for_video(conn, self.video())

    def test_success_saved_with_local_provenance_and_no_extraction(self):
        self.empty()
        before = self.claims()
        self.save()
        row = self.video()
        self.assertEqual(row['transcript_text'], self.text)
        self.assertTrue(row['transcript_source'].startswith('LocalASR/SenseVoiceSmall-int8/'))
        self.assertEqual(row['transcript_job']['state'], 'succeeded')
        self.assertEqual(row['transcript_job']['provider'], 'local_asr')
        self.assertEqual(self.claims(), before)
        self.remote.assert_not_called()
        self.extract.assert_not_called()

    def test_existing_transcript_never_runs_worker(self):
        before = self.video()
        self.save()
        self.assertEqual(self.video(), before)
        self.worker.assert_not_called()

    def test_private_video_failure_keeps_specific_reason_and_original_data(self):
        before, claims = self.video(), self.claims()
        error = 'local_asr_video_unavailable: access restricted (status_self_see)'
        self.worker.return_value = subprocess.CompletedProcess([], 1, '', json.dumps({'error': error}))
        with self.server.connect() as conn:
            with self.assertRaisesRegex(RuntimeError, 'status_self_see'):
                self.server.save_transcript_for_video(conn, before, refresh=True)
        after = self.video()
        self.assertEqual(after['transcript_job']['error'], error)
        self.assertEqual(after['transcript_text'], before['transcript_text'])
        self.assertEqual(after['transcript_source'], before['transcript_source'])
        self.assertEqual(self.claims(), claims)
        self.remote.assert_not_called()

    def test_failure_keeps_original_text_and_cards(self):
        before = self.video()
        self.worker.return_value = subprocess.CompletedProcess([], 1, '', '{"error":"local_asr_media_unavailable"}')
        with self.server.connect() as conn:
            with self.assertRaisesRegex(RuntimeError, 'media_unavailable'):
                self.server.save_transcript_for_video(conn, before, refresh=True)
        after = self.video()
        for field in ('transcript_text', 'transcript_source', 'status'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after['transcript_job']['state'], 'failed')
        self.assertEqual([r['id'] for r in self.active()], ['old'])

    def test_local_failure_can_retry(self):
        self.empty()
        self.worker.side_effect = [subprocess.CompletedProcess([], 1, '', '{"error":"local_asr_failed"}'),
                                   subprocess.CompletedProcess([], 0, json.dumps({'transcript_text': self.text}), '')]
        with self.assertRaises(RuntimeError):
            self.save()
        self.save()
        self.assertEqual(self.video()['transcript_text'], self.text)

    def test_manual_edit_during_asr_wins(self):
        self.empty()
        def worker(*args, **kwargs):
            with self.server.connect() as conn:
                conn.execute('UPDATE videos SET transcript_text=%s WHERE id=%s', ('manual text', self.video_id))
            return subprocess.CompletedProcess([], 0, json.dumps({'transcript_text': self.text}), '')
        self.worker.side_effect = worker
        self.save()
        self.assertEqual(self.video()['transcript_text'], 'manual text')
        self.assertTrue(self.video()['transcript_job']['preserved_manual'])

    def test_unknown_provider_fails_closed(self):
        self.empty()
        with patch.object(self.server, 'TRANSCRIPT_PROVIDER', 'unknown'):
            with self.assertRaisesRegex(RuntimeError, 'unsupported_transcript_provider'):
                self.save()
        self.worker.assert_not_called()

    def test_old_paid_pending_task_not_recreated_locally(self):
        self.empty()
        with self.server.connect() as conn:
            self.server.write_transcript_job(conn, self.video_id, {'provider':'transcriptgenerate', 'task_id':'paid-1', 'state':'pending'})
        with self.assertRaisesRegex(RuntimeError, 'requires_reconciliation'):
            self.save()
        self.worker.assert_not_called()

    def test_http_auth_and_existing_text_short_circuit(self):
        self.empty()
        server = self.server
        class QuietHandler(server.AppHandler):
            def log_message(self, *_):
                pass
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server, 'ADMIN_PASSWORD', 'test-only'), patch.dict(server.DB_STATUS, {'available': True}):
                for authenticated, expected in ((False, 401), (True, 200), (True, 200)):
                    headers = {'Content-Type': 'application/json'}
                    if authenticated:
                        headers['Cookie'] = server.ADMIN_SESSION_COOKIE + '=' + server.make_admin_session_value()
                    request = urllib.request.Request(
                        f'http://127.0.0.1:{httpd.server_port}/api/videos/{self.video_id}/transcript/retry',
                        data=b'{}', headers=headers, method='POST')
                    try:
                        response = urllib.request.urlopen(request, timeout=10)
                    except urllib.error.HTTPError as exc:
                        response = exc
                    with response:
                        self.assertEqual(response.status, expected)
                        body = json.load(response)
                    if authenticated:
                        self.assertEqual(body['video']['transcript_text'], self.text)
            self.worker.assert_called_once()
            self.remote.assert_not_called()
            self.extract.assert_not_called()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    @unittest.skipUnless(os.environ.get('ASR_LIVE_TEST_MEDIA'), 'optional real CPU model test')
    def test_real_model_saved_to_isolated_database(self):
        self.empty()
        def worker(command, **kwargs):
            command[-2:] = ['--media-file', os.environ['ASR_LIVE_TEST_MEDIA']]
            return REAL_RUN(command, **kwargs)
        self.worker.side_effect = worker
        self.save()
        row = self.video()
        self.assertGreater(len(row['transcript_text']), 100)
        self.assertEqual(row['transcript_job']['state'], 'succeeded')
        self.assertTrue(row['transcript_source'].startswith('LocalASR/'))
        self.assertEqual([r['id'] for r in self.active()], ['old'])
        self.remote.assert_not_called()
        self.extract.assert_not_called()

    def test_concurrent_local_requests_run_worker_once(self):
        self.empty()
        entered = threading.Event()
        response = self.worker.return_value
        def worker(*args, **kwargs):
            entered.set()
            time.sleep(0.1)
            return response
        self.worker.side_effect = worker
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.save)
            self.assertTrue(entered.wait(5))
            second = pool.submit(self.save)
            self.assertEqual(first.result(timeout=10)[0]['transcript_text'], self.text)
            self.assertEqual(second.result(timeout=10)[0]['transcript_text'], self.text)
        self.worker.assert_called_once()
        self.remote.assert_not_called()

    def test_current_setting_is_read_when_starting_a_new_job(self):
        self.empty()
        with patch.object(self.server, 'get_transcript_provider', return_value='transcriptgenerate'):
            with self.assertRaisesRegex(AssertionError, 'no remote ASR'):
                self.save()
        self.worker.assert_not_called()

    def test_recovering_local_job_keeps_local_route_after_switch_to_api(self):
        self.empty()
        with self.server.connect() as conn:
            self.server.write_transcript_job(conn, self.video_id, {'provider':'local_asr', 'state':'running', 'task_id':'local-old'})
        with patch.object(self.server, 'get_transcript_provider', return_value='transcriptgenerate'):
            self.save()
        self.assertEqual(self.video()['transcript_text'], self.text)
        self.worker.assert_called_once()
        self.remote.assert_not_called()
