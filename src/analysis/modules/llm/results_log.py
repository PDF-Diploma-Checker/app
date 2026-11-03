"""Log entries with the results of the content analysis and the calculation of the grade."""

import logging

logger = logging.getLogger(__name__)


def log_results(heading, /, **fields):
    """One log record with the named results of an analysis stage."""
    lines = [f"[RESULTS] {heading}"]
    lines += [f"{name}: {value}" for name, value in fields.items()]
    logger.info("\n".join(lines))


def log_grade_calculation(parts, overall):
    """parts: (name, score, weight) of every grade component; shows how the final grade was calculated."""
    lines = ["[GRADE] Overall grade calculation"]
    for name, score, weight in parts:
        lines.append(f"{name}: {score} x {weight} = {float(score) * weight:.2f}")
    lines.append(f"Overall grade: {overall:.2f} / 100")
    logger.info("\n".join(lines))


def log_embedding_results(purpose, items, threshold, average_similarity, grade):
    """Write everything in one log record, so the other analysis thread cannot break it up."""
    off_topic = sum(1 for item in items if item.get("below_threshold"))
    lines = [
        "[EMBEDDINGS] Purpose vs section summaries",
        f"Thesis purpose: {purpose or '(none)'}",
        f"Threshold: {threshold:.4f} | average similarity: {average_similarity:.4f} | "
        f"off-topic sections: {off_topic}/{len(items)} | embedding grade: {grade:.2f}",
    ]
    for number, item in enumerate(items, 1):
        status = "OFF-TOPIC" if item.get("below_threshold") else "ok"
        heading = item.get("display") or item.get("heading") or f"Section {number}"
        lines.append(f"{number}. [{float(item.get('cosine_similarity', 0.0)):.4f} {status}] {heading}")
        lines.append(f"   Summary: {item.get('summary') or '(none)'}")
    logger.info("\n".join(lines))
