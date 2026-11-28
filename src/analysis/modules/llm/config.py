"""Per-user config and helpers for the optional AI mode.

Never import llama_cpp / torch / huggingface_hub at module level:
the base build ships without them.
"""

import contextlib
import errno
import getpass
import functools
import importlib.util
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import run_control
from common.path import APP_CONFIG_PATH, APP_NAME, DATA_DIR, DEFAULT_MODEL_DIR, LEGACY_MODEL_DIR, PORTABLE

logger = logging.getLogger(__name__)

FROZEN = getattr(sys, "frozen", False)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SPACY_MODELS = {"pl": "pl_core_news_lg", "en": "en_core_web_lg"}
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_REPO_PREFIX = "sentence-transformers/"

GEMMA_REPO = "nocturne23/gemma-3-12b-it-Q4_K_M-GGUF"
GEMMA_FILE = "gemma-3-12b-it-q4_k_m.gguf"  # exact name from the repo (case matters on Linux)
GEMMA_SUBDIR = "gemma3_12b"
# The light profile: the whole analysis on the small Gemma 3 4B (a third of the download, about twice as fast, less
# accurate). The model that reviews the language findings is not used with it until it is shown to be reliable there.
LIGHT_REPO = "ggml-org/gemma-3-4b-it-GGUF"
LIGHT_FILE = "gemma-3-4b-it-Q4_K_M.gguf"
LIGHT_SUBDIR = "gemma3_4b"
PROFILES = ("full", "light")
DEFAULT_PROFILE = "full"
LANGUAGE_REVIEW_PROFILES = ("full",)        # the profiles in which the text model reviews the language findings
GOAL_CHECK_PROFILES = ("full",)             # ... and rates how well the thesis achieves its purpose (the small model
                                            # described a robot that the end of the thesis does not mention)
VISION_REPO = "unsloth/Qwen2.5-VL-7B-Instruct-GGUF"
VISION_FILE = "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"
VISION_MMPROJ_FILE = "mmproj-F16.gguf"
VISION_SUBDIR = "qwen2_5_vl"
REPLACED_MODEL_FILES = ("llava-v1.6-mistral-7b.Q4_K_M.gguf", "mmproj-model-f16.gguf")     # the old vision model


def llm_runtime_available():
    """True when this build/environment contains llama-cpp-python (cpu/gpu variant)."""
    return importlib.util.find_spec("llama_cpp") is not None


@functools.lru_cache(maxsize=1)
def _default_device():
    if not llm_runtime_available():
        return "cpu"
    try:
        import llama_cpp
        return "cuda" if llama_cpp.llama_supports_gpu_offload() else "cpu"
    except Exception:
        return "cpu"


def text_model_path(model_dir, profile):
    """Where the text model of `profile` lies in `model_dir`."""
    if profile == "light":
        return Path(model_dir) / LIGHT_SUBDIR / LIGHT_FILE
    return Path(model_dir) / GEMMA_SUBDIR / GEMMA_FILE


def language_review_enabled(profile=None):
    """Whether the text model reviews the language findings (with the light model all of them stay)."""
    return (profile or MODEL_PROFILE) in LANGUAGE_REVIEW_PROFILES


def goal_check_enabled(profile=None):
    """Whether the text model rates the realization of the purpose of the thesis."""
    return (profile or MODEL_PROFILE) in GOAL_CHECK_PROFILES


def default_config():
    device = _default_device()
    return {
        "model_profile": DEFAULT_PROFILE,
        "device": device,
        "n_gpu_layers": 25 if device == "cuda" else 0,
        "model_dir": "",                    # empty = the default folder (see default_model_dir())
        "language": "pl",
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "hardware_configured": False,       # becomes True once the user has seen the CPU/GPU setup
    }


def _models_present(model_dir, profile=None):
    """True when `model_dir` holds the Gemma model of `profile` (of any profile when none is given). Only that
    counts: a folder of an earlier version must stay in use when the vision model changes, otherwise 8 GB would be
    downloaded again next to the missing file."""
    profiles = (profile,) if profile else PROFILES
    return any(text_model_path(model_dir, p).is_file() for p in profiles)


