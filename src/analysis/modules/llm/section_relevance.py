"""Second opinion on the sections the embeddings find doubtful: is this section needed for the purpose of the thesis?

Embeddings only see the subject area, so a section about a neighbouring subject scores as high as a real section of the
thesis. The text model reads the purpose, the titles of all sections and the summary of the doubtful one.
"""

import json
import logging

from analysis.modules.llm import config
from analysis.modules.llm.llama_factory import make_llama
from common import run_control

logger = logging.getLogger(__name__)

MAX_ANSWER_TOKENS = 120
N_CTX = 4096
MAX_TITLES_CHARS = 3000

_PROMPTS = {
    "pl": """Cel pracy dyplomowej: {purpose}

Tytuły podrozdziałów tej pracy:
{titles}

Oceniany podrozdział: {title}
Jego treść w skrócie: {summary}

Czy ten podrozdział jest związany z tematem pracy? Związany jest też podrozdział opisujący teorię, metody, narzędzia, dane lub wyniki potrzebne do osiągnięcia celu pracy. Niezwiązany jest podrozdział o zagadnieniu, które nie jest potrzebne do osiągnięcia celu i nie łączy się z pozostałymi podrozdziałami.
Zwróć JSON z kluczami "uzasadnienie" (jedno zdanie) i "zwiazany" (true albo false).""",
    "en": """Purpose of the thesis: {purpose}

Titles of the sections of this thesis:
{titles}

Section under review: {title}
Its content in short: {summary}

Is this section related to the topic of the thesis? A section describing theory, methods, tools, data or results needed to achieve the purpose is related too. A section about a matter that is not needed to achieve the purpose and does not connect with the other sections is not related.
Return JSON with the keys "uzasadnienie" (one sentence, in English) and "zwiazany" (true or false).""",
}


def _is_related(answer):
    """True/False from the model's answer, None when it gave neither."""
    value = answer.get("zwiazany") if isinstance(answer, dict) else None
    if isinstance(value, str):
        value = {"true": True, "false": False}.get(value.strip().lower())
    return value if isinstance(value, bool) else None


def review_sections(purpose, titles, sections, language="pl"):
    """Set "off_topic_reason" on the sections the model finds unrelated; returns those sections.

    A section the model gives no clear answer about stays on topic: a failure must not lower the grade of the thesis.
    """
    if not sections:
        return []

    template = _PROMPTS.get(language, _PROMPTS["pl"])
    title_list = "\n".join(titles)[:MAX_TITLES_CHARS]
    llm = make_llama(
        purpose="Trafność podrozdziałów",
        model_path=str(config.MODEL_PATH),
        n_ctx=N_CTX,
        n_gpu_layers=config.N_GPU_LAYERS,
        verbose=False,
    )
    unrelated = []
    try:
        for section in sections:
            run_control.check_cancelled()
            prompt = (template.replace("{purpose}", purpose).replace("{titles}", title_list)
                      .replace("{title}", section["title"]).replace("{summary}", section["summary"]))
            try:
                response = llm.create_chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=MAX_ANSWER_TOKENS,
                )
                answer = json.loads(response["choices"][0]["message"]["content"])
            except run_control.AnalysisCancelled:
                raise
            except Exception:
                logger.exception("Section review failed for %r", section["title"])
                continue
            if _is_related(answer) is False:
                section["off_topic_reason"] = str(answer.get("uzasadnienie") or "")
                unrelated.append(section)
    finally:
        llm.close()
    return unrelated
