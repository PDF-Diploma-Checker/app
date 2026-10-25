import re
import string
from .helpers import language, lemmatization, add_match, get_match_info, normalize_math_letters
from .check_acronym import potential_acronym
import logging

logger = logging.getLogger(__name__)

DEFINITION_CONNECTORS = {
    "z", "ze", "w", "we", "i", "o", "na", "do", "dla", "od", "oraz", "lub",
    "of", "and", "for", "the", "a", "an", "in", "on", "to", "by", "with", "de",
}
MAX_EXTRA_DEFINITION_WORDS = 3

def add_definition_words(words, proper_names, lemma_language):
    """
    Appends cleaned definition words with their lemmas to proper names.
    """

    for word_raw in words:
        word_clean = word_raw.strip(string.punctuation + string.whitespace)
        if len(word_clean) >= 2:
            proper_names.append((word_clean, lemmatization(word_clean, lemma_language)))

def span_fits(acronym, span):
    """
    Checks if a (start, end) word span is short enough to be a real expansion of the acronym.
    """

    return span is not None and span[1] - span[0] + 1 <= len(acronym) + MAX_EXTRA_DEFINITION_WORDS

def sequence_span(acronym, indexed_initials, anchor):
    """
    Finds the word span covering the acronym letters as a subsequence of initials, searching from the
    start of the definition or backwards from its end.
    """

    letters = list(acronym)
    items = indexed_initials
    if anchor == "end":
        letters = letters[::-1]
        items = items[::-1]
    picked = []
    for letter, word_idx in items:
        if len(picked) == len(letters):
            break
        if letter == letters[len(picked)]:
            picked.append(word_idx)
    if len(picked) < len(letters):
        return None
    return min(picked), max(picked)

def rescue_single_word(acronym, word, proper_names, lemma_language):
    """
    Keeps a one-word term like 'polilaktyd (PLA)' when the full initials check failed, if the word
    starts with the first letter of the acronym.
    """

    word_clean = word.strip(string.punctuation + string.whitespace)
    if len(word_clean) < 2 or word_clean.lower() in DEFINITION_CONNECTORS:
        return
    if word_clean[0].lower() == acronym[0].lower():
        proper_names.append((word_clean, lemmatization(word_clean, lemma_language)))

def trailing_definition_words(acronym, def_words):
    """
    Walks back from the acronym parenthesis and returns the shortest tail of the definition whose
    initials (case-insensitive, hyphen parts counted separately) spell the acronym, or None.
    """

    expected = [c.lower() for c in acronym][::-1]
    limit = len(acronym) + MAX_EXTRA_DEFINITION_WORDS
    matched = 0
    for pos in range(len(def_words) - 1, -1, -1):
        if len(def_words) - pos > limit:
            return None
        word = def_words[pos].strip(string.punctuation + string.whitespace)
        if not word:
            continue
        if matched > 0 and word.lower() in DEFINITION_CONNECTORS:
            continue
        initials = [part[0].lower() for part in word.split('-') if part and part[0].isalpha()][::-1]
        if not initials or initials != expected[matched:matched + len(initials)]:
            return None
        matched += len(initials)
        if matched == len(expected):
            return def_words[pos:]
    return None

def add_trailing_definition(acronym, definition, proper_names, lemma_language):
    """
    Adds only the verified tail of an unchecked definition, falling back to the single word rescue.
    """

    def_words = definition.strip().split()
    if not def_words:
        return
    trimmed = trailing_definition_words(acronym, def_words)
    if trimmed:
        add_definition_words(trimmed, proper_names, lemma_language)
    else:
        rescue_single_word(acronym, def_words[-1], proper_names, lemma_language)

