"""PL/EN toggle switch that changes the UI language."""

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton

from . import styles
from .i18n import current_locale, language_signals, set_locale, t

TRACK_COLOR = QColor(styles.NEUTRAL_BG)
TRACK_BORDER = QColor(styles.BORDER)
KNOB_COLOR = QColor(styles.PRIMARY)
KNOB_HOVER = QColor(styles.PRIMARY_HOVER)
ACTIVE_TEXT = QColor("#FFFFFF")
INACTIVE_TEXT = QColor(styles.TEXT_2)
FOCUS_RING = QColor(styles.PRIMARY_200)


class LanguageSwitch(QAbstractButton):
    """Pill-shaped switch: PL on the left, EN on the right; the blue knob marks the active language.
    All instances stay in sync through `language_signals.changed`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFixedSize(self.sizeHint())
        self.setChecked(current_locale() == "en")
        self._offset = 1.0 if self.isChecked() else 0.0

        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.toggled.connect(self._on_toggled)
        language_signals.changed.connect(self._sync)
        self.retranslate_ui()

    def sizeHint(self):
        return QSize(96, 40)

    def _get_offset(self):
        return self._offset

    def _set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _on_toggled(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        set_locale("en" if checked else "pl")

    def _sync(self, locale):
        """Follow a language change made by another switch instance."""
        if self.isChecked() != (locale == "en"):
            self.blockSignals(True)
            self.setChecked(locale == "en")
            self.blockSignals(False)
            self._anim.stop()
            self._set_offset(1.0 if locale == "en" else 0.0)
        self.retranslate_ui()

    def retranslate_ui(self):
        tip = t("lang_switch.tooltip")
        self.setToolTip(tip)
        self.setAccessibleName(tip)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        track = QRectF(0.5, 0.5, w - 1, h - 1)
        radius = track.height() / 2
        p.setPen(QPen(TRACK_BORDER, 1))
        p.setBrush(TRACK_COLOR)
        p.drawRoundedRect(track, radius, radius)

        pad = 4
        half_w = (w - 2 * pad) / 2
        knob = QRectF(pad + self._offset * half_w, pad, half_w, h - 2 * pad)
        p.setPen(Qt.NoPen)
        p.setBrush(KNOB_HOVER if self.underMouse() else KNOB_COLOR)
        p.drawRoundedRect(knob, knob.height() / 2, knob.height() / 2)

        font = QFont(self.font())
        font.setWeight(QFont.DemiBold)
        font.setPixelSize(14)
        p.setFont(font)
        left = QRectF(pad, 0, half_w, h)
        right = QRectF(pad + half_w, 0, half_w, h)
        p.setPen(ACTIVE_TEXT if self._offset < 0.5 else INACTIVE_TEXT)
        p.drawText(left, Qt.AlignCenter, "PL")
        p.setPen(ACTIVE_TEXT if self._offset >= 0.5 else INACTIVE_TEXT)
        p.drawText(right, Qt.AlignCenter, "EN")

        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(FOCUS_RING, 2))
            p.drawRoundedRect(track.adjusted(1, 1, -1, -1), radius, radius)