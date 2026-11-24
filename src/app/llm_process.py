"""The AI part of the analysis runs in its own process.

llama.cpp fails in native code (CUDA out of memory, a GGML_ASSERT, a driver error) by calling abort() or with an
access violation. Python cannot catch that: the whole app died, the progress window just vanished, and the analysis
of the text that was already running in the other thread was lost. In a separate process such a failure ends only
that process. The app notices it, tells the user what happened and why (as far as can be told), finishes the
linguistic and formatting analysis and shows the report without the AI part.

    run_task_llm_isolated(...)  drop-in for app.llm_task.run_task_llm, same arguments, same return value

What the child process does is visible as before: its log records go through a pipe into the app log (and the log
window), its status lines into the progress view. Everything llama.cpp prints itself (also the last words before an
abort) goes to logs/llm_process.log; after a crash its end is copied into the app log.

When the process dies while the model was on the graphics card, the AI part is tried once more with half of the
layers on the card: most of these crashes are a card that has too little memory for the chosen number of layers.
"""

import copy
import faulthandler
import logging
import os
import pickle
import sys
import threading
import time
import traceback

from common import run_control
from common.cancellation import AnalysisCancelled, CancelToken

logger = logging.getLogger(__name__)

STDERR_LOG_NAME = "llm_process.log"
FIGURES_LOG_NAME = "llm_process_figures.log"   # the figures process that runs next to the text one has its own log
_CANCEL_GRACE_S = 5.0          # after a cancel the process may still end on its own, then it is killed
_TAIL_BYTES = 6000             # how much of llm_process.log goes into the app log after a crash
_FONT_PATCH = "get_most_common_font_size"


# =========================================================================== shared
def patch_most_common_font_size(doc_obj):
    """The formatting check replaces the method on the document; the AI part has to see the same value.
    (A lambda cannot be pickled, so the child process applies it again.)"""
    font_usage = doc_obj.get_font_size_usage()
    doc_obj.get_most_common_font_size = (
        lambda: max(font_usage, key=font_usage.get, default=12) if font_usage else 12
    )


def stderr_log_path(name=STDERR_LOG_NAME):
    from common.logging_setup import get_log_dir
    return get_log_dir() / name


# =========================================================================== child process
class _PipeLogHandler(logging.Handler):
    """Send log records of the child process to the app."""

    def __init__(self, send):
        super().__init__()
        self._send = send

    def emit(self, record):
        try:
            message = record.getMessage()
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            self._send(("log", {
                "name": record.name, "levelno": record.levelno, "levelname": record.levelname,
                "pathname": record.pathname, "lineno": record.lineno, "funcName": record.funcName,
                "msg": message, "exc_text": record.exc_text, "stack_info": record.stack_info,
                "created": record.created, "threadName": record.threadName,
            }))
        except Exception:
            pass


