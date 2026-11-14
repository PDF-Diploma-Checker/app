"""Presentation routing shared by the reader, panel and exports.

Categories also identify older saved findings, before explicit scope was stored.
"""
NUMBERING_CATEGORIES = {
    "Footer_on_forbidden_page", "No_footer", "Wrong_page_number",
    "Wrong_page_numbering_start", "numeration_invalid",
}


def finding_kind(error):
    category = error.get("category", error.get("kategoria", ""))
    if category == "bibliography_summary":
        return "bibliography"
    if error.get("scope") == "global" or category in NUMBERING_CATEGORIES:
        return "global"
    # Legacy font checks shared config_file with page-specific format checks.
    comment = str(error.get("comment", error.get("komentarz", ""))).lower()
    if category == "config_file" and any(word in comment for word in ("font", "czcion")):
        return "global"
    return "page"


def finding_text(error):
    comment = error.get("comment", error.get("komentarz", "")) or ""
    text = error.get("found_text", error.get("znaleziony_tekst", ""))
    return "\n".join(str(value) for value in (comment, text) if value and str(value) != "None")