def default_model_dir():
    """The folder next to the app (see common.path), unless an earlier version already downloaded the models
    into the per-user folder: those 13 GB must not be downloaded again."""
    if not _models_present(DEFAULT_MODEL_DIR) and _models_present(LEGACY_MODEL_DIR):
        return LEGACY_MODEL_DIR
    return DEFAULT_MODEL_DIR


def _is_another_install(model_dir):
    """True for the models folder of another copy of the app with no models in it: the settings come from an earlier
    version or the app folder was renamed, and using this path would create a folder that nothing else uses."""
    path = Path(model_dir).expanduser()
    app_folder = path.parent if path.name == "models" else path
    return PORTABLE and app_folder.name == APP_NAME and path != DEFAULT_MODEL_DIR and not _models_present(path)


# Settings that describe THIS computer. A settings file copied to another computer (for instance because the app
# folder was packed after it had been run and configured) must not carry them over: the other computer would "force"
# a GPU it does not have and look for the models in a folder of somebody else.
_MACHINE_KEYS = ("device", "n_gpu_layers", "model_dir", "hardware_configured")


def _machine_id():
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    return f"{platform.node()}|{user}|{sys.platform}"


def save_config(cfg):
    cfg = dict(cfg, machine=_machine_id())
    APP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = APP_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(APP_CONFIG_PATH)


def load_config():
    """Defaults overlaid with the user's file; creates the file on first run."""
    cfg = default_config()
    try:
        data = json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            cfg.update(data)
            saved_on = data.get("machine")
            if saved_on and saved_on != _machine_id():
                defaults = default_config()
                for key in _MACHINE_KEYS:
                    cfg[key] = defaults[key]
                logger.warning("The settings file comes from another computer (%s): hardware settings reset", saved_on)
            if cfg.get("model_dir") and _is_another_install(cfg["model_dir"]):
                logger.warning("Models folder %s belongs to another copy of the app: using the default", cfg["model_dir"])
                cfg["model_dir"] = ""
    except FileNotFoundError:
        try:
            save_config(cfg)
        except OSError:
            logger.exception("Cannot create %s", APP_CONFIG_PATH)
    except Exception:
        logger.exception("Cannot read %s, using defaults", APP_CONFIG_PATH)
    return cfg


# module-level names of this file that other modules copy with "from ...config import NAME"
_EXPORTED = (
    "MODEL_PROFILE", "DEVICE", "N_GPU_LAYERS", "MODEL_DIR", "LANGUAGE", "EMBEDDING_MODEL", "MODEL_PATH",
    "VISION_MODEL_PATH", "VISION_MMPROJ_PATH", "EMBEDDING_DIR", "OUTPUT_DIR", "THESIS_PATH",
)


def _apply(cfg):
    global MODEL_PROFILE, DEVICE, N_GPU_LAYERS, MODEL_DIR, LANGUAGE, EMBEDDING_MODEL, EMBEDDING_DIR
    global MODEL_PATH, VISION_MODEL_PATH, VISION_MMPROJ_PATH, OUTPUT_DIR, THESIS_PATH

    DEVICE = str(cfg.get("device", "cpu")).lower().strip()
    try:
        N_GPU_LAYERS = int(cfg.get("n_gpu_layers", 0))
    except (TypeError, ValueError):
        N_GPU_LAYERS = 0
    if DEVICE != "cuda":
        N_GPU_LAYERS = 0        # "cpu" must mean the CPU, whatever number of GPU layers is stored
    MODEL_DIR = Path(str(cfg.get("model_dir") or default_model_dir())).expanduser()
    LANGUAGE = str(cfg.get("language", "pl")).lower().strip()
    EMBEDDING_MODEL = str(cfg.get("embedding_model", DEFAULT_EMBEDDING_MODEL))

    MODEL_PROFILE = cfg.get("model_profile") if cfg.get("model_profile") in PROFILES else DEFAULT_PROFILE
    MODEL_PATH = text_model_path(MODEL_DIR, MODEL_PROFILE)
    VISION_MODEL_PATH = MODEL_DIR / VISION_SUBDIR / VISION_FILE
    VISION_MMPROJ_PATH = MODEL_DIR / VISION_SUBDIR / VISION_MMPROJ_FILE
    EMBEDDING_DIR = MODEL_DIR / "embeddings" / EMBEDDING_MODEL.split("/")[-1]

    OUTPUT_DIR = Path(str(cfg.get("output_dir") or DATA_DIR / "output")).expanduser()
    THESIS_PATH = Path(str(cfg.get("thesis_path") or Path.home() / "theses" / "thesis.pdf")).expanduser()


