"""The license agreement: its text and whether the user has accepted this version of it."""

from common.path import resource_path

EULA_VERSION = 1      # raise when the text changes in a way the user has to accept again


def read_eula():
    with open(resource_path("ui/assets/EULA.txt"), encoding="utf-8") as f:
        return f.read()


def is_accepted():
    from analysis.modules.llm import config
    return config.load_config().get("eula_accepted_version") == EULA_VERSION


def accept():
    from analysis.modules.llm import config
    cfg = config.load_config()
    cfg["eula_accepted_version"] = EULA_VERSION
    config.save_config(cfg)
