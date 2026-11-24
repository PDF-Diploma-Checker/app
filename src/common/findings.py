"""Presentation routing shared by the reader, panel and exports.

Categories also identify older saved findings, before explicit scope was stored.
"""
NUMBERING_CATEGORIES = {
    "Footer_on_forbidden_page", "No_footer", "Wrong_page_number",
    "Wrong_page_numbering_start", "numeration_invalid",
}


def finding_kind(error):
    category = error.get("category", error.get("kategoria", ""))
    if category == "raster_image":
        return "raster"
    if category == "missing_caption_source":
        return "caption_source"
    if category == "bibliography_summary":
        return "bibliography"
    if error.get("scope") == "global" or category in NUMBERING_CATEGORIES:
        return "global"
    # Legacy font checks shared config_file with page-specific format checks.
    comment = str(error.get("comment", error.get("komentarz", ""))).lower()
    global_document_prefixes = (
        "the document has ", "dokument ma ",
        "the font used (", "the font size used (",
        "używana czcionka (", "używany rozmiar czcionki (",
    )
    if category == "config_file" and comment.startswith(global_document_prefixes):
        return "global"
    return "page"


def finding_text(error):
    comment = error.get("comment", error.get("komentarz", "")) or ""
    text = error.get("found_text", error.get("znaleziony_tekst", ""))
    return "\n".join(str(value) for value in (comment, text) if value and str(value) != "None")


def _position(error):
    coords = error.get("coords", error.get("wspolrzedne", {})) or {}
    try:
        return float(coords.get("y", 0) or 0), float(coords.get("x", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0.0, 0.0


def assign_finding_ids(errors):
    """Copies of the findings with a short number each (`finding_id`: 1, 2, 3...) to talk about them: the same on the
    marker, in the list of the panel and in the log. The saved findings are not changed. The order is the order of
    reading (page, then the place on the page, the findings that are not about a page last), so the numbers do not
    depend on the order of the stored list."""
    copies = [dict(error) if isinstance(error, dict) else error for error in errors or []]

    def key(pair):
        index, error = pair
        page = error.get("page", error.get("strona"))
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = None
        on_page = finding_kind(error) == "page" and page is not None
        y, x = _position(error)
        return (0 if on_page else 1, page if on_page else 0, y, x,
                str(error.get("category", error.get("kategoria", ""))), str(error.get("comment", "")), index)

    numbered = sorted(((i, e) for i, e in enumerate(copies) if isinstance(e, dict)), key=key)
    for number, (_index, error) in enumerate(numbered, 1):
        error["finding_id"] = number
    return copies


def finding_label(error):
    """'#7' for a finding that has a number, else ''."""
    number = error.get("finding_id") if isinstance(error, dict) else None
    return f"#{number}" if number else ""
