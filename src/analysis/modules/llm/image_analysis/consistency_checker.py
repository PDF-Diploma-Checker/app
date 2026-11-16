import json
import logging
import re
from analysis.modules.llm.image_analysis.figures import image_text

logger = logging.getLogger(__name__)


_PROMPTS = {
    "pl": """Dane odczytane z rysunku:
{image_data}

Akapit z pracy:
{paragraph}

Sprawdź każdą wartość liczbową podaną w akapicie dla elementu, który występuje też w danych z rysunku.
Niezgodność to tylko sytuacja, gdy ten sam element ma w akapicie inną wartość niż na rysunku.
Nie jest niezgodnością: informacja, której nie ma na rysunku, wniosek, opis zależności, zaokrąglenie ani inna kolejność.
Zwróć JSON z kluczem "niezgodnosci": lista obiektów {"element": nazwa, "w_tekscie": wartość z akapitu razem z jednostką, "na_rysunku": wartość z rysunku razem z jednostką}, pusta gdy wszystko się zgadza. Do każdej niezgodności dodaj text_quote oraz image_quote: dosłowne fragmenty odpowiednio akapitu i danych z rysunku, zawierające nazwę elementu i jego wartość. Nazwa elementu musi identyfikować także serię, jeśli rysunek zawiera wiele serii. Cytuj najkrótszy samodzielny fragment wiążący element z wartością. Nie porównuj wartości z różnych elementów, serii, osi ani jednostek.""",
    "en": """Data read from the figure:
{image_data}

Paragraph from the thesis:
{paragraph}

Check every numeric value the paragraph gives for an item that also appears in the data from the figure.
A mismatch is only when the same item has a different value in the paragraph than in the figure.
These are not mismatches: information missing from the figure, a conclusion, a description of a trend, rounding, a different order.
Return JSON with the key "niezgodnosci": a list of objects {"element": name, "w_tekscie": value from the paragraph with its unit, "na_rysunku": value from the figure with its unit}, empty when everything agrees. Include text_quote and image_quote for each mismatch: verbatim excerpts from the paragraph and figure data respectively, containing the item name and its value. The item name must also identify the series if the figure has multiple series. Quote the shortest self-contained excerpt linking the item to its value. Never compare different items, series, axes or units.""",
}


_THOUSANDS = r"[1-9]\d{0,2}(?:[ \u00a0,]\d{3})+(?!\d)"
_NUMBER = re.compile(rf"(?<![\w.,])[-+−]?(?:{_THOUSANDS}|\d+(?:[.,]\d+)?)")
# Parse interval endpoints separately so an ASCII separator is not a minus sign.
_ENDPOINT = r"[-+−]?\d+(?:[.,]\d+)?"
_RANGE = re.compile(rf"^\s*({_ENDPOINT})\s*[–—-]\s*({_ENDPOINT})\s*[^\d]*$")
_READ_VALUE = re.compile(r":(.+)$", re.M)
_MIN_AXIS_RUN = 4       # so many printed numbers in a row with one step are the scale of an axis, not values of the data


def _value(text):
    """A value for comparing: no spaces, preserving case ('180 ms' and '180ms' are the same)."""
    return "".join(str(text).split())


def _numbers(text):
    """(number, decimal places) of each number in the text. "5,000" and "5 000" are thousands, "0,989" is a fraction."""
    interval = _RANGE.fullmatch(str(text))
    if interval:
        return _numbers(interval[1]) + _numbers(interval[2])
    found = []
    for digits in _NUMBER.findall(str(text)):
        digits = digits.replace("−", "-")
        sign = -1 if digits.startswith("-") else 1
        digits = digits.lstrip("+-")
        if re.fullmatch(_THOUSANDS, digits):
            found.append((sign * float(re.sub(r"\D", "", digits)), 0))
        else:
            whole, _, fraction = digits.replace(",", ".").partition(".")
            found.append((sign * float(f"{whole}.{fraction or 0}"), len(fraction)))
    return found


def _unit(text):
    return "".join(ch for ch in _NUMBER.sub("", str(text)) if ch.isalpha() or ch in "%/")


_UNITS = {"ms": ("time", .001), "s": ("time", 1), "min": ("time", 60),
          "kB": ("bytes", 1000), "KB": ("bytes", 1000),
          "MB": ("bytes", 1e6), "GB": ("bytes", 1e9),
          "%": ("fraction", .01), "fraction": ("fraction", 1),
          "proportion": ("fraction", 1)}


