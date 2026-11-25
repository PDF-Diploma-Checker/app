"""The thesis assistant in the reader: a round button with the AI sparkles in the bottom-right corner of the document
preview, which opens a small chat about the opened thesis.

AssistantPanel     the widget (collapsed: the round button; open: the chat card), placed over the PDF view
AssistantController the link to app/assistant_process.py: starts it only when it is needed, keeps the history of the
                   conversation per document, stops it before an analysis and after some idle minutes (video memory)

Every answer carries the pages it comes from: a click on [str. 12] scrolls there and highlights the fragment.
"""

import html
import itertools
import logging
import re

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QTextDocument
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from . import icons, styles
from .i18n import current_locale, t

logger = logging.getLogger(__name__)

BUTTON_SIZE = 52
CARD_WIDTH = 380
CARD_HEIGHT = 520
MARGIN = 18
_CITATION = re.compile(r"\[\s*(S?\d+(?:\s*,\s*S?\d+)*)\s*\]")


def _shadow(widget, blur=24, alpha=60):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 4)
    effect.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(effect)


def answer_html(result, link_prefix="src"):
    """The answer as HTML: the text with every citation turned into links to its pages, a warning for an answer
    without sources and, under it, the list of the fragments it used."""
    sources = {s["key"]: (i, s) for i, s in enumerate(result.get("sources") or [])}
    kind = result.get("kind")

    def link(key):
        entry = sources.get(key)
        if not entry or entry[1].get("page") is None:
            return ""
        index, source = entry
        return (f'<a href="{link_prefix}:{index}" style="color:{styles.PRIMARY}; text-decoration:none;">'
                f'{t("assistant.page_short", page=source["page"] + 1)}</a>')

    def replace(match):
        keys = [k.strip().upper() for k in match.group(1).split(",")]
        links = [link(k) for k in keys]
        links = [x for x in links if x]
        return f"[{', '.join(links)}]" if links else ""

    text = html.escape(result.get("text") or "")
    # the escaped text has no brackets inside entities, so the citations can be replaced after escaping
    body = _CITATION.sub(replace, text)
    body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
    body = body.replace("\n", "<br>")
    parts = [f"<div>{body}</div>"]
    if kind == "unsourced":
        parts.append(f'<div style="color:{styles.WARNING}; margin-top:6px;">{html.escape(t("assistant.unsourced"))}</div>')
    if kind == "answer" and sources:
        seen, items = set(), []
        for key, (index, source) in sources.items():
            if source.get("page") is None or (source["page"], source.get("label")) in seen:
                continue
            seen.add((source["page"], source.get("label")))
            label = html.escape(source.get("label") or "")
            items.append(f'<a href="{link_prefix}:{index}" style="color:{styles.PRIMARY}; text-decoration:none;">'
                         f'{t("assistant.page_short", page=source["page"] + 1)}</a>'
                         + (f' <span style="color:{styles.TEXT_2};">{label}</span>' if label else ""))
        parts.append(f'<div style="margin-top:6px; color:{styles.TEXT_2};">{html.escape(t("assistant.sources"))} '
                     + "; ".join(items) + "</div>")
    return "".join(parts)


