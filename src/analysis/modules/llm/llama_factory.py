"""The one place that creates llama.cpp models.

make_llama() is a drop-in replacement for `Llama(...)` that adds two things the analysis needs:

* it can be cancelled: while the model generates, a cancellation request (common.run_control) makes it emit the
  end-of-text token, so a running generation stops within a token or two instead of after minutes;
* it tells the user and the log WHERE the model runs (GPU or CPU, how much video memory it took, or why it fell
  back to the processor).
"""

import logging
import os
import sys
import time

import numpy as np
from llama_cpp import Llama, LogitsProcessorList

from analysis.modules.llm import config
from common import eta, gpu_check, run_control

logger = logging.getLogger(__name__)

_BIG_MODEL_BYTES = 1_000_000_000      # smaller files (projectors...) are not worth a status line
_VRAM_TAKEN_MB = 300                  # at least this much new video memory means the model really sits on the GPU


class _CancellableLlama(Llama):
    """A Llama whose chat completions stop when the analysis is cancelled."""

    def create_chat_completion(self, *args, **kwargs):
        run_control.check_cancelled()
        processors = kwargs.get("logits_processor")
        processors = LogitsProcessorList(list(processors) if processors else [])
        processors.append(self._cancel_processor)
        kwargs["logits_processor"] = processors
        result = super().create_chat_completion(*args, **kwargs)
        run_control.check_cancelled()       # a cancelled generation returns a cut-off answer: do not use it
        return result

    def _cancel_processor(self, input_ids, scores):
        """Called for every generated token. Once cancelled, only the end-of-text token stays possible."""
        if run_control.is_cancelled():
            scores[:] = -np.inf
            scores[self.token_eos()] = 1.0e4
        return scores


def device_description(n_gpu_layers, vram_used_mb=None):
    """(on_gpu, text) for the status line, e.g. (True, 'GPU (NVIDIA GeForce RTX 3060), 25 warstw, 4.8 GB VRAM')."""
    if not n_gpu_layers:
        return False, "procesor (CPU)"
    if not gpu_check.llama_gpu_support():
        return False, "procesor (CPU) - ta wersja llama.cpp nie ma obsługi GPU"
    gpus = gpu_check.nvidia_gpus()
    name = gpus[0]["name"] if gpus else "GPU"
    layers = "wszystkie warstwy" if n_gpu_layers < 0 else f"{n_gpu_layers} warstw"
    if vram_used_mb is not None and vram_used_mb < _VRAM_TAKEN_MB:
        return False, f"procesor (CPU) - karta {name} nie przejęła modelu (zajęte tylko {vram_used_mb:.0f} MB VRAM)"
    memory = f", {vram_used_mb / 1024:.1f} GB VRAM" if vram_used_mb else ""
    return True, f"GPU ({name}), {layers}{memory}"


def _free_gpu_memory():
    import gc

    gc.collect()
    torch = sys.modules.get("torch")
    try:
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _create_with_fallback(purpose, kwargs):
    """Create the model; when it does not fit into the video memory retry with fewer layers on the GPU.

    Returns (model, layers actually used). A card with little memory (4 GB) cannot hold the model plus its context:
    llama.cpp then fails with "Failed to load model" or "Failed to create llama_context". Better a slower analysis
    with some layers on the processor than no analysis at all.
    """
    layers = kwargs.get("n_gpu_layers", 0)
    while True:
        try:
            return _CancellableLlama(**dict(kwargs, n_gpu_layers=layers)), layers
        except (ValueError, RuntimeError, MemoryError) as error:
            if not layers:
                raise                                   # already on the processor: a real problem
            run_control.check_cancelled()
            lower = layers // 2 if layers > 1 else 0
            if layers < 0:
                lower = 24                              # "all layers" did not fit: start from a number
            logger.warning("%s: the model does not fit with n_gpu_layers=%s (%s); retrying with %s",
                           purpose, layers, error, lower)
            run_control.notify(f"{purpose}: za mało pamięci karty, ponawiam z mniejszą liczbą warstw GPU ({lower})")
            _free_gpu_memory()
            layers = lower


def make_llama(purpose="model", **kwargs):
    """Create a cancellable Llama and report on which device it runs. `purpose` is a short name for the log."""
    run_control.check_cancelled()
    if "n_gpu_layers" not in kwargs:
        kwargs["n_gpu_layers"] = config.N_GPU_LAYERS
    layers = kwargs["n_gpu_layers"]

    watch_memory = bool(layers)
    before = gpu_check.gpu_memory_used_mb() if watch_memory else None
    started = time.monotonic()

    llm, layers = _create_with_fallback(purpose, kwargs)
    kwargs["n_gpu_layers"] = layers

    seconds = time.monotonic() - started
    after = gpu_check.gpu_memory_used_mb() if watch_memory else None
    taken = (after - before) if (before is not None and after is not None) else None
    on_gpu, where = device_description(layers, taken)

    model = os.path.basename(str(kwargs.get("model_path", "")))
    logger.info("%s: model %s loaded in %.0f s, runs on: %s", purpose, model, seconds, where)
    try:
        size = os.path.getsize(str(kwargs.get("model_path")))
    except OSError:
        size = 0
    big = size >= _BIG_MODEL_BYTES
    if big:
        eta.record_model_load(size, seconds)       # real load speed of this computer, for the time estimate
        run_control.notify(f"{purpose}: model działa na: {where}")
    if layers and not on_gpu:
        logger.warning("%s: GPU was requested (n_gpu_layers=%s) but the model runs on the CPU", purpose, layers)
    run_control.check_cancelled()
    return llm