def _unit_scales(a, b):
    """Only explicit compatible units establish a conversion."""
    a, b = _unit(a), _unit(b)
    if a == b:
        return 1, 1
    if a in _UNITS and b in _UNITS and _UNITS[a][0] == _UNITS[b][0]:
        return _UNITS[a][1], _UNITS[b][1]
    return None


def _same_value(in_text, in_image):
    """Equal also when written differently (0,9 and 0.90), rounded (0.989 and 1.0) or within a range in the text."""
    if _value(in_text) == _value(in_image):
        return True
    text_numbers, image_numbers = _numbers(in_text), _numbers(in_image)
    if len(image_numbers) != 1:
        return False
    image, image_places = image_numbers[0]
    scales = _unit_scales(in_text, in_image)
    if scales is None:
        return False
    scale_a, scale_b = scales
    if len(text_numbers) == 2 and _RANGE.fullmatch(str(in_text)):
        low, high = sorted(number for number, _ in text_numbers)
        return low * scale_a <= image * scale_b <= high * scale_a
    if len(text_numbers) != 1:
        return False
    number, places = text_numbers[0]
    number, image = number * scale_a, image * scale_b
    if abs(number - image) < 1e-9:
        return True
    # Integers alone do not establish rounding precision: 0 is not 0.4.
    if not places or not image_places:
        return False
    tolerance = .5 * max(10 ** -places * scale_a, 10 ** -image_places * scale_b)
    return abs(number - image) <= tolerance + 1e-12


def _without_axes(printed):
    """The printed numbers without the scales of the axes. A value read from a line or from a bar without a label is
    only estimated against the scale, so a number of the scale proves nothing about the data."""
    labels, start = [], 0
    while start < len(printed):
        end = start + 1
        step = printed[end] - printed[start] if end < len(printed) else 0
        while step and end + 1 < len(printed) and abs(printed[end + 1] - printed[end] - step) < 1e-6:
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
    return bool({number for number, _ in _numbers(value)} & {number for number in _without_axes(printed)})


def values_are_printed(image_data, printed):
    """False when most of the values read from a chart are not printed in it: the whole reading is then an estimate."""
    if printed is None:
        return True
    labels = {number for number in _without_axes(printed)}
    read = [numbers[0][0] for numbers in map(_numbers, _READ_VALUE.findall(str(image_data))) if numbers]
    return sum(number in labels for number in read) * 2 > len(read)


def confirmed_reading(image_data, printed):
    """Keep independently confirmed values even if other rows were estimated.

    Axis ticks cannot confirm a value. Keep headings for context, but never
    pass an unconfirmed numeric row to the comparison model.
    """
    if printed is None:
        return str(image_data), False
    labels = set(_without_axes(printed))
    kept, confirmed, omitted = [], False, False
    for line in str(image_data).splitlines():
        value = _READ_VALUE.search(line)
        numbers = _numbers(value.group(1)) if value else []
        if numbers:
            if all(number in labels for number, _ in numbers):
                confirmed = True
                kept.append(line)
            else:
                omitted = True
        elif not _numbers(line) or (not value and re.search(r"[^\W\d_]", line)):
            kept.append(line)
    return ("\n".join(kept) if confirmed else ""), omitted


def _literal_quote(quote, source):
    """A quote may not truncate a numeric token (A: 0 from A: 0.81)."""
    quote = " ".join(quote.split())
    source = " ".join(str(source).split())
    for match in re.finditer(re.escape(quote), source):
        start, end = match.span()
        if start and quote[0].isalnum() and source[start - 1].isalnum():
            continue
        if end < len(source) and quote[-1].isalnum() and source[end].isalnum():
            continue
        if any(token.start() < start < token.end() or token.start() < end < token.end()
               for token in _NUMBER.finditer(source)):
            continue
        return True
    return False


def _grounded_value(quote, element, value):
    """Require a local, unambiguous item/value pair, not numbers from other rows.

    Multi-value clauses cannot establish a series association without structured
    evidence. Leave those for review rather than report a guessed discrepancy.
    """
    if not isinstance(element, str) or not element.strip():
        return False
    item = re.compile(r"(?<!\w)" + re.escape(element.strip()) + r"(?!\w)", re.I)
    expected = _numbers(value)
    for clause in re.split(r"[;\n]|[.!?](?!\d)", quote):
        match = item.search(clause)
        if match is None:
            continue
        remainder = (clause[:match.start()] + clause[match.end():]).strip(" :\t")
        if [n for n, _ in _numbers(remainder)] != [n for n, _ in expected]:
            continue
        if _unit(value) and _value(value) not in _value(remainder):
            continue
        return True
    return False


