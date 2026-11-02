import json
import gc
import logging

from analysis.modules.llm import config
from analysis.modules.llm.image_analysis.figures import collect_figures, is_caption
from analysis.modules.llm.image_analysis.llava_engine import LlavaEngine
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


def _failed_entry(image_id):
    """Report entry of a figure the models could not process: not a thesis error, so it is marked separately."""
    return {"obrazek": image_id, "odwolanie": "wystapilo", "poprawnosc_danych": "Error", "bledy": "Analiza nie powiodła się."}


def analyze_images(doc_obj, mapped_doc, verbose=False):
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
                "bledy": ["Brak prawdziwego odwołania omawiającego rysunek w tekście pracy (znaleziono jedynie podpis)."]
            })
        else:
            images_with_refs.append({"id": img["id"], "bytes": img["bytes"], "refs": refs})

    if not images_with_refs:
        return final_report

    if verbose:
        logger.info(f"\n[AI] Ładowanie modelu wizyjnego LLaVA do VRAM...")

    logger.info("Loading LLaVA vision model for image analysis (%d images)", len(images_with_refs))
    llava = LlavaEngine()
    extracted_image_data = {}
    
    for idx, img in enumerate(images_with_refs, 1):
        if verbose:
            logger.info(f"[{idx}/{len(images_with_refs)}] LLaVA analizuje obrazek {img['id']}...")
        try:
            extracted_image_data[img["id"]] = llava.extract_data(img["bytes"])
        except Exception:
            # one unreadable figure must not cost the results of all the others
            logger.exception("LLaVA could not read figure %s", img["id"])
            final_report.append(_failed_entry(img["id"]))

    if verbose:
        logger.info(f"\n[AI] Koniec pracy LLaVA. Zwalniam VRAM karty graficznej...")
        
    del llava
    gc.collect() 

    if verbose:
        logger.info(f"\n[AI] Ładowanie Sędziego (Gemma) do VRAM...")
        
    checker = ConsistencyChecker()
    
    for img in images_with_refs:
        if img["id"] not in extracted_image_data:
            continue
        img_data_text = extracted_image_data[img["id"]]
        for ref_para in img["refs"]:
            if verbose:
                logger.info(f" -> Sędzia ocenia akapit dla rysunku {img['id']}...")

            try:
                verification = checker.check(ref_para, img_data_text)
            except Exception:
                logger.exception("Consistency check failed for figure %s", img["id"])
                final_report.append(_failed_entry(img["id"]))
                continue

            final_report.append({
                "obrazek": img["id"],
                "odwolanie": "wystapilo",
                "poprawnosc_danych": verification.get("poprawnosc_danych", "False"),
                "bledy": verification.get("bledy", "None")
            })

    # Zwalniamy model sędziego po analizie, aby nie blokował VRAM dla kolejnych etapów.
    del checker
    gc.collect()

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