"""Per-user config and helpers for the optional AI mode.

Never import llama_cpp / torch / huggingface_hub at module level:
the base build ships without them.
"""

import errno
import getpass
import functools
import importlib.util
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from common import run_control
from common.path import APP_CONFIG_PATH, DATA_DIR, DEFAULT_MODEL_DIR, LEGACY_MODEL_DIR

logger = logging.getLogger(__name__)

FROZEN = getattr(sys, "frozen", False)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SPACY_MODELS = {"pl": "pl_core_news_lg", "en": "en_core_web_lg"}
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_REPO_PREFIX = "sentence-transformers/"

GEMMA_REPO = "nocturne23/gemma-3-12b-it-Q4_K_M-GGUF"
GEMMA_FILE = "gemma-3-12b-it-q4_k_m.gguf"  # exact name from the repo (case matters on Linux)
LLAVA_REPO = "cjpais/llava-1.6-mistral-7b-gguf"
LLAVA_FILE = "llava-v1.6-mistral-7b.Q4_K_M.gguf"
MMPROJ_FILE = "mmproj-model-f16.gguf"


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


def default_config():
    device = _default_device()
    return {
        "device": device,
        "n_gpu_layers": 25 if device == "cuda" else 0,
        "model_dir": "",                    # empty = the default folder (see default_model_dir())
        "language": "pl",
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "hardware_configured": False,       # becomes True once the user has seen the CPU/GPU setup
    }


def _models_present(model_dir):
    """True when the three model files of the AI mode are in `model_dir`."""
    model_dir = Path(model_dir)
    return all(p.is_file() for p in (
        model_dir / "gemma3_12b" / GEMMA_FILE, model_dir / LLAVA_FILE, model_dir / MMPROJ_FILE,
    ))


def default_model_dir():
    """The folder next to the app (see common.path), unless an earlier version already downloaded the models
    into the per-user folder: those 13 GB must not be downloaded again."""
    if not _models_present(DEFAULT_MODEL_DIR) and _models_present(LEGACY_MODEL_DIR):
        return LEGACY_MODEL_DIR
    return DEFAULT_MODEL_DIR


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
    "DEVICE", "N_GPU_LAYERS", "MODEL_DIR", "LANGUAGE", "EMBEDDING_MODEL", "MODEL_PATH",
    "LLAVA_MODEL_PATH", "LLAVA_MMPROJ_PATH", "EMBEDDING_DIR", "OUTPUT_DIR", "THESIS_PATH",
)


def _apply(cfg):
    global DEVICE, N_GPU_LAYERS, MODEL_DIR, LANGUAGE, EMBEDDING_MODEL, EMBEDDING_DIR
    global MODEL_PATH, LLAVA_MODEL_PATH, LLAVA_MMPROJ_PATH, OUTPUT_DIR, THESIS_PATH

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

    MODEL_PATH = MODEL_DIR / "gemma3_12b" / GEMMA_FILE
    LLAVA_MODEL_PATH = MODEL_DIR / LLAVA_FILE
    LLAVA_MMPROJ_PATH = MODEL_DIR / MMPROJ_FILE
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


def ai_models_status():
    """Which model files are present: {'gemma': bool, 'llava': bool, 'mmproj': bool, 'embeddings': bool}."""
    return {
        "gemma": MODEL_PATH.is_file(),
        "llava": LLAVA_MODEL_PATH.is_file(),
        "mmproj": LLAVA_MMPROJ_PATH.is_file(),
        "embeddings": embedding_path() is not None,
    }


def are_ai_models_downloaded():
    return all(ai_models_status().values())


def java_available():
    java = shutil.which("java")
    if not java:
        return False
    try:
        subprocess.run(
            [java, "-version"], check=True, capture_output=True, timeout=15,
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
        return True
    except Exception:
        return False


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


def download_ai_models_with_progress(progress_callback=None):
    """Download the optional AI models (only when the user asks for it).

    Everything is downloaded into plain folders (local_dir), never into the Hugging Face cache: the cache is made
    of symbolic links and on Windows creating them needs special privileges (WinError 1314)."""
    if not llm_runtime_available():
        raise RuntimeError("Ta wersja aplikacji nie zawiera modułu AI (llama-cpp-python).")

    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from huggingface_hub import hf_hub_download, snapshot_download

    def report(value, text):
        if progress_callback:
            progress_callback(value, text)

    try:
        if not MODEL_PATH.is_file():
            run_control.check_cancelled()
            report(15, "Pobieranie modelu Gemma 3 (ok. 8 GB)...")
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            hf_hub_download(repo_id=GEMMA_REPO, filename=GEMMA_FILE, local_dir=str(MODEL_PATH.parent))

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        if not LLAVA_MODEL_PATH.is_file():
            run_control.check_cancelled()
            report(50, "Pobieranie modelu LLaVA...")
            hf_hub_download(repo_id=LLAVA_REPO, filename=LLAVA_FILE, local_dir=str(MODEL_DIR))

        if not LLAVA_MMPROJ_PATH.is_file():
            run_control.check_cancelled()
            report(70, "Pobieranie projektora LLaVA...")
            hf_hub_download(repo_id=LLAVA_REPO, filename=MMPROJ_FILE, local_dir=str(MODEL_DIR))

        if embedding_path() is None:
            run_control.check_cancelled()
            report(80, "Pobieranie modelu embeddingów...")
            repo = _embedding_repo()
            EMBEDDING_DIR.mkdir(parents=True, exist_ok=True)
            snapshot_download(
                repo_id=repo, local_dir=str(EMBEDDING_DIR), ignore_patterns=_embedding_ignore_patterns(repo),
            )

        report(90, "Modele AI zostały pobrane pomyślnie.")
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