def _redirect_native_stderr(path):
    """Point file descriptor 2 (and the Windows standard error handle) at `path`: llama.cpp / ggml / CUDA print
    their errors there right before an abort. Returns the open file."""
    stream = open(path, "w", encoding="utf-8", errors="replace", buffering=1)
    stream.write(f"AI process {os.getpid()} started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    try:
        os.dup2(stream.fileno(), 2)
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            import msvcrt
            ctypes.windll.kernel32.SetStdHandle(-12, msvcrt.get_osfhandle(stream.fileno()))     # STD_ERROR_HANDLE
        except Exception:
            pass
    sys.stderr = stream
    faulthandler.enable(file=stream, all_threads=True)
    return stream


_LLAMA_LOG_CALLBACK = None      # ctypes keeps only a pointer: the Python object must stay alive


def _route_llama_log(stream):
    """llama.cpp's own log: everything into llm_process.log, warnings and errors also into the app log."""
    global _LLAMA_LOG_CALLBACK
    try:
        import ctypes
        import llama_cpp
    except Exception:
        return
    native = logging.getLogger("llama.cpp")
    levels = {2: logging.WARNING, 3: logging.ERROR}
    last = {"level": 1}

    @llama_cpp.llama_log_callback
    def callback(level, text, user_data):
        try:
            line = text.decode("utf-8", errors="replace") if text else ""
            if level == 5:                      # continuation of the previous message
                level = last["level"]
            last["level"] = level
            stream.write(line)
            if level in levels and line.strip():
                native.log(levels[level], line.rstrip())
        except Exception:
            pass

    _LLAMA_LOG_CALLBACK = callback
    try:
        llama_cpp.llama_log_set(callback, ctypes.c_void_p(0))
    except Exception:
        pass


CRASH_TEST_ENV = "DIPLOMA_CHECKER_LLM_CRASH_TEST"     # for testing a build: abort | segv | oom | exit | hang


def _simulate_crash(kind, send):
    """Die like llama.cpp does, to check that the app survives it (set DIPLOMA_CHECKER_LLM_CRASH_TEST)."""
    logger.warning("Simulating a crash of the AI process: %s", kind)
    send(("progress", 55, "AI: wyszukiwanie celu pracy... (test)"))
    if kind == "oom":
        sys.stderr.write("ggml_backend_cuda_buffer_type_alloc_buffer: allocating 512.00 MiB on device 0: "
                         "cudaMalloc failed: out of memory\nGGML_ASSERT(buf != NULL) failed\n")
        sys.stderr.flush()
        os.abort()
    if kind == "segv":
        import ctypes
        ctypes.string_at(0)
    if kind == "exit":
        os._exit(1)
    if kind == "hang":                      # stuck in native code: does not react to a cancel
        while True:
            time.sleep(1)
    os.abort()


def _child_main(conn, cancel_event, payload, pdf_path, language, check_images, gpu_layers, stderr_path, job="analysis",
                extra=None):
    """Entry point of the AI process."""
    lock = threading.Lock()

    def send(message):
        with lock:
            conn.send(message)

    stream = _redirect_native_stderr(stderr_path)

    root = logging.getLogger()
    for handler in list(root.handlers):         # a development start runs app/main.py here too
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    root.addHandler(_PipeLogHandler(send))
    root.setLevel(logging.INFO)
    threading.excepthook = lambda args: logger.critical(
        "Unhandled exception in thread %s", getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    token = CancelToken()

    def watch_cancel():
        while not token.is_cancelled():
            if cancel_event.wait(0.5):
                token.cancel()

    threading.Thread(target=watch_cancel, name="cancel-watch", daemon=True).start()

    def sink(value, text):
        token.check()
        send(("progress", value, text))

    run_control.bind(token, sink)
    try:
        from analysis.modules.llm import config
        if gpu_layers is not None and gpu_layers != config.N_GPU_LAYERS:
            config.override_gpu_layers(gpu_layers)
        _route_llama_log(stream)
        logger.info("AI process %s started (layers on the GPU: %s)", os.getpid(), config.N_GPU_LAYERS)

        if job == "language_review":
            from app.llm_task import run_language_review
            send(("result", run_language_review(pickle.loads(payload), language, token)))
            return

        if payload is not None:
            doc_obj, patched = pickle.loads(payload)
        else:
            from analysis.extraction.main_extractor import extractPDF
            logger.info("Reading the PDF again in the AI process")
            doc_obj, patched = extractPDF(pdf_path), True
        if patched:
            patch_most_common_font_size(doc_obj)

        crash_test = os.environ.get(CRASH_TEST_ENV, "")
        if crash_test:
            _simulate_crash(crash_test, send)

        if job == "figures":
            from app.llm_task import run_figures
            send(("result", run_figures(doc_obj, pdf_path, language, token)))
            return

        if job == "figures_read":
            from app.llm_task import run_figures_reading
            send(("result", run_figures_reading(doc_obj, pdf_path, language, token)))
            return

        if job == "figures_check":
            from app.llm_task import run_figures_analysis
            send(("result", run_figures_analysis(doc_obj, pdf_path, extra, language, token)))
            return

        from app.llm_task import run_task_llm
        result = run_task_llm(doc_obj=doc_obj, pdf_path=pdf_path, language=language, use_llm=True,
                              check_images=check_images, cancel_token=token)
        from common import eta
        send(("model_loads", eta.take_model_loads()))      # the time estimate learns from them in the app
        send(("result", result))
    except AnalysisCancelled:
        send(("cancelled",))
    except BaseException as error:
        logger.exception("The AI process failed")
        send(("error", f"{type(error).__name__}: {error}", traceback.format_exc()))
    finally:
        run_control.unbind()
        try:
            stream.flush()
        except Exception:
            pass
        conn.close()


# =========================================================================== diagnosis
_WINDOWS_CODES = {
    3: "abort()",
    0xC0000005: "access violation",
    0xC0000409: "abort() / stack buffer overrun",
    0xC00000FD: "stack overflow",
    0xC0000017: "out of memory",
    0xE06D7363: "unhandled C++ exception",
}
_SIGNALS = {6: "SIGABRT (abort)", 9: "SIGKILL", 11: "SIGSEGV (access violation)", 7: "SIGBUS"}


def describe_exit_code(code):
    if code is None:
        return "?"
    if -128 < code < 0:                     # POSIX: killed by a signal (a Windows status is a large number)
        return f"{_SIGNALS.get(-code, f'signal {-code}')}"
    unsigned = code & 0xFFFFFFFF
    name = _WINDOWS_CODES.get(unsigned)
    return f"0x{unsigned:08X} ({name})" if name else str(code)


def read_tail(path, size=_TAIL_BYTES):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - size))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


