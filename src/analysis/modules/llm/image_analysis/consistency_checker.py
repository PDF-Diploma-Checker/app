import json
import logging
import math
import re
from analysis.modules.llm import config
from analysis.modules.llm.image_analysis.figures import image_text
from analysis.modules.llm.llama_factory import make_llama

logger = logging.getLogger(__name__)


_PROMPTS = {
    "pl": """Dane odczytane z rysunku:
{image_data}

Akapit z pracy:
{paragraph}

Sprawdź każdą wartość liczbową podaną w akapicie dla elementu, który występuje też w danych z rysunku.
Niezgodność to tylko sytuacja, gdy ten sam element ma w akapicie inną wartość niż na rysunku.
Nie jest niezgodnością: informacja, której nie ma na rysunku, wniosek, opis zależności, zaokrąglenie ani inna kolejność.
Zwróć JSON z kluczem "niezgodnosci": lista obiektów {"element": nazwa, "w_tekscie": wartość z akapitu razem z jednostką, "na_rysunku": wartość z rysunku razem z jednostką}, pusta gdy wszystko się zgadza.""",
    "en": """Data read from the figure:
{image_data}

Paragraph from the thesis:
{paragraph}

Check every numeric value the paragraph gives for an item that also appears in the data from the figure.
A mismatch is only when the same item has a different value in the paragraph than in the figure.
These are not mismatches: information missing from the figure, a conclusion, a description of a trend, rounding, a different order.
Return JSON with the key "niezgodnosci": a list of objects {"element": name, "w_tekscie": value from the paragraph with its unit, "na_rysunku": value from the figure with its unit}, empty when everything agrees.""",
}


_THOUSANDS = r"[1-9]\d{0,2}(?:[ \u00a0,]\d{3})+(?!\d)"
_NUMBER = re.compile(rf"{_THOUSANDS}|\d+(?:[.,]\d+)?")
_READ_VALUE = re.compile(r":(.+)$", re.M)
_MIN_AXIS_RUN = 4       # so many printed numbers in a row with one step are the scale of an axis, not values of the data
_MAX_UNIT_LENGTH = 4    # "ms", "MB/s"; a longer word is a noun in some grammatical case: "200 błędów", "200 błędy"


def _value(text):
    """A value for comparing: no spaces, no case ('180 ms' and '180ms' are the same)."""
    return "".join(str(text).split()).lower()


def _numbers(text):
    """(number, decimal places) of each number in the text. "5,000" and "5 000" are thousands, "0,989" is a fraction."""
    found = []
    for digits in _NUMBER.findall(str(text)):
        if re.fullmatch(_THOUSANDS, digits):
            found.append((float(re.sub(r"\D", "", digits)), 0))
        else:
            whole, _, fraction = digits.replace(",", ".").partition(".")
            found.append((float(f"{whole}.{fraction or 0}"), len(fraction)))
    return found


def _unit(text):
    return "".join(ch for ch in _NUMBER.sub("", str(text)).lower() if ch.isalpha() or ch in "%/")


def _units_agree(a, b):
    """A chart often prints a bare number and has its unit elsewhere: "200 errors" in the text agrees with "200"."""
    a, b = _unit(a), _unit(b)
    return not a or not b or a == b or max(len(a), len(b)) > _MAX_UNIT_LENGTH


def _same_value(in_text, in_image):
    """Equal also when written differently (0,9 and 0.90), rounded (0.989 and 1.0) or within a range in the text."""
    if _value(in_text) == _value(in_image):
        return True
    text_numbers, image_numbers = _numbers(in_text), _numbers(in_image)
    if len(image_numbers) != 1:
        return False
    image, image_places = image_numbers[0]
    if len(text_numbers) == 2:
        low, high = sorted(number for number, _ in text_numbers)
        return low <= image <= high
    if len(text_numbers) != 1:
        return False
    number, places = text_numbers[0]
    return abs(number - image) <= 0.5 * 10 ** -min(places, image_places) + 1e-9 and _units_agree(in_text, in_image)


def _without_axes(printed):
    """The printed numbers without the scales of the axes. A value read from a line or from a bar without a label is
    only estimated against the scale, so a number of the scale proves nothing about the data."""
    labels, start = [], 0
    while start < len(printed):
        end = start + 1
        step = printed[end] - printed[start] if end < len(printed) else 0
        while step and end + 1 < len(printed) and math.isclose(printed[end + 1] - printed[end], step, abs_tol=1e-6):
            end += 1
        if step and end - start + 1 >= _MIN_AXIS_RUN:
            start = end + 1
        else:
            labels.append(printed[start])
            start += 1
    return labels


