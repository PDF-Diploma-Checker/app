"""The thesis as fragments for the assistant. A fragment keeps the section it is in, its first page and the boxes of
its lines, so an answer can point at the place in the PDF it comes from."""

import re

TARGET_WORDS = 170          # a fragment: about a paragraph or two (300-450 tokens of Polish)
MAX_WORDS = 240             # a longer paragraph is cut at sentence ends
TEXT_TYPES = ("paragraph", "list", "keywords")
CAPTION_TYPES = ("image_description", "table_description")
SKIPPED_TYPES = ("toc", "tot", "tof")      # tables of contents, of tables, of figures: only titles and page numbers

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9„(\[])")


def _clean(text):
    return " ".join(str(text or "").split())


def _line_rects(words):
    """One box [page, x0, y0, x1, y1] per printed line of the words (also the second part of a word hyphenated at a
    line end, when the extraction keeps it)."""
    rects = {}
    order = []
    for word in words or []:
        pieces = [(word.page_number, getattr(word, "line", 0), word.bbox)]
        pieces += [tuple(p) for p in getattr(word, "extra_boxes", None) or []]
        for page, line, bbox in pieces:
            if not bbox or len(bbox) < 4:
                continue
            key = (page, line, round(float(bbox[1]) / 4))
            if key not in rects:
                rects[key] = [int(page), float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                order.append(key)
            else:
                r = rects[key]
                r[1], r[2] = min(r[1], bbox[0]), min(r[2], bbox[1])
                r[3], r[4] = max(r[3], bbox[2]), max(r[4], bbox[3])
    return [[round(v, 1) if i else v for i, v in enumerate(rects[k])] for k in order]


def _first_page(words, default=0):
    for word in words or []:
        return int(word.page_number)
    return default


def _units(block):
    """(text, words) pieces of a block of about TARGET_WORDS words, cut at sentence ends (a block of at most
    MAX_WORDS words stays whole)."""
    text = _clean(block.content)
    words = list(getattr(block, "words", None) or [])
    if len(text.split()) <= MAX_WORDS:
        return [(text, words)]
    content = str(block.content or "")
    bounds = [0] + [m.start() for m in _SENTENCE_END.finditer(content)] + [len(content)]
    spans, start = [], 0
    for end in bounds[1:]:
        if len(content[start:end].split()) >= TARGET_WORDS or end == len(content):
            spans.append((start, end))
            start = end
    out = []
    for a, b in spans:
        piece = _clean(content[a:b])
        if piece:
            piece_words = [w for w in words if a <= getattr(w, "start_char", 0) < b] or words[:1]
            out.append((piece, piece_words))
    return out


def build_chunks(document):
    """{"chunks": [...], "sections": [...]} of a FinalDocument.

    chunk:   {"id", "kind" (text | caption), "section", "page" (from 0), "text", "rects": [[page, x0, y0, x1, y1]]}
    section: {"title", "page", "rects"} for every heading, in order (to point at a chapter)."""
    chunks, sections = [], []
    section = ""
    pending = None              # the fragment being filled: consecutive paragraphs of one section

    def flush():
        nonlocal pending
        if pending and pending["text"].strip():
            pending["id"] = len(chunks)
            chunks.append(pending)
        pending = None

    for block in getattr(document, "logical_blocks", None) or []:
        kind = getattr(block, "type", "paragraph")
        if kind in SKIPPED_TYPES or getattr(block, "is_bibliography", False):
            flush()
            continue
        words = getattr(block, "words", None) or []
        if kind == "heading":
            flush()
            section = _clean(block.content)[:160]
            sections.append({"title": section, "page": _first_page(words), "rects": _line_rects(words)})
            continue
        if kind in CAPTION_TYPES:
            flush()
            text = _clean(block.content)
            if text:
                chunks.append({"id": len(chunks), "kind": "caption", "section": section,
                               "page": _first_page(words), "text": text, "rects": _line_rects(words)})
            continue
        if kind not in TEXT_TYPES and kind != "acronyms":
            continue
        for text, unit_words in _units(block):
            size = len(text.split())
            if pending and (pending["section"] != section or pending["words"] + size > TARGET_WORDS):
                flush()
            if pending is None:
                pending = {"kind": "text", "section": section, "page": _first_page(unit_words),
                           "text": text, "rects": _line_rects(unit_words), "words": size}
            else:
                pending["text"] += "\n" + text
                pending["rects"] += _line_rects(unit_words)
                pending["words"] += size
    flush()
    for chunk in chunks:
        chunk.pop("words", None)
    return {"chunks": chunks, "sections": sections}
