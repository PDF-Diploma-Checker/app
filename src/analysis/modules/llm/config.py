"""Per-user config and helpers for the optional AI mode.

Never import llama_cpp / torch / huggingface_hub at module level:
the base build ships without them.
"""

import functools
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common.path import APP_CONFIG_PATH, DATA_DIR, DEFAULT_MODEL_DIR

logger = logging.getLogger(__name__)

FROZEN = getattr(sys, "frozen", False)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SPACY_MODELS = {"pl": "pl_core_news_lg", "en": "en_core_web_lg"}
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

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
        "model_dir": str(DEFAULT_MODEL_DIR),
        "language": "pl",
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
    }


def save_config(cfg):
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
    except FileNotFoundError:
        try:
            save_config(cfg)
        except OSError:
            logger.exception("Cannot create %s", APP_CONFIG_PATH)
    except Exception:
        logger.exception("Cannot read %s, using defaults", APP_CONFIG_PATH)
    return cfg


def _apply(cfg):
    global DEVICE, N_GPU_LAYERS, MODEL_DIR, LANGUAGE, EMBEDDING_MODEL
    global MODEL_PATH, LLAVA_MODEL_PATH, LLAVA_MMPROJ_PATH, OUTPUT_DIR, THESIS_PATH

    DEVICE = str(cfg.get("device", "cpu")).lower().strip()
    try:
        N_GPU_LAYERS = int(cfg.get("n_gpu_layers", 0))
    except (TypeError, ValueError):
        N_GPU_LAYERS = 0
    MODEL_DIR = Path(str(cfg.get("model_dir") or DEFAULT_MODEL_DIR)).expanduser()
    LANGUAGE = str(cfg.get("language", "pl")).lower().strip()
    EMBEDDING_MODEL = str(cfg.get("embedding_model", DEFAULT_EMBEDDING_MODEL))

    MODEL_PATH = MODEL_DIR / "gemma3_12b" / GEMMA_FILE
    LLAVA_MODEL_PATH = MODEL_DIR / LLAVA_FILE
    LLAVA_MMPROJ_PATH = MODEL_DIR / MMPROJ_FILE

    OUTPUT_DIR = Path(str(cfg.get("output_dir") or DATA_DIR / "output")).expanduser()
    THESIS_PATH = Path(str(cfg.get("thesis_path") or Path.home() / "theses" / "thesis.pdf")).expanduser()


def reload_config():
    _apply(load_config())


reload_config()


# --------------------------------------------------------------------------- checks

def are_ai_models_downloaded():
    return all(p.is_file() for p in (MODEL_PATH, LLAVA_MODEL_PATH, LLAVA_MMPROJ_PATH))


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

def download_ai_models_with_progress(progress_callback=None):
    """Download the optional AI models (only when the user asks for it)."""
    if not llm_runtime_available():
        raise RuntimeError("Ta wersja aplikacji nie zawiera modułu AI (llama-cpp-python).")

    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    from huggingface_hub import hf_hub_download, snapshot_download

    def report(value, text):
        if progress_callback:
            progress_callback(value, text)

    try:
        if not MODEL_PATH.is_file():
            report(15, "Pobieranie modelu Gemma 3 (ok. 8 GB)...")
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            hf_hub_download(repo_id=GEMMA_REPO, filename=GEMMA_FILE, local_dir=str(MODEL_PATH.parent))

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        if not LLAVA_MODEL_PATH.is_file():
            report(50, "Pobieranie modelu LLaVA...")
            hf_hub_download(repo_id=LLAVA_REPO, filename=LLAVA_FILE, local_dir=str(MODEL_DIR))

        if not LLAVA_MMPROJ_PATH.is_file():
            report(70, "Pobieranie projektora LLaVA...")
            hf_hub_download(repo_id=LLAVA_REPO, filename=MMPROJ_FILE, local_dir=str(MODEL_DIR))

        report(80, "Pobieranie modelu embeddingów...")
        repo = f"sentence-transformers/{EMBEDDING_MODEL}"
        try:
            snapshot_download(repo, local_files_only=True)
        except Exception:
            snapshot_download(repo)

        report(90, "Modele AI zostały pobrane pomyślnie.")
    except Exception as e:
        raise RuntimeError(f"Błąd pobierania modeli: {e}") from e