class AssistantPanel(QWidget):
    """The assistant over the PDF view: a round button that opens the chat card. Place it with `follow(view)`."""

    askRequested = Signal(str)
    stopRequested = Signal()
    sourceClicked = Signal(dict)
    opened = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._open = False
        self._busy = False
        self._available = True
        self._messages = []            # (role, text) of the conversation shown
        self._sources = []             # source dicts the links point at

        self.button = QPushButton(self)
        self.button.setObjectName("AssistantButton")
        self.button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setIcon(icons.icon("sparkles", "#FFFFFF", 26))
        self.button.setIconSize(QSize(26, 26))
        self.button.setToolTip(t("assistant.title"))
        self.button.setAccessibleName(t("assistant.title"))
        self.button.setStyleSheet(
            f"QPushButton#AssistantButton {{ background: {styles.PRIMARY}; border: none;"
            f" border-radius: {BUTTON_SIZE // 2}px; }}"
            f"QPushButton#AssistantButton:hover {{ background: {styles.PRIMARY_HOVER}; }}"
            f"QPushButton#AssistantButton:pressed {{ background: {styles.PRIMARY_PRESSED}; }}")
        _shadow(self.button, 20, 80)
        self.button.clicked.connect(self.toggle)

        self.card = QFrame(self)
        self.card.setObjectName("AssistantCard")
        self.card.setStyleSheet(
            f"QFrame#AssistantCard {{ background: {styles.SURFACE}; border: 1px solid {styles.BORDER};"
            " border-radius: 14px; }")
        _shadow(self.card)
        self.card.hide()
        card = QVBoxLayout(self.card)
        card.setContentsMargins(14, 12, 14, 12)
        card.setSpacing(8)

        head = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(icons.pixmap("sparkles", styles.PRIMARY, 18))
        head.addWidget(badge)
        self.title = QLabel(t("assistant.title"))
        self.title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {styles.TEXT}; border: none;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.clear_btn = QPushButton(t("assistant.clear"))
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet(f"QPushButton {{ border: none; color: {styles.TEXT_2}; font-size: 12px; }}"
                                     f"QPushButton:hover {{ color: {styles.TEXT}; }}")
        self.clear_btn.clicked.connect(self.clear)
        head.addWidget(self.clear_btn)
        self.close_btn = QPushButton()
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setIcon(icons.icon("chevron-down", styles.TEXT_3, 18))
        self.close_btn.setToolTip(t("assistant.collapse"))
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet(styles.ICON_BUTTON_STYLE)
        self.close_btn.clicked.connect(self.toggle)
        head.addWidget(self.close_btn)
        card.addLayout(head)

        # the conversation: chat bubbles, the question on the right, the answer on the left
        self.view = QScrollArea()
        self.view.setWidgetResizable(True)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                                "QScrollArea > QWidget > QWidget { background: transparent; }")
        self.thread = QWidget()
        self.thread_layout = QVBoxLayout(self.thread)
        self.thread_layout.setContentsMargins(0, 4, 4, 4)
        self.thread_layout.setSpacing(8)
        self.intro = QLabel(t("assistant.intro"))
        self.intro.setWordWrap(True)
        self.intro.setStyleSheet(f"color: {styles.TEXT_2}; font-size: 13px; border: none;")
        self.thread_layout.addWidget(self.intro)
        self.thread_layout.addStretch(1)
        self.view.setWidget(self.thread)
        self.view.verticalScrollBar().rangeChanged.connect(
            lambda _lo, hi: self.view.verticalScrollBar().setValue(hi))       # follow the newest message
        card.addWidget(self.view, 1)
        self._bubbles = []
        self._typing = None             # the bubble of the answer being written
        self._dots = 0
        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(400)
        self._dots_timer.timeout.connect(self._animate_dots)

        self.suggestions = QWidget()
        sl = QVBoxLayout(self.suggestions)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(4)
        for key in ("assistant.example_goal", "assistant.example_methods", "assistant.example_conclusions"):
            chip = QPushButton(t(key))
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(
                f"QPushButton {{ text-align: left; padding: 6px 10px; border: 1px solid {styles.BORDER};"
                f" border-radius: 8px; background: {styles.PRIMARY_50}; color: {styles.TEXT_3}; font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {styles.PRIMARY_200}; color: {styles.TEXT}; }}")
            chip.clicked.connect(lambda _=False, q=t(key): self._submit(q))
            sl.addWidget(chip)
        card.addWidget(self.suggestions)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {styles.TEXT_2}; font-size: 12px; border: none;")
        card.addWidget(self.status)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setMaxLength(600)
        self.input.setPlaceholderText(t("assistant.placeholder"))
        self.input.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {styles.BORDER_STRONG}; border-radius: 9px; padding: 8px 10px;"
            f" font-size: 13px; background: {styles.SURFACE}; color: {styles.TEXT}; }}"
            f"QLineEdit:focus {{ border-color: {styles.PRIMARY}; }}")
        self.input.returnPressed.connect(lambda: self._submit(self.input.text()))
        row.addWidget(self.input, 1)
        self.send_btn = QPushButton()
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(
            f"QPushButton {{ background: {styles.PRIMARY}; border: none; border-radius: 9px; }}"
            f"QPushButton:hover {{ background: {styles.PRIMARY_HOVER}; }}"
            f"QPushButton:disabled {{ background: {styles.BORDER_STRONG}; }}")
        self.send_btn.clicked.connect(self._send_or_stop)
        row.addWidget(self.send_btn)
        card.addLayout(row)

        note = QLabel(t("assistant.note"))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {styles.TEXT_2}; font-size: 11px; border: none;")
        card.addWidget(note)

        self._update_send()
        self._render()
        self._place()

    # ------------------------------------------------------------------ placement
    def follow(self, view):
        """Keep the panel in the bottom-right corner of the visible part of `view` (a QAbstractScrollArea)."""
        self._view = view
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)
        self._place()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Show):
            # the view is not resized yet when this filter sees the event, so the geometry of its viewport is the old
            # one (the button then stayed at the place of the smaller window, in the middle of the page): place it again
            # when the event has been handled
            self._place()
            QTimer.singleShot(0, self._place)
        return False

    def _place(self):
        view = getattr(self, "_view", None)
        if self._open:
            width, height = CARD_WIDTH, CARD_HEIGHT
            if view is not None:
                viewport = view.viewport().geometry()
                height = max(260, min(CARD_HEIGHT, viewport.height() - 2 * MARGIN))
                width = max(280, min(CARD_WIDTH, viewport.width() - 2 * MARGIN))
            self.resize(width, height)
            self.card.setGeometry(0, 0, width, height)
            for row in getattr(self, "_bubbles", []):
                for bubble in row.findChildren(QLabel):
                    self._fit(bubble)
        else:
            self.resize(BUTTON_SIZE + 8, BUTTON_SIZE + 8)
            self.button.move(4, 2)
        if view is not None:
            viewport = view.viewport().geometry()
            self.move(viewport.right() - self.width() - MARGIN + 1, viewport.bottom() - self.height() - MARGIN + 1)
        self.raise_()

    # ------------------------------------------------------------------ state
    def toggle(self):
        self._open = not self._open
        self.card.setVisible(self._open)
        self.button.setVisible(not self._open)
        self._place()
        if self._open:
            self.input.setFocus()
            self.opened.emit()

    def is_open(self):
        return self._open

    def set_available(self, available, reason=""):
        """Off: the chat says why (CPU mode, models not downloaded) and nothing can be asked."""
        self._available = available
        self.input.setEnabled(available)
        self.suggestions.setVisible(available and not self._messages)
        self.status.setText("" if available else reason)
        self._update_send()

    def set_status(self, text):
        self.status.setText(text or "")

    def set_busy(self, busy):
        self._busy = busy
        self._update_send()

    def _update_send(self):
        self.send_btn.setIcon(icons.icon("stop" if self._busy else "send", "#FFFFFF", 18))
        self.send_btn.setToolTip(t("assistant.stop") if self._busy else t("assistant.send"))
        self.send_btn.setEnabled(self._available)

    def clear(self):
        """A new conversation (also when another document is opened)."""
        self._messages, self._sources = [], []
        self._end_typing()
        for row in self._bubbles:
            row.setParent(None)
            row.deleteLater()
        self._bubbles = []
        self.suggestions.setVisible(self._available)
        self._render()

    # ------------------------------------------------------------------ messages
    def _submit(self, text):
        text = " ".join(str(text or "").split())
        if not text or self._busy or not self._available:
            return
        self.input.clear()
        self.add_question(text)
        self.askRequested.emit(text)

    def _send_or_stop(self):
        if self._busy:
            self.stopRequested.emit()
        else:
            self._submit(self.input.text())

    def _bubble_width(self):
        return max(180, int(self.card.width() * 0.8))

    def _add_bubble(self, role, content):
        """A chat bubble with rich text (links work); returns its label."""
        colors = {
            "user": (styles.PRIMARY, "#FFFFFF", "12px 12px 4px 12px"),
            "assistant": (styles.NEUTRAL_BG, styles.TEXT, "12px 12px 12px 4px"),
            "error": (styles.DANGER_BG, styles.DANGER, "12px 12px 12px 4px"),
            "note": ("transparent", styles.TEXT_2, "12px"),
        }
        background, color, radius = colors.get(role, colors["note"])
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        bubble = QLabel(content)
        bubble.setObjectName("Bubble")
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.RichText)
        bubble.setTextInteractionFlags(Qt.TextBrowserInteraction)
        bubble.setOpenExternalLinks(False)
        bubble.linkActivated.connect(self._link)
        bubble.setMaximumWidth(self._bubble_width())
        bubble.setStyleSheet(f"QLabel#Bubble {{ background: {background}; color: {color}; border-radius: 12px;"
                             f" border-top-right-radius: {'4px' if role == 'user' else '12px'};"
                             f" border-top-left-radius: {'4px' if role in ('assistant', 'error') else '12px'};"
                             f" padding: 8px 11px; font-size: 13px; }}")
        if role == "user":
            line.addStretch(1)
            line.addWidget(bubble)
        else:
            line.addWidget(bubble)
            line.addStretch(1)
        self.thread_layout.addWidget(row)
        self._bubbles.append(row)
        self.intro.hide()
        self._fit(bubble)
        return bubble

    def _fit(self, bubble):
        """A word-wrapped label takes its narrowest width: give the bubble the width of its text, up to the limit."""
        doc = QTextDocument()
        doc.setDefaultFont(bubble.font())
        doc.setHtml(bubble.text())
        limit = self._bubble_width()
        bubble.setMaximumWidth(limit)
        bubble.setMinimumWidth(min(limit, int(doc.idealWidth()) + 26))

    def add_question(self, text):
        self.suggestions.hide()
        self._messages.append(("user", text))
        self._add_bubble("user", html.escape(text))
        self._typing = self._add_bubble("assistant", "")
        self._dots = 0
        self._animate_dots()
        self._dots_timer.start()

    def _animate_dots(self):
        if self._typing is None:
            self._dots_timer.stop()
            return
        self._dots = self._dots % 3 + 1
        dots = "".join(f'<span style="color:{styles.TEXT_2 if i < self._dots else styles.BORDER_STRONG};">●</span> '
                       for i in range(3))
        self._typing.setText(dots)

    def show_partial(self, text):
        """The answer as the model writes it, in its own bubble."""
        if self._typing is None:
            self._typing = self._add_bubble("assistant", "")
        self._dots_timer.stop()
        shown = html.escape(text).replace("\n", "<br>")
        self._typing.setText(shown or "…")
        self._fit(self._typing)

    def _end_typing(self):
        self._dots_timer.stop()
        if self._typing is not None:
            row = self._typing.parentWidget()
            if row in self._bubbles:
                self._bubbles.remove(row)
            row.setParent(None)
            row.deleteLater()
        self._typing = None

    def show_answer(self, result):
        self._end_typing()
        if result.get("kind") == "cancelled":
            self._messages.append(("note", ""))
            self._add_bubble("note", html.escape(t("assistant.cancelled")))
            return
        offset = len(self._sources)
        self._sources.extend(result.get("sources") or [])
        self._messages.append(("assistant", result.get("text", "")))
        self._add_bubble("assistant", answer_html(result, link_prefix=f"src{offset}"))

    def show_error(self, text):
        self._end_typing()
        self._messages.append(("error", text))
        self._add_bubble("error", html.escape(text))

    def _render(self):
        self.intro.setVisible(not self._bubbles)

    def _link(self, target):
        match = re.match(r"src(\d+):(\d+)$", str(target))
        if not match:
            return
        index = int(match.group(1)) + int(match.group(2))
        if 0 <= index < len(self._sources):
            self.sourceClicked.emit(self._sources[index])


