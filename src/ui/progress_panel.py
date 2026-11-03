"""Pieces of the analysis progress view: the list of AI stages and the live GPU / CPU cards."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget,
)

from common import eta

from . import styles
from .i18n import t

GEMMA_LAYERS = eta.GEMMA_LAYERS
_LABEL = f"font-size: 13px; color: {styles.TEXT_2}; background: transparent; border: none;"
_VALUE = f"font-size: 13px; font-weight: 600; color: {styles.TEXT}; background: transparent; border: none;"


def _bar_style(color):
    return (
        f"QProgressBar {{ border: none; border-radius: 3px; background-color: {styles.NEUTRAL_BG};"
        " max-height: 6px; min-height: 6px; }"
        f"QProgressBar::chunk {{ border-radius: 3px; background-color: {color}; }}"
    )


# ----------------------------------------------------------------------------- stages
class StageList(QWidget):
    """The AI stages one under another: done (✓ + real time), running (●), waiting (○ + predicted time)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(1, 1)
        self._rows = []         # [(key, mark label, name label, time label)]

    def set_stages(self, stages):
        """stages: [(key, predicted seconds or None)] in the order they run."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows = []
        self._predicted = dict(stages)
        for i, (key, _) in enumerate(stages):
            mark, name, time = QLabel(), QLabel(t(f"analysis.stage_{key}")), QLabel()
            mark.setFixedWidth(18)
            mark.setAlignment(Qt.AlignCenter)
            time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(mark, i, 0)
            self._grid.addWidget(name, i, 1)
            self._grid.addWidget(time, i, 2)
            self._rows.append((key, mark, name, time))
        self.update_state("prep", {})

    def update_state(self, current, real_seconds):
        """current: key of the running stage; real_seconds: {key: seconds} of the stages reached so far."""
        keys = [r[0] for r in self._rows]
        index = keys.index(current) if current in keys else 0
        for i, (key, mark, name, time) in enumerate(self._rows):
            if i < index:
                mark.setText("✓")
                mark.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {styles.SUCCESS}; background: transparent;")
                name.setStyleSheet(_LABEL)
                seconds = real_seconds.get(key)
                time.setText(_short(seconds) if seconds is not None else "")
                time.setStyleSheet(_LABEL)
            elif i == index:
                mark.setText("●")
                mark.setStyleSheet(f"font-size: 13px; color: {styles.PRIMARY}; background: transparent;")
                name.setStyleSheet(_VALUE)
                predicted = self._predicted.get(key)
                time.setText(t("analysis.stage_about", time=_short(predicted)) if predicted else "")
                time.setStyleSheet(_LABEL)
            else:
                mark.setText("○")
                mark.setStyleSheet(f"font-size: 13px; color: {styles.BORDER_STRONG}; background: transparent;")
                name.setStyleSheet(f"font-size: 13px; color: {styles.TEXT_2}; background: transparent;")
                predicted = self._predicted.get(key)
                time.setText(t("analysis.stage_about", time=_short(predicted)) if predicted else "")
                time.setStyleSheet(f"font-size: 13px; color: {styles.BORDER_STRONG}; background: transparent;")


def _short(seconds):
    """'45 s', '3 min' - stage times are short, a range would be noise."""
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{max(1, round(seconds))} s"
    return f"{round(seconds / 60)} min"


def clock(seconds):
    """Elapsed time as m:ss (or h:mm:ss)."""
    seconds = int(max(0, seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ----------------------------------------------------------------------------- GPU / CPU
class _Meter(QWidget):
    """'Label ........ value' with an optional thin bar underneath."""

    def __init__(self, label, with_bar=True, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.label = QLabel(label)
        self.label.setStyleSheet(_LABEL)
        self.value = QLabel("–")
        self.value.setStyleSheet(_VALUE)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.label, 1)
        row.addWidget(self.value)
        lay.addLayout(row)
        self.bar = None
        if with_bar:
            self.bar = QProgressBar()
            self.bar.setRange(0, 100)
            self.bar.setTextVisible(False)
            self.bar.setStyleSheet(_bar_style(styles.PRIMARY))
            lay.addWidget(self.bar)

    def set(self, text, percent=None, color=styles.PRIMARY, text_color=styles.TEXT):
        self.value.setText(text)
        self.value.setStyleSheet(_VALUE.replace(styles.TEXT, text_color, 1))
        if self.bar is not None:
            self.bar.setValue(int(round(percent or 0)))
            self.bar.setStyleSheet(_bar_style(color))


class _Card(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("ResCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)     # never squeezed below its content
        self.setStyleSheet(
            f"QFrame#ResCard {{ background-color: {styles.SURFACE}; border: 1px solid {styles.BORDER};"
            " border-radius: 12px; }"
        )
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(10)
        head = QVBoxLayout()
        head.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLabel(title)
        self.title.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {styles.TEXT}; background: transparent;")
        self.badge = QLabel()          # e.g. the temperature, top right
        self.badge.setStyleSheet(_VALUE)
        self.badge.setVisible(False)
        title_row.addWidget(self.title, 1)
        title_row.addWidget(self.badge)
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet(f"font-size: 12px; color: {styles.TEXT_2}; background: transparent;")
        self.subtitle.setVisible(False)
        head.addLayout(title_row)
        head.addWidget(self.subtitle)
        self.lay.addLayout(head)

    def set_subtitle(self, text):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


class ResourcePanel(QWidget):
    """Live load of the graphics card and the processor, plus one sentence saying where the AI model runs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.gpu_card = _Card(t("analysis.res_gpu"))
        self.gpu_load = _Meter(t("analysis.res_load"))
        self.gpu_mem = _Meter(t("analysis.res_vram"))
        for meter in (self.gpu_load, self.gpu_mem):
            self.gpu_card.lay.addWidget(meter)
        self.gpu_none = QLabel(t("analysis.res_gpu_none"))
        self.gpu_none.setWordWrap(True)
        self.gpu_none.setStyleSheet(_LABEL)
        self.gpu_none.setVisible(False)
        self.gpu_card.lay.addWidget(self.gpu_none)
        self.gpu_card.lay.addStretch(1)

        self.cpu_card = _Card(t("analysis.res_cpu"))
        self.cpu_load = _Meter(t("analysis.res_load"))
        self.cpu_card.lay.addWidget(self.cpu_load)
        self.cpu_card.lay.addStretch(1)

        cards.addWidget(self.gpu_card, 1)
        cards.addWidget(self.cpu_card, 1)
        outer.addLayout(cards)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(styles.HINT_STYLE)
        outer.addWidget(self.note)
        self._watch_gpu = False

    def configure(self, use_llm, gpu, layers, gpu_name="", threads=None):
        """Which cards make sense for this run and the sentence explaining the expected load."""
        self._watch_gpu = use_llm and gpu
        self.gpu_card.setVisible(self._watch_gpu)
        self.gpu_card.badge.setVisible(False)
        self.gpu_card.set_subtitle(gpu_name)
        self.cpu_card.set_subtitle(t("analysis.res_threads", n=threads) if threads else "")
        if not use_llm:
            note = t("analysis.res_note_fast")
        elif not gpu:
            note = t("analysis.res_note_cpu")
        elif layers < 0 or layers >= GEMMA_LAYERS:
            note = t("analysis.res_note_gpu_full")
        else:
            note = t("analysis.res_note_gpu_part", layers=layers, total=GEMMA_LAYERS)
        self.note.setText(note)
        for meter in (self.gpu_load, self.gpu_mem, self.cpu_load):
            meter.set("–", 0)

    def update_sample(self, sample):
        """A ResourceMonitor sample: {'cpu': %, 'gpu': {'util', 'mem_used_mb', 'mem_total_mb', 'temp'} | None}."""
        if not sample:
            return
        cpu = sample.get("cpu")
        if cpu is not None:
            self.cpu_load.set(f"{cpu:.0f}%", cpu)
        if not self._watch_gpu:
            return
        gpu = sample.get("gpu")
        has_gpu = bool(gpu)
        for meter in (self.gpu_load, self.gpu_mem):
            meter.setVisible(has_gpu)
        self.gpu_none.setVisible("gpu" in sample and not has_gpu)
        if not has_gpu:
            return
        self.gpu_load.set(f"{gpu['util']:.0f}%", gpu["util"])
        used, total = gpu["mem_used_mb"] / 1024, gpu["mem_total_mb"] / 1024
        share = 100 * used / total if total else 0
        self.gpu_mem.set(t("analysis.res_vram_value", used=f"{used:.1f}", total=f"{total:.1f}"), share,
                         styles.DANGER_DOT if share >= 95 else styles.PRIMARY)
        temp = gpu.get("temp")
        badge = self.gpu_card.badge
        badge.setVisible(temp is not None)
        if temp is not None:
            badge.setText(f"{temp:.0f} °C")
            badge.setToolTip(t("analysis.res_temp"))
            badge.setStyleSheet(_VALUE.replace(styles.TEXT, styles.WARNING if temp >= 83 else styles.TEXT_2, 1))
