"""Word count of the Polish abstract (STRESZCZENIE or ABSTRAKT) and the English one (ABSTRACT).

Counts from the first word after the heading up to the keywords line ("Słowa kluczowe", "Keywords") or the field of
science line ("Dziedzina nauki", "Field(s) of science"), whichever comes first. A following heading or table of contents
also ends the section, so a thesis without a keywords line is not counted to its end.
"""

import re

RECOMMENDED_MIN_WORDS = 300

_TITLES = {'streszczenie': 'pl', 'abstrakt': 'pl', 'abstract': 'en'}
_STOP = re.compile(r'słowa\s+kluczowe|key\s*words|dziedzina\s+nauki|fields?\s+of\s+science', re.IGNORECASE)
_WORD = re.compile(r"\w+(?:[-‐'’]\w+)*")
_ENDING_TYPES = {'heading', 'toc'}


def _title_language(text):
    """'pl'/'en' when the block is an abstract heading, with any text after it; None otherwise."""
    words = text.split(None, 1)
    if not words:
        return None
    first = words[0].strip(' .:')
    language = _TITLES.get(first.casefold())
    if language is None:
        return None
    rest = words[1] if len(words) > 1 else ''
    # the heading alone, or written in capitals / followed by a colon at the start of the text ("ABSTRACT The ...");
    # an ordinary "abstract" inside a sentence is not a heading
    if not rest.strip() or first.isupper() or words[0].rstrip().endswith(':'):
        return language, rest
    return None


def _result(words):
    return {'count': len(words), 'first': words[0] if words else '', 'last': words[-1] if words else ''}


def count_abstract_words(document):
    """{'pl': {'count': n, 'first': word, 'last': word}, 'en': {...}} with only the abstracts found in the document
    ('first' and 'last' are the first and the last counted word); {} when there is none."""
    counts = {}
    language, words = None, []
    for block in getattr(document, 'logical_blocks', None) or []:
        text = ' '.join(str(getattr(block, 'content', '') or '').split())
        title = _title_language(text)
        if title is not None and title[0] not in counts and title[0] != language:
            if language is not None:
                counts[language] = _result(words)
            language, text = title
            words = []
        elif language is not None and getattr(block, 'type', None) in _ENDING_TYPES:
            counts[language], language = _result(words), None
            continue
        if language is None:
            continue
        stop = _STOP.search(text)
        if stop:
            text = text[:stop.start()]
        words += _WORD.findall(text)
        if stop:
            counts[language], language = _result(words), None
    if language is not None:
        counts[language] = _result(words)
    return counts


def abstract_count(value):
    """(count, first word, last word) of one saved abstract result."""
    if isinstance(value, dict):
        try:
            count = int(value.get('count', 0))
        except (TypeError, ValueError):
            count = 0
        return count, str(value.get('first', '') or ''), str(value.get('last', '') or '')
    try:
        return int(value), '', ''
    except (TypeError, ValueError):
        return 0, '', ''
