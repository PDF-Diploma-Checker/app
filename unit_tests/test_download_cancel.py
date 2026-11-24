"""Cancelling the model download stops it in the middle of a file, not after the file."""
import http.server
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common import run_control
from common.cancellation import AnalysisCancelled, CancelToken

try:
    from huggingface_hub import file_download
except ImportError:      # the base build has no AI libraries
    file_download = None

TOTAL = 60 * 1024 * 1024


class _SlowFile(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(TOTAL))
        self.end_headers()
        block = b"x" * (256 * 1024)
        try:
            for _ in range(TOTAL // len(block)):
                self.wfile.write(block)
                time.sleep(0.02)                 # about 12 MB/s: the whole file takes 5 s
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


@unittest.skipIf(file_download is None, "huggingface_hub is not installed")
class CancelDownloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SlowFile)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_cancel_stops_in_the_middle_of_the_file(self):
        from analysis.modules.llm.config import cancellable_downloads
        url = f"http://127.0.0.1:{self.server.server_address[1]}/model.gguf"
        token = CancelToken()
        run_control.bind(token)
        started = time.time()
        cancelled_at = []

        def cancel_soon():
            time.sleep(1.0)
            cancelled_at.append(time.time())
            token.cancel()

        threading.Thread(target=cancel_soon, daemon=True).start()
        try:
            with tempfile.NamedTemporaryFile() as temp, cancellable_downloads():
                with self.assertRaises(AnalysisCancelled):
                    file_download.http_get(url, temp, expected_size=TOTAL)
                written = temp.tell()
        finally:
            run_control.unbind()
        stopped_after = time.time() - cancelled_at[0]
        self.assertLess(stopped_after, 1.0, "the cancel took %.1f s" % stopped_after)
        self.assertLess(written, TOTAL // 2)
        self.assertLess(time.time() - started, 3.0)

    def test_the_download_settings_are_restored(self):
        from huggingface_hub import constants
        from analysis.modules.llm.config import cancellable_downloads
        bars = sys.modules["huggingface_hub.utils.tqdm"]
        chunk, tqdm_class = constants.DOWNLOAD_CHUNK_SIZE, bars.tqdm
        with cancellable_downloads():
            self.assertEqual(constants.DOWNLOAD_CHUNK_SIZE, 256 * 1024)
        self.assertEqual(constants.DOWNLOAD_CHUNK_SIZE, chunk)
        self.assertIs(bars.tqdm, tqdm_class)


if __name__ == "__main__":
    unittest.main()
