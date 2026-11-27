"""Cancelling the model download stops it in the middle of a file, and a cancelled download can be started again."""
import http.server
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.llm import config as app_config
from common import run_control
from common.cancellation import AnalysisCancelled, CancelToken

try:
    from huggingface_hub import file_download
except ImportError:      # the base build has no AI libraries
    file_download = None

TOTAL = 60 * 1024 * 1024


class _SlowFile(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        rng = self.headers.get("Range")
        start = 0
        if rng and rng.startswith("bytes="):
            start = int(rng.split("=", 1)[1].split("-", 1)[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{TOTAL - 1}/{TOTAL}")
            self.send_header("Content-Length", str(TOTAL - start))
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(TOTAL))
        self.end_headers()
        block = b"x" * (256 * 1024)
        remaining = TOTAL - start
        try:
            while remaining > 0:
                chunk = block[:remaining]
                self.wfile.write(chunk)
                remaining -= len(chunk)
                if start == 0:
                    time.sleep(0.02)             # about 12 MB/s: the first download takes 5 s
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

    def test_download_can_restart_and_resume_after_cancel(self):
        from analysis.modules.llm.config import cancellable_downloads
        url = f"http://127.0.0.1:{self.server.server_address[1]}/model.gguf"
        with tempfile.TemporaryDirectory() as folder:
            partial = Path(folder) / "model.incomplete"

            token1 = CancelToken()
            run_control.bind(token1)
            threading.Timer(0.4, token1.cancel).start()
            try:
                with partial.open("ab") as f, cancellable_downloads():
                    with self.assertRaises(AnalysisCancelled):
                        file_download.http_get(url, f, expected_size=TOTAL)
            finally:
                run_control.unbind()

            downloaded_first = partial.stat().st_size
            self.assertGreater(downloaded_first, 0)
            self.assertLess(downloaded_first, TOTAL)

            token2 = CancelToken()
            run_control.bind(token2)
            try:
                with partial.open("ab") as f, cancellable_downloads():
                    file_download.http_get(url, f, resume_size=f.tell(), expected_size=TOTAL)
            finally:
                run_control.unbind()

            self.assertEqual(partial.stat().st_size, TOTAL)

    def test_the_download_settings_are_restored(self):
        from huggingface_hub import constants
        from analysis.modules.llm.config import cancellable_downloads
        bars = sys.modules["huggingface_hub.utils.tqdm"]
        chunk, tqdm_class = constants.DOWNLOAD_CHUNK_SIZE, bars.tqdm
        with cancellable_downloads():
            self.assertEqual(constants.DOWNLOAD_CHUNK_SIZE, 256 * 1024)
        self.assertEqual(constants.DOWNLOAD_CHUNK_SIZE, chunk)
        self.assertIs(bars.tqdm, tqdm_class)


class PartialModelsPresenceTest(unittest.TestCase):
    def _write(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ok")

    def test_partial_download_is_not_treated_as_complete(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(app_config, "_embedding_in_hf_cache", return_value=None):
            base = Path(folder)
            self._write(app_config.text_model_path(base, "full"))
            # Gemma alone keeps the folder selected, but is not enough to skip downloading the rest
            self.assertTrue(app_config._models_present(base, "full"))
            self.assertFalse(app_config.are_ai_models_downloaded(base, "full"))

            self._write(base / app_config.VISION_SUBDIR / app_config.VISION_FILE)
            self.assertFalse(app_config.are_ai_models_downloaded(base, "full"))

            self._write(base / app_config.VISION_SUBDIR / app_config.VISION_MMPROJ_FILE)
            self.assertFalse(app_config.are_ai_models_downloaded(base, "full"))

            emb = app_config._embedding_dir(base)
            self._write(emb / "modules.json")
            self._write(emb / "model.safetensors")
            self.assertTrue(app_config.are_ai_models_downloaded(base, "full"))
            self.assertFalse(app_config.are_ai_models_downloaded(base, "light"))


class RestartDownloadDialogTest(unittest.TestCase):
    def setUp(self):
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as error:
            self.skipTest(f"Qt is not available: {error}")
        self.app = QApplication.instance() or QApplication([])

    def _write(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ok")

    def test_ai_setup_keeps_download_button_after_partial_download(self):
        from ui.ai_setup_dialog import AiSetupDialog

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(app_config, "_embedding_in_hf_cache", return_value=None), \
                mock.patch.object(app_config, "load_config", return_value={
                    "device": "cpu", "n_gpu_layers": 0, "model_dir": folder,
                    "model_profile": "full", "hardware_configured": True,
                }), \
                mock.patch.object(AiSetupDialog, "start_check"):
            base = Path(folder)
            # Cancelled after the first model (Gemma) finished, before Qwen2.5-VL / embeddings
            self._write(app_config.text_model_path(base, "full"))
            dialog = AiSetupDialog()
            self.addCleanup(dialog.close)
            state, _ = dialog._folder_state()
            self.assertNotEqual(state, "present")
            self.assertFalse(dialog.save_download_btn.isHidden())
            self.assertTrue(dialog.save_download_btn.isEnabled())

            # Once every required model is there, the download button hides
            self._write(base / app_config.VISION_SUBDIR / app_config.VISION_FILE)
            self._write(base / app_config.VISION_SUBDIR / app_config.VISION_MMPROJ_FILE)
            emb = app_config._embedding_dir(base)
            self._write(emb / "modules.json")
            self._write(emb / "model.safetensors")
            dialog._update_dir_status()
            self.assertEqual(dialog._folder_state()[0], "present")
            self.assertTrue(dialog.save_download_btn.isHidden())

    def test_model_download_dialog_can_restart_after_cancel(self):
        from PySide6.QtCore import QTimer
        from ui.model_download_dialog import ModelDownloadDialog

        attempts = []

        def fake_download(progress_callback=None):
            attempt = len(attempts) + 1
            attempts.append(attempt)
            for step in range(25):
                run_control.check_cancelled()
                if progress_callback:
                    progress_callback(15 + step, f"attempt {attempt} step {step}")
                time.sleep(0.02)

        with mock.patch.object(app_config, "download_ai_models_with_progress", side_effect=fake_download), \
                mock.patch.object(app_config, "are_ai_models_downloaded", return_value=True), \
                mock.patch("ui.model_download_dialog.MessageBox.information") as info_box, \
                mock.patch("ui.model_download_dialog.MessageBox.critical") as error_box:
            first = ModelDownloadDialog()
            QTimer.singleShot(80, first.reject)
            first.exec()
            self.assertFalse(first.ok)
            self.assertFalse(first.worker.isRunning())
            self.assertFalse(run_control.is_cancelled())
            info_box.assert_not_called()
            error_box.assert_not_called()

            second = ModelDownloadDialog()
            second.exec()
            self.assertTrue(second.ok)
            self.assertEqual(attempts, [1, 2])
            info_box.assert_called_once()
            error_box.assert_not_called()


if __name__ == "__main__":
    unittest.main()
