"""Time estimate of an analysis, from real data: the PDF, this computer and the runs it has already done.

How the number is made
1. DocFacts       the PDF itself: pages, characters of text, images (read with PyMuPDF).
2. MachineFacts   this computer: processor threads, RAM, graphics card and its VRAM (nvidia-smi), the device and the
                  number of GPU layers from the settings.
3. raw_estimate() a model of the work: how many tokens the language model has to read and write at every stage, how
                  fast this machine does it (GPU share of the layers, CPU threads) and how long loading the models
                  takes (the measured load speed of earlier runs, a cautious default for the first one).
4. history        every finished analysis stores its real duration and the real time of every stage next to the
                  model's prediction (data/run_history.json). Every stage is multiplied by the median real/predicted
                  ratio of that stage in the earlier runs of the same kind (mode, GPU or CPU); older records without
                  the stage predictions use the ratio of the whole run. So the estimate learns the speed of THIS
                  computer. With no history the figure is only a rough one and the range shown is wide.

EtaTracker follows a running analysis and re-estimates the remaining time at every stage change from the
real time the finished stages took.
"""

import json
import logging
import os
import statistics
import time
from dataclasses import dataclass, field

from common import gpu_check

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------- model constants
# Rough speeds of llama.cpp with Gemma 3 12B (Q4_K_M), tokens per second. They only matter until the history has
# calibrated the model, and they follow what the system reports (VRAM class, CPU threads).
GEMMA_GB = 7.3
LLAVA_GB = 5.0                      # LLaVA model + projector
GEMMA_LAYERS = 48
DEFAULT_LOAD_MB_S = 1500.0          # reading a model from disk (SSD) for the first run; measured afterwards
GEMMA_LOADS = 4                     # purpose, goal, summaries, SOTA each load the model again
LLAVA_LOADS = 2
TOKENS_PER_CHAR = 0.3
LLAVA_SPEEDUP = 1.7                 # the 7B vision model is faster than the 12B text model

LOW_HIGH = {0: (0.6, 1.8), 1: (0.8, 1.35), 2: (0.8, 1.35)}      # range around the estimate by number of past runs
LOW_HIGH_MANY = (0.9, 1.15)

# progress bar values at which the stages of run_task_llm() start (see app/llm_task.py STAGES)
STAGE_VALUES = (("purpose", 55), ("goal", 62), ("summaries", 70), ("images", 80), ("sota", 90))
HISTORY_LIMIT = 60
# raise it whenever raw_estimate() changes: real/predicted ratios measured against an older model would distort the
# calibration, so only the runs recorded with the same model version are used
MODEL_VERSION = 2


@dataclass
class DocFacts:
    pages: int
    chars: int
    images: int


@dataclass
class MachineFacts:
    threads: int
    ram_gb: float
    gpu: bool                       # the AI will really run (partly) on the GPU
    gpu_layers: int                 # -1 = all
    gpu_name: str = ""
    vram_gb: float = 0.0


@dataclass
class Estimate:
    total_s: float                  # best guess
    low_s: float
    high_s: float
    stages: list                    # [(stage key, predicted seconds)] in the order they run, calibrated
    n_history: int
    raw_total_s: float              # the model's prediction without calibration (stored in the history)
    raw_stages: list = field(default_factory=list)      # [(stage key, seconds)] without calibration
    basis: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- facts
def doc_facts(pdf_path):
    """Pages, characters and images of the PDF, or None when it cannot be read."""
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        with fitz.open(pdf_path) as doc:
            pages = doc.page_count
            chars = sum(len(page.get_text()) for page in doc)
            images = sum(len(page.get_images()) for page in doc)
        return DocFacts(pages, chars, images)
    except Exception:
        logger.exception("Cannot read %s for the time estimate", pdf_path)
        return None


