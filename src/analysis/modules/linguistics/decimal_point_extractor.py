import re
from .linguistics_types import Error_type
from .helpers import get_match_info
from .exeptions_check import check_quotes
from .proper_check import check_if_proper
import logging

logger = logging.getLogger(__name__)

def decimal_check(blocks, chapter_nums):
    '''Function uses regexes to find wrongly used decimal separators in Polish or English.
    Matches are passed to be checked by check_defimal_matches.'''
    logger.info("Starting decimal separator check")
    checked_matches = []
    chapter_numbers = set()
    pl_candidates = 0
    en_candidates = 0
    for block in blocks:
        if block.block.type in {"math", "code_snippet", "toc", "tot", "tof", "acronyms"}:
            continue
        if block.block.type == "list":
            if block.block.is_bibliography == True:
                continue
        if block.language == 'pl':
            regex = r'(?<![\d.a-zA-Z])\d+\.\d+(?!\.?\d)'
        else:
            regex = r'(\d+,(?!\d{3}(?!\d))\d+)'
        potential_matches = []
        text = block.contents
        regexes = list(re.finditer(regex, text))
        if block.language == 'pl':
            pl_candidates += len(regexes)
        else:
            en_candidates += len(regexes)
        for reg in regexes:
            start_page, end_page, word_idxs, error_coordinate, _ = get_match_info(block.block, reg.start(), reg.end()- reg.start())
            potential_matches.append(Error_type(
                content=text[reg.start():reg.end()],
                category= "DECIMAL",
                message= "",
                offset= reg.start(),
                error_length=reg.end() - reg.start(),
                block_id = block.block.block_id,
                page_start = start_page,
                page_end = end_page,
                word_idxs = word_idxs,
                error_coordinate= error_coordinate,
            ))
        if block.block.type == 'paragraph':
            checked_match = check_decimal_matches(potential_matches, block, chapter_numbers, 1, chapter_nums)
            checked_matches.extend(checked_match)
        else:
            checked_match = check_decimal_matches(potential_matches, block, chapter_numbers, 2, chapter_nums)
            checked_matches.extend(checked_match)

    certain_errors = sum(1 for m in checked_matches if "Niepoprawny" in m.message or "Wrong" in m.message)
    possible_errors = len(checked_matches) - certain_errors
    logger.info("Decimal check complete:")
    logger.info("  PL candidates: %d, EN candidates: %d", pl_candidates, en_candidates)
    logger.info("  Confirmed errors: %d, possible errors: %d", certain_errors, possible_errors)
    logger.info("  Total matches: %d", len(checked_matches))
    return checked_matches

# Rdzenie słów poprzedzających odwołanie do numeru rozdziału/elementu (np. "w podrozdziale 3.1",
# "w sekcji 2.4", "na rysunku 2.1"). Dopasowywane jako prefiks, żeby objąć wszystkie formy odmiany.
REFERENCE_STEMS = ("wersj", "rysun", "tabel", "wykres", "rozdzia", "podrozdzia", "obraz", "wzor", "wzór",
                   "równani", "listing", "sekcj", "podsekcj", "podpunk", "paragraf", "załącznik", "aneks",
                   "algorytm", "schemat", "diagram", "fotografi", "zdjęci", "ilustracj")
# Słowa dopasowywane dokładnie - jako prefiksy dawałyby fałszywe trafienia
# (np. "roz" -> "rozmiar", "punkt" -> "punktacja", "dodatk" -> "dodatkowo", "table" -> "tablet").
REFERENCE_WORDS = {"wer", "rys", "tab", "wyk", "roz", "rozdz", "podrozdz", "obr", "rów", "sek", "pkt",
                   "par", "zał", "fot", "il", "alg", "sec", "fig", "eq", "eqn", "tbl", "ch", "app",
                   "punkt", "punktu", "punktem", "punkcie", "punkty", "punktów", "punktach", "punktami", "punktom",
                   "dodatek", "dodatku", "dodatkiem", "dodatki", "dodatków", "dodatkach", "dodatkami", "dodatkom",
                   "section", "sections", "subsection", "subsections", "chapter", "chapters", "figure", "figures",
                   "table", "tables", "equation", "equations", "appendix", "appendices"}