def initials_match(acronym, definition, proper_names, block = None, lang = None, anchor = "start", trim = True, strict = False):
    """
    Verifies if the acronym initials match the given definition.
    On success adds the acronym and the words of the matched definition span to proper names.
    lang sets the lemmatization language (defaults to the detected language of the definition),
    anchor tells on which side of the captured text the real expansion sits ('start' or 'end'),
    trim=False adds all definition words (for trusted sources like the official acronym list),
    strict=True only accepts exact initials / CamelCase match.
    """

    org_words = [w for w in re.split(r'\s+', definition.strip()) if w]
    def_language = language(definition)
    pl_def = def_language == "pl"
    lemma_language = lang or def_language
    acronym_len = len(acronym)

    def accept(span, fallback_words=None):
        proper_names.append((acronym, acronym))
        if not trim:
            add_definition_words(org_words, proper_names, lemma_language)
        elif span_fits(acronym, span):
            add_definition_words(org_words[span[0]:span[1] + 1], proper_names, lemma_language)
        elif fallback_words:
            add_definition_words(fallback_words, proper_names, lemma_language)
        return True

    initials = [(part[0], i) for i, w in enumerate(org_words) for part in w.split('-') if part and part[0].isupper()]

    if not initials:
        return False

    if len(initials) >= acronym_len and all(initials[k][0] == acronym[k] for k in range(acronym_len)):
        idxs = [initials[k][1] for k in range(acronym_len)]
        return accept((idxs[0], idxs[-1]), [org_words[i] for i in sorted(set(idxs))])

    camel_idxs = camel_case_span(acronym, org_words)
    if camel_idxs:
        return accept((camel_idxs[0], camel_idxs[-1]), [org_words[i] for i in sorted(set(camel_idxs))])

    if strict:
        return False

    if not pl_def and len(org_words) >= acronym_len:
        initials_all = [(part[0].upper(), i) for i, w in enumerate(org_words) for part in w.split('-') if part and part[0].isalpha()]
        if sequence_match(acronym, [letter for letter, _ in initials_all]):
            return accept(sequence_span(acronym, initials_all, anchor))

    if pl_def:
        capitalized_idxs = [i for i, w in enumerate(org_words) if w and w[0].isupper() and w[1:].islower() and len(w) > 1]
        if len(capitalized_idxs) >= max(2, acronym_len):
            return accept((capitalized_idxs[0], capitalized_idxs[-1]))

    return False

def camel_case_match(acronym, words):
    """
    Check if the acronym matches the uppercase letters of the definition words, so CamelCase words give one initial per part.
    """

    initials = [c for w in words for c in w if c.isupper()]
    return initials[:len(acronym)] == list(acronym)

def camel_case_span(acronym, words):
    """
    Same check as camel_case_match, but returns the indexes of words that gave the matched uppercase
    letters, or None when there is no match.
    """

    initials = [(c, i) for i, w in enumerate(words) for c in w if c.isupper()]
    if [c for c, _ in initials[:len(acronym)]] != list(acronym):
        return None
    return [i for _, i in initials[:len(acronym)]]

def sequence_match(acronym, initials):
    """
    Check if the characters of the acronym appear in sequence within the provided initials.
    """
    
    idx = 0
    for letter in initials:
        if idx == len(acronym):
            break
        if letter == acronym[idx]:
            idx += 1
    return idx == len(acronym)


