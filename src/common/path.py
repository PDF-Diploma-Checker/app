import os
import sys


def resource_path(relative_path):
    """local and pyinstaller working path"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return os.path.join(base_path, relative_path)

from pathlib import Path
from platformdirs import user_config_dir, user_data_dir

APP_NAME = "DiplomaChecker"

CONFIG_DIR = Path(user_config_dir(APP_NAME, appauthor=False, roaming=True))
DATA_DIR = Path(user_data_dir(APP_NAME, appauthor=False, roaming=True))

APP_CONFIG_PATH = CONFIG_DIR / "app_config.json"
INDEX_PATH = DATA_DIR / "index.json"

# Models are huge: keep them out of the roaming profile on Windows.
DEFAULT_MODEL_DIR = Path(user_data_dir(APP_NAME, appauthor=False)) / "models"