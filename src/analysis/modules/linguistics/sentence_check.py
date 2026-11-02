from analysis.extraction.linguistics_conversion.schema import *
from .exeptions_check import check_quotes
from .helpers import get_match_info, morf, nlp_pl, nlp_en
from .linguistics_types import Error_type, Analisys_type
from .proper_check import check_if_proper
import re
import logging
from collections import Counter

logger = logging.getLogger(__name__)

#ostateczny fallback przy edge case złego wykrycia podpisów, aby nie tworzyć FP z NO_VERB, NO_SUBJECT.
DESCRIPTION_WHITELIST= {"wersja", "wersji", "wersjom", "wersjach", "wersję", "wer","wersją", "wersje", "wersjami", "rys", "rysunek", "rysunkom", "rysunkach", "rysunku", "tabela", "tabeli", "tabelom", "tabelach", "tab",
                     "wykres", "wykresu", "wykresom", "wykresowi", "wykresem", "wykresie", "wykresach", "wyk", "rozdziale", "rozdział", "rozdziały", "rozdziału", "rozdziałem", "rozdziałach", "roz", "rozdz", "rozdziałów", 
                     "obraz", "obr", "obrazie", "obrazu", "obrazowi", "obrazach", "obrazem","obrazom", 
                     "wzór", "wzoru", "wzorowi", "wzory", "wzorom", "wzorach", "wzorami", "wzorem", "wzorze",
                     "równanie", "równaniu", "równaniach", "równaniami", "równaniom", "równania", "równaniem", "rów", "listing"}

CAPTION_RE = re.compile(r'^\s*((Rys|Ryc|Rysunek|Tab|Tabela|Wykres|Listing|Fig|Figure|Table)\.?\s*[A-Z]?\d+([.:]\d+)*[.:]?\s|Źródło)')
SENTENCE_END_RE = re.compile(r'([.!?…:])["”»’)\]]*\s*$')
VERB_TAGS = {"fin", "praet", "imps", "impt", "bedzie", "winien", "pred"}

#skróty, po których kropka praktycznie nigdy nie kończy zdania
NEVER_END = {"m.in", "ds", "np", "tj", "ang", "tzw", "prof", "dr", "hab", "inż", "mgr", "ok", "św", "zob", "por", "cyt", "wg", "nr", "im", "zw"}
INITIAL_RE = re.compile(r"[A-ZĄĆĘŁŃÓŚŹŻ]|Ch|Th|Sz|Cz|Ph")
#części mowy Morfeusza, które wskazują na początek nowego zdania, a nie na nazwisko
FUNCTION_TAGS = {"prep", "conj", "comp", "adv", "part", "qub", "fin", "praet", "impt", "imps", "pcon", "pant", "inf",
                 "ppron12", "ppron3", "num", "pred", "interj", "bedzie", "winien"}
#słowa, po których inicjał w tekście naukowym prawie zawsze wprowadza autora
NAME_INTRO = {",", "i", "oraz", "a", "przez", "według", "zdaniem", "pisze", "piszą", "pisał", "wskazuje", "również",
              "sam", "prace", "pracach", "pracę", "praca", "pracami", "publikacje", "definicji", "badania", "rozważania",
              "autorstwa", "dorobku", "wobec", "kolei"}

def morfeusz_pos(word):
    '''
    Returns parts of speech of every Morfeusz interpretation of the word.
    '''
    return {i[2][2].split(":")[0] for i in morf.analyse(word)}

def looks_like_surname(token):
    '''
    Checks if the token can be a surname: no function word interpretation in Morfeusz and
    spaCy PROPN, Morfeusz first name/surname interpretation or a word unknown to Morfeusz.
    '''
    pos = morfeusz_pos(token.text)
    if pos & FUNCTION_TAGS:
        return False
    names = {name for i in morf.analyse(token.text) for name in i[2][3]}
    return token.pos_ == "PROPN" or bool(names & {"nazwisko", "imię"}) or (pos == {"ign"} and token.pos_ != "NOUN")

def only_genitive_continuation(word):
    '''
    Checks if the word is a noun/adjective that can be genitive but never nominative or instrumental
    ("Konwencji", "Europejskiego"), so it continues the phrase after a year abbreviation.
    '''
    tags = [i[2][2] for i in morf.analyse(word)]
    if any(tag.split(":")[0] not in ("subst", "adj", "depr") for tag in tags):
        return False
    cases = [set(re.split("[:.]", tag)) for tag in tags]
    return any("gen" in c for c in cases) and not any(c & {"nom", "inst"} for c in cases)

