"""Which figures of a thesis the image analysis looks at, and how the text refers to them.

No model is imported here, so this part can be tested without llama.cpp or a GPU.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Numbering series: "Rysunek 1" and "Wykres 1" are different figures when a thesis numbers them separately.
# Stems cover the Polish cases as well: "na rysunku 2.1", "na wykresie 3".
_FAMILIES = {
    "rys": ("rys", "fig", "rycin", "ilustracj", "grafik", "image", "img"),
    "wykres": ("wykres", "chart", "plot"),
    "fot": ("fot", "photo"),
    "schemat": ("schemat", "schema", "diagram"),
}
_NUMBER = r"\d+(?:\.\d+)*"
_ANY_STEM = "|".join(stem for stems in _FAMILIES.values() for stem in stems)
_CAPTION = re.compile(rf"^\s*((?:{_ANY_STEM})[^\W\d]*\.?)\s*({_NUMBER})", re.IGNORECASE)


def _family_of(word):
    word = word.lower()
    for family, stems in _FAMILIES.items():
        if word.startswith(stems):
            return family
    return "rys"


def reference_pattern(number, family="rys"):
    """Regex matching a mention of this figure in text, in any grammatical case."""
    stems = "|".join(_FAMILIES.get(family, _FAMILIES["rys"]))
    return re.compile(rf"(?<!\w)(?:{stems})[^\W\d]*\.?\s*{re.escape(str(number))}(?!\d|\.\d)", re.IGNORECASE)


def is_caption(paragraph, number, family="rys"):
    """True when the paragraph is the figure's own caption (or its entry in the list of figures)."""
    text = paragraph.strip()
    match = reference_pattern(number, family).match(text)
    if not match:
        return False
    return len(text) < 50 or text[match.end():].lstrip()[:1] in (":", ".", "-", "–", "—")


def figure_sort_key(label):
    """Natural order of labels such as 'Rys. 2.10': by the numbers in them, then by the text."""
    return [int(n) for n in re.findall(r"\d+", label)], label


def parse_yes_no(answer):
    """The model's yes/no answer as True/False; None when it gave neither ("unknown" must not count as "no")."""
    words = set(re.findall(r"[a-z]+", (answer or "").lower()))
    if words & {"yes", "true"}:
        return True
    if words & {"no", "false"}:
        return False
    return None


def consistency_verdict(verification):
    """Normalize the consistency model's answer to 'True', 'False', or 'Error' when it gave no usable verdict."""
    value = str(verification.get("poprawnosc_danych", "")).strip().lower()
    return {"true": "True", "false": "False"}.get(value, "Error")


def _area(img):
    x0, y0, x1, y1 = img.bbox
    return abs(x1 - x0) * abs(y1 - y0)


def collect_figures(doc_obj):
    """Return one entry per captioned figure of the document, read from the extracted image files.

    When one figure is made of several image pieces sharing a caption, the largest piece represents it.
    Images without a caption are skipped: most are decorations or false detections, and the text cannot refer to them.
    """
    best = {}
    uncaptioned = 0
    for page in doc_obj.pages:
        for img in getattr(page, "images", []):
            match = _CAPTION.match(getattr(img, "description", "") or "")
            if not match:
                uncaptioned += 1
                continue
            word, number = match.group(1), match.group(2).rstrip(".")
            key = (_family_of(word), number)
            if key not in best or _area(img) > _area(best[key][0]):
                best[key] = (img, f"{word} {number}")

    figures = []
    for (family, number), (img, label) in best.items():
        path = Path(img.path)
        try:
            data = path.read_bytes()
        except OSError:
            logger.exception("Cannot read the image of %s from %s", label, path)
            continue
        figures.append({
            "id": label,
            "number": number,
            "family": family,
            "bytes": data,
            "path": path,
        })
    logger.info("Image analysis: %d captioned figures, %d images without a caption skipped", len(figures), uncaptioned)
    return figures
