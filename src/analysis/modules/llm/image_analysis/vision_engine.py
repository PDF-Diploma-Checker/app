"""The vision model of the figure analysis: reads charts and answers yes/no questions about an image."""

import base64
import io
import logging

from llama_cpp.llama_chat_format import Qwen25VLChatHandler
from PIL import Image

from analysis.modules.llm import config
from analysis.modules.llm.llama_factory import make_llama

logger = logging.getLogger(__name__)

# The model answers these best in English, also for a Polish chart; the labels stay as printed in the image.
READ_PROMPT = (
    "Read this chart. Write its title, then one line for each bar or point in the form 'label: value', "
    "exactly as printed in the image. Do not add anything else."
)
READ_MAX_TOKENS = 512
YES_NO_MAX_TOKENS = 6
ALL_NUMBERS_PROMPT = "List all numbers printed anywhere in this image, separated by semicolons. If there are none, answer NONE."
PRINTED_MAX_TOKENS = 120
LIST_MAX_TOKENS = 60
MIN_READABLE_PIXELS = 150       # a shorter side below this holds no readable text, whatever the model says about it


def too_small_to_read(image_bytes):
    with Image.open(io.BytesIO(image_bytes)) as image:
        return min(image.size) < MIN_READABLE_PIXELS


class VisionEngine:
    """Use it in a `with` block: the model and its projector take gigabytes of video memory until they are closed."""

    def __init__(self, purpose, model_path=None, mmproj_path=None):
        model_path = model_path or str(config.VISION_MODEL_PATH)
        mmproj_path = mmproj_path or str(config.VISION_MMPROJ_PATH)
        logger.info("%s: loading the vision model from %s", purpose, model_path)
        self.chat_handler = None
        self.llm = None
        try:
            self.chat_handler = Qwen25VLChatHandler(clip_model_path=mmproj_path, verbose=False)
            self.llm = make_llama(
                purpose=purpose,
                model_path=model_path,
                chat_handler=self.chat_handler,
                n_ctx=4096,
                n_gpu_layers=config.N_GPU_LAYERS,
                verbose=False,
            )
        except Exception as e:
            self.close()
            logger.exception("Failed to load the vision model from %s", model_path)
            raise RuntimeError(f"Failed to load the vision model from {model_path}") from e

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """Free the video memory. The handler has no destructor: without this its projector stays there for good."""
        if self.llm is not None:
            self.llm.close()
            self.llm = None
        if self.chat_handler is not None:
            self.chat_handler._exit_stack.close()
            self.chat_handler = None

    def _ask(self, image_bytes, prompt, max_tokens):
        data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode("utf-8")
        response = self.llm.create_chat_completion(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return (response["choices"][0]["message"]["content"] or "").strip()

    def read_chart(self, image_bytes):
        """The title and the values of a chart as plain text."""
        return self._ask(image_bytes, READ_PROMPT, READ_MAX_TOKENS)

    def ask_yes_no(self, image_bytes, question):
        """The raw answer to a yes/no question."""
        return self._ask(image_bytes, f"{question} Answer YES or NO.", YES_NO_MAX_TOKENS)

    def list_numbers(self, image_bytes, prompt):
        """The raw answer to a request for the numbers in an image."""
        return self._ask(image_bytes, prompt, LIST_MAX_TOKENS)

    def printed_numbers(self, image_bytes):
        """The numbers really printed in the image, as floats."""
        from analysis.modules.llm.image_analysis.figures import parse_axis_numbers

        return parse_axis_numbers(self._ask(image_bytes, ALL_NUMBERS_PROMPT, PRINTED_MAX_TOKENS))

    def is_blurry(self, image_bytes):
        """True/False, or None when the answer was neither."""
        from analysis.modules.llm.image_analysis.figures import parse_yes_no

        return parse_yes_no(self.ask_yes_no(image_bytes, "Is this image blurry or pixelated?"))
