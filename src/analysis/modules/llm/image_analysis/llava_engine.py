from llama_cpp import Llama
from llama_cpp.llama_chat_format import Llava15ChatHandler
import base64
import time
import logging
from analysis.modules.llm import config

logger = logging.getLogger(__name__)


class LlavaEngine:
    def __init__(self, model_path=str(config.LLAVA_MODEL_PATH), mmproj_path=str(config.LLAVA_MMPROJ_PATH)):
        logger.debug("[LLaVA][INIT] start")
        logger.debug("[LLaVA][INIT] model_path=%s", model_path)
        logger.debug("[LLaVA][INIT] mmproj_path=%s", mmproj_path)
        logger.debug("[LLaVA][INIT] n_gpu_layers=%s", config.N_GPU_LAYERS)
        init_start = time.perf_counter()

        try:
            self.chat_handler = Llava15ChatHandler(clip_model_path=mmproj_path)
            self.llm = Llama(
                model_path=model_path,
                chat_handler=self.chat_handler,
                n_ctx=4096,
                n_gpu_layers=config.N_GPU_LAYERS,
                logits_all=True,
                verbose=False
            )
        except Exception as e:
            logger.exception("Failed to load LLaVA engine from %s", model_path)
            raise RuntimeError(f"Failed to load LLaVA engine from {model_path}") from e

        self.max_tokens = 256

        init_elapsed = time.perf_counter() - init_start
        logger.info("[LLaVA][INIT] done elapsed=%.2fs max_tokens=%s", init_elapsed, self.max_tokens)

    def extract_data(self, image_bytes):
        logger.debug("[LLaVA][EXTRACT] start image_bytes=%d max_tokens=%s", len(image_bytes), self.max_tokens)
        extract_start = time.perf_counter()

        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        data_uri = f"data:image/jpeg;base64,{base64_image}"

        logger.debug("[LLaVA][EXTRACT] base64_length=%d", len(base64_image))

        try:
            response = self.llm.create_chat_completion(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {"type": "text", "text": "Wyciągnij wszystkie etykiety, liczby i dane z tego wykresu/obrazka. Zwróć je jako surowe dane tekstowe."}
                        ]
                    }
                ],
                max_tokens=self.max_tokens
            )
        except Exception as e:
            logger.exception("LLaVA data extraction inference failed")
            raise RuntimeError("LLaVA data extraction inference failed") from e

        extract_elapsed = time.perf_counter() - extract_start
        logger.debug("[LLaVA][EXTRACT] create_chat_completion done elapsed=%.2fs", extract_elapsed)

        content = response["choices"][0]["message"]["content"]

        usage = response.get("usage")
        if usage is not None:
            logger.debug("[LLaVA][EXTRACT] usage=%s", usage)

        logger.debug("[LLaVA][EXTRACT] done output_length=%d", len(content) if content else 0)

        return content