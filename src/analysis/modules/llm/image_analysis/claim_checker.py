"""What the text says about a figure, checked on the figure itself.

A chart without printed values cannot be turned into numbers: a model reading a curve makes them up. So the text model
picks out what the paragraph says about the figure (a value, a trend, a comparison) and the vision model looks at the
figure with that statement in front of it. Only a confirmation is reported: a 7B vision model asked whether a figure
contradicts a statement does not catch real errors and turns true statements down, so a statement it does not confirm
is left unchecked, never reported as an error."""
import json
import logging
import re

from analysis.modules.llm.image_analysis.figures import image_text, mentions_figure, parse_yes_no

logger = logging.getLogger(__name__)

MAX_CLAIMS = 3

_PROMPTS = {
    "pl": """Akapit z pracy dyplomowej:
{paragraph}

Wypisz stwierdzenia tego akapitu o tym, co widać na rysunku {label}: wartości, przebiegi, trendy, porównania, zakresy.
Pomiń zdania o metodzie, przyczynach i wnioskach oraz zdania o innych rysunkach. Najwyżej {max_claims} stwierdzenia.
Zwróć JSON z kluczem "stwierdzenia": lista obiektów {{"cytat": dosłowny fragment akapitu, "teza": to samo stwierdzenie
po angielsku, jednym krótkim zdaniem, z liczbami i nazwami serii tak jak w akapicie}}. Pusta lista, gdy akapit nie mówi
nic, co można sprawdzić, patrząc na rysunek.""",
    "en": """Paragraph from a thesis:
{paragraph}

List the statements of this paragraph about what figure {label} shows: values, curves, trends, comparisons, ranges.
Leave out sentences about the method, causes and conclusions and sentences about other figures. At most {max_claims}.
Return JSON with the key "stwierdzenia": a list of objects {{"cytat": a verbatim excerpt of the paragraph, "teza": the
same statement in one short English sentence, with the numbers and series names as in the paragraph}}. An empty list
when the paragraph says nothing that can be checked by looking at the figure.""",
}

SUPPORT_QUESTION = ("Look at the figure, its axes, legend and labels. Does the figure support this statement from the "
                    'thesis text? Statement: "{claim}"')

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])")


def _plain(text):
    return " ".join(str(text).split())


def about_figure(paragraph, img, images):
    """The part of the paragraph about this figure. A paragraph on several figures keeps only its sentences that name
    this one: a statement about the next figure must not be checked on this one."""
    others = [other for other in images if other["id"] != img["id"] and mentions_figure(paragraph, other["number"], other["family"])]
    if not others:
        return paragraph
    sentences = _SENTENCE_END.split(paragraph)
    return " ".join(s for s in sentences if mentions_figure(s, img["number"], img["family"]))


def claims_from_answer(answer, paragraph):
    """The statements of the model's answer that really are in the paragraph."""
    entries = answer.get("stwierdzenia") if isinstance(answer, dict) else None
    if not isinstance(entries, list):
        return []
    source = _plain(paragraph).casefold()
    claims = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        quote, claim = _plain(entry.get("cytat", "")), _plain(entry.get("teza", ""))
        if quote and claim and quote.casefold() in source and quote not in (c["quote"] for c in claims):
            claims.append({"quote": quote, "claim": claim})
    return claims[:MAX_CLAIMS]


def extract_claims(llm, paragraph, label, language="pl"):
    """What the paragraph says that the figure can confirm, by the text model."""
    if not paragraph.strip():
        return []
    prompt = _PROMPTS.get(language, _PROMPTS["pl"]).format(paragraph=paragraph, label=label, max_claims=MAX_CLAIMS)
    try:
        response = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return claims_from_answer(json.loads(response["choices"][0]["message"]["content"]), paragraph)
    except Exception:
        logger.exception("Could not pick the statements about %s out of the paragraph", label)
        return []


def check_claim(engine, image_bytes, claim):
    """'supported' or 'unclear'. A "no" says nothing: a small model also says "no" when it cannot tell."""
    if parse_yes_no(engine.ask_yes_no(image_bytes, SUPPORT_QUESTION.format(claim=claim))):
        return "supported"
    return "unclear"


def claims_verdict(results, language="pl"):
    """The report entry fields for the statements of one paragraph: (poprawnosc_danych, bledy)."""
    if any(result == "supported" for _, result in results):
        return "True", "None"
    return "NoData", image_text(language, "claims_unclear" if results else "no_claims")
