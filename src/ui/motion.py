"""Small UI building blocks shared by the windows: interruptible animations, view transitions, skeleton
placeholders, undo toasts, the command menu, tabular numbers, balanced text and squircle corners."""

import math

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, Property, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from . import styles
from .i18n import t

HIT_SLOP = 12          # extra pixels around small targets that still count as a click


# --------------------------------------------------------------------------- text helpers
_tabular_font_ready = False


def tabular(widget):
    """Use a face whose digits all have the same width (Roboto, bundled), so counters, clocks and sizes do not
    jump while the value changes. The app style sheet maps the "tabular" property to that face; the rule is
    in styles.APP_STYLE. (PySide 6.8 cannot switch the OpenType 'tnum' feature of Inter from Python.)"""
    global _tabular_font_ready
    if not _tabular_font_ready:
        _tabular_font_ready = True
        import os
        from PySide6.QtGui import QFontDatabase
        from common.path import resource_path
        for name in ("Roboto-Regular.ttf", "Roboto-Bold.ttf"):
            QFontDatabase.addApplicationFont(resource_path(os.path.join("ui", "assets", name)))
    widget.setProperty("tabular", True)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def shortcut_text(key):
    return QKeySequence(key).toString(QKeySequence.NativeText)


def with_hint(text, key):
    """'Zoom in (Ctrl+=)': tooltip text that teaches the shortcut."""
    return f"{text}  ({shortcut_text(key)})"


def balanced(text, font, width):
    """Break `text` into lines of similar length (like CSS text-wrap: balance) for a box `width` pixels wide."""
    metrics = QFontMetrics(font)
    words = text.split()
    if len(words) < 3 or width <= 0:
        return text

    def lines_for(limit):
        lines, line = [], ""
        for word in words:
            trial = f"{line} {word}".strip()
            if line and metrics.horizontalAdvance(trial) > limit:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
        return lines

    target = len(lines_for(width))
    if target < 2:
        return text
    low, high = max(metrics.horizontalAdvance(w) for w in words), width
    while low < high:
        mid = (low + high) // 2
        if len(lines_for(mid)) <= target:
            high = mid
        else:
            low = mid + 1
    return "\n".join(lines_for(high))


