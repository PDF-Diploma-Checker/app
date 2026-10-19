"""Thin notice on the start page: "A new version is available". Checks in the background, never blocks the UI."""

import logging
import threading

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from . import icons, styles
from .i18n import language_signals, t

logger = logging.getLogger(__name__)

_SKIPPED_KEY = "updates/skipped_version"


def _settings():
    return QSettings("DiplomaChecker", "DiplomaChecker")


def _checks_enabled():
    """Checks can be turned off with  "check_updates": false  in app_config.json."""
    try:
        from analysis.modules.llm.config import load_config
        return bool(load_config().get("check_updates", True))
    except Exception:
        logger.exception("Could not read app_config.json for the update check")
        return True


class _Result(QObject):
    found = Signal(dict)


class UpdateBanner(QFrame):
    """Hidden until a newer release is found; "Skip this version" is remembered between runs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UpdateBanner")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#UpdateBanner {{ background-color: {styles.PRIMARY_50}; "
            f"border-bottom: 1px solid {styles.PRIMARY_200}; }}"
        )
        self._info = None
        self._result = _Result(self)
        self._result.found.connect(self._on_found)

        row = QHBoxLayout(self)
        row.setContentsMargins(32, 10, 24, 10)
        row.setSpacing(16)

        self.message = QLabel()
        self.message.setStyleSheet(
            f"font-size: 14px; font-weight: 500; color: {styles.TEXT}; background: transparent; border: none;"
        )
        row.addWidget(self.message, 1)

        self.download_btn = QPushButton()
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setStyleSheet(styles.BLUE_BUTTON_STYLE.replace("padding: 11px 22px", "padding: 7px 18px"))
        self.download_btn.clicked.connect(self._open_download_page)
        row.addWidget(self.download_btn)

        self.skip_btn = QPushButton()
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.setStyleSheet(styles.LINK_BUTTON_STYLE.replace("font-size: 15px", "font-size: 14px"))
        self.skip_btn.clicked.connect(self._skip_version)
        row.addWidget(self.skip_btn)

        self.close_btn = QPushButton()
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(styles.ICON_BUTTON_STYLE)
        self.close_btn.setIcon(icons.icon("close", styles.TEXT_2, 16))
        self.close_btn.setIconSize(QSize(16, 16))
        self.close_btn.clicked.connect(self.hide)
        row.addWidget(self.close_btn)

        self.hide()
        self.retranslate_ui()
        language_signals.changed.connect(self.retranslate_ui)

    # ------------------------------------------------------------------ check
    def start_check(self, check=None):
        """Look for a newer release in a background thread. `check` is replaceable for tests."""
        if not _checks_enabled():
            logger.info("Update check is turned off in app_config.json")
            return
        if check is None:
            from common.update_check import check_for_update as check
        threading.Thread(target=self._worker, args=(check,), daemon=True, name="update-check").start()

    def _worker(self, check):
        try:
            info = check()
            if info and info.get("version") != str(_settings().value(_SKIPPED_KEY, "")):
                self._result.found.emit(info)
        except RuntimeError:
            pass                     # the window was closed before the answer arrived
        except Exception:
            logger.exception("Update check failed")

    def _on_found(self, info):
        self._info = info
        self.retranslate_ui()
        self.show()

    # ---------------------------------------------------------------- actions
    def _open_download_page(self):
        from common.update_check import DOWNLOAD_PAGE_URL
        QDesktopServices.openUrl(QUrl(DOWNLOAD_PAGE_URL))

    def _skip_version(self):
        if self._info:
            _settings().setValue(_SKIPPED_KEY, self._info["version"])
        self.hide()

    # ------------------------------------------------------------------- text
    def retranslate_ui(self, *_):
        if self._info:
            self.message.setText(t("update.message", new=self._info["version"], current=self._info["current"]))
        self.download_btn.setText(t("update.download"))
        self.skip_btn.setText(t("update.skip"))
        self.close_btn.setToolTip(t("common.close"))
        self.close_btn.setAccessibleName(t("common.close"))