def check_position_if_new(new_acronym, definition, words, block_id, acronyms_with_definitions):
    """
    Determines the location of a newly found acronym definition and add it to the tracking dictionary.
    """

    tittle_pages_phrases = {
    "PRACA", "MAGISTERSKA", "INŻYNIERSKA", "DYPLOMOWA",
    "STRESZCZENIE", "ABSTRACT", "SŁOWA", "KLUCZOWE",
    "KEYWORDS", "WYKAZ", "SKRÓTÓW", "ABBREVIATIONS", "OECD",
    "ENGINEERING", "THESIS", "UNIVERSITY", "POLITECHNIKA",
    "WSTĘP", "CEL", "PRACY", "TEORIA", "PRZEGLĄD", "ROZWIĄZAŃ", "OPIS", 
    "WYNIKI", "ZAKOŃCZENIE", "DODATEK", "INSTRUKCJA", "PROGRAMISTY", 
    "DYPLOMU", "UŻYTKOWNIKA", "BIBLIOGRAFIA", "SPIS", "TREŚCI", "RYSUNKÓW", "TABEL"
    }
    new_acronym_clean = new_acronym.strip()
    if new_acronym_clean not in acronyms_with_definitions:
        if new_acronym_clean in tittle_pages_phrases:
            return acronyms_with_definitions
            
        words_list = list(words.values()) if isinstance(words, dict) else words
        word_page, word_bbox = None, None
        
        for w in words_list:
            clean_word_text = normalize_math_letters(w.text).strip('.,()[]{}:;"\'')
            if clean_word_text == new_acronym_clean:
                word_page = w.page_number
                word_bbox = w.bbox
                break
                
        if word_page is None:
            for w in words_list:
                clean_word_text = normalize_math_letters(w.text).strip('.,()[]{}:;"\'')
                if clean_word_text.startswith(new_acronym_clean):
                    word_page = w.page_number
                    word_bbox = w.bbox
                    break
        
        if word_page is None and len(words_list) > 0:
            w = words_list[0]
            word_page = w.page_number
            word_bbox = w.bbox
            
        if word_page is not None:
            acronyms_with_definitions[new_acronym_clean] = (definition, block_id, word_page, word_bbox)
            
    return acronyms_with_definitions


def check_italic_def(content, block, offset, length, block_language):
    """
    Returns a match if the foreign language definition is not written in italic.
    """
    start_page, end_page, word_idxs, error_coordinate, _ = get_match_info(block, offset, length)
    message = "Obcojęzyczne definicje powinny być zapisane kursywą."
    if block_language == "en":
        message = "Definition in a foreign language should be written in italic."
    matched_words = [w for w in block.words if w.word_index in word_idxs]
    logger.info("check_italic_def: word_idxs=%s, matched words: %s", word_idxs,
                [(w.word_index, w.text, w.italic) for w in matched_words])
    if matched_words and not all(w.italic for w in matched_words):
        return add_match(content, block.block_id, start_page, end_page, word_idxs, error_coordinate, category = "STYLE", message = message)
    return None