def _is_printed(value, printed):
    """True when a number of this value is really in the image. Nothing can be said when no list could be made."""
    if printed is None:
        return True
    return bool({number for number, _ in _numbers(value)} & {abs(number) for number in _without_axes(printed)})


def values_are_printed(image_data, printed):
    """False when most of the values read from a chart are not printed in it: the whole reading is then an estimate."""
    if printed is None:
        return True
    labels = {abs(number) for number in _without_axes(printed)}
    read = [numbers[0][0] for numbers in map(_numbers, _READ_VALUE.findall(str(image_data))) if numbers]
    return sum(number in labels for number in read) * 2 > len(read)


def _is_comparable(mismatch, paragraph):
    """Both values must be numbers and the one from the text must really be in the paragraph."""
    in_text, in_image = _numbers(mismatch.get("w_tekscie", "")), _numbers(mismatch.get("na_rysunku", ""))
    if not in_text or not in_image:
        return False
    return paragraph is None or {n for n, _ in in_text} <= {n for n, _ in _numbers(paragraph)}


def verdict_from_answer(answer, language="pl", printed=None, paragraph=None):
    """Turn the model's answer into {poprawnosc_danych, bledy}. The model also lists items whose two values are equal,
    so the verdict is decided here from the values and not taken from the model. `printed` holds the numbers printed
    in the image: a chart without values gets values made up when it is read, and those prove nothing against the text."""
    mismatches = answer.get("niezgodnosci") if isinstance(answer, dict) else None
    if not isinstance(mismatches, list):
        return {"poprawnosc_danych": "Error", "bledy": "None"}
    real = [
        m for m in mismatches
        if isinstance(m, dict) and _is_comparable(m, paragraph)
        and not _same_value(m.get("w_tekscie", ""), m.get("na_rysunku", ""))
    ]
    guessed = [m for m in real if not _is_printed(m.get("na_rysunku", ""), printed)]
    if guessed:
        logger.info("Dropped mismatches with values not printed in the figure: %r", guessed)
    real = [m for m in real if m not in guessed]
    if not real:
        return {"poprawnosc_danych": "True", "bledy": "None"}
    lines = [
        image_text(language, "mismatch", element=m.get("element", "?"), text=m.get("w_tekscie", "?"), image=m.get("na_rysunku", "?"))
        for m in real
    ]
    return {"poprawnosc_danych": "False", "bledy": "; ".join(lines)}


class ConsistencyChecker:
    def __init__(self, model_path=None):
        model_path = model_path or str(config.MODEL_PATH)
        logger.info("Loading consistency-checker LLM from %s", model_path)
        try:
            self.llm = make_llama(
                purpose="Spójność rysunków",
                model_path=model_path,
                n_ctx=4096,
                n_gpu_layers=config.N_GPU_LAYERS,
                verbose=False
            )
        except Exception as e:
            logger.exception("Failed to load consistency-checker LLM from %s", model_path)
            raise RuntimeError(f"Failed to load consistency-checker LLM from {model_path}") from e

    def close(self):
        self.llm.close()

    def check(self, paragraph, image_data, language="pl", printed=None):
        if not values_are_printed(image_data, printed):
            logger.info("Figure not compared, its values are not printed in it: %r", image_data)
            return {"poprawnosc_danych": "True", "bledy": "None"}

        template = _PROMPTS.get(language, _PROMPTS["pl"])
        prompt = template.replace("{image_data}", str(image_data)).replace("{paragraph}", str(paragraph))

        try:
            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format={
                    "type": "json_object",
                },
                temperature=0.0
            )
        except Exception as e:
            logger.exception("Consistency-check LLM inference failed")
            raise RuntimeError("Consistency-check LLM inference failed") from e

        result_text = response["choices"][0]["message"]["content"]

        try:
            return verdict_from_answer(json.loads(result_text), language, printed, paragraph)
        except json.JSONDecodeError:
            logger.exception("Failed to parse consistency-check JSON response: %r", result_text)
            return {"poprawnosc_danych": "Error", "bledy": "None"}