def has_finite_verb(span):
    return any(t.pos_ in {"VERB", "AUX"} and ("VerbForm=Fin" in t.morph or t.morph.get("VerbType") == ["Quasi"]) for t in span)

def starts_with_initial(span):
    return len(span) > 1 and bool(INITIAL_RE.fullmatch(span[0].text)) and span[1].text == "."

def should_merge(prev, nxt):
    '''
    Checks if sentence nxt continues sentence prev, which the sentencizer cut after an abbreviation or initial.
    '''
    if len(prev) < 2 or prev[-1].text != ".":
        return False
    abbr = prev[-2].text
    first = nxt[0].text
    if abbr.lower() in NEVER_END or [t.text for t in prev[-4:]] == ["m", ".", "in", "."]:
        return True
    if len(prev) == 2:
        return bool(INITIAL_RE.fullmatch(abbr))
    before = prev[-3]
    if INITIAL_RE.fullmatch(abbr):
        if before.like_num or before.text[-1] in "°%-–/+=" or (before.whitespace_ == "" and before.text[-1].isalnum()):
            return False
        after_abbreviation = before.text == "." and len(prev) >= 4
        if all(INITIAL_RE.fullmatch(t.text) or t.text == "." for t in prev):
            return True
        if after_abbreviation and INITIAL_RE.fullmatch(prev[-4].text):
            return True
        if len(nxt) > 2 and nxt[1].text in ("-", "–") and nxt[1].whitespace_ == "" and first[0].isupper() and nxt[2].text[0].isupper():
            return True
        if (before.lower_ in NAME_INTRO or after_abbreviation) and first[0].isupper() and not morfeusz_pos(first) & FUNCTION_TAGS:
            return True
        return looks_like_surname(nxt[0]) or starts_with_initial(nxt)
    if abbr == "r" and before.like_num:
        return starts_with_initial(nxt) or not has_finite_verb(prev) or only_genitive_continuation(first)
    return False

def merge_abbreviation_splits(sents):
    '''
    Merges sentences that the sentencizer split after an abbreviation or initial ("według F. Kotlera"),
    which caused false NO_SUBJECT/NO_VERB errors.
    '''
    merged = []
    for sent in sents:
        if merged and should_merge(merged[-1], sent):
            merged[-1] = sent.doc[merged[-1].start:sent.end]
        else:
            merged.append(sent)
    return merged

