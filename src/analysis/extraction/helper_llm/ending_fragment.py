"""Cut the ending of a thesis (the chapter with the conclusions) out of its plain text."""

import re

MAX_END_FRAGMENT_CHARS = 9000

ENDING_HEADINGS = [
    "PODSUMOWANIE",
    "ZAKOŃCZENIE",
    "WNIOSKI KOŃCOWE",
    "WNIOSKI",
    "CONCLUSIONS",
    "CONCLUSION",
    "FINAL REMARKS",
    "SUMMARY",
]


# The chapter that ends the thesis has a top-level number ("7. PODSUMOWANIE"). A subsection ("7.3. Wnioski") has a dotted
# one, and an appendix ("Dodatek B: Podsumowanie audytu ...") none, so neither is taken for the end of the thesis.
NUMBERED_ENDING_RE = re.compile(
    r"(?<![\w.])\d{1,2}\.?\s+(?:" + "|".join(re.escape(heading) for heading in ENDING_HEADINGS) + r")(?!\w)",
    re.IGNORECASE,
)

# What follows the conclusions: the bibliography, and after it the lists of figures and the appendices.
BACK_MATTER_RE = re.compile(
    r"(?<!\w)(?:Wykaz literatury|WYKAZ LITERATURY|Bibliografia|BIBLIOGRAFIA|Bibliography|BIBLIOGRAPHY|References|REFERENCES)(?!\w)"
)
MIN_ENDING_CHARS = 300


def normalize_text(text):
    """Normalize whitespace and non-breaking spaces in free-form text."""

    if not text:
        return ""

    return " ".join(str(text).replace("\xa0", " ").split()).strip()


def _ending_start(normalized):
    """Offset of the chapter that ends the thesis, -1 when there is none."""

    numbered = [match.start() for match in NUMBERED_ENDING_RE.finditer(normalized)]
    if numbered:
        return numbered[-1]

    best = -1

    for heading in ENDING_HEADINGS:
        for match in re.finditer(re.escape(heading), normalized, re.IGNORECASE):
            # "podsumowanie pracy", "wnioski z analizy": a phrase or a longer title, not the heading
            if normalized[match.end():].lstrip()[:1].islower():
                continue
            best = max(best, match.start())

    return best


def extract_ending_fragment(text):
    """Extract thesis ending fragment based on known final-section headings."""

    text = str(text or "")

    if not text.strip():
        return ""

    normalized = normalize_text(text)
    best_start = _ending_start(normalized)

    if best_start != -1:
        fragment = normalized[best_start:]
        back_matter = BACK_MATTER_RE.search(fragment)
        if back_matter and back_matter.start() >= MIN_ENDING_CHARS:
            fragment = fragment[:back_matter.start()]
    else:
        fragment = normalized[-MAX_END_FRAGMENT_CHARS:]

    if len(fragment) > MAX_END_FRAGMENT_CHARS:
        fragment = fragment[:MAX_END_FRAGMENT_CHARS]

    return fragment.strip()