_OOM_MARKS = ("out of memory", "cudamalloc", "failed to allocate", "unable to allocate", "cuda_error_out_of_memory",
              "not enough memory", "memoryerror", "bad_alloc", "ggml_backend_cuda_buffer_type_alloc_buffer")
_CUDA_MARKS = ("cuda error", "cublas", "ggml_cuda", "cudnn", "nvcuda", "driver version is insufficient",
               "no kernel image", "illegal memory access", "launch failure")


def _profile():
    try:
        from analysis.modules.llm import config
        return config.MODEL_PROFILE
    except Exception:
        return "full"


def _gpu_facts():
    try:
        from common import gpu_check
        gpus = gpu_check.nvidia_gpus()
        return gpus[0] if gpus else None
    except Exception:
        return None


def _layers_text(layers):
    return "max" if layers is not None and layers < 0 else str(layers)


def diagnose_crash(exit_code, tail, gpu_layers, configured_layers=None):
    """(kind, hint) from the exit code and the last lines llama.cpp printed. kind: oom, cuda, ram, assert, unknown.
    `gpu_layers`: what the crashed run used; `configured_layers`: the value in the settings, named in the hint."""
    from ui.i18n import t

    text = (tail or "").lower()
    on_gpu = bool(gpu_layers)
    if configured_layers:
        gpu_layers = configured_layers
    gpu = _gpu_facts() if on_gpu else None

    def gpu_hint():
        if not gpu:
            return t("llm_error.hint_layers_generic", layers=_layers_text(gpu_layers))
        from common import gpu_check
        recommended = gpu_check.recommend_gpu_layers(gpu["vram_gb"], _profile())
        return t("llm_error.hint_layers", layers=_layers_text(gpu_layers), name=gpu["name"],
                 vram=f"{gpu['vram_gb']:.1f}", recommended=_layers_text(recommended))

    if any(mark in text for mark in _OOM_MARKS):
        if on_gpu and ("cuda" in text or "vram" in text or "ggml_backend_cuda" in text or "cudamalloc" in text):
            return "oom", t("llm_error.cause_vram") + " " + gpu_hint()
        return "ram", t("llm_error.cause_ram")
    if on_gpu and any(mark in text for mark in _CUDA_MARKS):
        return "cuda", t("llm_error.cause_cuda") + " " + gpu_hint()
    if exit_code == -9:
        return "ram", t("llm_error.cause_killed")
    if "ggml_assert" in text or "assert" in text:
        hint = t("llm_error.cause_assert")
        return "assert", hint + (" " + gpu_hint() if on_gpu else "")
    if on_gpu:
        return "unknown", t("llm_error.cause_unknown_gpu") + " " + gpu_hint()
    return "unknown", t("llm_error.cause_unknown_cpu")


