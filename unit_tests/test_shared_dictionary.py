import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
import requests
from common import shared_dictionary as client
from dictionary_service.server import Store, handler


class DictionaryWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'queue.sqlite3'
        self.store = Store(self.path)
        salt = b'0123456789abcdef'
        digest = hashlib.scrypt(b'password', salt=salt, n=16384, r=8, p=1).hex()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.store, 'moderator', salt, digest))
        self.server.daemon_threads = True
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.headers = {'Authorization': 'Basic ' + base64.b64encode(b'moderator:password').decode(), 'X-Dictionary-Review': '1'}
        self.addCleanup(lambda: setattr(client, '_words', frozenset()))

    def test_end_to_end_persistence_and_rejection(self):
        with patch.object(client, 'service_url', return_value=self.url):
            self.assertEqual(client.propose('ŻÓŁWIK'), 'pending')
            self.assertEqual(client.propose('żółwik'), 'pending')
        self.assertEqual(len(Store(self.path).queue()), 1)
        self.assertEqual(requests.get(self.url + '/words').json(), {'words': []})
        row = self.store.queue()[0]
        result = requests.post(self.url + '/admin/review', headers=self.headers, json={'id': row['id'], 'decision': 'approved'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(Store(self.path).words(), ['żółwik'])
        with patch.object(client, 'service_url', return_value=self.url), patch.object(client, 'DATA_DIR', Path(self.tmp.name)):
            self.assertTrue(client.sync())
            self.assertTrue(client.contains('ŻÓŁWIK'))
            self.assertEqual(client.propose('żółwik'), 'approved')
            with patch.object(client.requests, 'get', side_effect=requests.ConnectionError):
                client._words = frozenset()
                self.assertFalse(client.sync())
                self.assertTrue(client.contains('żółwik'))
            self.assertEqual(client.propose('odrzucone'), 'pending')
            pending = self.store.queue()[0]
            self.store.review(pending['id'], 'rejected', 'moderator')
            self.assertEqual(client.propose('odrzucone'), 'rejected')
            self.assertTrue(client.sync())
            self.assertFalse(client.contains('odrzucone'))
        conflict = requests.post(self.url + '/admin/review', headers=self.headers, json={'id': row['id'], 'decision': 'rejected'})
        self.assertEqual(conflict.status_code, 409)

    def test_authentication_csrf_and_untrusted_input(self):
        for path in ('/admin', '/admin.js', '/admin/queue'):
            self.assertEqual(requests.get(self.url + path).status_code, 401)
        self.assertEqual(requests.post(self.url + '/admin/review', json={}).status_code, 401)
        no_csrf = {'Authorization': self.headers['Authorization']}
        self.assertEqual(requests.post(self.url + '/admin/review', headers=no_csrf, json={}).status_code, 403)
        for data in ({'word': 'two words'}, {'word': '<script>'}, {'word': 'valid', 'context': 'private thesis'}, {'word': 3}, []):
            self.assertEqual(requests.post(self.url + '/proposals', json=data).status_code, 400)
        self.assertEqual(requests.post(self.url + '/proposals', data='x' * 1025).status_code, 413)
        self.assertEqual(requests.get(self.url + '/admin/queue', headers=self.headers).status_code, 200)

    def test_native_admin_sign_in_approve_and_reject_on_worker(self):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        try:
            from PySide6.QtWidgets import QApplication
            from ui.dictionary_admin import AdminDialog
        except ImportError as error:
            self.skipTest(str(error))
        import time
        app = QApplication.instance() or QApplication([])
        dialog = AdminDialog()
        self.addCleanup(dialog.close)
        self.store.propose('approveword', 'test')
        self.store.propose('rejectword', 'test')

        def finish():
            deadline = time.monotonic() + 5
            while dialog.worker.isRunning() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            app.processEvents()
            self.assertFalse(dialog.worker.isRunning())

        with patch('ui.dictionary_admin.service_url', return_value=self.url):
            self.assertFalse(dialog.approve.isEnabled())
            self.assertEqual(dialog.password.text(), '')
            dialog.user.setText('moderator')
            dialog.password.setText('wrong')
            dialog.request()
            finish()
            self.assertIn('401', dialog.status.text())
            self.assertFalse(dialog.loaded)
            dialog.password.setText('password')
            dialog.request()
            self.assertFalse(dialog.refresh.isEnabled())
            finish()
            self.assertEqual(dialog.queue.count(), 2)
            dialog.queue.setCurrentRow(0)
            self.assertTrue(dialog.approve.isEnabled())
            dialog.approve.click()
            finish()
            self.assertEqual(self.store.words(), ['approveword'])
            self.assertEqual(dialog.queue.count(), 1)
            dialog.queue.setCurrentRow(0)
            dialog.reject_button.click()
            finish()
            self.assertEqual(dialog.queue.count(), 0)
            self.assertEqual(self.store.words(), ['approveword'])
            self.assertIsNone(dialog.worker.credentials)

    def test_rate_limit_survives_restart(self):
        for _ in range(30):
            self.store.propose('word', 'address')
        with self.assertRaises(OverflowError):
            Store(self.path).propose('other', 'address')

    def test_failed_sync_does_not_replace_cache(self):
        with patch.object(client, 'DATA_DIR', Path(self.tmp.name)), patch.object(client, 'service_url', return_value=self.url):
            client.cache_path().write_text(json.dumps({'words': ['approved']}))
            with patch.object(client.requests, 'get') as get:
                response = get.return_value.__enter__.return_value
                response.status_code = 200
                response.iter_content.return_value = [b'{"words":["bad phrase"]}']
                self.assertFalse(client.sync())
            self.assertTrue(client.contains('approved'))
            self.assertEqual(json.loads(client.cache_path().read_text()), {'words': ['approved']})

    def test_configuration_and_payload_privacy(self):
        with patch.dict(os.environ, {'DIPLOMACHECKER_DICTIONARY_URL': ''}):
            with self.assertRaises(ValueError):
                client.propose('valid')
        with patch.object(client, 'service_url', return_value='https://example.test'), patch.object(client.requests, 'post') as post:
            post.return_value.status_code = 201
            post.return_value.json.return_value = {'status': 'pending'}
            client.propose('VALID')
            self.assertEqual(post.call_args.kwargs['json'], {'word': 'valid'})
            self.assertFalse(post.call_args.kwargs['allow_redirects'])


class ProposalUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as error:
            raise unittest.SkipTest(str(error))
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_has_no_thesis_default_and_reports_failure(self):
        from ui.dictionary_proposal import ProposalDialog
        from ui.select_text import ErrorMarker
        marker = ErrorMarker({'category': 'TYPOS', 'found_text': 'private thesis sentence', 'comment': 'error'}, lang='en')
        dialog = ProposalDialog(marker, 'en')
        self.assertEqual(dialog.word.text(), '')
        self.assertEqual(marker.receivers('2customContextMenuRequested(QPoint)'), 1)
        dialog.show_result('failed')
        dialog.finished_submission()
        self.assertTrue(dialog.send.isEnabled())
        dialog.show_result('pending')
        dialog.finished_submission()
        self.assertFalse(dialog.send.isEnabled())
        other = ErrorMarker({'category': 'FONTS'}, lang='en')
        self.assertEqual(other.receivers('2customContextMenuRequested(QPoint)'), 0)
        self.assertEqual(other.toolTip(), '')
        other.close()
        marker.close()


if __name__ == '__main__':
    unittest.main()
