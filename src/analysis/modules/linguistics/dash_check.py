import re
from .linguistics_types import Error_type
from .helpers import get_match_info 
from .exeptions_check import check_quotes
import logging
from collections import Counter
from .exeptions_check import remove_errors_different_font

logger = logging.getLogger(__name__)

def dash_check(blocks, main_font=None):
    '''Checks text blocks for correct usage of hyphens, en dashes and em dashes in Polish and English.'''
    logger.info("Starting dash check")
    checked_matches = []
    different_font_dropped = 0

    for block in blocks:
        if block.block.type in {"keywords", "math", "code_snippet"}:
            continue
        if block.block.type == "list":
            if block.block.is_bibliography:
                continue
        # Przygotowujemy jednostki do sprawdzenia (tekst + obiekt)
        text = block.contents
        unit = block.block
        text_language = block.language

        errors = []

        has_en_dash = bool(re.search(r'–', text))
        has_em_dash = bool(re.search(r'—', text))

        if unit.type in {"acronyms", "toc", "tof", "tot"}:
            for word in unit.words:
                if word.text == '-':
                    if unit.language == 'en':
                        message = "Hyphen instead of en dash in a definition."
                    else:
                        message = "Dywiz zamiast półpauzy w definicji."
                    errors.append(Error_type(
                        content='-',
                        category="PUNCTUATION",
                        message=message,
                        offset=word.start_char,
                        error_length=1,
                        block_id=unit.block_id,
                        page_start=word.page_number,
                        page_end=word.page_number,
                        word_idxs=[word.word_index],
                        error_coordinate=[{"page": word.page_number, "coordinates": list(word.bbox)}]
                    ))

        else:
            #" - " lub " -" lub "- "
            hyphen_space_regex = r'(\s-\s|\s-(?=\D|$)|-\s)'
            for m in re.finditer(hyphen_space_regex, text):
                if unit.type == "heading":
                    pos_before = m.start() - 1
                    pos_after = m.end()
                    if (pos_before >= 0 and text[pos_before].isalpha() and
                            pos_after < len(text) and text[pos_after].isalpha()):
                        continue
                start_page, end_page, word_idxs, error_coordinare, _ = get_match_info(unit, m.start(), len(m.group()))
                if block.block.language == 'en':
                    message = "Hyphen instead of en dash or spaces around the hyphen in a hyphenated name."
                else:
                    message = "Dywiz zamiast półpauzy lub spacje wokół dywizu w nazwie łączonej."
                errors.append(Error_type(
                    content=m.group(),
                    category="PUNCTUATION",
                    message= message,
                    offset=m.start(),
                    error_length=len(m.group()),
                    block_id=unit.block_id,
                    page_start=start_page,
                    page_end=end_page,
                    word_idxs=word_idxs,
                    error_coordinate= error_coordinare
                ))

        if has_en_dash and has_em_dash:
            # blad spojnosci jak raz sie uzwa tego i tego
            match = re.search(r'—', text)
            if match:
                start_page, end_page, word_idxs, error_coordinare, _ = get_match_info(unit, match.start(), 1)
                if block.block.language == 'en':
                    message = "Inconsistency: the text uses both en dashes and em dashes."
                else:
                    message = "Niekonsekwencja: w tekście użyto zarówno półpauz, jak i pauz."
                errors.append(Error_type(
                    content="– / —",
                    category="PUNCTUATION",
                    message= message,
                    offset=match.start(),
                    error_length=1,
                    block_id=unit.block_id,
                    page_start=start_page,
                    page_end=end_page,
                    word_idxs=word_idxs,
                    error_coordinate= error_coordinare
                ))

        #litera, myślnik i litera bez spacji
        dash_no_space_regex = r'([a-zA-Z\d])[–—]([a-zA-Z])|([a-zA-Z])[–—]([a-zA-Z\d])'
        for m in re.finditer(dash_no_space_regex, text):
            # Sprawdzamy czy to nie jest zakres dat (cyfra-cyfra), co jest dopuszczalne
            if not (re.match(r'\d', m.group(1) or "") and re.match(r'\d', m.group(2) or "")):
                start_page, end_page, word_idxs, error_coordinare, _ = get_match_info(unit, m.start(), len(m.group()))
                if block.block.language == 'en':
                    message = "Missing space around dash in interjection."
                else:
                    message = "Brak spacji wokół myślnika we wtrąceniu."
                errors.append(Error_type(
                    content=m.group(),
                    category="PUNCTUATION",
                    message=message,
                    offset=m.start(),
                    error_length=len(m.group()),
                    block_id=unit.block_id,
                    page_start=start_page,
                    page_end=end_page,
                    word_idxs=word_idxs,
                    error_coordinate= error_coordinare
                ))

        #daty i zakresy
        if text_language == 'en':
            # en: półpauza bez spacji (1990–2000).
            date_error_regex = r'(\d+\s*[–-]\s*\d+|\d+-\d+)'
            for m in re.finditer(date_error_regex, text):
                content = m.group()
                if '-' in content or ' ' in content:
                    start_page, end_page, word_idxs, error_coordinare, _ = get_match_info(unit, m.start(), len(content))
                    if block.block.language == 'en':
                        message = "English dates do not use spaces around en dashes (–)."
                    else:
                        message = "W angielskich datach nie używa się spacji wokół półpauzy (–)."
                    errors.append(Error_type(
                        content=content,
                        category="PUNCTUATION",
                        message=message,
                        offset=m.start(),
                        error_length=len(content),
                        block_id=unit.block_id,
                        page_start=start_page,
                        page_end=end_page,
                        word_idxs=word_idxs,
                        error_coordinate= error_coordinare
                    ))
        else:
            # pl: półpauza lub dywiz bez spacji (1990–2000 lub 1990-2000).
            date_space_regex = r'(\d+\s+[–-]\s+\d+)'
            for m in re.finditer(date_space_regex, text):
                start_page, end_page, word_idxs, error_coordinare, _ = get_match_info(unit, m.start(), len(m.group()))
                if unit.language == 'en':
                    message = "In Polish date/number ranges, no spaces are used around the dash."
                else:
                    message = "W polskich zakresach dat/liczb nie używa się spacji wokół myślnika."     
                errors.append(Error_type(
                    content=m.group(),
                    category="PUNCTUATION",
                    message=message,
                    offset=m.start(),
                    error_length=len(m.group()),
                    block_id=unit.block_id,
                    page_start=start_page,
                    page_end=end_page,
                    word_idxs=word_idxs,
                    error_coordinate= error_coordinare
                ))

        kept_errors = [e for e in errors if not remove_errors_different_font(e, block, main_font, ignore_style=True)]
        different_font_dropped += len(errors) - len(kept_errors)
        checked_matches.extend(kept_errors)
        
    msg_counts = Counter()
    for m in checked_matches:
        if "Dywiz zamiast" in m.message or "Hyphen instead" in m.message:
            msg_counts["hyphen_as_dash"] += 1
        elif "Niekonsekwencja" in m.message or "Inconsistency" in m.message:
            msg_counts["inconsistent_dash"] += 1
        elif "Brak spacji" in m.message or "Missing space" in m.message:
            msg_counts["missing_space"] += 1
        elif "datach" in m.message or "dates" in m.message.lower() or "zakresach" in m.message or "ranges" in m.message.lower():
            msg_counts["date_range"] += 1
        else:
            msg_counts["other"] += 1
    logger.info("Dash check complete: %d matches", len(checked_matches))
    logger.info("  Different font dropped: %d", different_font_dropped)
    for error_type, count in msg_counts.most_common():
        logger.info("  Dash error type '%s': %d", error_type, count)
    return checked_matches


