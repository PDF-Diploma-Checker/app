"""Checks the value axis of charts: a missing scale, uneven steps, a bar chart that does not start at zero."""

import io
import logging

from PIL import Image

from analysis.modules.llm.image_analysis.figures import (
    collect_figures,
    image_text,
    parse_axis_numbers,
    parse_yes_no,
    scale_problem,
)
from analysis.modules.llm.image_analysis.vision_engine import ALL_NUMBERS_PROMPT, VisionEngine, too_small_to_read

logger = logging.getLogger(__name__)

BAR_QUESTION = "Is this a bar chart?"
LINE_QUESTION = "Is this a line chart?"
AXIS_PROMPT = "List the numbers printed in this image, from bottom to top, separated by semicolons. If there are none, answer NONE."
AXIS_WIDTH = 0.16       # the part of the image with the vertical axis
MIN_AXIS_PIXELS = 60


def _axis_strip(image_bytes, zoom):
    """Only the strip with the axis: shown a whole chart, the model reports the regular scale it expects to see."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        strip = image.convert("RGB").crop((0, 0, max(int(image.width * AXIS_WIDTH), MIN_AXIS_PIXELS), image.height))
    out = io.BytesIO()
    strip.resize((strip.width * zoom, strip.height * zoom), Image.LANCZOS).save(out, "PNG")
    return out.getvalue()


def _axis_error(engine, image_bytes, is_bar_chart, language):
    """The message for a chart with a bad axis, or None. The model can lose a number, so two readings at different
    sizes have to agree before anything is reported."""
    first = parse_axis_numbers(engine.list_numbers(_axis_strip(image_bytes, 2), AXIS_PROMPT))
    second = parse_axis_numbers(engine.list_numbers(_axis_strip(image_bytes, 3), AXIS_PROMPT))
    if not first and not second:
        if parse_axis_numbers(engine.list_numbers(image_bytes, ALL_NUMBERS_PROMPT)):
            return None     # values printed next to the data
        return image_text(language, "axis_no_scale")
    problem = scale_problem(first, is_bar_chart)
    if problem is None or problem != scale_problem(second, is_bar_chart):
        return None
    ticks = sorted(first)
    if problem == "uneven":
        return image_text(language, "axis_uneven", ticks=", ".join(f"{tick:g}" for tick in ticks))
    return image_text(language, "axis_truncated", start=f"{ticks[0]:g}")


def get_axis_report(doc_obj, mapped_doc, language="pl"):
    """Return a report of charts with a bad value axis. Only bar and line charts are looked at."""
    images = collect_figures(doc_obj)
    report = []

    if not images:
        return report

    with VisionEngine("Osie wykresów") as engine:
        for img in images:
            try:
                if too_small_to_read(img["bytes"]):
                    continue
                is_bar_chart = parse_yes_no(engine.ask_yes_no(img["bytes"], BAR_QUESTION))
                if not is_bar_chart and not parse_yes_no(engine.ask_yes_no(img["bytes"], LINE_QUESTION)):
                    continue
                if engine.is_blurry(img["bytes"]):      # reported by the quality check, and nothing can be read from it
                    continue
                error = _axis_error(engine, img["bytes"], bool(is_bar_chart), language)
            except Exception:
                logger.exception("Axis check inference failed")
                report.append({"rysunek": img["id"], "analysis_failed": True})
                continue
            if error:
                report.append({"rysunek": img["id"], "blad": error})

    return report
