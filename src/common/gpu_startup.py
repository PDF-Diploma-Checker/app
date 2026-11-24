"""What the GPU mode is still missing, worked out right after the app starts.

find_issues() is a plain function over the facts of common.gpu_check (and the model files), so it is easy to test.
check() gathers the facts (slow: run it off the UI thread) and returns the issues; the window that shows them is
ui/gpu_startup_dialog.py and the texts live in ui/translations.py (section "gpu_startup").

Nothing is reported for the CPU build, for a computer where the user chose the processor, or when all is in place.
"""

import logging
import sys
from dataclasses import dataclass, field

from common import gpu_check

logger = logging.getLogger(__name__)

DISMISSED_KEY = "gpu_hint_dismissed"        # in app_config.json: the issues the user asked not to be reminded of
GUIDE_URL = "https://github.com/PDF-Diploma-Checker/app/blob/main/setup_guide.md"
MODEL_LABELS = {
    "gemma": "Gemma 3 12B",
    "vision": "Qwen2.5-VL 7B",
    "mmproj": "Qwen2.5-VL projector",
    "embeddings": "Embeddings",
}


@dataclass
class Issue:
    id: str
    params: dict = field(default_factory=dict)


def setup_command():
    """The command that installs the GPU variant from the source tree."""
    return ".\\setup.ps1 gpu" if sys.platform == "win32" else "./setup.sh gpu"


def gpu_mode_wanted(facts, cfg):
    """True when this install is meant to run on the graphics card (and the user has not chosen the processor)."""
    if cfg.get("hardware_configured") and cfg.get("device") == "cpu":
        return False
    return facts.get("torch") == "cuda" or cfg.get("device") == "cuda"


def find_issues(facts, cfg):
    """Issues that stand in the way of the GPU mode, most fundamental first; [] when nothing is missing."""
    ai_runtime = bool(facts.get("ai_runtime"))
    if not ai_runtime or not gpu_mode_wanted(facts, cfg):
        # without the AI libraries this is the base build: it has no detailed mode at all, so there is nothing to set
        # up (the analysis dialog already says the detailed mode is unavailable)
        return []
    issues = []

    nvidia = facts.get("nvidia")
    free_vram = 0.0
    if nvidia:
        cuda = gpu_check._parse_cuda_version(facts.get("driver_cuda") or "")
        if cuda is not None and cuda < gpu_check.MIN_DRIVER_CUDA:
            issues.append(Issue("driver", {
                "driver": nvidia["driver"], "cuda": facts["driver_cuda"], "needed": "{}.{}".format(*gpu_check.MIN_DRIVER_CUDA),
            }))
        free_vram = max(float(nvidia["vram_gb"]) - float(nvidia.get("used_mb", 0.0)) / 1024.0, 0.0)
    elif facts.get("other_gpus"):
        issues.append(Issue("gpu_other", {"name": "; ".join(facts["other_gpus"])}))
    else:
        issues.append(Issue("gpu_none"))

    if ai_runtime and not facts.get("gpu_build"):
        issues.append(Issue("gpu_build", {"cmd": setup_command()}))

    profile = facts.get("profile", "full")
    if nvidia and gpu_check.is_weak_gpu(free_vram, profile):
        layers = gpu_check.recommend_gpu_layers(free_vram, profile)
        needed = gpu_check.LIGHT_GOOD_VRAM_GB if profile == "light" else gpu_check.GOOD_VRAM_GB
        issues.append(Issue("vram" if layers else "vram_tiny", {
            "vram": f"{free_vram:.1f}", "needed": f"{needed:.0f}", "layers": layers,
        }))

    models = facts.get("models") or {}
    labels = dict(MODEL_LABELS, gemma="Gemma 3 4B") if profile == "light" else MODEL_LABELS
    missing = [labels.get(name, name) for name, present in models.items() if not present]
    if missing:
        issues.append(Issue("models", {
            "missing": ", ".join(missing), "dir": facts.get("model_dir", ""), "size": f"{gpu_check.models_size_gb(profile):.0f}",
        }))
        free = float(facts.get("free_gb") or 0.0)
        if free < gpu_check.NEEDED_FREE_GB:
            issues.append(Issue("disk", {"free": f"{free:.0f}", "needed": f"{gpu_check.NEEDED_FREE_GB:.0f}"}))
    return issues


def signature(issues):
    """A short text that identifies a set of issues; a new problem changes it, so it is reported even after a dismissal."""
    return ",".join(sorted(issue.id for issue in issues))


def is_dismissed(issues, cfg):
    return bool(issues) and cfg.get(DISMISSED_KEY) == signature(issues)


def dismiss(issues):
    """Remember that the user does not want to be reminded of these issues."""
    from analysis.modules.llm import config
    cfg = config.load_config()
    cfg[DISMISSED_KEY] = signature(issues)
    config.save_config(cfg)


def check():
    """Everything that is missing for the GPU mode and has not been dismissed. Slow: run it off the UI thread."""
    from analysis.modules.llm import config

    cfg = config.load_config()
    if cfg.get("hardware_configured") and cfg.get("device") == "cpu":
        return []                                   # nothing to look up: the processor was chosen
    facts = gpu_check.collect_facts()
    facts["models"] = config.ai_models_status()
    facts["profile"] = config.MODEL_PROFILE
    issues = find_issues(facts, cfg)
    logger.info("GPU startup check: %s", signature(issues) or "nothing missing")
    return [] if is_dismissed(issues, cfg) else issues
