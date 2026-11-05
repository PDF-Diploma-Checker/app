import json
import logging
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


def _value(text):
    """A value for comparing: no spaces, no case ('180 ms' and '180ms' are the same)."""
    return "".join(str(text).split()).lower()


def _same_value(in_text, in_image):
    """A chart often prints a bare number and has its unit elsewhere: "200 errors" in the text agrees with "200"."""
    a, b = _value(in_text), _value(in_image)
    if a == b:
        return True
    number = re.fullmatch(r"\d+(?:[.,]\d+)?", b)
    return bool(number) and re.match(rf"{re.escape(b)}(?![\d.,])", a) is not None


def _is_printed(value, printed):
    """True when a number of this value is really in the image. Nothing can be said when no list could be made."""
    if printed is None:
        return True
    numbers = {float(number.replace(",", ".")) for number in re.findall(r"\d+(?:[.,]\d+)?", str(value))}
    return bool(numbers & {abs(number) for number in printed})


def verdict_from_answer(answer, language="pl", printed=None):
    """Turn the model's answer into {poprawnosc_danych, bledy}. The model also lists items whose two values are equal,
    so the verdict is decided here from the values and not taken from the model. `printed` holds the numbers printed
    in the image: a chart without values gets values made up when it is read, and those prove nothing against the text."""
    mismatches = answer.get("niezgodnosci") if isinstance(answer, dict) else None
    if not isinstance(mismatches, list):
        return {"poprawnosc_danych": "Error", "bledy": "None"}
    real = [
        m for m in mismatches
        if isinstance(m, dict) and not _same_value(m.get("w_tekscie", ""), m.get("na_rysunku", ""))
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
            return verdict_from_answer(json.loads(result_text), language, printed)
        except json.JSONDecodeError:
            logger.exception("Failed to parse consistency-check JSON response: %r", result_text)
            return {"poprawnosc_danych": "Error", "bledy": "None"}