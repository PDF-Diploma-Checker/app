from .helpers import add_match
import re
from collections import Counter 
import logging

logger = logging.getLogger(__name__)

MIN_SUPPORT = 3
MIN_SHARE = 0.6
MIN_TYPE_GROUP = 5
MIN_PARSE_CONFIDENCE = 0.5
DOT_SHARE = 0.8
SPECIAL_TYPES = {'legislation', 'standard', 'patent'}

FIELD_LABELS = {
    'pl': {
        'authors': 'autorzy', 'title': 'tytuł', 'container': 'czasopismo/materiały',
        'publisher': 'wydawca', 'place': 'miejsce', 'date': 'data', 'volume': 'wolumin',
        'pages': 'strony', 'url': 'adres URL', 'access_date': 'data dostępu',
    },
    'en': {
        'authors': 'authors', 'title': 'title', 'container': 'journal/proceedings',
        'publisher': 'publisher', 'place': 'place', 'date': 'date', 'volume': 'volume',
        'pages': 'pages', 'url': 'URL', 'access_date': 'access date',
    },
}

EQUIVALENT_DATE_FORMATS = [
    {"(yyyy)", "yyyy", "(yyyy, month)", "(yyyy, mon)", "(yyyy, miesiąc)", "(yyyy, mies.)"},
    {"dd mon yyyy", "dd mies. yyyy"},
    {"mon yyyy", "mies. yyyy"},
    {"yyyy-mm-dd", "yyyy.mm.dd", "yyyy/mm/dd"},
    {"dd month yyyy", "dd miesiąc yyyy"},
    {"dd.mm.yyyy", "dd/mm/yyyy", "dd-mm-yyyy"},
]


def check_item_words(matches, item, block, category, message, content):
    """
    Adds a match error with coordinates for a specific bibliography item.
    """
    if not item.item.words:
        return matches
    words = item.item.words
    word_idxs = [w.word_index for w in words]
    page_start = words[0].page_number
    page_end = words[-1].page_number
    error_coordinate = [{"page": words[0].page_number, "coordinates": [min(w.bbox[0] for w in words), min(w.bbox[1] for w in words), max(w.bbox[2] for w in words), max(w.bbox[3] for w in words)]}]
    matches.append(add_match(content, block.block_id, page_start, page_end, word_idxs, error_coordinate, category, message))
    return matches

def get_text(field):
    """
    Extracts the text value from a parsed bibliography field.
    """
    if not field or not isinstance(field, dict):
        return None
    return next(iter(field.keys()), None)

def get_format(field):
    """
    Extracts the format attribute from a parsed bibliography field.
    """
    if not field or not isinstance(field, dict):
        return None
    return next(iter(field.values()), None)


def check_order(item):
    """
    Determines the order of fields in a bibliography item from the positions found by the parser.
    Using parser spans instead of searching the text avoids matching a year that is part of the
    title or a publisher name that also appears elsewhere in the entry.
    """
    positions = {}
    for name, span in (item.spans or {}).items():
        if name in ('access_date', 'place'):
            continue
        if item.confidence and name in item.confidence and item.confidence[name] < MIN_PARSE_CONFIDENCE:
            continue
        positions[name] = span[0]
    return tuple(sorted(positions.keys(), key=lambda key: positions[key]))


def get_field_separator(item):
    """
    Identifies the most common separator character used between fields in a bibliography item.
    Used as a fallback when the parser could not determine the separator from field spans.
    """

    text = item.content
    separators = []
    if item.authors and get_text(item.authors):
        auth_str = get_text(item.authors)
        pos = text.find(auth_str)
        if pos != -1:
            end_pos = pos + len(auth_str)
            after = text[end_pos:].strip()
            match_date = re.match(r'^\s*\(\d{4}[^\)]*\)', after)
            if match_date:
                end_pos += match_date.end()
                after = text[end_pos:].strip()

            sep = re.match(r'^[.,;:]', after)
            if sep:
                separators.append(sep.group(0))
    if item.title and get_text(item.title):
        title_str = get_text(item.title)
        pos = text.find(title_str)
        if pos != -1:
            end_pos = pos + len(title_str)
            after = text[end_pos:].strip()
            while after and after[0] in '"”’\'':
                end_pos += 1
                after = text[end_pos:].strip()
            sep = re.match(r'^[.,;:]', after)
            if sep:
                separators.append(sep.group(0))

    return Counter(separators).most_common()[0][0] if separators else None


