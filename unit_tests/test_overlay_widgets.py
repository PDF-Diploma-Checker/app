"""Widgets laid over the PDF view stay in their corner when the window grows, and a toast that has faded out is not used."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
except Exception as error:      # pragma: no cover
    raise unittest.SkipTest(f"Qt is not available: {error}")


def _settle(app):
    for _ in range(3):
        app.processEvents()


class OverlayPlacementTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def view(self):
        view = QScrollArea()
        view.resize(400, 300)
        view.show()
        _settle(self.app)
        self.addCleanup(view.close)
        return view

    def test_the_assistant_button_follows_the_corner_when_the_view_grows(self):
        from ui.assistant_panel import AssistantPanel
        view = self.view()
        panel = AssistantPanel(view)
        panel.follow(view)
        panel.show()
        view.resize(1300, 900)
        _settle(self.app)
        viewport = view.viewport().geometry()
        self.assertGreater(panel.x() + panel.width(), viewport.right() - 60)
        self.assertGreater(panel.y() + panel.height(), viewport.bottom() - 60)

    def test_the_search_bar_follows_the_top_right_corner_when_the_view_grows(self):
        from ui.pdf_find import PdfFindBar
        view = self.view()
        bar = PdfFindBar(view)
        bar.follow(view)
        bar.show()
        view.resize(1300, 900)
        _settle(self.app)
        viewport = view.viewport().geometry()
        self.assertGreater(bar.x() + bar.width(), viewport.right() - 60)
        self.assertLess(bar.y(), 60)


class ToastHostTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_a_toast_that_faded_out_is_not_used_again(self):
        from ui import motion
        window = QWidget()
        window.resize(600, 400)
        window.show()
        self.addCleanup(window.close)
        host = motion.ToastHost(window)
        toast = host.show("Usunięto komentarz", "Cofnij", timeout=60000)
        toast._finish()                                  # what the end of the fade-out does
        _settle(self.app)
        self.app.sendPostedEvents(toast, QEvent.DeferredDelete)       # only this one: other tests own live objects
        host.reposition()                                # a resize of the window after the toast was deleted
        host.dismiss_current()
        self.assertIsNone(host._current)
        QTest.qWait(300)                                 # let every fade-out end before the window goes away

    def test_a_new_toast_replaces_the_old_one(self):
        from ui import motion
        window = QWidget()
        window.resize(600, 400)
        window.show()
        self.addCleanup(window.close)
        host = motion.ToastHost(window)
        host.show("Pierwszy")
        second = host.show("Drugi")
        self.assertIs(host._current, second)
        host.dismiss_current()
        QTest.qWait(400)                                 # let every fade-out end before the window goes away


if __name__ == "__main__":
    unittest.main()