def hardware_info():
    """Slow (external commands, loads llama.cpp): run it off the UI thread. Used by machine_from_config()."""
    gpus = gpu_check.nvidia_gpus()
    return {
        "threads": os.cpu_count() or 4,
        "ram_gb": gpu_check.total_ram_gb(),
        "gpu_name": gpus[0]["name"] if gpus else "",
        "vram_gb": gpus[0]["vram_gb"] if gpus else 0.0,
        "gpu_build": gpu_check.llama_gpu_support(),
    }


def machine_from_config(cfg, hw):
    """Combine the user's settings with what the system reported. A GPU setting counts only when a card and a
    GPU-capable llama.cpp are really there."""
    layers = int(cfg.get("n_gpu_layers", 0) or 0)
    gpu = bool(cfg.get("device") == "cuda" and layers != 0 and hw.get("gpu_build") and hw.get("vram_gb", 0) > 0)
    return MachineFacts(
        threads=hw.get("threads", 4), ram_gb=hw.get("ram_gb", 0.0), gpu=gpu, gpu_layers=layers if gpu else 0,
        gpu_name=hw.get("gpu_name", ""), vram_gb=hw.get("vram_gb", 0.0),
    )


# ----------------------------------------------------------------------------- the model of the work
def _speeds(machine):
    """(generation tok/s, prompt-processing tok/s) of the 12B model on this machine."""
    threads = max(1, min(machine.threads, 12))              # llama.cpp hardly scales beyond that
    cpu_gen = max(1.0, 0.45 * threads)
    cpu_prompt = max(8.0, 4.0 * threads)
    if not machine.gpu:
        return cpu_gen, cpu_prompt
    if machine.vram_gb >= 16:
        gpu_gen, gpu_prompt = 60.0, 1500.0
    elif machine.vram_gb >= 10:
        gpu_gen, gpu_prompt = 40.0, 800.0
    else:
        gpu_gen, gpu_prompt = 25.0, 400.0
    share = 1.0 if machine.gpu_layers < 0 else min(machine.gpu_layers / GEMMA_LAYERS, 1.0)
    # layers run one after another: per-token time is the sum of the GPU part and the CPU part
    gen = 1.0 / (share / gpu_gen + (1.0 - share) / cpu_gen)
    # a CUDA build of llama.cpp also sends the prompt of the layers kept in RAM through the GPU (big batches), so
    # reading the prompt stays fast with a partial offload; only the generation runs those layers on the CPU
    prompt = 1.0 / (share / gpu_prompt + (1.0 - share) / max(cpu_prompt, gpu_prompt / 4))
    return gen, prompt


def _load_speed(history):
    """Bytes per second at which models were loaded in earlier runs (median), or the default."""
    speeds = []
    for record in history:
        for size, seconds in record.get("loads", []):
            if size >= 1e9 and seconds > 1:
                speeds.append(size / seconds)
    return statistics.median(speeds) if speeds else DEFAULT_LOAD_MB_S * 1024 * 1024


def raw_estimate(doc, machine, use_llm, check_images, history=()):
    """[(stage, seconds)] predicted by the model of the work, no calibration."""
    if not use_llm:
        return [("prep", 8.0 + 1.0 * doc.pages)]           # engine start, LanguageTool, rules for every page
    # with the AI the language checks run next to it: "prep" lasts only until the first AI stage starts
    stages = [("prep", 3.0 + 0.3 * doc.pages)]

    gen, prompt = _speeds(machine)
    load = _load_speed(history)
    gemma_load = GEMMA_GB * 1024 ** 3 / load
    text_tokens = doc.chars * TOKENS_PER_CHAR
    sections = doc.pages / 6.0 + 3

    def work(prefill_share, generated):
        return gemma_load + text_tokens * prefill_share / prompt + generated / gen

    stages += [
        ("purpose", work(0.6, 100)),
        ("goal", work(0.25, 150)),
        ("summaries", work(1.0, sections * 80)),
    ]
    if check_images and doc.images:
        llava_load = LLAVA_GB * 1024 ** 3 / load
        per_image = 700 / (prompt * LLAVA_SPEEDUP) + 80 / (gen * LLAVA_SPEEDUP)
        stages.append(("images", LLAVA_LOADS * llava_load + doc.images * per_image))
    stages.append(("sota", work(0.3, 400)))
    return stages