def _is_comparable(mismatch, paragraph, image_data=None):
    """Both values must be numbers and the one from the text must really be in the paragraph."""
    in_text, in_image = _numbers(mismatch.get("w_tekscie", "")), _numbers(mismatch.get("na_rysunku", ""))
    if not in_text or not in_image:
        return False
    # Unknown conversions and missing units cannot establish a quantity.
    if _unit_scales(mismatch.get("w_tekscie", ""), mismatch.get("na_rysunku", "")) is None:
        return False
    # A pair such as 37/80 is a ratio, not a range or a single measured value.
    if len(in_image) != 1 or (len(in_text) != 1 and not _RANGE.fullmatch(str(mismatch.get("w_tekscie", "")))):
        return False
    if image_data is not None:
        # The model must point to evidence on both sides, rather than borrow an
        # unrelated number from another series or the surrounding paragraph.
        for key, source, value in (("text_quote", paragraph, mismatch.get("w_tekscie", "")),
                                   ("image_quote", image_data, mismatch.get("na_rysunku", ""))):
            quote = mismatch.get(key)
            if not isinstance(quote, str) or not quote.strip() or source is None:
                return False
            if not _literal_quote(quote, source):
                return False
            if not _grounded_value(quote, mismatch.get("element", ""), value):
                return False
    # Literal, item-grounded quotes already establish presence in both sources.
    if image_data is not None:
        return True
    return paragraph is None or {n for n, _ in in_text} <= {n for n, _ in _numbers(paragraph)}


def verdict_from_answer(answer, language="pl", printed=None, paragraph=None, image_data=None):
    """Turn the model's answer into {poprawnosc_danych, bledy}. The model also lists items whose two values are equal,
    so the verdict is decided here from the values and not taken from the model. `printed` holds the numbers printed
    in the image: a chart without values gets values made up when it is read, and those prove nothing against the text."""
    mismatches = answer.get("niezgodnosci") if isinstance(answer, dict) else None
    if not isinstance(mismatches, list) or any(not isinstance(m, dict) for m in mismatches):
        return {"poprawnosc_danych": "Unreadable", "bledy": image_text(language, "unverified_values")}
    real = [
        m for m in mismatches
        if isinstance(m, dict) and _is_comparable(m, paragraph, image_data)
        and not _same_value(m.get("w_tekscie", ""), m.get("na_rysunku", ""))
    ]
    guessed = [m for m in real if not _is_printed(m.get("na_rysunku", ""), printed)]
    if guessed:
        logger.info("Dropped mismatches with values not printed in the figure: %r", guessed)
    real = [m for m in real if m not in guessed]
    if not real:
        if guessed or any(isinstance(m, dict) and not _is_comparable(m, paragraph, image_data) for m in mismatches):
            return {"poprawnosc_danych": "Unreadable", "bledy": image_text(language, "unverified_values")}
        return {"poprawnosc_danych": "True", "bledy": "None"}
    lines = [
        image_text(language, "mismatch", element=m.get("element", "?"), text=m.get("w_tekscie", "?"), image=m.get("na_rysunku", "?"))
        for m in real
    ]
    return {"poprawnosc_danych": "False", "bledy": "; ".join(lines)}


class ConsistencyChecker:
    def __init__(self, model_path=None):
        from analysis.modules.llm import config
        from analysis.modules.llm.llama_factory import make_llama

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
        image_data, omitted = confirmed_reading(image_data, printed)
        if not image_data:
            logger.info("Figure not compared, its values are not printed in it: %r", image_data)
            return {"poprawnosc_danych": "Unreadable", "bledy": image_text(language, "unverified_values")}

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
        except Exception:
            logger.exception("Consistency-check LLM inference failed")
            return {"poprawnosc_danych": "Unreadable", "bledy": image_text(language, "unverified_values")}

        result_text = None
        try:
            result_text = response["choices"][0]["message"]["content"]
            result = verdict_from_answer(json.loads(result_text), language, printed, paragraph, image_data)
            if omitted and result["poprawnosc_danych"] == "True":
                result = {"poprawnosc_danych": "Partial", "bledy": image_text(language, "partial_values")}
            return result
        except (json.JSONDecodeError, TypeError, KeyError, IndexError):
            logger.exception("Failed to parse consistency-check JSON response: %r", result_text)
            return {"poprawnosc_danych": "Unreadable", "bledy": image_text(language, "unverified_values")}
