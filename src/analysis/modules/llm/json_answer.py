"""Answers of the text model that must be a JSON object.

JSON mode of llama.cpp (a grammar) makes the sampler check every candidate token against it, and Gemma has a
vocabulary of 262 thousand tokens: with the grammar one answer took 3-4 times longer (4.5 s against 1.4 s for a section
review, measured on Gemma 3 4B), and the GPU stood idle meanwhile. So the model is asked in plain mode (the prompts ask
for a JSON object anyway) and the answer is parsed; only when it cannot be parsed is the question asked again in JSON mode.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```\s*$")


def parse_json_answer(text):
    """The first JSON object in an answer (maybe inside a ``` fence, maybe with words around it), or None."""
    if not text:
        return None
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    start = cleaned.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
        start = cleaned.find("{", start + 1)
    return None


def chat_json(llm, messages, **kwargs):
    """The answer of `llm` as a dict (None when the model gave no JSON object even in JSON mode) and its raw text.
    `kwargs` go to create_chat_completion (temperature, max_tokens, ...)."""
    kwargs.pop("response_format", None)
    response = llm.create_chat_completion(messages=messages, **kwargs)
    text = response["choices"][0]["message"]["content"]
    data = parse_json_answer(text)
    if data is not None:
        return data, text
    logger.info("The answer is not JSON, asking again in JSON mode: %r", (text or "")[:80])
    response = llm.create_chat_completion(messages=messages, response_format={"type": "json_object"}, **kwargs)
    text = response["choices"][0]["message"]["content"]
    return parse_json_answer(text), text