def sentence_check(blocks, chapter_nums, check_first_person=True, acronyms_with_definitions=None):
    '''
    Parses paragraph sentences. Marks usage of first person as error when it is not excluded in user JSON, 
    Marks sentences with no verb or no subject as an error, creates statistics of each sentence form usage across paragraphs.
    '''
    logger.info("Starting sentence check (check_first_person=%s)", check_first_person)
    sentence_count = 0
    passive_count = 0
    active_count = 0
    verbless_count = 0
    impersonal_count = 0
    checked_matches = []
    for block in blocks:
        if block.block.type == "paragraph":
            if block.language == 'pl':
                nlp = nlp_pl
            else:
                nlp = nlp_en
            text = block.contents
            clean_text, idx_map = exclude_brackets(text)
            content = nlp(clean_text)
            sentence_before = ""
            sentences = merge_abbreviation_splits(content.sents) if block.language == 'pl' else content.sents
            for sentence in sentences:
                first_upper = None
                if sum(1 for letter in sentence.text if letter.isalpha()) < 15:
                    sentence_before = sentence.text
                    continue
                for letter in sentence.text:
                    if letter.isalpha():
                        first_upper = letter
                        break
                if first_upper is None or not first_upper.isupper():
                    continue
                if re.search(r'\.[ .]{4,}', block.contents):
                    continue
                passive = False
                is_subject = False
                is_verb = False
                is_impersonal = False
                sentence_count += 1
                for token in sentence:
                    if token.morph.get("Person"):
                        is_subject = True
                        if check_first_person and token.morph.get("Person")[0] == '1':
                            to_add = True
                            if block.language == 'pl':
                                to_add = morfeusz_check(token.text)
                            if token.idx > 0 and (clean_text[token.idx - 1] == '-'):
                                to_add = False
                            elif (token.idx + len(token) + 1) < len(clean_text) and (clean_text[token.idx + len(token)] == '-'):
                                to_add = False
                            if to_add:
                                offset = idx_map[token.idx]
                                error_length = idx_map[token.idx + len(token)] - offset
                                start_page, end_page, word_idxs, error_coordinate, _ = get_match_info(block.block, offset, error_length)
                                if block.block.language == 'en':
                                    message = f"Use of {token.morph.get("Person")[0]} personal form."
                                else:
                                    message = f"Użycie {token.morph.get("Person")[0]} formy osobowej."
                                match = Error_type(
                                content= token.text,
                                category= "PERSONAL_FORM",
                                message= message,
                                offset= offset,
                                error_length= error_length,
                                block_id = block.block.block_id,
                                page_start = start_page,
                                page_end = end_page,
                                word_idxs = word_idxs,
                                error_coordinate= error_coordinate
                                )   
                                if not check_quotes(match.offset, match.offset + match.error_length, text) and not check_if_proper(block.block, match, is_diff = True):
                                    checked_matches.append(match)
                    if token.dep_ in {'nsubj', 'nsubj:pass', 'nsubjpass', 'attr'}:
                        is_subject = True
                    if token.pos_ in {'VERB', 'AUX'}:
                        is_verb = True
                    if token.dep_ == 'cop' or (block.language == 'pl' and token.pos_ in {'NOUN', 'PROPN', 'ADV', 'X'} and morfeusz_pos(token.text) <= VERB_TAGS):
                        is_verb = True
                    if block.language == 'pl' and token.pos_ in {'VERB', 'AUX'} and "VerbForm=Fin" in token.morph and token.morph.get("VerbType") != ["Quasi"] and not ("Gender=Neut" in token.morph and "Number=Sing" in token.morph):
                        is_subject = True
                    if token.dep_ == "aux:pass":
                        passive = True
                    if token.morph.get("Person") and token.morph.get("Person")[0] == "0":
                        is_impersonal = True
                    elif block.language =='pl'and token.text == "się":
                        if token.head.morph.get("Person") and token.head.morph.get("Person")[0] == "3":
                            if not any(child.dep_ == "nsubj" for child in token.head.children):
                                is_impersonal = True
                if block.language == 'pl' and not is_subject and passive:
                    if any(tok.pos_ in {"NOUN", "PROPN"} and "Case=Nom" in tok.morph for tok in sentence):
                        is_subject = True
                if not is_subject:
                    root = None
                    for tok in sentence:
                        if tok.dep_ == "ROOT":
                            root = tok
                            break
                    if root and root.pos_ in {"NOUN", "PROPN"} and "Case=Nom" in root.morph:
                        is_subject = True
                    elif root:
                        nom_children = [
                            tok for tok in root.children
                            if tok.pos_ in {"NOUN", "PROPN"} and "Case=Nom" in tok.morph
                        ]
                        if nom_children:
                            is_subject = True
                if not is_subject and acronyms_with_definitions:
                    if any(tok.text in acronyms_with_definitions for tok in sentence):
                        is_subject = True
                match_list = []
                if description_exclude_backup(sentence.text, sentence_before, chapter_nums):
                    continue
                end = SENTENCE_END_RE.search(sentence.text)
                is_sentence = not CAPTION_RE.match(sentence.text) and end is not None and (end.group(1) != ":" or is_verb)
                if is_sentence and not is_subject:
                    #zdania z czasownikami niewłaściwymi np. "Na podstawie badań można sformułować wnioski" uznawane są za błąd - nie mają podmiotu domyślnego.
                    if block.block.language == 'en':
                        match_list.append(("NO_SUBJECT", "No subject in the sentence."))
                    else:
                        match_list.append(("NO_SUBJECT", "Brak podmiotu w zdaniu."))
                if is_sentence and not is_verb:
                    if block.block.language == 'en':
                        match_list.append(("NO_VERB", "No verb in the sentence."))
                    else:
                        match_list.append(("NO_VERB", "Brak orzeczenia w zdaniu."))
                og_start = idx_map[sentence.start_char]
                og_end = idx_map[sentence.end_char]
                for category, message in match_list:
                    start_page, end_page, word_idxs, error_coordinate, _ = get_match_info(block.block, og_start, og_end - og_start)
                    match = Error_type(
                    content= text[og_start:og_end],
                    category=  category,
                    message= message,
                    offset= og_start,
                    error_length= og_end - og_start,
                    block_id = block.block.block_id,
                    page_start = start_page,
                    page_end = end_page,
                    word_idxs = word_idxs,
                    error_coordinate= error_coordinate
                    )
                    #sprawdzanie czy zdanie jest cytatem, aby nie uwzględniać ich jako błędów.
                    if not check_quotes(match.offset, match.offset + match.error_length, text) and not check_if_proper(block.block, match, is_diff=True) and not definicion(block.block, word_idxs, sentence.text):
                        checked_matches.append(match)
                if passive:
                    passive_count += 1
                elif not is_verb:
                    verbless_count += 1
                else: 
                    active_count += 1
                if is_impersonal:
                    impersonal_count +=1
                sentence_before = sentence.text
    if passive_count + active_count + verbless_count > 0:
        passive_ratio = round(passive_count/(passive_count + active_count + verbless_count) * 100)
        verbless_ratio = round(verbless_count/(passive_count + active_count + verbless_count) * 100)
    else:
        passive_ratio = 0
        verbless_ratio = 0

    active_ratio = 100 - passive_ratio - verbless_ratio
    analisys = Analisys_type(
        active_ratio = f"{active_ratio}%",
        passive_ratio= f"{passive_ratio}%",
        verbless_ratio= f"{verbless_ratio}%"
    )
    match_cats = Counter(m.category for m in checked_matches)
    logger.info("Sentence check complete: %d matches", len(checked_matches))
    logger.info("  Total sentences: %d", sentence_count)
    logger.info("  Active: %d (%s)", active_count, analisys.active_ratio)
    logger.info("  Passive: %d (%s)", passive_count, analisys.passive_ratio)
    logger.info("  Verbless: %d (%s)", verbless_count, analisys.verbless_ratio)
    logger.info("  Impersonal: %d", impersonal_count)
    for cat, count in match_cats.most_common():
        logger.info("  Sentence error type '%s': %d", cat, count)
    return checked_matches, analisys

