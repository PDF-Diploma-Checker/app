from common import shared_dictionary
import atexit
import os
from pathlib import Path

import language_tool_python
from .linguistics_types import Error_type
from analysis.extraction.linguistics_conversion.schema import *
from .helpers import get_match_info, morf, spell, nlp_pl, WHITELIST_ONLY_WORDS
from .decision_log import dropped
import re
import string
import logging
from collections import Counter

logger = logging.getLogger(__name__)

# Stały katalog LanguageTool, aby uniknąć wielokrotnego pobierania przy kolejnych uruchomieniach.
os.environ.setdefault("LTP_PATH", str(Path.home() / ".cache" / "language_tool_python"))

# ===== CACHE LANGUAGE TOOLS NA POZIOMIE MODUŁU =====
_TOOL_EN = None
_TOOL_PL = None


def _close_language_tools():
    global _TOOL_EN, _TOOL_PL

    if _TOOL_PL is not None:
        _TOOL_PL.close()
        _TOOL_PL = None

    if _TOOL_EN is not None:
        _TOOL_EN.close()
        _TOOL_EN = None


atexit.register(_close_language_tools)

def _init_language_tools():
    '''Inicialize language tools only once during first boot.'''
    global _TOOL_EN, _TOOL_PL

    if _TOOL_EN is None:
        try:
            logger.info("Initializing LanguageTool EN (en-GB)")
            _TOOL_EN = language_tool_python.LanguageTool('en-GB', language_tool_download_version="6.6")
            _TOOL_EN.disabled_categories.add('BRE_STYLE_OXFORD_SPELLING')
            _TOOL_EN.disabled_categories.add('MULTITOKEN_SPELLING')
            _TOOL_EN.disabled_categories.add('CONFUSED_WORDS')
            _TOOL_EN.disabled_rules.add('EN_UNPAIRED_BRACKETS')
            _TOOL_EN.disabled_rules.add('COMMA_PERIOD_CONFUSION')
            _TOOL_EN.disabled_rules.add('EN_UNPAIRED_QUOTES')
            _TOOL_EN.disabled_categories.add('TON_ACADEMIC')
            _TOOL_EN.disabled_categories.add('CONFUSED_WORDS')
            _TOOL_EN.disabled_categories.add('NONSTANDARD_PHRASES')
            _TOOL_EN.disabled_categories.add('REPETITIONS_STYLE')
            _TOOL_EN.disabled_categories.add('STYLE')
            _TOOL_EN.disabled_categories.add('MISC')
            _TOOL_EN.disabled_rules.add('COMMA_PARENTHESIS_WHITESPACE')
            _TOOL_EN.disabled_rules.add('WHITESPACE_RULE')
            _TOOL_EN.disabled_categories.add('CONSECUTIVE_SPACES')
            _TOOL_EN.disabled_categories.add('CASING')
            _TOOL_EN.disabled_categories.add('DASH_RULE')
            _TOOL_EN.disabled_categories.add('WIKIPEDIA')
            _TOOL_EN.disabled_categories.add('TEXT_ANALYSIS')
            _TOOL_EN.disabled_categories.add('CREATIVE_WRITING')
        except Exception as e:
            logger.exception("Failed to initialize LanguageTool EN")
            _TOOL_EN = None
    
    if _TOOL_PL is None:
        try:
            logger.info("Initializing LanguageTool PL (pl-PL)")
            _TOOL_PL = language_tool_python.LanguageTool('pl-PL', language_tool_download_version="6.6")
            _TOOL_PL.disabled_rules.add('NIETYPOWA_KOMBINACJA_DUZYCH_I_MALYCH_LITER')
            _TOOL_PL.disabled_rules.add('PL_UNPAIRED_BRACKETS')
            _TOOL_PL.disabled_rules.add('SUBST_ADJ_UNIFY')
            _TOOL_PL.disabled_rules.add('ADJ_SUBST_ADJ_UNIFY')
            _TOOL_PL.disabled_rules.add('FORMAT_DZIESIETNY')
            _TOOL_PL.disabled_rules.add('OD_X_Y_OD_X_DO_Y')
            _TOOL_PL.disabled_rules.add('SPACJA_ZA_PRZECINKIEM_DZIESITNYM')
            _TOOL_PL.disabled_rules.add('ZDANIE_PODRZEDNE_Z_KTORY_LUB_JAKI')
            _TOOL_PL.disabled_categories.add('MISC')
            _TOOL_PL.disabled_rules.add('COMMA_PARENTHESIS_WHITESPACE')
            _TOOL_PL.disabled_rules.add('WHITESPACE_RULE')
            _TOOL_PL.disabled_rules.add('BRAK_SPACJI_NAWIAS')
            _TOOL_PL.disabled_rules.add('PRZEDROSTKI')
            _TOOL_PL.disabled_rules.add('ZBIEG_NAWIASOW')
            _TOOL_PL.disabled_categories.add('CASING')
            _TOOL_PL.disabled_rules.add('DYWIZ')
        except Exception as e:
            logger.exception("Failed to initialize LanguageTool PL")
            _TOOL_PL = None

