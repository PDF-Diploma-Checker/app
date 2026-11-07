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


def stderr_log_path():
    from common.logging_setup import get_log_dir
    return get_log_dir() / STDERR_LOG_NAME


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


def _child_main(conn, cancel_event, payload, pdf_path, language, check_images, gpu_layers, stderr_path):
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
        recommended = gpu_check.recommend_gpu_layers(gpu["vram_gb"])
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
    recommended = gpu_check.recommend_gpu_layers(gpu["vram_gb"])
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
            recommended = gpu_check.recommend_gpu_layers(gpu["vram_gb"])
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


def _run_once(payload, pdf_path, language, check_images, gpu_layers, cancel_token):
    """Run the AI part in a child process once. Returns an _Outcome: result / error / crash. Raises on a cancel."""
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    cancel_event = ctx.Event()
    stderr_path = str(stderr_log_path())
    process = ctx.Process(
        target=_child_main, name="llm-worker",
        args=(sender, cancel_event, payload, pdf_path, language, check_images, gpu_layers, stderr_path),
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


def run_task_llm_isolated(doc_obj, pdf_path, language="pl", use_llm=True, check_images=True, cancel_token=None):
    """app.llm_task.run_task_llm in a separate process; a native crash there does not end the app."""
    if not use_llm:
        return None, None, "Tryb Szybki."

    from analysis.modules.llm import config
    from ui.i18n import t

    layers = configured = config.N_GPU_LAYERS
    warning = layers_warning(layers)
    if warning:
        _report("llm_error.title_layers", warning, popup=False)

    payload = _serialize(doc_obj)
    attempts = 0
    while True:
        attempts += 1
        outcome = _run_once(payload, pdf_path, language, check_images, layers, cancel_token)

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