def message(block):
    """Returns the full set of messages in the language of the bibliography block."""
    return MESSAGES_EN if getattr(block, 'language', None) == 'en' else MESSAGES_PL


def label(block, field):
    """
    Retrieves the translated label for a given bibliography field based on the block's language.
    """
    return FIELD_LABELS['en' if getattr(block, 'language', None) == 'en' else 'pl'].get(field, field)


def detail(block, expected, found):
    """
    Appendix "expected X, found Y" — without it the coherence message does not tell
    the user what exactly to fix.
    """
    if expected is None or found is None:
        return ''
    if getattr(block, 'language', None) == 'en':
        return f" (expected: „{expected}”, found: „{found}”)"
    return f" (oczekiwano: „{expected}”, znaleziono: „{found}”)"


def dominant(values):
    """
    Dominant value computed only when it has enough support and a clear lead. This prevents
    one of two entries of a given type from being automatically flagged as an error.
    """
    values = [value for value in values if value]
    if len(values) < MIN_SUPPORT:
        return None
    counted = Counter(values).most_common()
    top_value, top_count = counted[0]
    if len(counted) > 1 and top_count == counted[1][1]:
        return None
    if top_count / len(values) < MIN_SHARE:
        return None
    return top_value


def group_key(item, grouped_types):
    """Entries are compared within their type only when the type has enough representatives;
    otherwise they are compared against the entire bibliography."""
    return item.bibtex_type if item.bibtex_type in grouped_types else '*'


def reliable(item):
    """
    Determines if a bibliography item contains sufficient recognized data
    to be considered reliable for coherence checks.
    """
    return (item.parse_confidence or 0) >= MIN_PARSE_CONFIDENCE


def comparable(item):
    """Whether the entry can participate in formatting coherence comparisons."""
    return reliable(item) and item.entry_type not in SPECIAL_TYPES


def check_iso(matches, item, block):
    """
    Fills in the entry separator when the parser could not derive it from field spans.
    The final-dot rule is checked for the whole bibliography in check_coherence_iso.
    """
    if item.separator is None and item.authors and get_text(item.authors):
        item.separator = get_field_separator(item)
    return matches


def get_ending(item):
    """
    Determines how the entry ends (with a dot or otherwise).
    Special handling is applied to URLs and DOIs which do not require a dot.
    """
    if getattr(item, 'ending', None):
        return item.ending
    text = item.content.strip()
    ends_with_url = bool(re.search(r'https?:\s*//(?:\S*[./%\-_=&?]\s+(?=[a-z0-9]))*\S+$|www\.\S+$|doi\.org/\S+$', text))
    if text.endswith('.') or ends_with_url:
        return 'dot'
    return 'other'

def check_final_dots(matches, Bib_context, bib_blocks):
    """
    Final dot at the end of an entry. Always required. If the bibliography consistently ends
    entries without a dot, a single summary remark is reported instead of flagging each entry
    individually — otherwise a single thesis could receive 125 identical messages.
    """
    items = [item for item in Bib_context.items
             if bib_blocks.get(item.item.item_id)]
    if not items:
        return matches
    endings = [get_ending(item) for item in items]
    with_dot = sum(1 for ending in endings if ending == 'dot')
    total = len(items)
    block = bib_blocks.get(items[0].item.item_id)
    messages = message(block)

    if total and with_dot / total >= DOT_SHARE:
        for item, ending in zip(items, endings):
            if ending == 'dot':
                continue
            item_block = bib_blocks.get(item.item.item_id)
            matches = check_item_words(matches, item, item_block, "MISSING_FINAL_DOT",
                                       messages["MISSING_FINAL_DOT"], item.content.strip())
        return matches

    missing = total - with_dot
    if missing:
        summary = messages["MISSING_FINAL_DOT_ALL"].format(missing=missing, total=total)
        matches = check_item_words(matches, items[0], block, "MISSING_FINAL_DOT", summary,
                                   items[0].content.strip())
    return matches


