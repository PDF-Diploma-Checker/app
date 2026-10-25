import atexit
import os
from pathlib import Path

import language_tool_python
from .linguistics_types import Error_type
from analysis.extraction.linguistics_conversion.schema import *
from .helpers import get_match_info, morf, spell
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
                if (match.category == 'TYPOGRAPHY' or match.category == 'PUNCTUATION'):
                    if block.block.type != "paragraph":
                        continue
                    elif not any(letter.isalpha() for letter in match.matched_text):
                        continue
                if match.category in {"TYPOS", "SPELLING", "COMPOUNDING", "SYNTAX"}:
                    word = contents[match.offset:match.offset + match.error_length].strip(string.punctuation + string.whitespace)
                    if typo_check(word):
                        continue
                    elif text_language == 'pl':
                        en_matches = tool_en.check(word)
                        for en_match in en_matches:
                            en_match.sentence = match.sentence
                            en_match.offset += match.offset
                            en_match.message = match.message
                        new_matches.extend(en_matches)
                        continue
                    else:
                        pl_matches = tool_pl.check(word)
                        for pl_match in pl_matches:
                            pl_match.sentence = match.sentence
                            pl_match.offset += match.offset
                            pl_match.message = match.message
                        new_matches.extend(pl_matches)
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

def is_known_word(word):
    '''Checks if word is in the Polish (Morfeusz) or English (pyspellchecker) dictionary.'''
    if any(interpretation[2][2] != "ign" for interpretation in morf.analyse(word)):
        return True
    return not spell.unknown(word.lower().split())

def is_polish_inflected_loanword(word):
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
            elif candidate in spell:
                return True
    return False

def typo_check(typo_text):
    '''Double check typos found by language analysis with Polish and English dictionaries.'''
    # Każde słowo osobno - Morfeusz dla całej frazy zwraca interpretacje każdego słowa,
    # więc jedno znane słowo ukrywałoby literówkę w pozostałych
    words = typo_text.split()
    return bool(words) and all(is_known_word(w) or is_polish_inflected_loanword(w) for w in words)