def check_first_definition(blocks, proper_names, extracted_acronyms):
    """
    Scans document blocks to find and extract the first definitions of acronyms.
    """
    logger.info("Starting first definition check")
    acronyms_with_definitions = {}
    italic_matches = []
    bibliography_re = re.compile(r"^\[\d+\]")
    list_acronyms = re.compile(r'^[A-Z]{2,}\s+[\u2013\u2014\-\u2212:]\s|^((\S+\s){1,4})[\u2013\u2014\-\u2212:]\s')
    paragraph_def_first = re.compile(r'(?<![A-Za-z\u0104\u0106\u0118\u0141\u0143\u00d3\u015a\u0179\u017b\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c])([A-Z\u0104\u0106\u0118\u0141\u0143\u00d3\u015a\u0179\u017b][a-zA-Z\u00d3\u00f3\u0104-\u017e\s\-]{2,}?)\s*\(([A-Z]{2,})\)(?=[,\s\.\)\;]|$)',re.UNICODE)
    paragraph_def_first_lower = re.compile(r'(?<![A-Za-z\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c])([a-z\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c][a-zA-Z\u00d3\u00f3\u0104-\u017e\s\-]{2,}?)\s*\(([A-Z]{2,})\)(?=[,\s\.\)\;]|$)',re.UNICODE)
    paragraph_def_with_comma = re.compile(r'(?<![A-Za-z\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c])([a-zA-Z\u00d3\u00f3\u0104-\u017e][a-zA-Z\u00d3\u00f3\u0104-\u017e\s\-]{2,}?)\s*\(([A-Z]{2,})[,\s]',re.UNICODE)
    paragraph_acr_first = re.compile(r'\(([A-Z]{2,})\)\s([A-Z\u00c0-\u017d][a-z\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c\w\s]+)')
    paragraph_ang_pattern = re.compile(r'\b([A-Z]{2,})\s*\((?:ang\.|pol\.|fr\.|niem\.)\s+([^)]{3,}?)\s*\)', re.UNICODE)
    paragraph_ang_pol_pattern = re.compile(r'\b([A-Z]{2,10})\s*\(\s*(?:ang\.|pol\.|niem\.|fr\.|łac\.)?\s*([A-Za-z\u00d3\u00f3\u0104-\u017e][A-Za-z\u00d3\u00f3\u0104-\u017e\s\-]{3,}?)\s*(?:,|;|\s{2,})', re.UNICODE)
    paragraph_acr_then_expansion = re.compile(r'\b([A-Z]{2,})\s*\(([A-Z][a-zA-ZÀ-Ž][a-zA-ZÀ-Žąćęłńóśźż\s\-]{2,})\)')
    paragraph_acr_quoted = re.compile(r'\b([A-Z]{2,})\s*\(["\u201e\u201c\u00ab\u2018]([A-Za-z][^"\u201d\u00bb\u2019)]{3,}?)["\u201d\u00bb\u2019]\)',re.UNICODE)
    broken_parenthesis_ang = re.compile(r'\b([A-Z]{2,})\s*\(\s*(?:ang\.|pol\.|fr\.|niem\.)\s+([A-Za-z\u00d3\u00f3\u0104-\u017e\s\-]{3,}?)\s*(?:\)|,|$)', re.UNICODE)
    broken_parenthesis_acr_dash = re.compile(r'\(\s*([A-Z]{2,})\s*[\-\u2013\u2014:]\s*(?:ang\.|pol\.|fr\.|niem\.)?\s*([A-Za-z\u00d3\u00f3\u0104-\u017e\s\-]{3,}?)\s*(?:\)|,|$)', re.UNICODE)
    parenthesis_def_dash_acr = re.compile(r'\(\s*(?:ang\.|pol\.|fr\.|niem\.|łac\.)?\s*([A-Za-z\u00d3\u00f3\u0104-\u017e][A-Za-z\u00d3\u00f3\u0104-\u017e\s\-]{2,}?)\s*[\-\u2013\u2014]\s*([A-Z]{2,})\s*\)', re.UNICODE)
    broken_no_parenthesis_svm = re.compile(r'\b([A-Z]{2,})\s+([A-Z][a-z]+\s+[A-Z][a-z]+[\w\s\-]*)\s*\)', re.UNICODE)
    paragraph_ang_phrase = re.compile(r'((?:[A-Za-z\u00d3\u00f3\u0104-\u017e][A-Za-z\u00d3\u00f3\u0104-\u017e\-]*\s+){1,3})\((?:ang\.|pol\.|niem\.|fr\.|\u0142ac\.)\s+([^)]{3,}?)\)', re.UNICODE)
    paragraph_ang_def_acr = re.compile(r'\((?:ang\.|pol\.|niem\.|fr\.)\s+([A-Za-z\u00d3\u00f3\u0104-\u017e\s\-,]{3,}?),\s*([A-Z]{2,})\s*\)', re.UNICODE)
    simple_paren_acronym = re.compile(r'([\w][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ\s\-]{3,}?)\s\(([A-Z]{2,6})\)',re.UNICODE)
    paragraph_acr_expansion_suffix = re.compile(r'\b([A-Z]{2,})\s*\((?:ang\.|pol\.|fr\.|niem\.|łac\.)?\s*([A-Za-z\u00d3\u00f3\u0104-\u017e][A-Za-z\u00d3\u00f3\u0104-\u017e\s\-]{2,}?)\s*[\-\u2013\u2014,;]\s*(?:ang\.|pol\.|fr\.|niem\.|łac\.)[^)]*\)', re.UNICODE)
    paragraph_def_then_ang = re.compile(r'\b([A-Z]{2,})\s*\([^()]*?[\s,;\-\u2013\u2014]\s*(?:ang\.|pol\.|fr\.|niem\.|łac\.)\s+([^()]{3,}?)\s*\)', re.UNICODE)
    foreign_def_in_parenthesis = re.compile(r'\(\s*(?:ang\.|pol\.|niem\.|fr\.|\u0142ac\.)\s*["\u201e\u201c\u00ab]?([A-Za-z\u00d3\u00f3\u0104-\u017e][^,;:!?()\[\]"\u201d\u00bb\u2013\u2014]*?)\s*(?=[,;:!?()\[\]"\u201d\u00bb\u2013\u2014]|\s[\-\u2010\u2011]\s|$)', re.UNICODE)
    paragraph_acr_dash_def = re.compile(r'\b([A-Z]{2,10})\s+[\-\u2013\u2014]\s+([A-Z\u0104\u0106\u0118\u0141\u0143\u00d3\u015a\u0179\u017b][A-Za-z\u00d3\u00f3\u0104-\u017e\-]*(?:\s+[A-Za-z\u00d3\u00f3\u0104-\u017e][A-Za-z\u00d3\u00f3\u0104-\u017e\-]*)+?)(?=\s+[\-\u2013\u2014]|\s*[,;.(]|$)(?:\s*\((?:ang\.|pol\.|niem\.|fr\.|\u0142ac\.)\s+([^()]{3,}?)\s*\))?', re.UNICODE)
    split = re.compile(r"\s[-\u2013\u2014]\s")

    if extracted_acronyms:
        for item in extracted_acronyms:
            if not item.words:
                item_page = 0
                item_bbox = [0.0, 0.0, 0.0, 0.0]
            else:
                item_page = item.words[0].page_number
                item_bbox = item.words[0].bbox

            acronym = normalize_math_letters(item.acronym)
            definition = normalize_math_letters(item.definition)
            initials_match(acronym, definition, proper_names, trim=False)
            acronyms_with_definitions[acronym] = (definition, "official_list", item_page, item_bbox)

    for b in blocks:
        block = b.block
        words = block.words 
        if bibliography_re.search(block.content):
            continue
        if block.type in {"math", "code_snippet", "toc", "tot", "tof"}:
            continue
        if block.type == "list":
            if block.is_bibliography:
                continue
            for item in block.items:
                item_text = normalize_math_letters(item.text)
                if list_acronyms.search(item_text):
                    new_acronym = split.split(item_text, 1)
                    new_acronym[0] = new_acronym[0].strip()
                    if len(new_acronym) > 1 and potential_acronym(new_acronym[0]):
                        acronyms_with_definitions = check_position_if_new(new_acronym[0], new_acronym[1].strip(), item.words, block.block_id, acronyms_with_definitions)


        if block.type in ("paragraph", "heading", "list"):
            if block.type == "list" and block.is_bibliography:
                continue
            if block.type == "paragraph":
                text = normalize_math_letters(block.content)
                for acronym, definition, foreign_definition in paragraph_acr_dash_def.findall(text):
                    if not potential_acronym(acronym):
                        continue
                    for candidate in (definition, foreign_definition):
                        if candidate and initials_match(acronym, candidate, proper_names, block, strict=True):
                            acronyms_with_definitions = check_position_if_new(acronym, candidate, words, block.block_id, acronyms_with_definitions)
                            break
            if '(' in block.content or ')' in block.content:
                text = normalize_math_letters(block.content)
                new_acronyms = paragraph_acr_first.findall(text)
                new_acronyms.extend(paragraph_acr_then_expansion.findall(text))
                new_acronyms.extend(paragraph_ang_pattern.findall(text))
                new_acronyms.extend(paragraph_ang_pol_pattern.findall(text))
                new_acronyms.extend(paragraph_acr_quoted.findall(text))
                new_acronyms.extend(broken_parenthesis_ang.findall(text))
                new_acronyms.extend(broken_parenthesis_acr_dash.findall(text))
                new_acronyms.extend(broken_no_parenthesis_svm.findall(text))
                new_acronyms.extend(paragraph_acr_expansion_suffix.findall(text))
                for new_acronym in new_acronyms:
                    if initials_match(new_acronym[0], new_acronym[1], proper_names, block, lang=b.language, anchor="start"):
                        acronyms_with_definitions = check_position_if_new(new_acronym[0], new_acronym[1], words, block.block_id, acronyms_with_definitions)
                    else:
                        def_words = new_acronym[1].strip().split()
                        if def_words:
                            rescue_single_word(new_acronym[0], def_words[0], proper_names, b.language)
                for acronym, definition in paragraph_def_then_ang.findall(text):
                    if acronym in acronyms_with_definitions:
                        continue
                    if initials_match(acronym, definition, proper_names, block, lang=b.language, anchor="start"):
                        acronyms_with_definitions = check_position_if_new(acronym, definition, words, block.block_id, acronyms_with_definitions)
                    else:
                        def_words = definition.strip().split()
                        if def_words:
                            rescue_single_word(acronym, def_words[0], proper_names, b.language)
                for before_phrase, inside_phrase in paragraph_ang_phrase.findall(text):
                    before_words = before_phrase.strip().split()[-1:]
                    before_words = [w for w in before_words if w.strip(string.punctuation).lower() not in DEFINITION_CONNECTORS]
                    add_definition_words(before_words + inside_phrase.strip().split(), proper_names, b.language)
                new_acronyms = paragraph_def_first.findall(text)
                new_acronyms.extend(paragraph_def_with_comma.findall(text))
                new_acronyms.extend(paragraph_def_first_lower.findall(text))
                new_acronyms.extend(parenthesis_def_dash_acr.findall(text))
                for new_acronym in new_acronyms:
                    if initials_match(new_acronym[1], new_acronym[0], proper_names, block, lang=b.language, anchor="end"):
                        acronyms_with_definitions = check_position_if_new(new_acronym[1], new_acronym[0], words, block.block_id, acronyms_with_definitions)
                    else:
                        def_words = new_acronym[0].strip().split()
                        if def_words:
                            rescue_single_word(new_acronym[1], def_words[-1], proper_names, b.language)

                for definition, acronym in paragraph_ang_def_acr.findall(text):
                    if potential_acronym(acronym):
                        add_trailing_definition(acronym, definition, proper_names, b.language)
                        proper_names.append((acronym, acronym))
                        acronyms_with_definitions = check_position_if_new(acronym, definition, words, block.block_id, acronyms_with_definitions)

                for definition, acronym in simple_paren_acronym.findall(text):
                    def_words = definition.strip().split()
                    if potential_acronym(acronym) and len(def_words) >= 2:
                        add_trailing_definition(acronym, definition, proper_names, b.language)
                        proper_names.append((acronym, acronym))
                        acronyms_with_definitions = check_position_if_new(acronym, definition, words, block.block_id, acronyms_with_definitions)
                
                for m in paragraph_ang_pattern.finditer(text):
                    acronym, definition = m.group(1), m.group(2)
                    if potential_acronym(acronym):
                        proper_names.append((acronym, acronym))
                        acronyms_with_definitions = check_position_if_new(acronym, definition, words, block.block_id, acronyms_with_definitions)

                for m in foreign_def_in_parenthesis.finditer(text):
                    italic_match = check_italic_def(m.group(1), block, m.start(1), m.end(1) - m.start(1), b.language)
                    if italic_match:
                        italic_matches.append(italic_match)
    logger.info("First definition check complete: %d acronyms with definitions found, %d proper names",
                len(acronyms_with_definitions), len(proper_names))

    return acronyms_with_definitions, proper_names, italic_matches