# ----------------------------------------------------------------------------- history
def _history_path():
    from common.path import DATA_DIR
    return DATA_DIR / "run_history.json"


def load_history():
    try:
        data = json.loads(_history_path().read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _kind(use_llm, check_images, gpu):
    return {"llm": bool(use_llm), "images": bool(check_images) if use_llm else False, "gpu": bool(gpu) if use_llm else False}


def _record_kind(record):
    """The kind of a stored run. Records written before "n_images" existed kept the number of figures under "images"
    (it overwrote the flag), so for them a figure count above 0 is read as "figures were checked"."""
    images = record.get("images")
    if "n_images" not in record:
        images = bool(images) if record.get("llm") else False
    return {"llm": record.get("llm"), "images": images, "gpu": record.get("gpu")}


def record_run(doc, machine, use_llm, check_images, estimate, actual_s, stage_seconds, loads):
    """Store a finished analysis: its real duration next to the model's prediction."""
    record = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        **_kind(use_llm, check_images, machine.gpu),
        "model": MODEL_VERSION,
        "pages": doc.pages, "chars": doc.chars, "n_images": doc.images,
        "raw_predicted_s": round(estimate.raw_total_s, 1) if estimate else None,
        "raw_stages": {k: round(v, 1) for k, v in estimate.raw_stages} if estimate else {},
        "actual_s": round(actual_s, 1),
        "stages": {k: round(v, 1) for k, v in stage_seconds.items()},
        "loads": [[int(size), round(sec, 1)] for size, sec in loads],
    }
    history = load_history()
    history.append(record)
    try:
        path = _history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history[-HISTORY_LIMIT:], indent=1), encoding="utf-8")
    except OSError:
        logger.exception("Cannot save the run history")
    logger.info("Analysis took %.0f s (model predicted %s s)", actual_s, record["raw_predicted_s"])


# model loads measured during the current run (filled by analysis.modules.llm.llama_factory)
_model_loads = []


def record_model_load(size_bytes, seconds):
    _model_loads.append((size_bytes, seconds))


def take_model_loads():
    loads = list(_model_loads)
    _model_loads.clear()
    return loads


def _stage_factor(records, key, default):
    """Median real/predicted time of one stage in earlier runs (records with stage predictions), else `default`."""
    ratios = []
    for record in records:
        predicted = (record.get("raw_stages") or {}).get(key)
        actual = (record.get("stages") or {}).get(key)
        if predicted and predicted > 0 and actual is not None:
            ratios.append(actual / predicted)
    return statistics.median(ratios) if ratios else default


def estimate(doc, machine, use_llm, check_images, history=None):
    """The estimate shown before the analysis starts."""
    history = load_history() if history is None else history
    raw = raw_estimate(doc, machine, use_llm, check_images, history)
    raw_total = sum(s for _, s in raw)

    kind = _kind(use_llm, check_images, machine.gpu)
    same = [r for r in history if r.get("model") == MODEL_VERSION and _record_kind(r) == kind
            and r.get("raw_predicted_s") and r.get("actual_s")]
    ratios = [r["actual_s"] / r["raw_predicted_s"] for r in same]
    factor = statistics.median(ratios) if ratios else 1.0
    low_f, high_f = LOW_HIGH_MANY if len(ratios) >= 3 else LOW_HIGH.get(len(ratios), LOW_HIGH_MANY)

    stages = [(key, s * _stage_factor(same, key, factor)) for key, s in raw]
    total = sum(s for _, s in stages)
    return Estimate(
        total_s=total, low_s=total * low_f, high_s=total * high_f, stages=stages, n_history=len(ratios),
        raw_total_s=raw_total, raw_stages=raw,
        basis={"pages": doc.pages, "chars": doc.chars, "images": doc.images, "gpu": machine.gpu,
               "gpu_name": machine.gpu_name, "layers": machine.gpu_layers, "threads": machine.threads},
    )


