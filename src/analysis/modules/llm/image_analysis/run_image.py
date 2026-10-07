import json
import re
import gc
import logging
from pathlib import Path

from analysis.modules.llm import config
from analysis.modules.llm.image_analysis.llava_engine import LlavaEngine
from analysis.modules.llm.image_analysis.reference_matcher import ReferenceMatcher
from analysis.modules.llm.image_analysis.consistency_checker import ConsistencyChecker

logger = logging.getLogger(__name__)


def adapt_data_for_images(doc_obj, mapped_doc):
    """Extract clean paragraphs and deduplicated image payloads for image analysis."""
    paragraphs = []
    
    for block in mapped_doc.logical_blocks:
        text = getattr(block, "content", "").strip()
        if text:
            paragraphs.append(text)
            
    caption_pattern = re.compile(r"(?i)rys(?:unek|\.)?\s*(\d+(?:\.\d+)?)")
    unique_images = {}
    
    for page in doc_obj.pages:
        for img in page.images:
            desc = getattr(img, "description", "")
            if desc:
                match = caption_pattern.search(desc)
                if match:
                    found_id = match.group(1)
                    
                    if found_id not in unique_images:
                        unique_images[found_id] = {"desc": desc, "bytes": None}
                        img_path = Path(img.path)
                        if img_path.exists():
                            try:
                                with open(img_path, "rb") as f:
                                    unique_images[found_id]["bytes"] = f.read()
                            except OSError:
                                logger.exception("Failed to read image file %s", img_path)
                    else:
                        old_desc = unique_images[found_id]["desc"]
                        if not re.match(r"(?i)^rys", old_desc.strip()) and re.match(r"(?i)^rys", desc.strip()):
                            unique_images[found_id]["desc"] = desc
                            img_path = Path(img.path)
                            if img_path.exists():
                                try:
                                    with open(img_path, "rb") as f:
                                        unique_images[found_id]["bytes"] = f.read()
                                except OSError:
                                    logger.exception("Failed to read image file %s", img_path)
                        
    images = [{"id": img_id, "bytes": data["bytes"]} for img_id, data in unique_images.items() if data["bytes"] is not None]
    
    return paragraphs, images

def analyze_images(doc_obj, mapped_doc, verbose=False):
    """Analyze image references and verify paragraph-to-image consistency."""
    matcher = ReferenceMatcher()
    paragraphs, images = adapt_data_for_images(doc_obj, mapped_doc)
    
    images_with_refs = []
    final_report = []

    for img in images:
        raw_refs = matcher.find_references(paragraphs, img["id"])
        refs = []
        for r in raw_refs:
            if re.match(rf"(?i)^rys(?:unek|\.)?\s*{re.escape(str(img['id']))}\s*[:\.\-]", r.strip()):
                continue
            if len(r.strip()) < 50 and "rys" in r.lower():
                continue
            refs.append(r)

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
        extracted_image_data[img["id"]] = llava.extract_data(img["bytes"])
  
    if verbose:
        logger.info(f"\n[AI] Koniec pracy LLaVA. Zwalniam VRAM karty graficznej...")
        
    del llava
    gc.collect() 

    if verbose:
        logger.info(f"\n[AI] Ładowanie Sędziego (Gemma) do VRAM...")
        
    checker = ConsistencyChecker()
    
    for img in images_with_refs:
        img_data_text = extracted_image_data[img["id"]]
        for ref_para in img["refs"]:
            if verbose:
                logger.info(f" -> Sędzia ocenia akapit dla rysunku {img['id']}...")
                
            verification = checker.check(ref_para, img_data_text)
            
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