ABBREV_NO_SPACE = re.compile(
    r'(?<![\w.])(?:tzw|tzn|np|itp|itd|tj|wg|ww|ds|ang|pol|niem|fr)\.(?=[a-ząćęłńóśźż])'
)

def abbreviation_space_check(blocks, main_font=None):
    '''Finds abbreviations followed by a word with no space after the dot, e.g. "tzw.krótkiej".'''
    checked_matches = []
    for block in blocks:
        unit = block.block
        if unit.type in {"math", "code_snippet", "toc", "tof", "tot", "acronyms", "keywords"}:
            continue
        if unit.type == "list" and getattr(unit, "is_bibliography", False):
            continue
        text = block.contents
        for m in ABBREV_NO_SPACE.finditer(text):
            word_end = m.end()
            while word_end < len(text) and text[word_end].isalpha():
                word_end += 1
            if check_quotes(m.start(), word_end, text):
                continue
            if "/" in text[max(0, m.start() - 10):word_end + 10]:   # adresy URL
                continue
            start_page, end_page, word_idxs, coords, has_index = get_match_info(unit, m.start(), word_end - m.start())
            if has_index:
                continue
            all_words = unit.words if hasattr(unit, "words") and unit.words else [
                w for item in getattr(unit, "items", []) for w in item.words
            ]
            matched_words = [w for w in all_words if not (w.end_char <= m.start() or w.start_char >= word_end)]
            if main_font and any(w.font != main_font for w in matched_words):
                continue
            lang = getattr(unit, "language", getattr(block, "language", "pl"))
            message = "Missing space after an abbreviation." if lang == "en" else "Brak spacji po skrócie."
            checked_matches.append(Error_type(
                content=text[m.start():word_end], category="PUNCTUATION", message=message,
                offset=m.start(), error_length=word_end - m.start(), block_id=unit.block_id,
                page_start=start_page, page_end=end_page, word_idxs=word_idxs, error_coordinate=coords,
            ))
    return checked_matches