# ----------------------------------------------------------------------------- a running analysis
class EtaTracker:
    """Follows the progress of a running analysis and says how long is left.

    The progress bar jumps from stage to stage (STAGE_VALUES), so at every stage change the real time spent so far is
    compared with what was predicted for it, and the stages still ahead are scaled by that ratio."""

    def __init__(self, est, now=None):
        self.estimate = est
        self.start = time.monotonic() if now is None else now
        self.stage = "prep"
        self.stage_started = {"prep": self.start}
        self.ratio = None
        self._predicted_start = {}
        done = 0.0
        for key, seconds in est.stages:
            self._predicted_start[key] = done
            done += seconds
        self._total = done
        self._last_value = 0

    def on_progress(self, value, now=None):
        now = time.monotonic() if now is None else now
        self._last_value = max(self._last_value, value)
        stage = "prep"
        for key, threshold in STAGE_VALUES:
            if value >= threshold:
                stage = key
        order = [k for k, _ in self.estimate.stages]
        if stage in order and stage != self.stage and order.index(stage) > order.index(self.stage):
            self.stage = stage
            self.stage_started[stage] = now
            predicted = self._predicted_start.get(stage, 0.0)
            if predicted > 0:
                self.ratio = (now - self.start) / predicted

    def remaining(self, now=None):
        """Seconds left. It always accounts for the time that has already passed, so the total shown next to it
        (elapsed + left) never contradicts it."""
        now = time.monotonic() if now is None else now
        elapsed = now - self.start
        total = max(self._total, 1.0)
        if len(self.estimate.stages) == 1:
            # fast mode: the progress bar says little (it stops at 50% until the very end), so use the model
            left = total - elapsed
            if left > 0:
                return max(left, 0.05 * total)
            return max(0.3 * elapsed, 30.0)             # slower than predicted: some more is still to come
        if self.ratio is None:                          # still preparing: no real data about the speed yet
            left = total - elapsed
            return max(left, 0.1 * total) if left > 0 else max(0.3 * elapsed, 30.0)
        order = [(k, s) for k, s in self.estimate.stages]
        keys = [k for k, _ in order]
        i = keys.index(self.stage) if self.stage in keys else len(keys) - 1
        current = order[i][1]
        after = sum(s for _, s in order[i + 1:])
        in_stage = now - self.stage_started.get(self.stage, now)
        current_left = self.ratio * current - in_stage
        if current_left <= 0:                           # this stage runs longer than predicted
            current_left = 0.25 * in_stage
        return max(current_left + self.ratio * after, 0.03 * total)

    def stage_seconds(self, now=None):
        """Real seconds of every stage reached so far."""
        now = time.monotonic() if now is None else now
        keys = [k for k, _ in self.estimate.stages if k in self.stage_started]
        out = {}
        for i, key in enumerate(keys):
            end = self.stage_started[keys[i + 1]] if i + 1 < len(keys) else now
            out[key] = end - self.stage_started[key]
        return out

    def elapsed(self, now=None):
        return (time.monotonic() if now is None else now) - self.start


# ----------------------------------------------------------------------------- text
def format_duration(seconds, t):
    """'poniżej minuty', '12 min', '1 h 20 min'. Long times are rounded: a precise figure would suggest precision."""
    minutes = seconds / 60.0
    if minutes < 1:
        return t("analysis.eta_lt1")
    if minutes >= 20:
        minutes = round(minutes / 5.0) * 5
    elif minutes >= 5:
        minutes = round(minutes)
    else:
        minutes = max(1, round(minutes))
    minutes = int(minutes)
    if minutes >= 60:
        return t("analysis.eta_hm", h=minutes // 60, m=minutes % 60)
    return t("analysis.eta_min", m=minutes)


def format_range(est, t):
    low, high = format_duration(est.low_s, t), format_duration(est.high_s, t)
    return low if low == high else t("analysis.eta_range", low=low, high=high)
