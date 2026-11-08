"""The license notice and terms of use: their text and whether the user has accepted this version of them."""

from common.path import resource_path

TERMS_VERSION = 1      # raise when the text changes in a way the user has to accept again


def read_terms():
    with open(resource_path("ui/assets/TERMS.txt"), encoding="utf-8") as f:
        return f.read()


def is_accepted():
    from analysis.modules.llm import config
    return config.load_config().get("terms_accepted_version") == TERMS_VERSION


def accept():
    from analysis.modules.llm import config
    cfg = config.load_config()
    cfg["terms_accepted_version"] = TERMS_VERSION
    config.save_config(cfg)
