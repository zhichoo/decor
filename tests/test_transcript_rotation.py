"""Task rotation against disposable PostgreSQL and a fake upstream (no paid calls)."""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_pipeline_safety as pipeline

ROOT = Path(__file__).resolve().parents[1]


class TranscriptRotationTests(unittest.TestCase):
    setUpClass = classmethod(pipeline.PipelineSafetyTests.setUpClass.__func__)
    tearDownClass = classmethod(pipeline.PipelineSafetyTests.tearDownClass.__func__)
    video = pipeline.PipelineSafetyTests.video
    active = pipeline.PipelineSafetyTests.active
    claims = pipeline.PipelineSafetyTests.claims

    def setUp(self):
        pipeline.PipelineSafetyTests.setUp(self)
        with self.server.connect() as c:
            c.execute("UPDATE videos SET transcript_text=NULL,has_transcript=false,transcript_length=0,status='created'")
        self.accounts = [self.server.normalize_transcript_account({
            'id': name, 'email': name + '@example.invalid', 'password': 'fake-password',
            'token': 'fake-token-' + name,
        }, index) for index, name in enumerate(('a', 'b', 'c'))]
        self.quotas = dict.fromkeys(('a', 'b', 'c'), 10)
        self.calls = []
        self.text = '转写成功后的完整文案。' * 20
        self.query_status = 'SUCCESS'
        self.create_error = None
        self.create_response = None
        self.on_query = None
        self.addCleanup(patch.stopall)
        patch.object(self.server, 'TRANSCRIPT_ACCOUNTS', self.accounts).start()
        patch.object(self.server, 'TRANSCRIPT_POLL_INTERVAL_SECONDS', 0).start()
        patch.object(self.server, 'TRANSCRIPT_MAX_POLLS', 1).start()
        patch.object(self.server, 'transcript_request_once', side_effect=self.upstream).start()
        self.model = patch.object(self.server, 'call_deepseek', side_effect=AssertionError('no extraction during transcription')).start()
        self.extract = patch.object(self.server, 'extract_claims_for_video', side_effect=AssertionError('no automatic extraction')).start()

    def upstream(self, path, method='GET', account=None, **kwargs):
        self.assertIsNotNone(account)
        account_id = account['id']
        self.calls.append((path, account_id, kwargs))
        if path == '/login':
            return {'code': 200, 'token': 'new-fake-' + account_id}
        if path == '/ai-face/userBenefitsAndUsage':
            return {'code': 200, 'data': {'benefits': [{
                'functionKey': 'VIDEO_TO_TEXT', 'remainingAmount': self.quotas[account_id],
                'totalQuota': 10, 'isLimitReached': self.quotas[account_id] == 0,
            }]}}
        if path == '/transcript/createTask':
            # Commit boundaries are checked from a different physical connection.
            with self.server.connect() as c:
                row = c.execute("SELECT transcript_job FROM videos WHERE source_url=%s", (kwargs['payload']['workUrl'],)).fetchone()
                self.assertEqual(row['transcript_job']['state'], 'creating')
                self.assertEqual(row['transcript_job']['account_id'], account_id)
            if self.create_error:
                raise self.create_error
            return self.create_response or {'code': 200, 'data': 'task-' + account_id + '-' + str(len(self.calls))}
        if path == '/transcript/queryTask':
            task_id = kwargs['params']['taskId']
            with self.server.connect() as c:
                row = c.execute("SELECT transcript_job FROM videos WHERE transcript_job->>'task_id'=%s", (task_id,)).fetchone()
                self.assertEqual(row['transcript_job']['account_id'], account_id)
                self.assertEqual(row['transcript_job']['task_id'], task_id)
            if self.on_query:
                self.on_query()
            return {'code': 200, 'data': {'status': self.query_status, 'textContent': self.text,
                                         'title': '标题不是文案'}}
        raise AssertionError(path)

    def save(self, video_id=None, refresh=False):
        with self.server.connect() as c:
            row = c.execute('SELECT * FROM videos WHERE id=%s', (video_id or self.video_id,)).fetchone()
            return self.server.save_transcript_for_video(c, row, refresh=refresh)

    def add_video(self, video_id):
        with self.server.connect() as c:
            c.execute("""INSERT INTO videos(id,platform,creator,title,source_url,created_at,updated_at)
                      VALUES(%s,'test','test',%s,%s,1,1)""", (video_id, video_id, 'https://example.invalid/' + video_id))

    def creates(self):
        return [(a, kw) for path, a, kw in self.calls if path == '/transcript/createTask']

    def test_round_robin_commits_before_create_and_poll_and_saves_without_extraction(self):
        self.save()
        for name in ('v2', 'v3', 'v4'):
            self.add_video(name)
            self.save(name)
        self.assertEqual([a for a, _ in self.creates()], ['a', 'b', 'c', 'a'])
        self.assertEqual(self.video()['transcript_text'], self.text)
        self.assertEqual(self.video()['transcript_job']['state'], 'succeeded')
        self.assertEqual(self.video()['transcript_job']['provider'], 'transcriptgenerate')
        self.assertEqual([r['id'] for r in self.active()], ['old'])
        self.extract.assert_not_called()
        self.model.assert_not_called()
        self.assertNotIn('fake-password', json.dumps(self.video()['transcript_job']))
        self.assertNotIn('fake-token', json.dumps(self.video()['transcript_job']))

    def test_skips_exhausted_and_failed_login_before_creation(self):
        self.quotas['a'] = 0
        self.accounts[1]['runtime_token'] = ''
        original = self.upstream

        def requests(path, **kwargs):
            if path == '/login' and kwargs['account']['id'] == 'b':
                raise RuntimeError('login rejected')
            return original(path, **kwargs)

        with patch.object(self.server, 'transcript_request_once', side_effect=requests):
            self.save()
        self.assertEqual([a for a, _ in self.creates()], ['c'])

    def test_login_and_auth_refresh_stay_with_selected_account(self):
        self.accounts[0]['runtime_token'] = ''
        self.save()
        self.assertEqual(self.calls[0][:2], ('/login', 'a'))
        self.assertEqual(self.video()['transcript_job']['account_id'], 'a')

    def test_all_exhausted_does_not_submit_or_change_transcript(self):
        self.quotas = dict.fromkeys(self.quotas, 0)
        with self.assertRaisesRegex(RuntimeError, '额度不足'):
            self.save()
        self.assertFalse(self.creates())
        self.assertIsNone(self.video()['transcript_job'])
        self.assertEqual([r['id'] for r in self.active()], ['old'])

    def test_ambiguous_create_blocks_all_future_submission_even_after_restart(self):
        self.create_error = TimeoutError('network timed out fake-password fake-token-a')
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, '创建结果不明'):
                self.save()
        self.assertEqual(len(self.creates()), 1)
        job = self.video()['transcript_job']
        self.assertEqual((job['state'], job['account_id']), ('creation_uncertain', 'a'))
        self.assertNotIn('fake-password', job['error'])
        self.assertNotIn('fake-token-a', job['error'])
        self.assertEqual([r['id'] for r in self.active()], ['old'])

    def test_missing_task_id_is_not_recreated(self):
        self.create_response = {'code': 200, 'data': {}}
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, '创建结果不明'):
                self.save()
        self.assertEqual(len(self.creates()), 1)

    def test_quota_rejection_does_not_hidden_resend_next_manual_attempt_uses_next(self):
        self.create_response = {'code': 601, 'msg': '权益次数不足'}
        with self.assertRaises(self.server.TranscriptQuotaError):
            self.save()
        self.assertEqual([a for a, _ in self.creates()], ['a'])
        self.assertEqual(self.video()['transcript_job']['state'], 'rejected')
        self.create_response = None
        self.save()
        self.assertEqual([a for a, _ in self.creates()], ['a', 'b'])

    def test_restart_resumes_original_task_even_with_disabled_exhausted_account(self):
        self.query_status = 'PROCESSING'
        with self.assertRaisesRegex(RuntimeError, '超时'):
            self.save()
        task_id = self.video()['transcript_job']['task_id']
        # Lose all runtime objects, cursor and tokens, as after a restart.
        restored = [self.server.normalize_transcript_account({
            'id': a['id'], 'email': a['email'], 'password': 'fake-password', 'enabled': False,
        }, i) for i, a in enumerate(reversed(self.accounts))]
        self.query_status = 'SUCCESS'
        self.quotas = dict.fromkeys(self.quotas, 0)
        with patch.object(self.server, 'TRANSCRIPT_ACCOUNTS', restored):
            self.save()
        self.assertEqual(len(self.creates()), 1)
        queries = [(a, kw['params']['taskId']) for p, a, kw in self.calls if p.endswith('/queryTask')]
        self.assertEqual(queries, [('a', task_id), ('a', task_id)])
        self.assertEqual(self.video()['transcript_job']['state'], 'succeeded')

    def test_query_error_and_failed_task_keep_task_and_never_rotate(self):
        self.query_status = 'FAILED'
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, '任务失败'):
                self.save()
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(self.video()['transcript_job']['state'], 'failed')
        self.assertIsNone(self.video()['transcript_text'])
        self.assertEqual([r['id'] for r in self.active()], ['old'])

    def test_partial_text_and_empty_success_are_not_saved(self):
        self.query_status = 'PROCESSING'
        with self.assertRaisesRegex(RuntimeError, '超时'):
            self.save()
        self.assertIsNone(self.video()['transcript_text'])
        self.query_status = 'SUCCESS'
        self.text = ''
        with self.assertRaisesRegex(RuntimeError, 'without_text'):
            self.save()
        self.assertEqual(len(self.creates()), 1)
        self.assertIsNone(self.video()['transcript_text'])

    def test_existing_transcript_is_reused_without_any_provider_request(self):
        with self.server.connect() as c:
            c.execute("UPDATE videos SET transcript_text=%s,has_transcript=true,transcript_length=%s", (self.old_text, len(self.old_text)))
        video, _ = self.save()
        self.assertEqual(video['transcript_text'], self.old_text)
        self.assertEqual(self.calls, [])
        self.assertEqual([r['id'] for r in self.active()], ['old'])

    def test_manual_edit_during_request_is_preserved(self):
        def edit():
            with self.server.connect() as c:
                c.execute("UPDATE videos SET transcript_text='人工修改',has_transcript=true,transcript_length=4")
        self.on_query = edit
        video, _ = self.save()
        self.assertEqual(video['transcript_text'], '人工修改')
        self.assertTrue(self.video()['transcript_job']['preserved_manual'])
        self.assertEqual([r['id'] for r in self.active()], ['old'])

    def test_concurrent_requests_create_once(self):
        entered = threading.Event()

        def query():
            entered.set()
            time.sleep(0.05)
        self.on_query = query
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.save)
            self.assertTrue(entered.wait(3))
            second = pool.submit(self.save)
            self.assertEqual(first.result(timeout=5)[0]['transcript_text'], self.text)
            self.assertEqual(second.result(timeout=5)[0]['transcript_text'], self.text)
        self.assertEqual(len(self.creates()), 1)

    def test_http_manual_transcript_retry_uses_pool_and_keeps_claims(self):
        server = self.server

        class QuietHandler(server.AppHandler):
            def log_message(self, *_):
                pass
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
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
                        response = urllib.request.urlopen(request, timeout=5)
                    except urllib.error.HTTPError as exc:
                        response = exc
                    with response:
                        self.assertEqual(response.status, expected)
                        body = json.load(response)
                    if authenticated:
                        self.assertEqual(body['video']['transcript_text'], self.text)
            self.assertEqual(len(self.creates()), 1)
            self.assertEqual([r['id'] for r in self.active()], ['old'])
            self.extract.assert_not_called()
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=3)

    def test_array_config_serializes_as_json_and_empty_pool_preserves_legacy(self):
        spec = importlib.util.spec_from_file_location('decor_dev_config_test', ROOT / 'scripts/dev.py')
        dev = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dev)
        configured = [{'id': 'first', 'email': 'a@example.invalid', 'password': 'fake', 'enabled': False}]
        env = dev.app_env({'TRANSCRIPTGENERATE_ACCOUNTS': configured})
        self.assertEqual(json.loads(env['TRANSCRIPTGENERATE_ACCOUNTS']), configured)
        with patch.dict(os.environ, {'TRANSCRIPTGENERATE_ACCOUNTS': env['TRANSCRIPTGENERATE_ACCOUNTS']}):
            loaded = self.server.load_transcript_accounts()
        self.assertEqual(len(loaded), 1)
        self.assertFalse(loaded[0]['enabled'])
        with patch.dict(os.environ, {'TRANSCRIPTGENERATE_ACCOUNTS': '[]'}), \
             patch.object(self.server, 'TRANSCRIPT_ACCOUNTS_PATH', ROOT / '.runtime/no-such-pool.json'), \
             patch.object(self.server, 'TRANSCRIPTGENERATE_EMAIL', 'legacy@example.invalid'), \
             patch.object(self.server, 'TRANSCRIPTGENERATE_PASSWORD', 'fake'):
            self.assertEqual(self.server.load_transcript_accounts()[0]['id'], 'config_default')

    def test_query_transport_error_is_only_resumed_on_original_account(self):
        original = self.upstream
        def failed_query(path, **kwargs):
            if path.endswith('/queryTask'):
                raise TimeoutError('query disconnected')
            return original(path, **kwargs)
        with patch.object(self.server, 'transcript_request_once', side_effect=failed_query):
            with self.assertRaisesRegex(RuntimeError, '续查'):
                self.save()
        task_id = self.video()['transcript_job']['task_id']
        self.save()
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(self.video()['transcript_job']['task_id'], task_id)
        self.assertEqual(self.video()['transcript_job']['account_id'], 'a')

    def test_manual_edit_before_restart_survives_explicit_full_retry(self):
        self.query_status = 'PROCESSING'
        with self.assertRaisesRegex(RuntimeError, '超时'):
            self.save()
        with self.server.connect() as c:
            c.execute("UPDATE videos SET transcript_text='重启前人工文案',has_transcript=true,transcript_length=8")
        self.query_status = 'SUCCESS'
        video, _ = self.save(refresh=True)
        self.assertEqual(video['transcript_text'], '重启前人工文案')
        self.assertTrue(self.video()['transcript_job']['preserved_manual'])
        self.assertEqual(len(self.creates()), 1)

    def test_additive_migration_is_idempotent_and_preserves_rows(self):
        spec = importlib.util.spec_from_file_location('decor_init_test', ROOT / 'scripts/init_db.py')
        initializer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(initializer)
        # The migrator imports init_db from the scripts directory in normal CLI use.
        import sys
        with patch.dict(sys.modules, {'init_db': initializer}):
            spec = importlib.util.spec_from_file_location('decor_migration_test', ROOT / 'scripts/migrate_transcript_jobs.py')
            migrator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migrator)
        before = dict(self.video())
        with self.server.connect() as c:
            c.execute('ALTER TABLE videos DROP COLUMN transcript_job')
        migrator.migrate(self.dsn)
        migrator.migrate(self.dsn)
        self.assertEqual(dict(self.video()), before)
        self.assertFalse(initializer.init_db(self.dsn))

    def test_api_can_start_after_a_failed_local_attempt(self):
        with self.server.connect() as conn:
            self.server.write_transcript_job(conn, self.video_id, {'provider':'local_asr', 'state':'failed', 'task_id':'local-old'})
        self.save()
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(self.video()['transcript_job']['provider'], 'transcriptgenerate')
        self.assertEqual(self.video()['transcript_text'], self.text)


if __name__ == '__main__':
    unittest.main()
