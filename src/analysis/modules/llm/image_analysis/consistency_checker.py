from llama_cpp import Llama
import json
import logging
import config

logger = logging.getLogger(__name__)


class ConsistencyChecker:
    def __init__(self, model_path=str(config.MODEL_PATH)):
        logger.info("Loading consistency-checker LLM from %s", model_path)
        try:
            self.llm = Llama(
                model_path=model_path,
                n_ctx=4096,
                n_gpu_layers=config.N_GPU_LAYERS,
                verbose=False
            )
        except Exception as e:
            logger.exception("Failed to load consistency-checker LLM from %s", model_path)
            raise RuntimeError(f"Failed to load consistency-checker LLM from {model_path}") from e

    def check(self, paragraph, image_data):
        prompt = f"""
        Dane z obrazka: {image_data}
        Akapit z pracy: {paragraph}
        
        Przeanalizuj, czy dane w akapicie zgadzają się z obrazkiem.
        Zwróć wynik w JSON. Klawisze: "poprawnosc_danych" (jako string "True" lub "False") oraz "bledy" (jako string "None" lub cytaty błędnych zdań).
        """
        
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
            return {"poprawnosc_danych": "False", "bledy": "Błąd parsowania wymuszonego JSONa z modelu."}