def is_reference_word(word):
    '''Checks if word (lowercase) introduces a reference to a numbered chapter, figure, table etc.'''
    return word in REFERENCE_WORDS or word.startswith(REFERENCE_STEMS)

def check_decimal_matches(potential_matches, block, chapter_numbers, error_tolerance, chapter_nums):
    '''Filters candidate decimal matches. Discards section/chapter numbering, values inside quotes or proper names
    and listing references.'''
    black_list = {"%", "$", "€", "£", "zł", "usd", "eur", "gbp", "°"}
    white_list_pl = {"wersja", "wersji", "wersjom", "wersjach", "wersję", "wer","wersją", "wersje", "wersjami", "rys", "rysunek", "rysunkom", "rysunkach", "rysunku", "tabela", "tabele", "tabelę", "tabeli", "tabelom", "tabelach", "tab",
                     "wykres", "wykresu", "wykresom", "wykresowi", "wykresem", "wykresie", "wykresach", "wyk", "rozdziale", "rozdział", "rozdziały", "rozdziału", "rozdziałem", "rozdziałach", "roz", "rozdz", "rozdziałów", 
                     "obraz", "obr", "obrazie", "obrazu", "obrazowi", "obrazach", "obrazem","obrazom", 
                     "wzór", "wzoru", "wzorowi", "wzory", "wzorom", "wzorach", "wzorami", "wzorem", "wzorze", "wzorów", 
                     "równanie", "równaniu", "równaniach", "równaniami", "równaniom", "równania", "równaniem", "rów", "listing"}
    checked_matches = []
    for match in potential_matches: 
        is_error = 1 #0 - brak błędu, 1 - potencjalny błąd, 1 - potencjalny błąd, 2 - pewny błąd.
        match_end = match.offset + match.error_length
        after_text = block.contents[match_end:].lstrip()
        before_text = block.contents[:match.offset].rstrip()
        end_check_idx = min(match_end+15, len(block.contents))
        following_text = re.findall(r'[^.()\[\]{}:,;\s]+',block.contents[match_end:end_check_idx].lower())
        begin_check_idx = max(match.offset-15, 0)
        previous_text = re.findall(r'[^.()\[\]{}:,;\s]+', block.contents[begin_check_idx:match.offset].lower())
        in_black_list = len(black_list.intersection(following_text)) > 0
        if re.match(r'[^.\d]*\.[ .]{4,}', block.contents) and not in_black_list:
            chapter_numbers.add(match.content)
            continue
        if match.content in chapter_numbers and not in_black_list:
            continue
        if (before_text.endswith('[') or before_text.endswith('(')) and (after_text.startswith(']') or after_text.startswith(')')):
            continue
        if check_quotes(match.offset, match.offset + match.error_length, block.contents):
            is_error = 0
        elif check_if_proper(block.block, match, is_diff= True):
            is_error = 0
        elif in_black_list:
            is_error = 2
        elif any(is_reference_word(word) for word in previous_text):
            is_error = 0
            chapter_numbers.add(match.content)
        elif following_text and len(set(white_list_pl).intersection(following_text)) > 0:
            is_error = 0 
            chapter_numbers.add(match.content)
        elif block.block.type == "heading" and match.word_idxs and (match.word_idxs[0] == 0 or match.word_idxs[0] == 1):
            is_error = 0
        if match.content.strip(" .:,") in chapter_nums and is_error<2:
            is_error = 0
        if is_error>= error_tolerance:
            if is_error == 2:
                if block.block.language == 'en':
                    error_message = "Wrong decimal separator."
                else:
                    error_message = "Niepoprawny separator dziesiętny."
            else:
                if block.block.language == 'en':
                    error_message = "Possible use of an incorrect decimal separator."
                else:
                    error_message = "Możliwe zastosowanie błędnego separatora dziesiętnego."

            match.message = error_message
            checked_matches.append(match)
    return checked_matches