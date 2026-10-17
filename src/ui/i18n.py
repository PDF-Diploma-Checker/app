from PySide6.QtCore import QObject, QSettings, Signal

from .translations import PHRASES

DEFAULT_LOCALE = "pl"
SUPPORTED_LOCALES = ("pl", "en")
_SETTINGS_KEY = "ui/language"


def _flatten(phrases, prefix="", out=None):
    """Turn nested phrase dicts into {"section.key": text}."""
    if out is None:
        out = {}
    for key, value in phrases.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            _flatten(value, full_key, out)
        else:
            out[full_key] = value
    return out


# Flattened once at import; switching language only swaps which dict is active.
_TABLES = {locale: _flatten(PHRASES[locale]) for locale in SUPPORTED_LOCALES}


class _LanguageSignals(QObject):
    changed = Signal(str)


language_signals = _LanguageSignals()


def _settings():
    return QSettings("DiplomaChecker", "DiplomaChecker")


def _load_saved_locale():
    value = _settings().value(_SETTINGS_KEY, DEFAULT_LOCALE)
    return value if value in SUPPORTED_LOCALES else DEFAULT_LOCALE


_locale = _load_saved_locale()
_active = _TABLES[_locale]


def t(key, **kwargs):
    """Return the phrase for `key` in the current language; unknown keys return the key itself."""
    phrase = _active.get(key, key)
    if not kwargs:
        return phrase
    try:
        return phrase.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return phrase


def current_locale():
    return _locale


def set_locale(locale):
    """Switch UI language, remember it for the next start and notify widgets."""
    global _locale, _active
    if locale not in SUPPORTED_LOCALES or locale == _locale:
        return
    _locale = locale
    _active = _TABLES[locale]
    _settings().setValue(_SETTINGS_KEY, locale)
    language_signals.changed.emit(locale)