def morfeusz_check(text):
    '''
    Helper that double checks if words matched as first person usage in Polish
    are also marked as that in polish dictionary.
    '''
    personal_tags = {"pri", "ppron12"}
    analysis = morf.analyse(text)
    for interpretation in analysis:
        tags = set(interpretation[2][2].split(":"))
        if len(set(personal_tags).intersection(tags)) > 0:
            return True
    return False

def definicion(block, word_idxs, sentence_text):
    '''
    Excludes no verb/no subject errors in definition formatted sentences.
    '''
    if not word_idxs:
        return False
    pattern = r'^\s*\w[\w\s]*[:–-]'
    words_by_idx = {w.word_index: w for w in block.words}
    target_word = words_by_idx.get(word_idxs[0])
    if target_word and target_word.bold and re.match(pattern, sentence_text):
        return True
    return False

def description_exclude_backup(sentence_text, sentence_before, chapter_nums):
    '''
    Helper function that excludes errors of no verb/no subject from wrongly parsed floating elements descriptions.
    '''
    words = sentence_text.split()
    words_before = sentence_before.split()
    if len(words) < 3:
        return True
    if any(word.strip(" .:") in chapter_nums for word in words[:2]):
        return True
    if any(word.strip(" .:") in chapter_nums for word in words_before[-2:]):
        return True
    if words[0].lower().strip() in DESCRIPTION_WHITELIST and not words[1].isalpha():
        return True
    if not words[0].isalpha() and words[1][0].isupper():
        return True
    if len(words_before) > 1:
        if words_before[0].lower().strip(" :.") in DESCRIPTION_WHITELIST and not words_before[1].isalpha():
            return True
    return False

def exclude_brackets(block_contents):
    '''
    Maskes sentences in brackets with a single space before spacy analysis to prevent wrong parsing.
    Returns masked text and index map that translates masked text to original one.
    '''
    n = len(block_contents)
    removed = [False] * n
    stack = []
    for i, char in enumerate(block_contents):
        if char in {'(', '['}:
            stack.append(i)
        elif char in {')', ']'}:
            if stack:
                start_idx = stack.pop()
                for k in range(start_idx, i + 1):
                    removed[k] = True
    #zdublowane przez parser nawiasy 
            else:
                removed[i] = True
    for j in stack:
        removed[j] = True

    clean = []
    mask_idxs_map = []
    i = 0
    while i < n:
        if removed[i]:
            clean.append(" ")
            mask_idxs_map.append(i)
            while i < n and removed[i]:
                i += 1
            continue
        clean.append(block_contents[i])
        mask_idxs_map.append(i)
        i += 1
    mask_idxs_map.append(n)
    masked_text = "".join(clean)
    return masked_text, mask_idxs_map
    
