import os
import shutil
import sys


def resource_path(relative_path):
    """local and pyinstaller working path"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return os.path.join(base_path, relative_path)

from pathlib import Path
from platformdirs import user_config_dir, user_data_dir, user_log_dir

APP_NAME = "DiplomaChecker"
LOG_APP_NAME = "Diploma Checker"      # the log folder has always been called like this
FROZEN = getattr(sys, "frozen", False)

# Where the app keeps what it writes (settings, logs, downloaded models).
#
# Built (PyInstaller) app: next to the executable, so everything the app creates sits in one folder and
#   nothing is scattered over the user's home directory:
#       <folder with DiplomaChecker>/data/     app_config.json, index.json, output/
#       <folder with DiplomaChecker>/models/   downloaded AI models
#       <folder with DiplomaChecker>/logs/     app.log
#   (not inside "_internal": that folder belongs to the build and is replaced by every update)
# If that folder is read-only (e.g. the app is installed system-wide) or when running from source, the
# per-user directories of the operating system are used instead.
# DIPLOMACHECKER_HOME=<folder> forces the first layout in a chosen folder.

_LEGACY_CONFIG_DIR = Path(user_config_dir(APP_NAME, appauthor=False, roaming=True))
_LEGACY_DATA_DIR = Path(user_data_dir(APP_NAME, appauthor=False, roaming=True))
LEGACY_MODEL_DIR = Path(user_data_dir(APP_NAME, appauthor=False)) / "models"   # local, not roaming profile
LEGACY_LOG_DIR = Path(user_log_dir(LOG_APP_NAME, appauthor=False))


def _is_writable_dir(path):
    """True if the folder exists (or can be created) and a file can be written there."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _portable_root():
    override = os.environ.get("DIPLOMACHECKER_HOME")
    if override:
        root = Path(override).expanduser()
    elif FROZEN:
        root = Path(sys.executable).resolve().parent
    else:
        return None
    return root if _is_writable_dir(root / "data") else None


PORTABLE_ROOT = _portable_root()
PORTABLE = PORTABLE_ROOT is not None

if PORTABLE:
    CONFIG_DIR = PORTABLE_ROOT / "data"
    DATA_DIR = PORTABLE_ROOT / "data"
    DEFAULT_MODEL_DIR = PORTABLE_ROOT / "models"
    LOG_DIR = PORTABLE_ROOT / "logs"
else:
    CONFIG_DIR = _LEGACY_CONFIG_DIR
    DATA_DIR = _LEGACY_DATA_DIR
    DEFAULT_MODEL_DIR = LEGACY_MODEL_DIR
    LOG_DIR = LEGACY_LOG_DIR

APP_CONFIG_PATH = CONFIG_DIR / "app_config.json"
INDEX_PATH = DATA_DIR / "index.json"


def _migrate_legacy_files():
    """Settings and the document index of an earlier version live in the user profile: copy them once."""
    if not PORTABLE:
        return
    for name, old_dir, new_dir in (
        ("app_config.json", _LEGACY_CONFIG_DIR, CONFIG_DIR),
        ("index.json", _LEGACY_DATA_DIR, DATA_DIR),
    ):
        old, new = old_dir / name, new_dir / name
        try:
            if old.is_file() and not new.exists():
                shutil.copy2(old, new)
        except OSError:
            pass


_migrate_legacy_files()


def _languagetool_dir():
    """Where language_tool_python keeps its (about 200 MB) LanguageTool download."""
    old = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / APP_NAME / "LanguageTool"
    if not PORTABLE:
        return old
    new = DATA_DIR / "LanguageTool"
    if old.is_dir() and any(old.iterdir()) and not new.exists():
        return old                      # already downloaded by an earlier version: do not download it again
    if sys.platform == "win32" and len(str(new)) > 110:
        return old                      # the archive has deep paths: stay clear of the 260 character limit
    return new


LANGUAGETOOL_DIR = _languagetool_dir()