class _Bridge(QObject):
    """Messages of the assistant process arrive on a reader thread: a queued signal brings them to the UI thread."""
    message = Signal(object)


class AssistantController(QObject):
    """Connects the panel, the PDF view and the assistant process."""

    IDLE_MS = 60 * 1000

    def __init__(self, panel, pdf_view, availability=None, client_factory=None):
        super().__init__(panel)
        self.panel = panel
        self.pdf_view = pdf_view
        self._availability = availability
        self._client_factory = client_factory
        self.client = None
        self.path = None
        self.summaries = []
        self.history = []
        self.opened_path = None
        self._qid = itertools.count(1)
        self._pending = None            # (qid, question) waiting for the answer
        self._suspended = False
        self._bridge = _Bridge()
        self._bridge.message.connect(self._on_message, Qt.QueuedConnection)
        panel.askRequested.connect(self.ask)
        panel.stopRequested.connect(self.cancel)
        panel.sourceClicked.connect(self.show_source)
        panel.opened.connect(self._prepare)
        self._idle = QTimer(self)
        self._idle.setInterval(self.IDLE_MS)
        self._idle.timeout.connect(self._check_idle)
        self._idle.start()
        self.refresh_availability()

    # ------------------------------------------------------------------ availability
    def refresh_availability(self):
        if self._availability is None:
            from app.assistant_process import availability
            self._availability = availability
        try:
            ok, reason = self._availability()
        except Exception:
            logger.exception("Assistant availability check failed")
            ok, reason = False, "assistant.off_no_ai"
        self.available = ok
        self.panel.set_available(ok, t(reason) if reason else "")
        # only in the GPU mode: in the base build or on the processor the button is not shown at all (a 12B model
        # on the CPU answers in minutes); with the GPU set up but the model missing it says what to download
        self.panel.setVisible(ok or reason == "assistant.off_models")
        return ok

    def _make_client(self):
        if self.client is None:
            if self._client_factory is not None:
                self.client = self._client_factory(self._bridge.message.emit)
            else:
                from app.assistant_process import AssistantClient
                self.client = AssistantClient(self._bridge.message.emit, current_locale())
        return self.client

    # ------------------------------------------------------------------ documents and analyses
    def set_document(self, path, report_data=None):
        """Another document in the reader: a new conversation. Nothing is started until the panel is opened."""
        summaries = list((report_data or {}).get("section_summaries") or [])
        self.refresh_availability()
        if path == self.path and summaries == self.summaries:
            return
        self.cancel()
        self.path, self.summaries, self.history = path, summaries, []
        self.opened_path = None
        self._pending = None
        self.panel.set_busy(False)
        self.panel.clear()
        self.pdf_view.clear_source()
        if self.client is not None:
            self.client.forget_document()
        if self.panel.is_open():
            self._prepare()

    def suspend(self):
        """An analysis starts: it needs the video memory, the assistant process is ended (it starts again later)."""
        self._suspended = True
        self._stop_client()

    def resume(self):
        self._suspended = False
        self.refresh_availability()

    def shutdown(self):
        self._idle.stop()
        self._stop_client()

    def _stop_client(self):
        if self.client is not None:
            self.client.stop()
        self.opened_path = None
        if self._pending is not None:
            self._pending = None
            self.panel.set_busy(False)
            self.panel.show_answer({"kind": "cancelled"})

    def _check_idle(self):
        from app.assistant_process import IDLE_MINUTES
        if self.client is not None and self.client.running() and self._pending is None \
                and self.client.idle_for() > IDLE_MINUTES * 60:
            logger.info("Assistant idle for %s minutes: its process is stopped to free the memory", IDLE_MINUTES)
            self._stop_client()

    def _prepare(self):
        """The panel was opened: read the thesis into the index (in the background) so the first answer is faster."""
        if not self.available or self._suspended or not self.path or self.opened_path == self.path:
            return
        self.opened_path = self.path
        self.panel.set_status(t("assistant.reading"))
        self._make_client().open_document(self.path, self.summaries)

    # ------------------------------------------------------------------ questions
    def ask(self, question):
        if self._suspended:
            self.panel.show_error(t("assistant.wait_analysis"))
            return
        if not self.available or not self.path:
            return
        self._prepare()
        qid = next(self._qid)
        self._pending = (qid, question)
        self.panel.set_busy(True)
        self.panel.set_status(t("assistant.thinking"))
        self._make_client().ask(qid, question, self.history, current_locale())

    def cancel(self):
        if self._pending is not None and self.client is not None:
            self.client.cancel()

    def _on_message(self, message):
        kind = message[0]
        if kind == "status":
            self.panel.set_status(t(message[1]) if message[1].startswith("assistant.") else message[1])
        elif kind == "ready":
            if self._pending is None:
                self.panel.set_status(t("assistant.ready", n=message[1].get("chunks", 0)))
        elif kind == "partial":
            if self._pending and message[1] == self._pending[0]:
                self.panel.show_partial(message[2])
        elif kind == "answer":
            if not self._pending or message[1] != self._pending[0]:
                return
            question = self._pending[1]
            result = message[2]
            self._pending = None
            self.panel.set_busy(False)
            self.panel.set_status("")
            self.panel.show_answer(result)
            if result.get("kind") in ("answer", "not_found", "unsourced"):
                self.history.append((question, result.get("text", "")))
                self.history = self.history[-4:]
        elif kind == "failed":
            qid = message[1]
            logger.error("Assistant failed: %s", message[2])
            if qid is None:
                self.opened_path = None         # the thesis could not be read: try again with the next question
            if qid is None or (self._pending and qid == self._pending[0]):
                self._pending = None if qid is not None else self._pending
                self.panel.set_busy(self._pending is not None)
                self.panel.set_status("")
                self.panel.show_error(t("assistant.failed", error=message[2]))
        elif kind == "crashed":
            self.opened_path = None
            self._pending = None
            self.panel.set_busy(False)
            self.panel.set_status("")
            self.panel.show_error(t("assistant.crashed", hint=message[1]))

    def show_source(self, source):
        page = source.get("page")
        if page is None:
            return
        self.pdf_view.show_source(page, source.get("rects") or [])