def _propagate(old_values):
    """Modules that did "from config import MODEL_PATH" keep the old value after a reload (the user changed the
    settings, picked another folder for the models...). Point them at the new one."""
    me = sys.modules[__name__]
    for name, module in list(sys.modules.items()):
        if module is None or module is me or not name.startswith("analysis.modules.llm"):
            continue
        for attr, old in old_values.items():
            if attr in vars(module) and vars(module)[attr] == old:
                setattr(module, attr, getattr(me, attr))


def reload_config():
    old = {name: globals()[name] for name in _EXPORTED if name in globals()}
    _apply(load_config())
    _propagate(old)


reload_config()


def override_gpu_layers(layers):
    """Use `layers` GPU layers in this process only (the AI process retrying with fewer layers); not saved."""
    global N_GPU_LAYERS
    old = {"N_GPU_LAYERS": N_GPU_LAYERS}
    N_GPU_LAYERS = int(layers) if DEVICE == "cuda" else 0
    _propagate(old)


# --------------------------------------------------------------------------- checks

def _embedding_complete(directory):
    """A sentence-transformers folder with its configuration and the weights."""
    directory = Path(directory)
    return (directory / "modules.json").is_file() and any(
        (directory / weights).is_file() for weights in ("model.safetensors", "pytorch_model.bin")
    )


def _embedding_in_hf_cache():
    """Folder of the embedding model in the Hugging Face cache (an earlier version downloaded it there), or None."""
    try:
        from huggingface_hub import snapshot_download
        path = Path(snapshot_download(_embedding_repo(), local_files_only=True))
        return path if _embedding_complete(path) else None
    except Exception:
        return None


def _embedding_repo():
    return EMBEDDING_MODEL if "/" in EMBEDDING_MODEL else EMBEDDING_REPO_PREFIX + EMBEDDING_MODEL


def embedding_path():
    """Local folder with the embedding model, or None when it has not been downloaded."""
    if _embedding_complete(EMBEDDING_DIR):
        return EMBEDDING_DIR
    return _embedding_in_hf_cache()


def resolve_embedding_model(name=None):
    """What to pass to SentenceTransformer: the local folder when we have it (no network, no cache symlinks),
    otherwise the model name (sentence-transformers then looks in its own cache or downloads it)."""
    if name is None or name == EMBEDDING_MODEL:
        local = embedding_path()
        if local is not None:
            return str(local)
    return name or EMBEDDING_MODEL


def _embedding_dir(model_dir):
    return Path(model_dir) / "embeddings" / EMBEDDING_MODEL.split("/")[-1]


def ai_models_status(model_dir=None, profile=None):
    """Which model files are present: {'gemma': bool, 'vision': bool, 'mmproj': bool, 'embeddings': bool}.

    With no arguments, checks the active config paths. When `model_dir` or `profile` is given, checks that
    folder and profile instead."""
    if model_dir is None and profile is None:
        return {
            "gemma": MODEL_PATH.is_file(),
            "vision": VISION_MODEL_PATH.is_file(),
            "mmproj": VISION_MMPROJ_PATH.is_file(),
            "embeddings": embedding_path() is not None,
        }
    base = Path(model_dir) if model_dir is not None else MODEL_DIR
    prof = profile or MODEL_PROFILE
    return {
        "gemma": text_model_path(base, prof).is_file(),
        "vision": (base / VISION_SUBDIR / VISION_FILE).is_file(),
        "mmproj": (base / VISION_SUBDIR / VISION_MMPROJ_FILE).is_file(),
        "embeddings": _embedding_complete(_embedding_dir(base)) or _embedding_in_hf_cache() is not None,
    }


