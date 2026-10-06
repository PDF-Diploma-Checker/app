import sys
import json
from pathlib import Path
import os

def get_app_dir():
    """
    Zwraca katalog zawierający konfigurację aplikacji.
    W trybie deweloperskim zwraca główny katalog projektu.
    W spakowanej wersji PyInstaller zwraca folder, w którym znajduje się plik wykonywalny.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    else:
        return Path(__file__).resolve().parent.parent.parent

APP_DIR = get_app_dir()
APP_CONFIG_PATH = APP_DIR / "app_config.json"

THESIS_DIR = Path.home() / "theses"

def ensure_and_load_config():
    """
    Sprawdza, czy app_config.json istnieje. 
    Jeśli go nie ma, tworzy domyślny plik konfiguracyjny z bazowymi ustawieniami.
    Następnie wczytuje i zwraca zawartość słownika JSON.
    """
    if not APP_CONFIG_PATH.exists():
        default_config = {
            "device": "cuda",
            "n_gpu_layers": 25,
            "model_dir": str(Path.home() / "models"),
            "language": "pl",
            "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
            "thesis_path": str(THESIS_DIR / "jost2.pdf"),
            "output_dir": str(APP_DIR / "output")
        }
        try:
            APP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with APP_CONFIG_PATH.open("w", encoding="utf-8") as file:
                json.dump(default_config, file, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CONFIG] Nie udało się utworzyć domyślnego app_config.json: {e}")

    try:
        with APP_CONFIG_PATH.open("r", encoding="utf-8") as file:
            config = json.load(file)
            if isinstance(config, dict):
                return config
    except Exception as e:
        print(f"[CONFIG] Błąd odczytu app_config.json: {e}")

    return {
        "device": "cuda",
        "n_gpu_layers": 25,
        "model_dir": str(Path.home() / "models"),
        "language": "pl"
    }

_CONFIG = ensure_and_load_config()

DEVICE = str(_CONFIG.get("device", "cuda")).lower().strip()
N_GPU_LAYERS = int(_CONFIG.get("n_gpu_layers", 25))

print("[CONFIG] N_GPU_LAYERS =", N_GPU_LAYERS)

MODEL_DIR = Path(str(_CONFIG.get("model_dir", Path.home() / "models"))).expanduser()
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