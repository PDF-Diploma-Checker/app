"""Compute thesis-related grading signals based on summaries and purpose alignment."""

import sys
import os
import time
import logging

_src_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
for _p in (os.path.dirname(_src_dir), _src_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)


from analysis.extraction.helper_llm.extraction_json_llm import extractPDF_llm
from analysis.extraction.helper_llm.converter_linguistics_llm import get_plain_text

from analysis.modules.llm.get_purpose import get_purpose
from analysis.modules.llm.get_subtitles import get_subtitles
from analysis.modules.llm.get_summary import get_summaries
from analysis.modules.llm.results_log import log_embedding_results, log_grade_calculation
from analysis.modules.llm.similarity import compute_similarity_for_summaries
from analysis.modules.llm.goal_realization import get_purpose_grade
from analysis.modules.llm.config import EMBEDDING_MODEL, THESIS_PATH, LANGUAGE

logger = logging.getLogger(__name__)

# Calibrated for paraphrase-multilingual-MiniLM-L12-v2 on real theses: sections of a thesis stay above 0.30 when compared
# with the rest of that thesis, unrelated text stays below 0.20. A different embedding model needs its own value.
threshold = 0.25

SOTA_WEIGHT = 0.2
PURPOSE_WEIGHT = 0.2
EMBEDDING_WEIGHT = 0.6


def calculate_embedding_grade(purpose, summaries):
    """Compute an embedding-based grade and per-section off-topic flags."""

    similarity_result = compute_similarity_for_summaries(
        purpose=purpose,
        summaries=summaries,
        embedding_model=EMBEDDING_MODEL,
    )

    # a section without text says nothing about the topic
    items = [item for item in similarity_result.get("items", []) if item.get("has_content", True)]
    total_sections = len(items)

    if total_sections == 0:
        log_embedding_results(purpose, items, threshold, 0.0, None)
        return {
            "grade": None,
            "max_grade": 100.0,
            "s_emb": None,
            "threshold": threshold,
            "total_sections": 0,
            "off_topic_sections": 0,
            "p_off": 0.0,
            "items": [],
        }

    off_topic_sections = 0

    for item in items:
        # off-topic only when the section fits neither the purpose nor the rest of the thesis
        best_similarity = max(float(item.get("cosine_similarity", 0.0)), float(item.get("section_similarity", 0.0)))
        below_threshold = best_similarity < threshold
        item["below_threshold"] = below_threshold

        if below_threshold:
            off_topic_sections += 1

    p_off = (off_topic_sections / total_sections) * 100.0
    s_emb = 100.0 - p_off
    grade = s_emb

    log_embedding_results(purpose, items, threshold, similarity_result.get("average_similarity", 0.0), grade)

    return {
        "grade": round(grade, 2),
        "max_grade": 100.0,
        "s_emb": s_emb,
        "threshold": threshold,
        "total_sections": total_sections,
        "off_topic_sections": off_topic_sections,
        "p_off": p_off,
        "items": items,
    }


def get_content_grade(purpose, summaries):
    """Return overall embedding grade and labels of off-topic sections."""

    embedding_result = calculate_embedding_grade(
        purpose=purpose,
        summaries=summaries
    )
    
    grade = embedding_result.get("grade")
    items = embedding_result.get("items", [])
    
    # Extract off-topic heading labels (items below threshold)
    off_topic_headings = [
        (
            item.get("display")
            or item.get("heading")
            or item.get("title")
            or item.get("subtitle")
            or f"Section {idx + 1}"
        )
        for idx, item in enumerate(items)
        if item.get("below_threshold", False)
    ]
    
    # Return (grade, off_topic_heading_labels)
    return (grade, off_topic_headings)

def get_overall_grade(purpose_grade, embedding_grade, sota_grade):
    """Combine partial scores into the final weighted grade. A score that could not be computed (None: a thesis
    without numbered sections) is left out and the weights of the others are scaled up, it does not count as 0."""

    parts = [("SOTA", sota_grade, SOTA_WEIGHT), ("Purpose realization", purpose_grade, PURPOSE_WEIGHT),
             ("Embeddings", embedding_grade, EMBEDDING_WEIGHT)]
    known = [part for part in parts if part[1] is not None]
    total_weight = sum(weight for _, _, weight in known)
    scaled = [(name, grade, weight / total_weight) for name, grade, weight in known]
    overall_grade = sum(grade * weight for _, grade, weight in scaled)
    log_grade_calculation(scaled, overall_grade)
    return overall_grade


def main():
    """Run the full grading pipeline for the configured thesis PDF."""

    pdf_path = THESIS_PATH
    language = LANGUAGE

    logger.info(f"PDF_PATH: {pdf_path}")
    logger.info(f"PDF_EXISTS: {pdf_path.exists()}")
    logger.info(f"PDF_ABSOLUTE: {pdf_path.resolve()}")

    if not pdf_path.exists():
        logger.error("PDF file does not exist: %s", pdf_path)
        logger.info(f"Error: file does not exist: {pdf_path}")
        return

    raw_doc = extractPDF_llm(str(pdf_path.resolve()))

    if raw_doc is None:
        logger.error("extractPDF_llm returned None for %s", pdf_path)
        logger.info("Error: extractPDF_llm returned None.")
        return

    plain_text = get_plain_text(pdf_path)

    purpose = get_purpose(plain_text, LANGUAGE)

    subtitles = get_subtitles(raw_doc)
    summaries = get_summaries(subtitles, LANGUAGE)

    grade, off_topic_headings = get_content_grade(
        purpose=purpose,
        summaries=summaries
    )

    purpose_score, purpose_reason = get_purpose_grade(plain_text, purpose, LANGUAGE)

    logger.info("THESIS PURPOSE:")
    logger.info(purpose)
    logger.info("")
    logger.info("EMBEDDING SCORE:")
    logger.info(f"Score: {grade}")
    logger.info(f"PURPOSE REALIZATION SCORE: {purpose_score} - {purpose_reason}")
    logger.info(f"Off-topic headings indices: {off_topic_headings}")



if __name__ == "__main__":
    start = time.perf_counter()
    main()
    end = time.perf_counter()
    logger.info(f"Program runtime: {end - start:.2f} s")