class BalancedLabel(QLabel):
    """Centered, word-wrapped label whose lines are balanced instead of leaving one short last word."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._raw = text
        self.setWordWrap(False)
        self.setText(text)

    def setText(self, text):
        self._raw = text
        self._rebalance()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebalance()

    def _rebalance(self):
        width = self.width() if self.width() > 40 else self.maximumWidth()
        shown = balanced(self._raw, self.font(), min(width, self.maximumWidth()))
        if shown != self.text():
            super().setText(shown)


# --------------------------------------------------------------------------- squircle
def squircle_path(rect, radius, n=4.0):
    """Rounded rectangle with continuous (superellipse) corners instead of circular arcs."""
    r = min(radius * 1.25, rect.width() / 2, rect.height() / 2)
    steps = 24

    def power(value):
        return math.copysign(abs(value) ** (2 / n), value)

    def corner(cx, cy, start):
        for i in range(steps + 1):
            a = start + (math.pi / 2) * i / steps
            yield QPointF(cx + r * power(math.cos(a)), cy + r * power(math.sin(a)))

    l, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    points = []
    points += corner(right - r, top + r, -math.pi / 2)
    points += corner(right - r, bottom - r, 0)
    points += corner(l + r, bottom - r, math.pi / 2)
    points += corner(l + r, top + r, math.pi)
    path = QPainterPath()
    path.moveTo(points[0])
    for point in points[1:]:
        path.lineTo(point)
    path.closeSubpath()
    return path


class SquircleFrame(QFrame):
    """Frame that paints its own fill and border with continuous corners (QSS can only draw circular ones)."""

    def __init__(self, fill, border, radius=14, border_width=1, dashed=False, hover_fill=None,
                 hover_border=None, parent=None):
        super().__init__(parent)
        self._fill, self._border = QColor(fill), QColor(border)
        self._hover_fill = QColor(hover_fill) if hover_fill else None
        self._hover_border = QColor(hover_border) if hover_border else None
        self._radius, self._bw, self._dashed = radius, border_width, dashed
        self._hot = False
        self.setAttribute(Qt.WA_Hover, True)

    def set_hot(self, value):
        self._hot = bool(value)
        self.update()

    def enterEvent(self, event):
        self.set_hot(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_hot(False)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        half = self._bw / 2
        path = squircle_path(QRectF(self.rect()).adjusted(half, half, -half, -half), self._radius)
        p.fillPath(path, self._hover_fill if (self._hot and self._hover_fill) else self._fill)
        pen = QPen(self._hover_border if (self._hot and self._hover_border) else self._border, self._bw)
        if self._dashed:
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern([5, 4])
        p.setPen(pen)
        p.drawPath(path)


# --------------------------------------------------------------------------- hit slop
class HitSlop(QWidget):
    """Event filter that makes `target` clickable a few pixels outside its edges, so a quick move to
    the corner still hits it."""

    def __init__(self, container, target, slop=HIT_SLOP):
        super().__init__(container)
        self._target, self._slop = target, slop
        container.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if self._target.isVisible() and obj.childAt(pos) is None:
                area = self._target.geometry().adjusted(-self._slop, -self._slop, self._slop, self._slop)
                if area.contains(pos):
                    self._target.click()
                    return True
        return False


# --------------------------------------------------------------------------- view transition
def fade_to(stack, index, duration=180):
    """Switch a QStackedWidget page with a short cross-fade. A new switch while one is running continues
    from the current frame instead of jumping."""
    if stack.currentIndex() == index:
        return
    old = getattr(stack, "_fade_label", None)
    if old is not None:
        old.hide()
        old.deleteLater()
    shot = QLabel(stack)
    shot.setPixmap(stack.grab())
    shot.setGeometry(stack.rect())
    shot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    effect = QGraphicsOpacityEffect(shot)
    shot.setGraphicsEffect(effect)
    shot.show()
    shot.raise_()
    stack.setCurrentIndex(index)
    stack._fade_label = shot
    anim = QPropertyAnimation(effect, b"opacity", shot)
    anim.setDuration(duration)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def done():
        shot.hide()
        shot.deleteLater()
        if getattr(stack, "_fade_label", None) is shot:
            stack._fade_label = None

    anim.finished.connect(done)
    anim.start()


# --------------------------------------------------------------------------- skeleton
class Skeleton(QWidget):
    """Grey placeholder bar with a soft moving highlight, shown where content is still loading."""

    _timer = None

    def __init__(self, width=None, height=14, radius=7, parent=None):
        super().__init__(parent)
        if width:
            self.setFixedWidth(width)
        self.setFixedHeight(height)
        self._radius = radius
        self._phase = 0.0
        self._anim = QPropertyAnimation(self, b"phase", self)
        self._anim.setDuration(1300)
        self._anim.setStartValue(-0.4)
        self._anim.setEndValue(1.4)
        self._anim.setLoopCount(-1)
        self._anim.start()

    def _get_phase(self):
        return self._phase

    def _set_phase(self, value):
        self._phase = value
        self.update()

    phase = Property(float, _get_phase, _set_phase)

    def hideEvent(self, event):
        self._anim.pause()
        super().hideEvent(event)

    def showEvent(self, event):
        if self._anim.state() == QPropertyAnimation.Paused:
            self._anim.resume()
        super().showEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        p.fillPath(path, QColor("#E9EDF2"))
        grad = QLinearGradient(rect.width() * (self._phase - 0.3), 0, rect.width() * (self._phase + 0.3), 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, 190))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setClipPath(path)
        p.fillRect(rect, grad)


def skeleton_report():
    """Placeholder for the verification panel while the saved analysis is being loaded."""
    box = QWidget()
    box.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 8, 0, 0)
    lay.setSpacing(10)
    lay.addWidget(Skeleton(None, 76, 12))
    lay.addSpacing(6)
    lay.addWidget(Skeleton(150, 16))
    for _ in range(2):
        card = QFrame()
        card.setStyleSheet(styles.CARD_STYLE)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(10)
        cl.addWidget(Skeleton(None, 12))
        cl.addWidget(Skeleton(None, 12))
        cl.addWidget(Skeleton(120, 12))
        lay.addWidget(card)
    lay.addStretch(1)
    return box


# --------------------------------------------------------------------------- toast
class Toast(QFrame):
    """Message at the bottom of the window with an optional action ("Undo"). Hovering pauses the timer;
    a new toast replaces the old one without waiting for its fade-out."""

    actionClicked = Signal()
    expired = Signal()

    def __init__(self, parent, text, action_text=None, action_hint=None, timeout=6000):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#Toast {{ background-color: {styles.TEXT}; border-radius: 12px; }}"
            "QLabel { color: white; font-size: 14px; background: transparent; }"
            "QPushButton { color: #8EC5FF; background: transparent; border: none; font-size: 14px;"
            " font-weight: 600; padding: 6px 8px; border-radius: 6px; }"
            "QPushButton:hover { background-color: rgba(255,255,255,0.12); }"
            "QLabel#ToastHint { color: #9CA3AF; font-size: 12px; }"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 8, 10, 8)
        lay.setSpacing(10)
        lay.addWidget(QLabel(text))
        self._acted = False
        if action_text:
            btn = QPushButton(action_text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._on_action)
            lay.addWidget(btn)
            if action_hint:
                hint = QLabel(action_hint)
                hint.setObjectName("ToastHint")
                lay.addWidget(hint)
        self.adjustSize()
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(160)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout)
        self._timer.timeout.connect(self.dismiss)
        self._closing = False
        self.setAttribute(Qt.WA_Hover, True)

    def place(self):
        parent = self.parentWidget()
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)

    def popup(self):
        self.place()
        self.show()
        self.raise_()
        self._animate(1.0)
        self._timer.start()

    def _animate(self, end):
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(end)
        self._fade.start()

    def enterEvent(self, event):
        self._timer.stop()
        if self._closing:
            self._closing = False
            self._fade.finished.disconnect()
            self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._closing:
            self._timer.start(2500)
        super().leaveEvent(event)

    def _on_action(self):
        self._acted = True
        self.actionClicked.emit()
        self.dismiss(quick=True)

    def dismiss(self, quick=False):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._fade.setDuration(80 if quick else 200)
        self._animate(0.0)
        self._fade.finished.connect(self._finish)

    def _finish(self):
        self.hide()
        if not self._acted:
            self.expired.emit()
        self.deleteLater()


class ToastHost:
    """Keeps at most one toast on a window; showing a new one commits the previous one right away."""

    def __init__(self, window):
        self._window = window
        self._current = None

    def show(self, text, action_text=None, on_action=None, on_expire=None, action_hint=None, timeout=6000):
        if self._current is not None:
            old, self._current = self._current, None
            old.dismiss(quick=True)
        toast = Toast(self._window, text, action_text, action_hint, timeout)
        if on_action:
            toast.actionClicked.connect(on_action)
        if on_expire:
            toast.expired.connect(on_expire)
        self._current = toast
        toast.popup()
        return toast

    def dismiss_current(self):
        if self._current is not None:
            current, self._current = self._current, None
            current.dismiss(quick=True)

    def reposition(self):
        if self._current is not None:
            self._current.place()


# --------------------------------------------------------------------------- command menu
class Command:
    def __init__(self, title, callback, shortcut=None, keywords=""):
        self.title, self.callback, self.shortcut, self.keywords = title, callback, shortcut, keywords


def _fuzzy(query, text):
    """Score of `query` as an in-order subsequence of `text` (higher is better), or None."""
    query, text = query.lower(), text.lower()
    if query in text:
        return 1000 - text.index(query)
    pos, score = 0, 0
    for ch in query:
        found = text.find(ch, pos)
        if found < 0:
            return None
        score += 10 - min(9, found - pos)
        pos = found + 1
    return score


class CommandPalette(QDialog):
    """Ctrl+K menu: type to filter every action of the app, Enter runs it."""

    def __init__(self, parent, commands):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self._commands = commands
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = SquircleFrame(styles.SURFACE, styles.BORDER_STRONG, 16)
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        self.input = QLineEdit()
        self.input.setPlaceholderText(t("palette.placeholder"))
        self.input.setFixedHeight(44)
        self.input.setStyleSheet(
            f"QLineEdit {{ border: none; border-bottom: 1px solid {styles.BORDER}; border-radius: 0;"
            f" background: transparent; font-size: 16px; padding: 0 10px; color: {styles.TEXT}; }}"
        )
        self.input.textChanged.connect(self._filter)
        self.input.installEventFilter(self)
        lay.addWidget(self.input)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { border-radius: 8px; }"
            f"QListWidget::item:selected {{ background-color: {styles.NEUTRAL_BG}; }}"
        )
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        lay.addWidget(self.list)

        self.empty = QLabel(t("palette.empty"))
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color: {styles.TEXT_2}; font-size: 14px; padding: 20px;")
        lay.addWidget(self.empty)

        foot = QLabel(t("palette.footer"))
        foot.setStyleSheet(f"color: {styles.TEXT_2}; font-size: 12px; padding: 2px 10px;")
        lay.addWidget(foot)

        self.setFixedWidth(560)
        self._filter("")
        self._effect = QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(130)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

    def _row_widget(self, command):
        row = QWidget()
        row.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 0, 12, 0)
        title = QLabel(command.title)
        title.setStyleSheet(f"font-size: 14px; color: {styles.TEXT}; background: transparent;")
        h.addWidget(title, 1)
        if command.shortcut:
            key = QLabel(shortcut_text(command.shortcut))
            key.setStyleSheet(
                f"font-size: 12px; color: {styles.TEXT_3}; background-color: {styles.NEUTRAL_BG};"
                f" border: 1px solid {styles.BORDER}; border-radius: 6px; padding: 2px 8px;"
            )
            key.setFixedHeight(24)
            tabular(key)
            h.addWidget(key, 0, Qt.AlignVCenter)
        return row

    def _filter(self, query):
        self.list.clear()
        scored = []
        for command in self._commands:
            score = 0 if not query.strip() else _fuzzy(query.strip(), f"{command.title} {command.keywords}")
            if score is not None:
                scored.append((score, command))
        if query.strip():
            scored.sort(key=lambda pair: -pair[0])
        for _, command in scored[:9]:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, command)
            item.setSizeHint(QSize(0, 42))
            self.list.addItem(item)
            self.list.setItemWidget(item, self._row_widget(command))
        has = self.list.count() > 0
        self.empty.setVisible(not has)
        self.list.setVisible(has)
        if has:
            self.list.setCurrentRow(0)
            self.list.setFixedHeight(42 * self.list.count() + 6)
        self.layout().activate()
        self.resize(self.width(), self.layout().sizeHint().height())

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up):
                step = 1 if key == Qt.Key_Down else -1
                row = max(0, min(self.list.count() - 1, self.list.currentRow() + step))
                self.list.setCurrentRow(row)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter) and self.list.currentItem():
                self._run(self.list.currentItem())
                return True
        return super().eventFilter(obj, event)

    def _run(self, item):
        command = item.data(Qt.UserRole)
        self.accept()
        QTimer.singleShot(0, command.callback)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            top_left = parent.mapToGlobal(QPointF(0, 0).toPoint())
            self.move(top_left.x() + (parent.width() - self.width()) // 2, top_left.y() + 110)
        self.input.setFocus()
        self._fade.start()
