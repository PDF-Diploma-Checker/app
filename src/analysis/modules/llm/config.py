import sys
import os
import json
from pathlib import Path
import subprocess
import spacy
from huggingface_hub import hf_hub_download

def get_app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    else:
        return Path(__file__).resolve().parent.parent.parent

APP_DIR = get_app_dir()
APP_CONFIG_PATH = APP_DIR / "app_config.json"
THESIS_DIR = Path.home() / "theses"

def ensure_and_load_config():
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
            print(f"[CONFIG] Nie udało się utworzyć app_config.json: {e}")

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

MODEL_DIR = Path(str(_CONFIG.get("model_dir", Path.home() / "models"))).expanduser()
LANGUAGE = str(_CONFIG.get("language", "pl")).lower().strip()

MODEL_PATH = MODEL_DIR / "gemma3_12b" / "gemma-3-12b-it-Q4_K_M.gguf"
LLAVA_MODEL_PATH = MODEL_DIR / "llava-v1.6-mistral-7b.Q4_K_M.gguf"
LLAVA_MMPROJ_PATH = MODEL_DIR / "mmproj-model-f16.gguf"

THESIS_PATH = Path(str(_CONFIG.get("thesis_path", THESIS_DIR / "jost2.pdf"))).expanduser()
OUTPUT_DIR = Path(str(_CONFIG.get("output_dir", APP_DIR / "output"))).expanduser()
EMBEDDING_MODEL = str(_CONFIG.get("embedding_model", "paraphrase-multilingual-MiniLM-L12-v2"))


def are_ai_models_downloaded():
    """Sprawdza, czy wszystkie wymagane pliki modeli AI fizycznie istnieją na dysku."""
    return MODEL_PATH.exists() and LLAVA_MODEL_PATH.exists() and LLAVA_MMPROJ_PATH.exists()


def download_specific_language(lang_code=None):
    """Zapewnia obecność pakietów językowych SpaCy."""
    os.environ["TQDM_DISABLE"] = "True"
    try:
        import pl_core_news_lg
    except ImportError:
        try:
            spacy.cli.download("pl_core_news_lg")
        except Exception:
            pass
        
    try:
        import en_core_web_lg
    except ImportError:
        try:
            spacy.cli.download("en_core_web_lg")
        except Exception:
            pass


def check_and_download_requirements(parent=None):
    """
    Sprawdza Javę i pakiety SpaCy. NIE pobiera ciężkich modeli AI automatycznie bez pytania!
    """
    os.environ["TQDM_DISABLE"] = "True"
    
    try:
        subprocess.run(["java", "-version"], check=True, capture_output=True)
    except Exception:
        print("[SETUP] Ostrzeżenie: Java nie została zainstalowana w systemie.")

    try:
        download_specific_language()
    except Exception as e:
        print(f"[SETUP] Błąd pobierania języków SpaCy: {e}")

    return True


def download_ai_models_with_progress(progress_callback=None):
    """Pobiera modele AI z Hugging Face z opcjonalnym raportowaniem postępu (tylko na żądanie)."""
    try:
        if progress_callback:
            progress_callback(15, "Pobieranie modelu Gemma 3 (ok. 8GB)...")
            
        if not MODEL_PATH.exists():
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            hf_hub_download(
                repo_id="nocturne23/gemma-3-12b-it-Q4_K_M-GGUF",
                filename="gemma-3-12b-it-q4_k_m.gguf",
                local_dir=str(MODEL_DIR / "gemma3_12b")
            )

        if progress_callback:
            progress_callback(50, "Pobieranie modeli LLaVA...")

        if not LLAVA_MODEL_PATH.exists():
            LLAVA_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            hf_hub_download(
                repo_id="cjpais/llava-1.6-mistral-7b-gguf",
                filename="llava-v1.6-mistral-7b.Q4_K_M.gguf",
                local_dir=str(MODEL_DIR)
            )

        if not LLAVA_MMPROJ_PATH.exists():
            LLAVA_MMPROJ_PATH.parent.mkdir(parents=True, exist_ok=True)
            hf_hub_download(
                repo_id="cjpais/llava-1.6-mistral-7b-gguf",
                filename="mmproj-model-f16.gguf",
                local_dir=str(MODEL_DIR)
            )
            
        if progress_callback:
            progress_callback(90, "Modele AI zostały pobrane pomyślnie.")
            
    except Exception as e:
        raise RuntimeError(f"Błąd pobierania modeli: {str(e)}")