def language_tool_analisys(blocks):
    '''Finds mistakes in text: grammar, style, typos, punctuation in paragraphs and more.'''
    logger.info("Starting LanguageTool analysis on %d blocks", len(blocks))
    errors = []

    polish_messages = {
        'COLLOCATIONS': "Błąd kolokacji.",
        'COMPOUNDING': "Błąd łączenia słów.",
        'GRAMMAR': "Błąd gramatyczny.",
        'PLAIN_ENGLISH': "Możliwe złe użycie stałego stwierdzenia.",
        'TYPOS': "Możliwa literówka.",
        'PROPER_NOUNS': "Zła pisownia nazwy własnej.",
        'PUNCTUATION': "Błąd interpunkcyjny.",
        'REDUNDANCY': "Wyrażenie nadmiarowe.",
        'SEMANTICS': "Błąd semantyczny.",
        'TYPOGRAPHY': "Błąd typograficzny.",
    }

    english_messages = {
        'PHONETICS': "Phonetics error.",
        'CONFUSED_WORDS': "Phraseological error.",
        'PUNCTUATION': "Punctuation error.",
        'STYLE': "Lexical error.",
        'GRAMMAR': "Grammar error.",
        'SPELLING': "Orthographic error.",
        'GENDER': "Grammatical gender error.",
        'MISC': "Miscellaneous error.",
        'SYNTAX': "Syntax error.",
        'TYPOGRAPHY': "Typographical error.",
        'WORD_ORDER': "Word order error.",
        'NUMBERS': "Number formatting error.",
        'CASING': "Capitalization error.",
        'REDUNDANCY': "Redundant statement.",
        'TYPOS': "Possible typo.",
        'SEMANTICS': "Sematics error.",
    }

    _init_language_tools()
    tool_pl = _TOOL_PL
    tool_en = _TOOL_EN

    for block in blocks:
        if block.block.type not in {"acronyms", "keywords", "math", "code_snippet", "toc", "tof", "tot"}:
            if block.block.type == "list":
                if block.block.is_bibliography == True:
                    continue
            contents = block.contents
            text_language = block.language
            matches = tool_pl.check(contents) if text_language == "pl" else tool_en.check(contents)
            new_matches = []
            for match in matches:
                matched_span = contents[match.offset:match.offset + match.error_length]
                if is_noop_suggestion(matched_span, match.replacements):
                    dropped("all suggestions match the original text", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                    continue
                if (match.category == 'TYPOGRAPHY' or match.category == 'PUNCTUATION'):
                    if block.block.type != "paragraph":
                        dropped("punctuation outside a paragraph", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                        continue
                    elif not any(letter.isalpha() for letter in match.matched_text):
                        dropped("no letters in the match", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                        continue
                    elif match.rule_id == "ZDANIA_ZLOZONE" and text_language == "pl" and SENTENCE_BREAK_RE.search(
                            contents[match.offset:match.offset + match.error_length]):
                        # LanguageTool reads "Hz." as an abbreviation and joins two sentences into one
                        dropped("two sentences, not one compound sentence", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                        continue
                    elif match.rule_id == "ZDANIA_ZLOZONE" and text_language == "pl":
                        if spans_two_sentences(match.matched_text):
                            dropped("spans two sentences (LT did not split after a capitalized word with a period)", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                            continue
                        reason = predicative_adjective_reason(match.message, contents, match.offset, match.error_length)
                        if reason:
                            dropped(f"predicative adjective, not a second verb ({reason})", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                            continue
                    elif match.rule_id == "ROWNIE_JAK" and text_language == "pl" and is_verbless_comparison(
                            contents, match.offset, match.error_length):
                        dropped("comparison without a verb", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                        continue
                    elif text_language == "pl" and removed_enumeration_comma(
                            contents, match.offset, match.error_length, match.replacements):
                        dropped("comma between items of an enumeration", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                        continue
                if match.rule_id == "WE_W" and "/" in contents[match.offset:match.offset + match.error_length + 1]:
                    # "we/wy" (inputs/outputs) is an abbreviation, not the preposition "we"
                    dropped("part of an abbreviation with a slash", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                    continue
                if match.category in {"TYPOS", "SPELLING", "COMPOUNDING", "SYNTAX"}:
                    word = contents[match.offset:match.offset + match.error_length].strip(string.punctuation + string.whitespace)
                    if typo_check(word):
                        dropped("word known to the dictionaries", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                        continue
                    elif match.category == "SYNTAX" and len(word.split()) > 1:
                        # a misspelled verb looks like a sentence without one, and this finding hides the typo itself
                        primary_tool = tool_pl if text_language == 'pl' else tool_en
                        other_tool = tool_en if text_language == 'pl' else tool_pl
                        typos = []
                        span = contents[match.offset:match.offset + match.error_length]
                        for token in re.finditer(r"[^\W\d_]+(?:[-’'][^\W\d_]+)*", span):
                            if typo_check(token.group()):
                                continue
                            for typo in primary_tool.check(token.group()):
                                if typo.category != "TYPOS":
                                    continue
                                if not other_tool.check(typo.matched_text):
                                    continue
                                typo.sentence = match.sentence
                                typo.offset += match.offset + token.start()
                                typos.append(typo)
                        new_matches.extend(typos)
                        if not typos:
                            dropped("a whole sentence without a misspelled word", match.category, match.rule_id, contents, match.offset, match.error_length, block)
                        continue
                    else:
                        # The other language is a veto for intentional foreign words, not
                        # the source of a replacement diagnosis or its suggestions.
                        other_tool = tool_en if text_language == 'pl' else tool_pl
                        if not other_tool.check(word):
                            other_language = "English" if text_language == 'pl' else "Polish"
                            dropped(f"correct in {other_language}", match.category, match.rule_id,
                                    contents, match.offset, match.error_length, block)
                            continue
                new_matches.append(match)

            for m in new_matches:
                start_page, end_page, word_idxs, error_coordinate, has_index = get_match_info(block.block, m.offset, m.error_length)
                message = m.message
                if text_language == 'en':
                    if block.block.language == 'en':
                        message = m.message
                    else:
                        message = polish_messages.get(m.category, m.message)
                else:
                    if block.block.language == 'en':
                        message = english_messages.get(m.category, m.message)
                    else:
                        message = m.message

                if has_index:
                    dropped("index entry", m.category, m.rule_id, contents, m.offset, m.error_length, block)
                    continue

                errors.append(Error_type(
                    content=contents[m.offset:m.offset + m.error_length],
                    category=m.category,
                    message=message,
                    offset=m.offset,
                    error_length=m.error_length,
                    block_id=block.block.block_id,
                    page_start=start_page,
                    page_end=end_page,
                    word_idxs=word_idxs,
                    error_coordinate=error_coordinate,
                    rule=m.rule_id,
                    why=f"LanguageTool {text_language}: {m.message}; suggestions: {m.replacements[:3]}",
                ))

    category_counts = Counter(e.category for e in errors)
    logger.info("LanguageTool analysis complete: %d errors found", len(errors))
    for cat, count in category_counts.most_common():
        logger.info("  LT category '%s': %d", cat, count)
    return errors

# Polskie końcówki dodawane do zapożyczeń (np. "rank-owania", "transformer-owym", "framework-u").
# Posortowane od najdłuższej, żeby odcinać jak najdłuższą końcówkę.
POLISH_LOANWORD_SUFFIXES = sorted((
    "owaniami", "owaniach", "owaniem", "owaniom", "owaniu", "owania", "owanie", "owań",
    "owanego", "owanemu", "owanej", "owanym", "owanych", "owanymi", "owaną", "owana", "owane", "owany", "owani",
    "owaliśmy", "owałem", "owałam", "owałeś", "owali", "owała", "owało", "owały", "ował", "ować",
    "ujemy", "ujecie", "ujesz", "ują", "uje", "uję",
    "owego", "owemu", "owych", "owymi", "owym", "owej", "ową", "owa", "owe", "owy", "owi",
    "ami", "ach", "iem", "em", "om", "ów", "u", "a", "y", "i", "e",
), key=len, reverse=True)
# Rdzenie krótsze niż 4 litery (np. "the" + "a") dawałyby fałszywe trafienia. Rdzenie 4-literowe muszą być
# częstymi słowami angielskimi ("rank"), bo słownik zawiera też rzadkie skróty ("prog" -> "progamowania").
MIN_LOANWORD_STEM = 4
SHORT_LOANWORD_STEM = 5
MIN_SHORT_STEM_FREQUENCY = 1000

def in_english_dictionary(word, use_whitelist=True):
    '''Checks if lowercase word is in the English (pyspellchecker) dictionary. With use_whitelist=False
    words added only by word_whitelist.txt are treated as unknown.'''
    return word in spell and (use_whitelist or word not in WHITELIST_ONLY_WORDS)

def is_known_word(word, use_whitelist=True):
    '''Checks if word is in the Polish (Morfeusz) or English (pyspellchecker) dictionary.'''
    if shared_dictionary.contains(word):
        return True
    if any(interpretation[2][2] != "ign" for interpretation in morf.analyse(word)):
        return True
    words = word.lower().split()
    if not use_whitelist and any(w in WHITELIST_ONLY_WORDS for w in words):
        return False
    return not spell.unknown(words)

def is_polish_inflected_loanword(word, use_whitelist=True):
    '''Checks if word is a known English word with a Polish ending, e.g. "rankowania", "transformerowym".
    Stems are checked only in the English dictionary - Polish forms are already recognized by Morfeusz,
    and Polish stems would accept typos (e.g. "progam" + "owania").'''
    word = word.lower()
    for suffix in POLISH_LOANWORD_SUFFIXES:
        if not word.endswith(suffix):
            continue
        stem = word[:-len(suffix)]
        if len(stem) < MIN_LOANWORD_STEM:
            continue
        # Niema końcówka -e jest pomijana przy odmianie (np. "cache" -> "cachowania")
        for candidate in (stem, stem + "e"):
            if len(candidate) < SHORT_LOANWORD_STEM:
                if spell[candidate] >= MIN_SHORT_STEM_FREQUENCY:
                    return True
            elif in_english_dictionary(candidate, use_whitelist):
                return True
    return False

COMPOUND_SENTENCE_VERBS_RE = re.compile(r"\(„([^”]+)”\)\s+a drugim\s+\(„([^”]+)”\)")


UPPERCASE = "A-ZĄĆĘŁŃÓŚŹŻ"
SENTENCE_BOUNDARY_RE = re.compile(rf"\b[{UPPERCASE}]\w*\.\s+[{UPPERCASE}]")

def spans_two_sentences(text):
    '''Checks if text contains a capitalized word, a period and a capital letter, e.g. "3200 Hz. Na".'''
    return SENTENCE_BOUNDARY_RE.search(text) is not None

# Łączniki zamykające wyliczenie "coś, coś, ... i/lub/oraz coś".
ENUMERATION_CONNECTOR_RE = re.compile(
    r",?\s+(?:i/lub|i/albo|a także|jak również|a też|i|lub|oraz|albo|bądź|czy|ani|tudzież|&)\s+\S")
ENUMERATION_STOP_RE = re.compile(r"[;:!?]|\.(?:\s|$)")
MAX_ENUMERATION_ITEM_WORDS = 3
VERB_TAGS = {"fin", "praet", "impt", "imps", "inf", "bedzie", "winien", "pred", "aglt", "pcon", "pant"}
CASES = {"nom", "gen", "dat", "acc", "inst", "loc", "voc"}
SYMBOL_TAGS = {"brev", "ign", "dig", "romandig"}

def _word_tags(word):
    return [interpretation[2][2] for interpretation in morf.analyse(word)]

def _is_symbol(word):
    '''Letters, numbers and acronyms: "B", "30%", "F1", "LSTM".'''
    return not any(char.islower() for char in word)

def _cases(word):
    '''All grammatical cases Morfeusz allows for word.'''
    return {case for tag in _word_tags(word) for field in tag.split(":") for case in field.split(".") if case in CASES}

def _has_verb(words):
    return any(tag.split(":")[0] in VERB_TAGS for word in words for tag in _word_tags(word))

def _items_agree(word_before, word_after):
    '''Two enumeration items agree: both are symbols ("B", "C") or they share a grammatical case ("precyzji", "czułości").'''
    if _is_symbol(word_before) or _is_symbol(word_after):
        return _is_symbol(word_before) and _is_symbol(word_after)
    return bool(_cases(word_before.lower()) & _cases(word_after.lower()))

def is_enumeration_comma(contents, comma):
    '''Checks if the comma at index comma separates items of an enumeration "A, B, ... i/lub/oraz C".'''
    before = re.findall(r"[\w%]+", contents[:comma][-60:])
    after = contents[comma + 1:]
    stop = ENUMERATION_STOP_RE.search(after)
    after = after[:stop.start()] if stop else after
    connector = ENUMERATION_CONNECTOR_RE.search(after)
    if not before or not connector:
        return False
    items = [re.findall(r"[\w%]+", item) for item in after[:connector.start()].split(",")]
    if not all(0 < len(item) <= MAX_ENUMERATION_ITEM_WORDS for item in items):
        return False
    if _has_verb([word for item in items for word in item]):
        return False
    return _items_agree(before[-1], items[0][-1])

def removed_enumeration_comma(contents, offset, length, replacements):
    '''Checks if a LanguageTool suggestion only removes a comma that separates items of an enumeration,
    e.g. POZA_TYM in "Dla 30% budżetu wyniki wariantów B, C i D uległy zbliżeniu".'''
    matched = contents[offset:offset + length]
    normalize = lambda text: " ".join(text.split())
    suggestions = {normalize(r) for r in replacements}
    for i, char in enumerate(matched):
        if char == "," and normalize(matched[:i] + matched[i + 1:]) in suggestions:
            if is_enumeration_comma(contents, offset + i):
                return True
    return False

def is_noop_suggestion(matched_text, replacements):
    '''True when LanguageTool gives suggestions, but every one is identical to the text already written
    (e.g. Polish JEDNE_DZIECKO suggesting "ponowne" in place of "ponowne").'''
    if not replacements:
        return False
    target = matched_text.strip()
    return all(r.strip() == target for r in replacements)


COMPARISON_BOUNDARY_TOKENS = {",", ";", ":", ".", "!", "?", "(", ")", "–", "—"}


def is_verbless_comparison(contents, offset, length):
    '''Checks if a Polish comparison matched by ROWNIE_JAK ("tak samo jak upadek", "równie szybki jak poprzedni")
    has no verb after "jak" up to the next clause boundary. In Polish, a comma before comparative "jak" is only
    required when it introduces a subordinate clause with a verb.'''
    after_start = offset + length
    doc = nlp_pl(contents)
    seen_word = False
    for token in doc:
        if token.idx < after_start:
            continue
        if token.text in COMPARISON_BOUNDARY_TOKENS:
            break
        if token.is_space:
            continue
        if token.pos_ in {"VERB", "AUX"}:
            return False
        if not token.is_punct:
            seen_word = True
    return seen_word


def is_adjective_verb_homograph(word):
    '''Checks if word is both an adjective and a past tense verb in Morfeusz, e.g. "stała" (stały / stać).'''
    tags = {interpretation[2][2].split(":")[0] for interpretation in morf.analyse(word.lower())}
    return "adj" in tags and "praet" in tags

# a sentence ends inside the match: a dot after a word and a capital letter after it, unless the word is an
# abbreviation that goes on with the same sentence ("np. Arduino")
SENTENCE_BREAK_RE = re.compile(
    r"(?<![\w.])(?!(?:np|tzw|tj|tzn|ang|łac|wg|ok|dr|inż|mgr|prof|ul|ww|zob|por|cyt)\.)[^\W\d_]{2,}[.!?]\s+[A-ZĄĆĘŁŃÓŚŹŻ]")

def predicative_adjective_reason(message, contents, offset, length):
    '''Checks if the second "verb" found by LanguageTool rule ZDANIA_ZLOZONE is an adjective after a copula.
    Returns the reason for dropping the match or None.'''
    verbs = COMPOUND_SENTENCE_VERBS_RE.search(message)
    if not verbs or not is_adjective_verb_homograph(verbs.group(2)):
        return None
    doc = nlp_pl(contents)
    token = next((t for t in doc if offset <= t.idx < offset + length and t.text == verbs.group(2)), None)
    if token is None:
        return None
    has_copula = any(child.dep_ == "cop" for child in token.children)
    conjuncts = [child for child in token.children if child.dep_ == "conj"]
    if not has_copula and any(c.pos_ == "VERB" and "Past" in c.morph.get("Tense") for c in conjuncts):
        return None
    if has_copula:
        return "copula"
    if token.dep_.startswith("xcomp"):
        return f"complement of '{token.head.lemma_}'"
    if any(c.pos_ == "ADJ" and "Nom" in c.morph.get("Case")
           and c.morph.get("Gender") == token.morph.get("Gender")
           and c.morph.get("Number") == token.morph.get("Number") for c in conjuncts):
        return "coordinated with an adjective"
    return None

def typo_check(typo_text, use_whitelist=True):
    '''Double check typos found by language analysis with Polish and English dictionaries.
    use_whitelist=False ignores word_whitelist.txt (used by check_acronym).'''
    # Każde słowo osobno - Morfeusz dla całej frazy zwraca interpretacje każdego słowa,
    # więc jedno znane słowo ukrywałoby literówkę w pozostałych
    words = typo_text.split()
    return bool(words) and all(is_known_word(w, use_whitelist) or is_polish_inflected_loanword(w, use_whitelist) for w in words)