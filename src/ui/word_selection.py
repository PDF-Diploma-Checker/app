"""Text selection on a PDF page, done on the words of the page (PyMuPDF `get_text("words")` tuples:
x0, y0, x1, y1, text, block, line, word).

Two ways of selecting:
- select_words(): the words whose centre lies in a rectangle (kept for the old rectangle selection),
- flow selection (ordered_words / hit_index / selection_between): like in a browser or a PDF reader, from the word under
  the press to the word under the mouse, in reading order, across lines. It is highlighted line by line (line_rects).
"""

import re


def select_words(words, rect):
    """(text, bounds) of the words whose centre is inside `rect` (x0, y0, x1, y1, in PDF points), in reading order.
    `bounds` is the box around exactly those words, or None when nothing was selected."""
    left, top, right, bottom = rect
    chosen = [w for w in words
              if left <= (w[0] + w[2]) / 2 <= right and top <= (w[1] + w[3]) / 2 <= bottom and str(w[4]).strip()]
    if not chosen:
        return "", None
    chosen.sort(key=lambda w: (w[5], w[6], w[7]))
    text = " ".join(str(w[4]) for w in chosen)
    bounds = (min(w[0] for w in chosen), min(w[1] for w in chosen),
              max(w[2] for w in chosen), max(w[3] for w in chosen))
    return text, bounds


# ------------------------------------------------------------------------------------------------- flow selection
def ordered_words(words):
    """The non-empty words of a page in reading order (block, line, word)."""
    return sorted((w for w in words or [] if str(w[4]).strip()), key=lambda w: (w[5], w[6], w[7]))


def _lines(ordered):
    """[(first index, last index, top, bottom)] of every line of `ordered`."""
    lines = []
    for i, w in enumerate(ordered):
        key = (w[5], w[6])
        if lines and lines[-1][4] == key:
            first, _, top, bottom, _ = lines[-1]
            lines[-1] = (first, i, min(top, w[1]), max(bottom, w[3]), key)
        else:
            lines.append((i, i, w[1], w[3], key))
    return [line[:4] for line in lines]


def hit_index(ordered, x, y):
    """Index in `ordered` of the word the point (x, y) refers to, or None for a page without words.

    The line is the one whose height holds y (the nearest one when y is between lines or in the margin; with two
    columns the one also nearest horizontally). In that line: the word under x, the first word when x is before the
    line and the last one when it is after it, like the caret of a text editor."""
    if not ordered:
        return None
    best = None
    for first, last, top, bottom in _lines(ordered):
        left = min(ordered[i][0] for i in range(first, last + 1))
        right = max(ordered[i][2] for i in range(first, last + 1))
        dy = 0.0 if top <= y <= bottom else min(abs(y - top), abs(y - bottom))
        dx = 0.0 if left <= x <= right else min(abs(x - left), abs(x - right))
        score = (dy, dx)
        if best is None or score < best[0]:
            best = (score, first, last)
    _, first, last = best
    for i in range(first, last + 1):
        w = ordered[i]
        if x < w[2] or i == last:
            # a point in the gap before a word belongs to that word; past the line end it is the last word
            return i
    return last


def selection_between(ordered, anchor, focus):
    """The words from index `anchor` to `focus` (in either order), inclusive."""
    if anchor is None or focus is None:
        return []
    start, end = sorted((anchor, focus))
    return ordered[start:end + 1]


def _same_row(a, b):
    """True when two boxes (x0, y0, x1, y1) are on the same printed line (their heights overlap by half)."""
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    return overlap > 0.5 * min(a[3] - a[1], b[3] - b[1])


def line_rects(chosen, pad=1.0):
    """One rectangle (x0, y0, x1, y1) per printed line of the chosen words: the highlight follows the text, not a
    box. (PyMuPDF splits a justified line at its wide spaces; the pieces of one printed line are joined again.)"""
    rects = []
    for w in chosen:
        box = (w[0], w[1], w[2], w[3])
        if rects and w[5] == rects[-1][4] and _same_row(rects[-1], box) and box[0] >= rects[-1][0]:
            last = rects[-1]
            rects[-1] = (last[0], min(last[1], box[1]), max(last[2], box[2]), max(last[3], box[3]), w[5])
        else:
            rects.append(box + (w[5],))
    return [(x0 - pad, y0 - pad, x1 + pad, y1 + pad) for x0, y0, x1, y1, _ in rects]


def bounds_of(chosen):
    if not chosen:
        return None
    return (min(w[0] for w in chosen), min(w[1] for w in chosen), max(w[2] for w in chosen), max(w[3] for w in chosen))


_HYPHENS = ("-", "­", "‐")


def selection_text(chosen):
    """The selected words as text: lines joined with a space, paragraphs (PyMuPDF blocks, e.g. a heading and the
    text under it) with a line break, a word split by a hyphen at the end of a line joined back
    ("przy-" + "kład" -> "przykład")."""
    out = ""
    previous = None
    for w in chosen:
        text = str(w[4])
        if previous is None:
            out = text
        elif w[5] != previous[5]:
            out += "\n" + text
        elif w[6] != previous[6] and out.endswith(_HYPHENS) and len(out) > 1 and out[-2].isalpha() \
                and text[:1].islower():
            out = out[:-1] + text
        else:
            out += " " + text
        previous = w
    return out


# ------------------------------------------------------------------------------------------------- plagiarism search
GOOGLE_MAX_WORDS = 32          # Google ignores the words of a query after the 32nd
MIN_WORDS = 6                  # a shorter exact phrase is found everywhere and says nothing
MAX_SEARCHES = 3

_CITATION = re.compile(r"\[\s*\d+(?:\s*[,–-]\s*\d+)*\s*\]")     # [12], [3, 4], [5-7]
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def clean_for_search(text):
    """The text as it is in the thesis, without what is not in any source: reference numbers like [12],
    repeated whitespace and quotation marks (they would end the exact phrase)."""
    text = _CITATION.sub(" ", text)
    text = text.replace('"', " ").replace("„", " ").replace("”", " ")
    return " ".join(text.split())


def search_phrases(text, max_words=GOOGLE_MAX_WORDS, limit=MAX_SEARCHES):
    """Exact phrases to search for: whole sentences packed into pieces of at most `max_words` words (a longer
    sentence is cut at that many words; a paragraph break, e.g. after a heading, always ends a piece), at most
    `limit` pieces. Pieces shorter than MIN_WORDS are dropped unless nothing longer is left."""
    pieces = []
    for paragraph in str(text).split("\n"):
        paragraph = clean_for_search(paragraph)
        current = []
        for sentence in _SENTENCE_END.split(paragraph):
            words = sentence.split()
            while len(words) > max_words:
                if current:
                    pieces.append(current)
                    current = []
                pieces.append(words[:max_words])
                words = words[max_words:]
            if current and len(current) + len(words) > max_words:
                pieces.append(current)
                current = []
            current = current + words
        if current:
            pieces.append(current)
    pieces = [p for p in pieces if p]
    long_enough = [p for p in pieces if len(p) >= MIN_WORDS]
    chosen = long_enough or pieces[:1]
    return [" ".join(p) for p in chosen[:limit]]
