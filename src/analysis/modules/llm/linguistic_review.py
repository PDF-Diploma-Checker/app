"""Second opinion on the findings of the language checks: is this really an error, in this place of the thesis?

The rules see a word or a pattern, so a technical term, a name or a version number looks like an error to them. The text
model reads the finding with the text around it. Findings that depend on what the text does not show (the italics, the
whole document, the rules of a bibliography) are not asked about.
"""

import itertools
import json
import logging
import string

from analysis.modules.linguistics.decision_log import confirmed_by_model, not_reviewed, rejected_by_model
from analysis.modules.linguistics.helpers import morf, nlp_pl
from analysis.modules.linguistics.language_error_extractor import typo_check
from analysis.modules.llm import config
from analysis.modules.llm.llama_factory import make_llama
from analysis.modules.llm.results_log import log_results
from common import run_control

logger = logging.getLogger(__name__)

MAX_ANSWER_TOKENS = 100
N_CTX = 2048
NOTIFY_EVERY = 20
MAX_COPIED_CHARS = 40   # a longer fragment would not fit into the answer
REVIEWED_SOURCES = ("language_tool", "sentence_check", "decimal_check")
FORMAT_RULES = ("PERSONAL_FORM",)   # correct Polish that a thesis must still avoid: the model only sees the grammar
_POLISH_LETTERS = {"a": "ą", "c": "ć", "e": "ę", "l": "ł", "n": "ń", "o": "ó", "s": "ś", "z": "źż"}
MAX_MISSING_LETTERS = 2
_ALPHABET = "aąbcćdeęfghijklłmnńoóprsśtuwyzźż"
MIN_TYPO_LENGTH = 7     # a shorter unknown word is one letter from too many real ones ("stdio": "studio")
UNREADABLE_RULES = ("ZDANIA_ZLOZONE",)  # the model calls a missing comma between two clauses correct text

_PROMPTS = {
    "pl": """Fragment pracy dyplomowej (zgłoszone miejsce stoi między « i »):
{context}

Zgłoszony fragment: {found}
Treść zgłoszenia: {message}
Szczegóły z narzędzia: {why}

Automatyczne narzędzie uznało to miejsce za błąd językowy. Oceń, czy w tym kontekście to naprawdę błąd.
To nie jest błąd, gdy zgłoszony fragment jest poprawny i narzędzie go nie rozumie, na przykład: nazwa własna, termin techniczny, nazwa biblioteki, funkcji lub zmiennej, celowo użyty wyraz obcy, skrót, numer wersji, tytuł, fragment wzoru lub kodu, zdanie z podmiotem domyślnym wynikającym z poprzedniego zdania.
To jest błąd, gdy tekst rzeczywiście ma literówkę (także brak polskich znaków), błędną odmianę, brak przecinka lub inny błąd opisany w zgłoszeniu.
Jeśli nie masz pewności, uznaj to za błąd.
Zwróć JSON z kluczami {keys}.""",
    "en": """A fragment of a thesis (the reported place stands between « and »):
{context}

Reported fragment: {found}
What was reported: {message}
Details from the tool: {why}

An automatic tool found a language error in this place. Decide whether it really is an error in this context.
It is not an error when the reported fragment is correct and the tool does not understand it, for example: a proper name, a technical term, a name of a library, function or variable, a foreign word used on purpose, an abbreviation, a version number, a title, a part of a formula or code.
It is an error when the text really has a typo, a wrong form, a missing comma or another error that the report describes.
If you are not sure, treat it as an error.
Return JSON with the keys {keys}.""",
}

_ANSWER_KEYS = {
    "pl": '"uzasadnienie" (jedno krótkie zdanie) i "blad" (true albo false)',
    "en": '"uzasadnienie" (one short sentence, in English) and "blad" (true or false)',
}
_SPELLING_KEY = {
    "pl": '"poprawny_zapis" (zgłoszony fragment tak, jak powinien być napisany: przepisz go znak po znaku, razem z polskimi znakami; gdy jest poprawny, bez żadnej zmiany), ',
    "en": '"poprawny_zapis" (the reported fragment as it should be written: copy it character by character; when it is correct, without any change), ',
}

_PROGRESS = {
    "pl": "AI: weryfikacja błędów językowych ({done}/{total})...",
    "en": "AI: verifying the language errors ({done}/{total})...",
}


def _with_polish_letters(text):
    """The known word this unknown one becomes with Polish letters ("czesto": "często"), None when there is none.
    Such a word is a typo for certain, and the model would read it as the correct one."""
    word = text.strip(string.punctuation + string.whitespace)
    if not (word.isalpha() and word.islower()) or typo_check(word):
        return None
    places = [i for i, letter in enumerate(word) if letter in _POLISH_LETTERS]
    for count in range(1, MAX_MISSING_LETTERS + 1):
        for chosen in itertools.combinations(places, count):
            for letters in itertools.product(*(_POLISH_LETTERS[word[i]] for i in chosen)):
                candidate = list(word)
                for i, letter in zip(chosen, letters):
                    candidate[i] = letter
                if typo_check("".join(candidate)):
                    return "".join(candidate)
    return None


def _is_polish(word):
    return any(interpretation[2][2] != "ign" for interpretation in morf.analyse(word))


