import re
from functools import lru_cache
from .linguistics_types import Error_type
from .helpers import get_match_info, morf
from .exeptions_check import check_quotes
import logging
from collections import Counter
from .exeptions_check import remove_errors_different_font
from .bibliography_check import EN_MONTH_LONG, EN_MONTH_SHORT, PL_MONTH_LONG, PL_MONTH_SHORT

logger = logging.getLogger(__name__)

DASHES = '-–—'
_ROMAN = re.compile(r'(?=[IVX])X{0,3}(?:IX|IV|V?I{0,3})')
_MONTH = re.compile(rf'(?i)(?:{EN_MONTH_LONG}|{PL_MONTH_LONG})')        # styczeń, stycznia, May
_MONTH_ABBREV = re.compile(rf'(?i)(?:{EN_MONTH_SHORT}|{PL_MONTH_SHORT})')  # sty, sier, Sept
_WEEKDAYS = {
    'poniedziałek', 'wtorek', 'środa', 'czwartek', 'piątek', 'sobota', 'niedziela',
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
}
_WEEKDAY_ABBREVS = {'pon', 'wt', 'śr', 'czw', 'pt', 'sob', 'nd', 'niedz',
                    'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}


_MATERIAL_CODE = re.compile(r'[A-Z]+\d+')


@lru_cache(maxsize=8192)
def _lemmas(word):
    return frozenset(interp[2][1].split(':')[0].lower() for interp in morf.analyse(word))


@lru_cache(maxsize=8192)
def _tag_classes(word):
    return frozenset(interp[2][2].split(':')[0] for interp in morf.analyse(word))


def _period_kind(word):
    '''"month" / "weekday" / "month_abbrev" / "weekday_abbrev", e.g. "stycznia", "May", "piątku", "sty", "pt".
    Months come from bibliography_check patterns, weekdays from Morfeusz lemmas.'''
    if _MONTH.fullmatch(word):
        return 'month'
    if word.lower() in _WEEKDAY_ABBREVS:      # before lemmas: Morfeusz reads "pt" as piątek
        return 'weekday_abbrev'
    if _WEEKDAYS & (_lemmas(word) | {word.lower()}):
        return 'weekday'
    if _MONTH_ABBREV.fullmatch(word):
        return 'month_abbrev'
    return None


@lru_cache(maxsize=8192)
def _is_adjectival_compound(left, right):
    '''Morfeusz tags the first part of "polsko-niemiecki", "biało-czerwony" as adja,
    but only when the whole hyphenated word is analysed'''
    left_l, right_l = left.lower(), right.lower()
    left_adja = right_adj = False
    for _, _, (orth, _, tag, *_rest) in morf.analyse(f"{left}-{right}"):
        cls = tag.split(':')[0]
        if orth.lower() == left_l and cls == 'adja':
            left_adja = True
        elif orth.lower() == right_l and cls == 'adj':
            right_adj = True
    return left_adja and right_adj


def classify_dash(left, right):
    '''Decides what the words joined by a dash/hyphen form.
    Returns (kind, reason); kind is "compound", "range" or "unknown" 
    (two nouns: for ex.Bielsko-Biała cannot be told apart without knowing the meaning).'''
    if left.isdigit() and right.isdigit():
        return 'range', 'number'
    left_roman, right_roman = _ROMAN.fullmatch(left), _ROMAN.fullmatch(right)
    if left_roman and right_roman:
        return 'range', 'roman'
    if not (left.isalnum() and right.isalnum()):
        return 'unknown', None
    if left.isdigit() and right.isalpha() and right.islower():
        return 'compound', 'number_suffix' #10-letni
    if left_roman and right.isalpha() and right.islower():
        return 'compound', 'number_suffix' # XIX-wieczny
    if left.isalpha() and left.isupper() and right.isdigit():
        return 'compound', 'identifier' #RS-232, F-16
    if _MATERIAL_CODE.fullmatch(left) and right.isalpha() and right.isupper() and len(right) <= 3:
        return 'compound', 'identifier' # PA12-C
    if (len(left) >= 2 and left.isupper() and right.isalpha() and right.islower()
            and (len(right) <= 4 or right.startswith('ow'))):
        return 'compound', 'abbrev_inflection' # PDF-a,
    if len(left) == 1 and left.islower() and left.isalpha() and right.isalpha() and len(right) >= 3:
        return 'compound', 'letter_prefix'# e-mail, e-learning
    left_period, right_period = _period_kind(left), _period_kind(right)
    if left_period and left_period == right_period:
        return 'range', left_period  # maj–czerwiec, poniedziałek–piątek, pon–pt, sty–mar
    if left.isalpha() and right.isalpha() and _is_adjectival_compound(left, right):
        return 'compound', 'adjectival'  # polsko-niemiecki, biało-czerwony
    if (left.isalpha() and left.islower() and right.isalpha() and right.islower()
            and _tag_classes(left) == {'prep'} and _tag_classes(right) <= {'adj', 'ign'}):
        return 'compound', 'prep_prefix' # między-datasetowych
    return 'unknown', None


def _words_around(text, pos):
    '''Alphanumeric words directly touching the dash at pos (no spaces) and whether
    they are part of a chain like "end-to-end" (another dash right before/after).'''
    start = pos
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    end = pos + 1
    while end < len(text) and text[end].isalnum():
        end += 1
    chained = (start > 0 and text[start - 1] in DASHES) or (end < len(text) and text[end] in DASHES)
    return start, end, text[start:pos], text[pos + 1:end], chained

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
            marker_word = getattr(unit, "marker_word", None)
            candidate_words = ([marker_word] if marker_word is not None else []) + list(unit.words)
            for word in candidate_words:
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

        # półpauza/pauza bez spacji między wyrazami: odróżniamy nazwę łączoną (dywiz) od zakresu (półpauza)
        for m in re.finditer(r'[–—]', text):
            pos = m.start()
            if not (0 < pos < len(text) - 1 and text[pos - 1].isalnum() and text[pos + 1].isalnum()):
                continue
            start, end, left, right, chained = _words_around(text, pos)
            if m.group() == '—':
                # pauza bez spacji: brakujące spacje we wtrąceniu (zakres cyfra—cyfra pomijamy)
                if text[pos - 1].isdigit() and text[pos + 1].isdigit():
                    continue
                err_start, err_len = pos - 1, 3
                if block.block.language == 'en':
                    message = "Missing space around dash in interjection."
                else:
                    message = "Brak spacji wokół myślnika we wtrąceniu, bądź półpauza zamiast dywizu w nazwie łączonej."
            else:
                #półpauza bez spacji jest poprawna w zakresach i relacjach (1990–2000, klient–serwer), błędem jest tylko w nazwie łączonej
                if chained or classify_dash(left, right)[0] != 'compound':
                    continue
                err_start, err_len = start, end - start
                if block.block.language == 'en':
                    message = "En dash instead of hyphen in a compound word."
                else:
                    message = "Półpauza zamiast dywizu w nazwie łączonej."
            content = text[err_start:err_start + err_len]
            start_page, end_page, word_idxs, error_coordinare, _ = get_match_info(unit, err_start, err_len)
            errors.append(Error_type(
                content=content,
                category="PUNCTUATION",
                message=message,
                offset=err_start,
                error_length=err_len,
                block_id=unit.block_id,
                page_start=start_page,
                page_end=end_page,
                word_idxs=word_idxs,
                error_coordinate= error_coordinare
            ))

        #dywiz zamiast półpauzy w zakresie słownym (maj-czerwiec, pon-pt);
        if unit.type not in {"acronyms", "toc", "tof", "tot"}:
            for m in re.finditer(r'(?<=\w)-(?=\w)', text):
                start, end, left, right, chained = _words_around(text, m.start())
                if chained or not left or not right:
                    continue
                kind, reason = classify_dash(left, right)
                if kind != 'range' or reason not in {'month', 'weekday', 'month_abbrev', 'weekday_abbrev'}:
                    continue
                start_page, end_page, word_idxs, error_coordinare, _ = get_match_info(unit, start, end - start)
                if block.block.language == 'en':
                    message = "Hyphen instead of en dash in a range."
                else:
                    message = "Dywiz zamiast półpauzy w zakresie."
                errors.append(Error_type(
                    content=text[start:end],
                    category="PUNCTUATION",
                    message=message,
                    offset=start,
                    error_length=end - start,
                    block_id=unit.block_id,
                    page_start=start_page,
                    page_end=end_page,
                    word_idxs=word_idxs,
                    error_coordinate= error_coordinare
                ))

        #daty i zakresy
        if text_language == 'en':
            # en: półpauza bez spacji (1990–2000).
            # (?<!\w): liczba nie może być doklejona do litery/cyfry (SG90-30 to oznaczenie, nie zakres)
            date_error_regex = r'(?<!\w)(\d+\s*[–-]\s*\d+|\d+-\d+)'
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
            date_space_regex = r'(?<!\w)(\d+\s+[–-]\s+\d+)'
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
        if "Półpauza zamiast dywizu" in m.message or "En dash instead" in m.message:
            msg_counts["dash_as_hyphen"] += 1
        elif "Dywiz zamiast" in m.message or "Hyphen instead" in m.message:
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