def check_missing_fields(matches, Bib_context, bib_blocks):
    """
    Iterates through all bibliography entries and ensures they contain
    the required bibliographic fields (e.g., authors, dates).
    """
    for item in Bib_context.items:
        block = bib_blocks.get(item.item.item_id)
        if block is None:
            continue
        check_item(matches, item, block)
    
    logger.info("Missing fields check complete: %d matches found", len(matches))
    return matches

PERSISTENT_URL = re.compile(
    r'(10\.\d{4,9}/|'                                 
    r'doi\.org/|ieeexplore\.ieee\.org/document/|dl\.acm\.org/|'
    r'arxiv\.org/abs/|zenodo\.org/|link\.springer\.com/|sciencedirect\.com/science/article/|'
    r'linkinghub\.elsevier\.com/retrieve/pii/|mdpi\.com/\d{4}-\d{3}[\dX]/|ojs\.aaai\.org/)',
    re.IGNORECASE)


def is_online(item):
    """
    Checks if the bibliography item is an online source based on its type
    or the presence of a URL.
    """
    return item.bibtex_type == 'online' or bool(item.url and get_text(item.url))


def has_persistent_id(item):
    """DOI, or a URL pointing to a stable scientific repository."""
    if get_text(item.doi):
        return True
    url = get_text(item.url) if item.url else None
    return bool(url and PERSISTENT_URL.search(url))

def check_item(matches, item, block):
    """
    Validates a single bibliography item for the presence of required fields,
    generating error messages for missing authors, dates, or access identifiers.
    """
    if not reliable(item) or item.entry_type in SPECIAL_TYPES:
        return matches
    messages = message(block)
    text = item.content.strip()

    is_web_page = is_online(item) and not has_persistent_id(item)
    if not (item.date and get_text(item.date[0])):
        if not is_web_page:
            matches = check_item_words(matches, item, block, "MISSING_DATE", messages["MISSING_DATE"], text)
    if is_online(item) and not get_text(item.access_date) and not has_persistent_id(item):
        matches = check_item_words(matches, item, block, "MISSING_ACCESS_DATE_OR_DOI",
                                   messages["MISSING_ACCESS_DATE_OR_DOI"], text)
    return matches


