import sys
import json
import logging
from pathlib import Path
from common.path import resource_path
import os

logger = logging.getLogger(__name__)


def get_app_dir():
    """
    Return the directory containing the application configuration.
    In development mode, this returns the project root directory.
    In a PyInstaller build, this returns the directory containing the executable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    else:
        return Path(__file__).resolve().parent.parent.parent

APP_DIR = get_app_dir()
APP_CONFIG_PATH = APP_DIR / "app_config.json"

EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
THESIS_DIR = Path.home() / "theses"

MODEL_PATH = Path.home() / "models" / "gemma3_12b" / "google_gemma-3-12b-it-Q4_K_M.gguf"
N_GPU_LAYERS = 25
LLAVA_MODEL_PATH = Path.home() / "models" / "llava-v1.6-mistral-7b.Q4_K_M.gguf"
LLAVA_MMPROJ_PATH = Path.home() / "models" / "mmproj-model-f16.gguf"
THESIS_PATH = THESIS_DIR / "jost2.pdf"
LANGUAGE = "en"


def load_app_config():
    """
    Load app_config.json from the application directory.
    """
    if not APP_CONFIG_PATH.exists():
        logger.error("Missing app_config.json: %s", APP_CONFIG_PATH)
        raise FileNotFoundError(f"Missing app_config.json: {APP_CONFIG_PATH}")

    try:
        with APP_CONFIG_PATH.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except json.JSONDecodeError as e:
        logger.exception("Failed to parse app_config.json at %s", APP_CONFIG_PATH)
        raise ValueError(f"app_config.json is not valid JSON: {APP_CONFIG_PATH}") from e

    if not isinstance(config, dict):
        logger.error("app_config.json did not contain a JSON object: %s", APP_CONFIG_PATH)
        raise ValueError("app_config.json must contain a JSON object.")

    return config

_CONFIG = load_app_config()

try:
    DEVICE = str(_CONFIG["device"]).lower().strip()
    N_GPU_LAYERS = int(_CONFIG["n_gpu_layers"])
except KeyError as e:
    logger.exception("Missing required key in app_config.json: %s", APP_CONFIG_PATH)
    raise ValueError(f"Missing required key {e} in app_config.json: {APP_CONFIG_PATH}") from e

logger.info("N_GPU_LAYERS = %s", N_GPU_LAYERS)

try:
    MODEL_DIR = Path(str(_CONFIG["model_dir"])).expanduser()
except KeyError as e:
    logger.exception("Missing required key in app_config.json: %s", APP_CONFIG_PATH)
    raise ValueError(f"Missing required key {e} in app_config.json: {APP_CONFIG_PATH}") from e

LANGUAGE = str(_CONFIG.get("language", "pl")).lower().strip()

MODEL_PATH = MODEL_DIR / "gemma3_12b" / "google_gemma-3-12b-it-Q4_K_M.gguf"
LLAVA_MODEL_PATH = MODEL_DIR / "llava-v1.6-mistral-7b.Q4_K_M.gguf"
LLAVA_MMPROJ_PATH = MODEL_DIR / "mmproj-model-f16.gguf"

THESIS_PATH = Path(str(_CONFIG.get("thesis_path", THESIS_DIR / "jost2.pdf"))).expanduser()
OUTPUT_DIR = Path(str(_CONFIG.get("output_dir", APP_DIR / "output"))).expanduser()

EMBEDDING_MODEL = str(
    _CONFIG.get(
        "embedding_model",
        "paraphrase-multilingual-MiniLM-L12-v2",
    )
)