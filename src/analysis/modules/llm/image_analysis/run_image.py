import json
import logging

from analysis.modules.llm import config
from analysis.modules.llm.image_analysis.figures import collect_figures, consistency_verdict, image_text, is_caption
from analysis.modules.llm.image_analysis.vision_engine import VisionEngine, too_small_to_read
from analysis.modules.llm.image_analysis.reference_matcher import ReferenceMatcher
from analysis.modules.llm.image_analysis.consistency_checker import ConsistencyChecker

logger = logging.getLogger(__name__)


def adapt_data_for_images(doc_obj, mapped_doc):
    """Extract clean paragraphs and deduplicated figures for image analysis."""
    paragraphs = []

    for block in mapped_doc.logical_blocks:
        text = getattr(block, "content", "").strip()
        if text:
            paragraphs.append(text)

    return paragraphs, collect_figures(doc_obj)


def _failed_entry(image_id, language):
    """Report entry of a figure the models could not process: not a thesis error, so it is marked separately."""
    return {"obrazek": image_id, "odwolanie": "wystapilo", "poprawnosc_danych": "Error", "bledy": image_text(language, "analysis_failed")}


def _unreadable_entry(image_id, language):
    """A figure too unclear to compare: nothing went wrong with the models and nothing is proved against the text."""
    return {"obrazek": image_id, "odwolanie": "wystapilo", "poprawnosc_danych": "Unreadable", "bledy": image_text(language, "unreadable_figure")}


def analyze_images(doc_obj, mapped_doc, verbose=False, language="pl"):
    """Analyze image references and verify paragraph-to-image consistency."""
    matcher = ReferenceMatcher()
    paragraphs, images = adapt_data_for_images(doc_obj, mapped_doc)
    
    images_with_refs = []
    final_report = []

    for img in images:
        raw_refs = matcher.find_references(paragraphs, img["number"], img["family"])
        refs = [r for r in raw_refs if not is_caption(r, img["number"], img["family"])]

        if not refs:
            final_report.append({
                "obrazek": img["id"],
                "odwolanie": "brak",
                "poprawnosc_danych": "False",
                "bledy": [image_text(language, "no_reference")]
            })
        else:
            images_with_refs.append({"id": img["id"], "bytes": img["bytes"], "refs": refs})

    if not images_with_refs:
        return final_report

    logger.info("Loading the vision model for image analysis (%d images)", len(images_with_refs))
    extracted_image_data = {}

    with VisionEngine("Analiza obrazów") as engine:
        for idx, img in enumerate(images_with_refs, 1):
            if verbose:
                logger.info("[%d/%d] Odczyt rysunku %s...", idx, len(images_with_refs), img["id"])
            try:
                # a model reading an unclear image makes up plausible values: such a figure is not compared at all
                if too_small_to_read(img["bytes"]) or engine.is_blurry(img["bytes"]):
                    final_report.append(_unreadable_entry(img["id"], language))
                    continue
                image_data = engine.read_chart(img["bytes"])
                if not image_data:
                    raise ValueError("The vision model returned no data")
                extracted_image_data[img["id"]] = image_data
            except Exception:
                # one unreadable figure must not cost the results of all the others
                logger.exception("Could not read figure %s", img["id"])
                final_report.append(_failed_entry(img["id"], language))

    if not extracted_image_data:
        return final_report

    if verbose:
        logger.info("[AI] Ładowanie modelu sprawdzającego spójność (Gemma) do VRAM...")

    checker = ConsistencyChecker()
    try:
        for img in images_with_refs:
            if img["id"] not in extracted_image_data:
                continue
            img_data_text = extracted_image_data[img["id"]]
            for ref_para in img["refs"]:
                if verbose:
                    logger.info(" -> Ocena akapitu dla rysunku %s...", img["id"])

                try:
                    verification = checker.check(ref_para, img_data_text, language)
                except Exception:
                    logger.exception("Consistency check failed for figure %s", img["id"])
                    final_report.append(_failed_entry(img["id"], language))
                    continue

                verdict = consistency_verdict(verification)
                if verdict == "Error":
                    logger.error("Unusable consistency verdict for figure %s: %r", img["id"], verification)
                    final_report.append(_failed_entry(img["id"], language))
                    continue

                final_report.append({
                    "obrazek": img["id"],
                    "odwolanie": "wystapilo",
                    "poprawnosc_danych": verdict,
                    "bledy": verification.get("bledy", "None")
                })
    finally:
        checker.close()     # the model must not block the video memory for the next stages

    return final_report

if __name__ == "__main__":
    import time
    
    logger.info("==================================================")
    logger.info("URUCHAMIANIE TESTOWE ZOPTYMALIZOWANEGO RUN_IMAGE")
    logger.info("==================================================")
    logger.info(f"Plik: {config.THESIS_PATH}")
    
    from analysis.extraction.main_extractor import extractPDF
    from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
    
    start_time = time.time()
    
    logger.info("\n[1/3] Trwa główna ekstrakcja z pliku PDF...")
    doc_obj = extractPDF(str(config.THESIS_PATH))
    logger.info("[2/3] Trwa mapowanie lingwistyczne...")
    mapped_doc = PDFMapper().map_to_schema(doc_obj)
    
    logger.info("\n[3/3] Rozpoczynamy analizę obrazów (AI)...")
    
    # Tutaj włączamy verbose=True, aby widzieć logi tylko podczas testów
    raport = analyze_images(doc_obj, mapped_doc, verbose=True)
    
    end_time = time.time()
    elapsed_time = int(end_time - start_time)
    
    logger.info("\n==================================================")
    logger.info("TEST ZAKOŃCZONY SUKCESEM!")
    logger.info("==================================================")
    logger.info(f"Czas wykonania: {elapsed_time // 60} min {elapsed_time % 60} sek.")
    
    logger.info("\n--- RAPORT JSON ---")
    logger.info(json.dumps(raport, indent=4, ensure_ascii=False))