def _last_error_line(tail):
    """The most telling line llama.cpp printed, for the message to the user: the most specific kind of line wins,
    the last of that kind."""
    lines = [line.strip() for line in (tail or "").splitlines()
             if line.strip() and not line.lower().startswith(("  file ", "file ", "fatal python error"))]
    for keys in (("ggml_assert", "cuda error", "out of memory", "cudamalloc"), ("error", "failed", "abort")):
        for line in reversed(lines):
            if any(k in line.lower() for k in keys):
                return line[:300]
    return ""


def layers_warning(gpu_layers):
    """A warning before the analysis when the chosen number of GPU layers is more than this card is known to hold."""
    if not gpu_layers:
        return None
    gpu = _gpu_facts()
    if not gpu:
        return None
    from common import gpu_check
    recommended = gpu_check.recommend_gpu_layers(gpu["vram_gb"], _profile())
    too_many = recommended >= 0 and (gpu_layers < 0 or gpu_layers > recommended)
    if not too_many:
        return None
    from ui.i18n import t
    return t("llm_error.layers_warning", layers=_layers_text(gpu_layers), name=gpu["name"],
             vram=f"{gpu['vram_gb']:.1f}", recommended=_layers_text(recommended))


def _fewer_layers(layers):
    if layers < 0:
        gpu = _gpu_facts()
        if gpu:
            from common import gpu_check
            recommended = gpu_check.recommend_gpu_layers(gpu["vram_gb"], _profile())
            if recommended > 0:
                return max(recommended // 2, 1)
        return 24
    return layers // 2 if layers > 1 else 0


# =========================================================================== parent side
def _report(title_key, text, popup=True):
    """A problem the user must see now (the progress window shows it), and the log keeps."""
    try:
        from ui.i18n import t
        title = t(title_key)
    except Exception:
        title = title_key
    run_control.report_problem(title, text, popup)


def _forward_log(data):
    record = logging.makeLogRecord(dict(data, args=None, exc_info=None))
    record.processName = "AI"
    logging.getLogger(record.name).handle(record)


def _serialize(doc_obj):
    """The document for the child process: (bytes, whether the font size method was replaced) or None."""
    try:
        doc = copy.copy(doc_obj)
        patched = _FONT_PATCH in vars(doc)
        vars(doc).pop(_FONT_PATCH, None)
        return pickle.dumps((doc, patched), protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        logger.warning("The document cannot be passed to the AI process, it will read the PDF again", exc_info=True)
        return None


class _Outcome:
    def __init__(self, kind, value=None, detail=None):
        self.kind, self.value, self.detail = kind, value, detail


def _run_once(payload, pdf_path, language, check_images, gpu_layers, cancel_token, job="analysis", extra=None,
              quiet=False, stderr_name=STDERR_LOG_NAME):
    """Run the AI part in a child process once. Returns an _Outcome: result / error / crash. Raises on a cancel.
    quiet: its status lines are not shown (a process running next to the main one would confuse the progress view)."""
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    cancel_event = ctx.Event()
    stderr_path = str(stderr_log_path(stderr_name))
    process = ctx.Process(
        target=_child_main, name="llm-worker",
        args=(sender, cancel_event, payload, pdf_path, language, check_images, gpu_layers, stderr_path, job, extra),
    )
    process.start()
    sender.close()              # only the child writes: the pipe reports EOF once the child is gone
    logger.info("AI process %s started (GPU layers: %s)", process.pid, gpu_layers)

    last_status = ""
    outcome = None
    cancel_deadline = None
    try:
        while True:
            if cancel_deadline is None and cancel_token is not None and cancel_token.is_cancelled():
                cancel_event.set()
                cancel_deadline = time.monotonic() + _CANCEL_GRACE_S
            if cancel_deadline is not None and time.monotonic() > cancel_deadline:
                break
            try:
                if not receiver.poll(0.25):
                    if not process.is_alive() and not receiver.poll(0):
                        break
                    continue
                message = receiver.recv()
            except (EOFError, OSError):
                break
            kind = message[0]
            if kind == "log":
                _forward_log(message[1])
            elif kind == "progress":
                _, value, text = message
                if text:
                    last_status = text
                if quiet:
                    continue
                try:
                    run_control.notify(text, None if value is None or value < 0 else value)
                except AnalysisCancelled:
                    pass                # noticed at the top of the loop
            elif kind == "model_loads":
                from common import eta
                for size, seconds in message[1]:
                    eta.record_model_load(size, seconds)
            elif kind == "result":
                outcome = _Outcome("result", message[1])
                break
            elif kind == "error":
                outcome = _Outcome("error", message[1], message[2])
                break
            elif kind == "cancelled":
                break
    finally:
        process.join(timeout=10 if outcome is not None else 2)
        if process.is_alive():
            logger.warning("The AI process %s does not end, killing it", process.pid)
            process.kill()
            process.join(timeout=5)
        receiver.close()

    if cancel_token is not None and cancel_token.is_cancelled():
        raise AnalysisCancelled()
    if outcome is not None:
        return outcome
    return _Outcome("crash", process.exitcode, last_status)


def _failure(stage, error, hint, crashed):
    from ui.i18n import t
    failure = {"stage": stage, "error": error, "hint": hint, "crashed": crashed,
               "log": str(stderr_log_path())}
    return {"analysis_error": failure}, None, t("llm_error.summary")


def run_language_review_isolated(matches, language="pl", cancel_token=None):
    """app.llm_task.run_language_review in a separate process. When that process fails all the findings stay."""
    from analysis.modules.llm import config

    if not config.language_review_enabled():
        logger.info("The language findings are not reviewed with the light model: all of them stay in the report")
        return matches
    outcome = _run_once(pickle.dumps(matches, protocol=pickle.HIGHEST_PROTOCOL), "", language, False, config.N_GPU_LAYERS,
                        cancel_token, job="language_review")
    if outcome.kind == "result":
        return outcome.value
    if outcome.kind == "crash":
        logger.error("The review of the language findings crashed: exit code %s. All the findings stay in the report.\n"
                     "Last lines of %s:\n%s", describe_exit_code(outcome.value), stderr_log_path(), read_tail(stderr_log_path()))
    else:
        logger.error("The review of the language findings failed, all of them stay in the report: %s\n%s", outcome.value, outcome.detail)
    return matches


# what the text model and the vision model take of the video memory (MB), to see whether they fit together. Measured
# on a 16 GB card: the text model with all layers needs about 10 GB (weights 7.3, the context 1.5, compute buffers 1.4),
# the vision model about 6 GB while it reads. Together that does not fit 16 GB: the text model then failed to create its
# context and fell back to 24 layers, which made the whole analysis twice as slow. So the margin is generous.
_TEXT_BASE_MB, _TEXT_ALL_LAYERS_MB, _VISION_MB, _OVERLAP_MARGIN_MB = 3000, 7300, 6200, 1000
_MODEL_LAYERS = 49
# the small text model of the light profile (Gemma 3 4B): the weights 2.5 GB, a smaller context and buffers
_LIGHT_TEXT_BASE_MB, _LIGHT_TEXT_ALL_LAYERS_MB, _LIGHT_MODEL_LAYERS = 1500, 2500, 35


def overlap_needs_mb(layers, profile="full"):
    """Video memory needed to read the figures next to the text stages: the text model with `layers` layers on the
    card (-1: all) plus the vision model."""
    if profile == "light":
        share = 1.0 if layers < 0 else min(layers / _LIGHT_MODEL_LAYERS, 1.0)
        return _LIGHT_TEXT_BASE_MB + _LIGHT_TEXT_ALL_LAYERS_MB * share + _VISION_MB + _OVERLAP_MARGIN_MB
    share = 1.0 if layers < 0 else min(layers / _MODEL_LAYERS, 1.0)
    return _TEXT_BASE_MB + _TEXT_ALL_LAYERS_MB * share + _VISION_MB + _OVERLAP_MARGIN_MB


def can_overlap_figures(layers, free_mb=None, profile=None):
    """True when the vision model fits next to the text model: then reading the figures runs at the same time as the
    text stages instead of after them (the card is far from busy during the text stages). `free_mb`: free video memory,
    read from nvidia-smi when not given."""
    if not layers:
        return False
    if free_mb is None:
        gpu = _gpu_facts()
        if not gpu:
            return False
        free_mb = gpu["vram_gb"] * 1024 - gpu.get("used_mb", 0)
    if profile is None:
        from analysis.modules.llm import config
        profile = config.MODEL_PROFILE
    return free_mb >= overlap_needs_mb(layers, profile)


class _LinkedToken:
    """Cancelled when the analysis is, or on its own (to stop work that is no longer needed)."""

    def __init__(self, parent):
        self._parent = parent
        self._own = False

    def cancel(self):
        self._own = True

    def is_cancelled(self):
        return self._own or (self._parent is not None and self._parent.is_cancelled())


class _Background:
    """A job in a thread next to the main one; `wait()` returns its value or raises what it raised."""

    def __init__(self, target, parent_token, name):
        self.token = _LinkedToken(parent_token)
        self._value = None
        self._error = None
        self._thread = threading.Thread(target=self._run, args=(target,), name=name, daemon=True)
        self._thread.start()

    def _run(self, target):
        try:
            self._value = target(self.token)
        except BaseException as error:
            self._error = error

    def wait(self):
        self._thread.join()
        if self._error is not None:
            raise self._error
        return self._value

    def stop(self):
        self.token.cancel()
        self._thread.join(timeout=_CANCEL_GRACE_S * 3)


def _figure_job(job, payload, pdf_path, language, layers, cancel_token, extra=None, quiet=False):
    """One half of the figure checks in its own process. When it crashes it runs once more with the models on the
    processor: slower, but a card short of memory cannot abort them there. Returns the result, or None."""
    from ui.i18n import t

    log_name = FIGURES_LOG_NAME if quiet else STDERR_LOG_NAME      # two processes must not write one log
    while True:
        outcome = _run_once(payload, pdf_path, language, True, layers, cancel_token, job=job, extra=extra, quiet=quiet,
                            stderr_name=log_name)
        if outcome.kind == "result":
            return outcome.value
        if outcome.kind == "error":
            logger.error("The figure checks (%s) reported an error: %s\n%s", job, outcome.value, outcome.detail)
            return None
        exit_text = describe_exit_code(outcome.value)
        logger.error("The figure checks (%s) crashed: exit code %s, GPU layers %s, last status %r.\nLast lines of %s:\n%s",
                     job, exit_text, layers, outcome.detail or "?", stderr_log_path(log_name),
                     read_tail(stderr_log_path(log_name)))
        if not layers:
            return None
        logger.warning("Checking the figures again with the model on the processor")
        if not quiet:
            run_control.notify(t("llm_error.figures_on_cpu"))
        layers = 0


def run_figures_isolated(payload, pdf_path, language, layers, cancel_token=None, reading=None):
    """The figure checks after the text, in two processes one after the other (the vision model alone, then the text
    model for the comparison with the text): the first half may already be done, passed in `reading`, when it ran next
    to the text stages. When a half fails the figures are reported as not checked; the text results are kept."""
    from app.llm_task import STAGES, no_figure_checks
    from ui.i18n import t

    if reading is None:
        reading = _figure_job("figures_read", payload, pdf_path, language, layers, cancel_token)
    else:
        run_control.notify(t("progress.stage_images"), STAGES["images"])
    result = None
    if reading is not None:
        result = _figure_job("figures_check", payload, pdf_path, language, layers, cancel_token, extra=reading)
    if result is None:
        _report("llm_error.title", t("llm_error.figures_failed", log=stderr_log_path()))
        return no_figure_checks(language, failed=True)
    return result


def run_task_llm_isolated(doc_obj, pdf_path, language="pl", use_llm=True, check_images=True, cancel_token=None):
    """app.llm_task.run_task_llm in a separate process; a native crash there does not end the app.

    When the video memory holds the text model and the vision model together, the figures are read in a second process
    at the same time as the text stages run (see can_overlap_figures)."""
    if not use_llm:
        return None, None, "Tryb Szybki."

    from analysis.modules.llm import config

    layers = config.N_GPU_LAYERS
    payload = _serialize(doc_obj)
    background = None
    if check_images and can_overlap_figures(layers):
        logger.info("The figures are read next to the text stages (the video memory holds both models)")
        background = _Background(
            lambda token: _figure_job("figures_read", payload, pdf_path, language, layers, token, quiet=True),
            cancel_token, "figures-read")
    elif check_images and layers:
        logger.info("The figures are read after the text stages: the video memory does not hold both models "
                    "(needs about %.0f GB free)", overlap_needs_mb(layers, config.MODEL_PROFILE) / 1024)
    try:
        return _run_task_llm_isolated(payload, pdf_path, language, check_images, cancel_token, background)
    finally:
        if background is not None:
            background.stop()


def _run_task_llm_isolated(payload, pdf_path, language, check_images, cancel_token, background):
    from analysis.modules.llm import config
    from ui.i18n import t

    layers = configured = config.N_GPU_LAYERS
    warning = layers_warning(layers)
    if warning:
        _report("llm_error.title_layers", warning, popup=False)

    attempts = 0
    while True:
        attempts += 1
        outcome = _run_once(payload, pdf_path, language, False, layers, cancel_token)    # the figures come apart

        if outcome.kind == "result":
            result = outcome.value
            data = result[0] if isinstance(result, (tuple, list)) and result else None
            if isinstance(data, dict) and attempts > 1:
                data["gpu_layers_fallback"] = layers
            if isinstance(data, dict) and data.get("analysis_error"):
                error = data["analysis_error"]
                error.setdefault("log", str(stderr_log_path()))
                _report("llm_error.title", t("llm_error.failed_python", stage=error.get("stage", "?"),
                                             error=error.get("error", "?")))
            elif attempts > 1:
                _report("llm_error.title_recovered", t("llm_error.recovered", layers=_layers_text(layers)))
            if isinstance(data, dict) and check_images and not data.get("analysis_error"):
                reading = background.wait() if background is not None else None
                data.update(run_figures_isolated(payload, pdf_path, language, layers, cancel_token, reading))
            return tuple(result)

        if outcome.kind == "error":
            logger.error("The AI process reported an error: %s\n%s", outcome.value, outcome.detail)
            _report("llm_error.title", t("llm_error.failed_python", stage="?", error=outcome.value))
            return _failure("?", outcome.value, "", False)

        # the process died without a word: native crash (abort, access violation) or killed by the system
        tail = read_tail(stderr_log_path())
        exit_text = describe_exit_code(outcome.value)
        kind, hint = diagnose_crash(outcome.value, tail, layers, configured)
        if layers != configured:
            hint += " " + t("llm_error.retry_failed", layers=_layers_text(layers))
        stage = outcome.detail or "?"
        logger.error("The AI process crashed: exit code %s, GPU layers %s, last status %r, diagnosis %s.\n"
                     "Last lines of %s:\n%s", exit_text, layers, stage, kind, stderr_log_path(), tail)
        try:
            from common import crash_log
            crash_log.note(f"AI process crashed (exit code {exit_text}, GPU layers {layers}, status {stage!r})\n{tail}")
        except Exception:
            pass

        lower = _fewer_layers(layers) if layers else None
        if attempts == 1 and lower is not None and kind != "ram":
            logger.warning("Retrying the AI analysis with %s GPU layers instead of %s", lower, layers)
            run_control.notify(t("llm_error.retrying", layers=_layers_text(layers), lower=_layers_text(lower)))
            layers = lower
            continue

        line = _last_error_line(tail)
        error = f"{exit_text}" + (f" - {line}" if line else "")
        _report("llm_error.title", t("llm_error.crashed", stage=stage, code=exit_text, hint=hint,
                                     log=stderr_log_path()))
        return _failure(stage, error, hint, True)
