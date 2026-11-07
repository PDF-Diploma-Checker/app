"""No process of the app may outlive it.

The app starts other programs: the LanguageTool servers (Java, one per language) and the process that runs the AI
models (app.llm_process). Windows does not end the children of a process that dies, so after a crash in native code
(llama.cpp) or after "End task" in the Task Manager they used to stay behind: several "OpenJDK Platform binary"
entries holding hundreds of MB each.

    install()               at startup: on Windows the app joins a job object that the system closes when the app
                            ends in ANY way, and closing it kills every process started from the app;
                            also removes LanguageTool servers left behind by an earlier run
    kill_children()         ends all processes started from this one (except the update helper, see below)
    exit_now(code)          the way the app ends: closes what can be closed, kills the rest, leaves without waiting
                            for analysis threads that may be stuck in native code
    breakaway_flags()       creation flags for a process that must survive the app (the update helper)
"""

import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

_job_handle = None          # kept open for the whole life of the app: closing it kills the children
_spared = set()             # pids that must not be killed (the update helper)


# --------------------------------------------------------------------------- Windows job object
def _create_kill_on_close_job():
    """A job object that kills its processes once its last handle is closed (= when the app ends)."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    # BREAKAWAY_OK: the update helper is started with CREATE_BREAKAWAY_FROM_JOB, it has to outlive the app
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
    if not kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                            ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        # e.g. started from a tool that put the app into its own job without breakaway rights
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    return job


def breakaway_flags():
    """subprocess creation flags for a process that must keep running after the app has ended."""
    if sys.platform != "win32":
        return 0
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    return CREATE_BREAKAWAY_FROM_JOB if _job_handle else 0


def spare(pid):
    """Never kill this process in kill_children() (it is the update helper)."""
    _spared.add(pid)


# --------------------------------------------------------------------------- children
def _psutil():
    try:
        import psutil
        return psutil
    except Exception:           # not in every build: the job object still does the work on Windows
        return None


def kill_children(timeout=3.0):
    """Terminate every process started from this one, then kill what is still running after `timeout` seconds."""
    psutil = _psutil()
    if psutil is None:
        return
    try:
        children = [p for p in psutil.Process().children(recursive=True) if p.pid not in _spared]
    except Exception:
        logger.debug("Could not list child processes", exc_info=True)
        return
    if not children:
        return
    for child in children:
        try:
            logger.info("Ending child process %s (%s)", child.pid, child.name())
            child.terminate()
        except Exception:
            pass
    try:
        _, alive = psutil.wait_procs(children, timeout=timeout)
    except Exception:
        alive = children
    for child in alive:
        try:
            logger.warning("Child process %s did not end, killing it", child.pid)
            child.kill()
        except Exception:
            pass


def _our_languagetool_dir():
    try:
        from common.path import LANGUAGETOOL_DIR
        return os.path.normcase(str(LANGUAGETOOL_DIR))
    except Exception:
        return None


def _is_our_languagetool(proc, lt_dir):
    """A Java process running the LanguageTool server from the folder of this app (not of another program)."""
    try:
        if "java" not in (proc.name() or "").lower():
            return False
        cmdline = os.path.normcase(" ".join(proc.cmdline()))
        return "languagetool" in cmdline.lower() and (lt_dir is None or lt_dir in cmdline)
    except Exception:
        return False


def _looks_like_this_app(proc):
    try:
        name = (proc.name() or "").lower()
    except Exception:
        return False
    return "diplomachecker" in name or "python" in name


def kill_orphaned_languagetool():
    """LanguageTool servers of this app whose app no longer runs were left behind by a run that crashed: remove them.

    Orphan: the parent process is gone, the pid now belongs to a process started after the server (Windows reuses
    pids), or the server was handed over to another parent (Linux re-parents orphans to init / systemd).
    Servers of an app that is still running (a second window, another user) are kept."""
    psutil = _psutil()
    if psutil is None:
        return 0
    lt_dir = _our_languagetool_dir()
    killed = 0
    for proc in psutil.process_iter(["pid", "ppid", "create_time"]):
        if not _is_our_languagetool(proc, lt_dir):
            continue
        try:
            parent = psutil.Process(proc.info["ppid"]) if proc.info["ppid"] else None
            if (parent is not None and parent.create_time() <= proc.info["create_time"]
                    and _looks_like_this_app(parent)):
                continue
        except psutil.NoSuchProcess:
            pass
        except Exception:
            continue
        try:
            logger.warning("Killing a LanguageTool server left behind by an earlier run (pid %s)", proc.pid)
            proc.kill()
            killed += 1
        except Exception:
            logger.debug("Could not kill %s", proc.pid, exc_info=True)
    return killed


# --------------------------------------------------------------------------- lifecycle
def install():
    """Call once at startup, before any child process is started."""
    global _job_handle
    if sys.platform == "win32":
        try:
            _job_handle = _create_kill_on_close_job()
            logger.info("Child processes will end together with the app (job object)")
        except Exception:
            logger.exception("Could not create the job object: child processes may outlive a crash")
    try:
        threading.Thread(target=kill_orphaned_languagetool, name="orphan-cleanup", daemon=True).start()
    except Exception:
        logger.exception("Could not start the cleanup of old LanguageTool servers")


def _close_language_tools():
    module = sys.modules.get("analysis.modules.linguistics.language_error_extractor")
    close = getattr(module, "_close_language_tools", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("Closing LanguageTool failed", exc_info=True)


def exit_now(code=0):
    """End the app at once. A normal interpreter exit waits for every analysis thread, and a thread stuck in native
    code (llama.cpp, spaCy) never ends: the window closed but the process stayed in the Task Manager, and an update
    could not replace the files it held."""
    logger.info("Application exits (code %s)", code)
    _close_language_tools()
    kill_children()
    try:
        logging.shutdown()
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(int(code or 0))