def check_coherence_iso(matches, Bib_context, bib_blocks):
    """
    Checks the overall coherence of formatting (separators, dates, authors, titles, field order)
    across all bibliography items.
    """
    reliable = [item for item in Bib_context.items
                if bib_blocks.get(item.item.item_id) and comparable(item)]

    type_counts = Counter(item.bibtex_type for item in reliable if item.bibtex_type)
    grouped_types = {name for name, count in type_counts.items() if count >= MIN_TYPE_GROUP}

    separators, author_formats = {}, {}
    date_formats, title_formats = {}, {}
    date_positions = {}
    field_order = {}

    for item in Bib_context.items:
        block = bib_blocks.get(item.item.item_id)
        if block is None:
            continue
        check_iso(matches, item, block)

    for item in reliable:
        key = group_key(item, grouped_types)

        if item.authors and get_format(item.authors) not in (None, 'different', 'organization'):
            author_formats.setdefault(key, []).append(get_format(item.authors))
        for date_val in item.date or []:
            fmt = get_format(date_val)
            if fmt:
                date_formats.setdefault(key, []).append(fmt)
                break

    dominant_author_fmt = {key: value for key, value in ((k, dominant(v)) for k, v in author_formats.items()) if value}
    dominant_date_fmt = {key: value for key, value in ((k, dominant(v)) for k, v in date_formats.items()) if value}

    for item in reliable:
        block = bib_blocks.get(item.item.item_id)
        messages = message(block)
        key = group_key(item, grouped_types)

        author_fmt = get_format(item.authors)
        expected = dominant_author_fmt.get(key)
        if author_fmt and expected and author_fmt not in ('different', 'organization'):
            # "Jan Nowak" is a superset of initial-based formats — the same author fits both.
            equivalent = expected == 'Jan Nowak' and author_fmt in {'Nowak J.', 'Nowak, J.'}
            if not equivalent and author_fmt != expected:
                matches = check_item_words(matches, item, block, "AUTHOR_FORMAT_COHERENCE",
                                           messages["AUTHOR_FORMAT_COHERENCE"] + detail(block, expected, author_fmt),
                                           item.content)

        expected = dominant_date_fmt.get(key)
        if item.date and expected:
            found = get_format(item.date[0])
            if found and not date_formats_match(found, expected):
                matches = check_item_words(matches, item, block, "DATE_FORMAT_COHERENCE",
                                           messages["DATE_FORMAT_COHERENCE"] + detail(block, expected, found),
                                           item.content)

    matches = check_final_dots(matches, Bib_context, bib_blocks)
    logger.info("ISO coherence check complete: %d matches found", len(matches))
    return matches


def title_format(item):
    """Title formatting reduced to a form comparable across entries."""
    fmt = get_format(item.title) if item.title else None
    if fmt == 'italic+quotes':
        fmt = 'quotes'
    if fmt in ('sentence_case', 'title_case', 'plain', None):
        return None
    return fmt


def date_formats_match(found, expected):
    """Whether two date notations should be considered the same format."""
    if found == expected:
        return True
    groups = list(EQUIVALENT_DATE_FORMATS)
    for group in groups:
        if found.lower() in group and expected.lower() in group:
            return True
    return False


MESSAGES_PL = {
    "MISSING_FINAL_DOT": "Nie zastosowano kropki na końcu wpisu. Jeśli wpis kończy się linkiem lub doi kropka powinna byc po spacji, żeby nie popsuć funkcjonalności linku.",
    "MISSING_FINAL_DOT_ALL": "Wpisy bibliografii nie są zakończone kropką ({missing} z {total}); norma PN-ISO 690 przewiduje kropkę na końcu wpisu.",
    "MISSING_DATE": "Brakuje daty we wpisie.",
    "MISSING_ACCESS_DATE_OR_DOI": "Wpis online nie ma ani DOI, ani daty dostępu. Dodaj DOI (jeśli publikacja je ma) albo datę dostępu.",
    "AUTHOR_FORMAT_COHERENCE": "Niespójny format autorów wpisu z pozostałymi wpisami bibliografii.",
    "DATE_FORMAT_COHERENCE": "Niespójny format dat wpisu z pozostałymi wpisami bibliografii.",
}

MESSAGES_EN = {
    "MISSING_FINAL_DOT": "A final dot was not used at the end of the entry.",
    "MISSING_FINAL_DOT_ALL": "Bibliography entries do not end with a full stop ({missing} of {total}); PN-ISO 690 expects a dot at the end of an entry.",
    "MISSING_DATE": "Missing date in the entry.",
    "MISSING_ACCESS_DATE_OR_DOI": "Online entry has neither a DOI nor an access date. Add a DOI (if the publication has one) or an access date.",
    "AUTHOR_FORMAT_COHERENCE": "Inconsistent author format in the entry compared to other bibliography entries.",
    "DATE_FORMAT_COHERENCE": "Inconsistent date format in the entry compared to other bibliography entries.",
}
