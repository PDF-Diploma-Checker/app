import sys
import json
import logging
from pathlib import Path

current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir.parent))
sys.path.append(str(current_dir.parents[3]))

from analysis.modules.llm.image_analysis.figures import collect_figures, image_text, parse_yes_no
from analysis.modules.llm.image_analysis.vision_engine import VisionEngine

logger = logging.getLogger(__name__)


FONT_QUESTION = "Is any text in this image much bigger or much smaller than the other labels?"


def get_font_consistency_report(doc_obj, mapped_doc, verbose=False, language="pl"):
    """Return a report of figures with inconsistent font sizing."""
    images = collect_figures(doc_obj)
    bad_fonts_report = []

    if not images:
        return bad_fonts_report

    with VisionEngine("Czcionki na rysunkach") as engine:
        for idx, img in enumerate(images, 1):
            if verbose:
                logger.info("[%d/%d] Weryfikacja czcionek rysunku %s...", idx, len(images), img["id"])
            try:
                inconsistent = parse_yes_no(engine.ask_yes_no(img["bytes"], FONT_QUESTION))
            except Exception:
                logger.exception("Font consistency check inference failed")
                bad_fonts_report.append({"rysunek": img["id"], "analysis_failed": True})
                continue
            if inconsistent is None:    # not checked is something else than checked and fine
                logger.warning("No clear font answer for figure %s", img["id"])
                bad_fonts_report.append({"rysunek": img["id"], "analysis_failed": True})
                continue
            if inconsistent:
                bad_fonts_report.append({
                    "rysunek": img["id"],
                    "blad": image_text(language, "fonts_inconsistent"),
                })

    return bad_fonts_report


if __name__ == "__main__":
    import time
    from analysis.modules.llm.config import THESIS_PATH
    from analysis.extraction.main_extractor import extractPDF
    from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
    
    logger.info("MODUŁ: SPÓJNOŚĆ CZCIONEK NA OBRAZKACH")
    
    start_time = time.time()
    
    doc_obj = extractPDF(str(THESIS_PATH))
    mapped_doc = PDFMapper().map_to_schema(doc_obj)
    
    raport_czcionek = get_font_consistency_report(doc_obj, mapped_doc, verbose=True)
    
    end_time = time.time()
    logger.info(f"CZAS WYKONANIA: {int(end_time - start_time)} sek.")
    logger.info("--- RAPORT NIESPÓJNYCH CZCIONEK ---")
    if not raport_czcionek:
        logger.info(json.dumps({"status": "Wszystkie obrazki mają piękne i spójne czcionki!"}, indent=4, ensure_ascii=False))
    else:
        logger.info(json.dumps(raport_czcionek, indent=4, ensure_ascii=False))