def _is_common(word):
    """True for a word of ordinary texts: spaCy has vectors for the 500 000 most frequent ones. Morfeusz also accepts
    forms nobody writes ("odległoościowe", "rabotycznych"), which do not show a typo."""
    return nlp_pl.vocab.has_vector(word)


def _one_letter_from_polish(match):
    """The common Polish word this unknown one becomes with one letter fixed ("przbiega": "przebiega"), None when there
    is none. The model calls such a word a technical term. A capital is only ignored at the start of a sentence,
    elsewhere it is a name."""
    word = match.content.strip(string.punctuation + string.whitespace)
    before = match.context.partition("«")[0].rstrip()
    if word.istitle() and (not before or before[-1] in ".!?:"):
        word = word.lower()
    if not (word.isalpha() and word.islower()) or len(word) < MIN_TYPO_LENGTH or typo_check(word):
        return None
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    candidates = itertools.chain(
        (left + right[1] + right[0] + right[2:] for left, right in splits if len(right) > 1),
        (left + letter + right for left, right in splits for letter in _ALPHABET),
        (left + right[1:] for left, right in splits if right),
        (left + letter + right[1:] for left, right in splits if right for letter in _ALPHABET),
    )
    return next((candidate for candidate in candidates
                 if candidate != word and _is_polish(candidate) and _is_common(candidate)), None)


def _why_not_asked(match, language):
    """Why the model does not read this finding, None when it should."""
    if match.source not in REVIEWED_SOURCES or match.category in FORMAT_RULES:
        return "a rule of the format, the text alone does not settle it"
    if match.rule in UNREADABLE_RULES:
        return "a comma between clauses, the model does not judge it well"
    if not match.context:
        return "no text around it"
    if language != "pl":
        return None
    fixed = _with_polish_letters(match.content)
    if fixed:
        return f"a typo for certain, the word is {fixed}"
    near = _one_letter_from_polish(match)
    return f"a typo for certain, one letter from {near}" if near else None


def _flat(text):
    return " ".join(str(text).split())


def _is_short(match):
    return len(match.content) <= MAX_COPIED_CHARS


def _verdict(answer, match):
    """(True if an error, False if correct, None without a clear answer; the reason). The model reads "czesto" as
    "często" and calls it correct, so for a short fragment what it would write decides: a change means an error."""
    if not isinstance(answer, dict):
        return None, ""
    value = answer.get("blad")
    if isinstance(value, str):
        value = {"true": True, "false": False}.get(value.strip().lower())
    reason = str(answer.get("uzasadnienie") or "")
    if not isinstance(value, bool):
        return None, reason
    if value or not _is_short(match):
        return value, reason
    fixed = answer.get("poprawny_zapis")
    if not isinstance(fixed, str):
        return None, reason
    if _flat(fixed) != _flat(match.content):
        return True, f"it would write {_flat(fixed)!r}; {reason}"
    return False, reason


def _ask(llm, template, match, language):
    keys = _ANSWER_KEYS.get(language, _ANSWER_KEYS["pl"])
    if _is_short(match):
        keys = _SPELLING_KEY.get(language, _SPELLING_KEY["pl"]) + keys
    prompt = (template.replace("{keys}", keys).replace("{context}", match.context).replace("{found}", match.content)
              .replace("{message}", match.message).replace("{why}", match.why or "-"))
    response = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=MAX_ANSWER_TOKENS,
    )
    return json.loads(response["choices"][0]["message"]["content"])


def review_findings(matches, language="pl"):
    """The findings without those the model is sure are correct text; every decision goes to the log.

    A finding the model gives no clear answer about stays: a failure of the model must not hide an error of the thesis.
    """
    to_ask = []
    for match in matches:
        reason = _why_not_asked(match, language)
        if reason:
            not_reviewed(reason, match)
        else:
            to_ask.append(match)
    if not to_ask:
        return matches

    template = _PROMPTS.get(language, _PROMPTS["pl"])
    progress = _PROGRESS.get(language, _PROGRESS["pl"])
    llm = make_llama(
        purpose="Weryfikacja błędów językowych",
        model_path=str(config.MODEL_PATH),
        n_ctx=N_CTX,
        n_gpu_layers=config.N_GPU_LAYERS,
        verbose=False,
    )
    rejected, confirmed, unclear = set(), 0, 0
    try:
        for done, match in enumerate(to_ask):
            run_control.check_cancelled()
            if done % NOTIFY_EVERY == 0:
                run_control.notify(progress.format(done=done, total=len(to_ask)))
            try:
                answer = _ask(llm, template, match, language)
            except Exception:
                logger.exception("Review of the finding %r failed", match.content)
                not_reviewed("the model failed", match)
                unclear += 1
                continue
            verdict, reason = _verdict(answer, match)
            if verdict is False:
                rejected_by_model(match, reason)
                rejected.add(id(match))
            elif verdict:
                confirmed_by_model(match, reason)
                confirmed += 1
            else:
                not_reviewed(f"no clear answer: {answer}", match)
                unclear += 1
    finally:
        llm.close()
    log_results("Language findings reviewed by the model", all_findings=len(matches), asked=len(to_ask),
                confirmed=confirmed, rejected=len(rejected), unclear=unclear)
    return [match for match in matches if id(match) not in rejected]
