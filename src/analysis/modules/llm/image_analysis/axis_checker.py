"""Checks the value axis of charts: a missing scale, uneven steps, a bar chart that does not start at zero."""

import io
import logging
import re

from PIL import Image

from analysis.modules.llm.image_analysis.figures import (
    collect_figures,
    image_text,
    parse_axis_numbers,
    scale_problem,
)
from analysis.modules.llm.image_analysis.vision_engine import VisionEngine, too_small_to_read

logger = logging.getLogger(__name__)

BAR_QUESTION = "Is this a bar chart?"
LINE_QUESTION = "Is this a line chart?"
AXIS_PROMPT = "List the numbers printed in this image, from bottom to top, separated by semicolons. If there are none, answer NONE."
AXIS_QUESTION = (
    "Is the complete vertical numeric value axis clearly visible on the left, with a linear scale "
    "and no axis break? Answer NO for logarithmic, cropped, unreadable or non-Cartesian axes."
)
_UNCHECKED = {
    "pl": "Nie udało się jednoznacznie potwierdzić typu wykresu i odczytu pełnej liniowej osi wartości.",
    "en": "The chart type and complete linear value axis could not be confirmed unambiguously.",
}


class _AxisUnchecked(Exception):
    """Insufficient visual evidence to assess the axis."""


def _answer(answer):
    # Accept only explicit, unambiguous classification answers.
    value = re.sub(r"[.!]$", "", (answer or "").strip().lower())
    return {"yes": True, "true": True, "no": False, "false": False}.get(value)


AXIS_WIDTH = 0.16       # the part of the image with the vertical axis
MIN_AXIS_PIXELS = 60


def _axis_strip(image_bytes, zoom):
    """Only the strip with the axis: shown a whole chart, the model reports the regular scale it expects to see."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        strip = image.convert("RGB").crop((0, 0, min(image.width, max(int(image.width * AXIS_WIDTH), MIN_AXIS_PIXELS)), image.height))
    out = io.BytesIO()
    strip.resize((strip.width * zoom, strip.height * zoom), Image.LANCZOS).save(out, "PNG")
    return out.getvalue()


def _read_ticks(answer):
    """Do not silently discard an unreadable label from an otherwise numeric answer."""
    parts = [part.strip() for part in (answer or "").replace("\n", ";").split(";") if part.strip()]
    ticks = []
    for part in parts:
        values = parse_axis_numbers(part)
        if len(values) != 1 or not (-float("inf") < values[0] < float("inf")):
            raise _AxisUnchecked
        ticks.extend(values)
    return ticks


def _axis_error(engine, image_bytes, is_bar_chart, language):
    """The message for a chart with a bad axis, or None. The model can lose a number, so two readings at different
    sizes have to agree before anything is reported."""
    first = _read_ticks(engine.list_numbers(_axis_strip(image_bytes, 2), AXIS_PROMPT))
    second = _read_ticks(engine.list_numbers(_axis_strip(image_bytes, 3), AXIS_PROMPT))
    if len(first) < 4 or first != second:
        raise _AxisUnchecked
    if not (all(a < b for a, b in zip(first, first[1:]))
            or all(a > b for a, b in zip(first, first[1:]))):
        raise _AxisUnchecked
    problem = scale_problem(first, is_bar_chart)
    if problem is None:
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
                    raise _AxisUnchecked
                is_bar_chart = _answer(engine.ask_yes_no(img["bytes"], BAR_QUESTION))
                if is_bar_chart is None:
                    raise _AxisUnchecked
                if is_bar_chart is False:
                    is_line_chart = _answer(engine.ask_yes_no(img["bytes"], LINE_QUESTION))
                    if is_line_chart is None:
                        raise _AxisUnchecked
                    if is_line_chart is False:
                        continue
                if engine.is_blurry(img["bytes"]) is not False:
                    raise _AxisUnchecked
                if _answer(engine.ask_yes_no(img["bytes"], AXIS_QUESTION)) is not True:
                    raise _AxisUnchecked
                error = _axis_error(engine, img["bytes"], is_bar_chart, language)
            except _AxisUnchecked:
                report.append({"rysunek": img["id"], "analysis_unchecked": True,
                               "reason": _UNCHECKED.get(language, _UNCHECKED["pl"])})
                continue
            except Exception:
                logger.exception("Axis check inference failed")
                report.append({"rysunek": img["id"], "analysis_failed": True})
                continue
            if error:
                report.append({"rysunek": img["id"], "blad": error})

    return report
