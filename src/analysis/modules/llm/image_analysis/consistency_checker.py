import json
import logging
from analysis.modules.llm import config
from analysis.modules.llm.llama_factory import make_llama

logger = logging.getLogger(__name__)


_PROMPTS = {
    "pl": """
        Dane z obrazka: {image_data}
        Akapit z pracy: {paragraph}

        Przeanalizuj, czy dane w akapicie zgadzają się z obrazkiem.
        Zwróć wynik w JSON. Klawisze: "poprawnosc_danych" (jako string "True" lub "False") oraz "bledy" (jako string "None" lub cytaty błędnych zdań).
        Odpowiadaj po polsku.
        """,
    "en": """
        Data from the image: {image_data}
        Paragraph from the thesis: {paragraph}

        Check whether the data in the paragraph agrees with the image.
        Return the result as JSON. Keys: "poprawnosc_danych" (the string "True" or "False") and "bledy" (the string "None" or quotes of the incorrect sentences).
        Answer in English.
        """,
}


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

    def check(self, paragraph, image_data, language="pl"):
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
            return json.loads(result_text)
        except json.JSONDecodeError:
            logger.exception("Failed to parse consistency-check JSON response: %r", result_text)
            return {"poprawnosc_danych": "Error", "bledy": "None"}