def _remove_replaced_models():
    """Free the 5 GB of the old vision model, once the new one is in place. Only these exact files are touched."""
    for name in REPLACED_MODEL_FILES:
        try:
            (MODEL_DIR / name).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove the old model file %s", MODEL_DIR / name)


def are_ai_models_downloaded(model_dir=None, profile=None):
    if model_dir is None and profile is None:
        return all(ai_models_status().values())
    base = Path(model_dir) if model_dir is not None else MODEL_DIR
    prof = profile or MODEL_PROFILE
    if not (
        text_model_path(base, prof).is_file()
        and (base / VISION_SUBDIR / VISION_FILE).is_file()
        and (base / VISION_SUBDIR / VISION_MMPROJ_FILE).is_file()
    ):
        return False
    return _embedding_complete(_embedding_dir(base)) or _embedding_in_hf_cache() is not None


JAVA_MIN_VERSION = 17


def java_version():
    """Major version of the Java on PATH (8 for "1.8.0_292", 17 for "17.0.2"), or None if it is missing or unreadable."""
    java = shutil.which("java")
    if not java:
        return None
    try:
        # `java -version` writes to stderr
        result = subprocess.run(
            [java, "-version"], capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    match = re.search(r'version "([^"]+)"', (result.stderr or "") + (result.stdout or ""))
    if not match:
        return None
    parts = match.group(1).split(".")
    try:
        if parts[0] == "1" and len(parts) > 1:  # old scheme: 1.8 means Java 8
            return int(parts[1])
        return int(re.match(r"\d+", parts[0]).group())
    except (AttributeError, ValueError):
        return None


def java_available():
    version = java_version()
    return version is not None and version >= JAVA_MIN_VERSION


class LanguageToolUnavailable(RuntimeError):
    """LanguageTool cannot run (usually no Java or a too old one): the analysis stops, the message says what to fix."""


def java_howto():
    """Steps for this system that put a new enough Java where the app looks for it (the first `java` on PATH)."""
    from ui.i18n import t
    system = "windows" if platform.system() == "Windows" else "linux"
    return t(f"analysis.java_howto_{system}", min=JAVA_MIN_VERSION)


def java_problem():
    """None when the Java on PATH can run LanguageTool, otherwise a message telling the user how to fix it."""
    from ui.i18n import t
    version = java_version()
    if version is None:
        return t("analysis.java_missing", min=JAVA_MIN_VERSION, howto=java_howto())
    if version < JAVA_MIN_VERSION:
        return t("analysis.java_too_old", version=version, min=JAVA_MIN_VERSION, howto=java_howto())
    return None


def download_specific_language(lang_code=None):
    """spaCy models are installed by uv (source) or bundled (frozen); never pip-install at runtime."""
    names = [SPACY_MODELS[lang_code]] if lang_code in SPACY_MODELS else list(SPACY_MODELS.values())
    for name in names:
        if importlib.util.find_spec(name) is None:
            raise RuntimeError(
                f"Brakuje modelu językowego {name}. "
                + ("Ta kompilacja aplikacji jest niekompletna." if FROZEN else "Uruchom ponownie setup (uv sync).")
            )


def check_and_download_requirements(parent=None):
    """Startup check. Never blocks the app and never downloads anything."""
    if not java_available():
        logger.warning("Java not found: LanguageTool (linguistic analysis) will be unavailable")
    try:
        download_specific_language()
    except Exception:
        logger.exception("spaCy model check failed")
    return True


# --------------------------------------------------------------------------- downloads

def _embedding_ignore_patterns(repo):
    """The repository also holds ONNX/OpenVINO/TensorFlow copies of the weights (gigabytes): skip them."""
    ignore = ["onnx/*", "openvino/*", "*.h5", "*.msgpack", "*.ot", "*.onnx", "*.tflite", "*.gguf"]
    try:
        from huggingface_hub import list_repo_files
        if "model.safetensors" in set(list_repo_files(repo)):
            ignore.append("pytorch_model.bin")      # one copy of the weights is enough
    except Exception:
        logger.debug("Could not list %s", repo, exc_info=True)
    return ignore


@contextlib.contextmanager
def cancellable_downloads():
    """Make the Hugging Face downloads stop within a fraction of a second after a cancel.

    huggingface_hub downloads a whole file (gigabytes for the models) in one call, so a cancel only took effect
    between two files. While this is active: every chunk that arrives is a checkpoint (the progress bar of the
    download raises the cancel), chunks are small (256 KB instead of 10 MB, which at a slow connection is seconds of
    waiting for the next one) and the Xet transfer, whose Rust threads cannot be interrupted from Python, is off.
    The part already downloaded stays in a .incomplete file and is continued next time."""
    import sys
    from huggingface_hub import constants
    import huggingface_hub.utils.tqdm      # noqa: F401  (makes sure the module is loaded)

    # the progress bar of a download is created in huggingface_hub/utils/tqdm.py (the name "huggingface_hub.utils.tqdm"
    # in the package namespace is the class, the module itself is only in sys.modules)
    bars = sys.modules["huggingface_hub.utils.tqdm"]
    original_tqdm = bars.tqdm
    original_chunk = constants.DOWNLOAD_CHUNK_SIZE
    original_xet = getattr(constants, "HF_HUB_DISABLE_XET", False)

    class CancellableTqdm(original_tqdm):
        def update(self, n=1):
            run_control.check_cancelled()
            return super().update(n)

    bars.tqdm = CancellableTqdm
    constants.DOWNLOAD_CHUNK_SIZE = 256 * 1024
    constants.HF_HUB_DISABLE_XET = True
    try:
        yield
    finally:
        bars.tqdm = original_tqdm
        constants.DOWNLOAD_CHUNK_SIZE = original_chunk
        constants.HF_HUB_DISABLE_XET = original_xet


def download_ai_models_with_progress(progress_callback=None):
    """Download the optional AI models (only when the user asks for it).

    Everything is downloaded into plain folders (local_dir), never into the Hugging Face cache: the cache is made
    of symbolic links and on Windows creating them needs special privileges (WinError 1314)."""
    if not llm_runtime_available():
        raise RuntimeError("Ta wersja aplikacji nie zawiera modułu AI (llama-cpp-python).")

    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from huggingface_hub import hf_hub_download, snapshot_download
    from ui.i18n import t

    def report(value, text):
        if progress_callback:
            progress_callback(value, text)

    try:
        with cancellable_downloads():
            if not MODEL_PATH.is_file():
                run_control.check_cancelled()
                light = MODEL_PROFILE == "light"
                report(15, t("progress.download_gemma_light" if light else "progress.download_gemma"))
                MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
                hf_hub_download(repo_id=LIGHT_REPO if light else GEMMA_REPO,
                                filename=LIGHT_FILE if light else GEMMA_FILE, local_dir=str(MODEL_PATH.parent))

            VISION_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            if not VISION_MODEL_PATH.is_file():
                run_control.check_cancelled()
                report(50, t("progress.download_vision"))
                hf_hub_download(repo_id=VISION_REPO, filename=VISION_FILE, local_dir=str(VISION_MODEL_PATH.parent))

            if not VISION_MMPROJ_PATH.is_file():
                run_control.check_cancelled()
                report(70, t("progress.download_projector"))
                hf_hub_download(repo_id=VISION_REPO, filename=VISION_MMPROJ_FILE, local_dir=str(VISION_MODEL_PATH.parent))

            _remove_replaced_models()

            if embedding_path() is None:
                run_control.check_cancelled()
                report(80, t("progress.download_embedding"))
                repo = _embedding_repo()
                EMBEDDING_DIR.mkdir(parents=True, exist_ok=True)
                snapshot_download(
                    repo_id=repo, local_dir=str(EMBEDDING_DIR), ignore_patterns=_embedding_ignore_patterns(repo),
                )

            report(90, t("progress.download_done"))
    except run_control.AnalysisCancelled:
        raise
    except OSError as e:
        if e.errno == errno.ENOSPC:
            raise RuntimeError(
                f"Brak miejsca na dysku w folderze modeli ({MODEL_DIR}). Zwolnij miejsce albo wybierz inny folder."
            ) from e
        raise RuntimeError(f"Błąd pobierania modeli: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Błąd pobierania modeli: {e}") from e
