import sys
import os
import logging
from pathlib import Path

current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir.parent))
sys.path.append(str(current_dir.parents[3]))

from .figures import figure_sort_key, image_text
from .quality_analysis import check_image_quality
from .vision_quality_checker import get_vision_quality_report

logger = logging.getLogger(__name__)

def _dpi_reason(item, language):
    reason = f"[DPI]: {item.get('blad')}"
    density = item.get("zageszczenie_pikseli")
    return f"{reason} ({image_text(language, 'score')}: {density})" if density else reason


def get_full_image_quality_json(doc_obj, mapped_doc, pdf_path, verbose=False, language="pl"):
    """
    Czysta funkcja do użycia w Twoim głównym pipeline.
    Zwraca ostateczny raport jako listę słowników (JSON).
    """
    if verbose: logger.info("[1/2] Test matematyczny DPI (próg 75)...")
    dpi_report = check_image_quality(doc_obj, str(pdf_path), dpi_threshold=75, language=language)
    
    if verbose: logger.info("[2/2] Test wizualny (czytelność)...")
    vision_report = get_vision_quality_report(doc_obj, mapped_doc, verbose=verbose, language=language)
    
    merged_results = {}
    
    for item in dpi_report:
        rys = item["rysunek"]
        merged_results[rys] = {
            "rysunek": rys,
            "format": item.get("format", image_text(language, "unknown")),
            "powody_odrzucenia": [_dpi_reason(item, language)]
        }
        
    failed_checks = []
    for item in vision_report:
        if item.get("analysis_failed"):
            failed_checks.append(item)
            continue
        rys = item["rysunek"]
        blad_ai = f"[AI]: {item.get('blad_wizyjny')}"
        
        if rys in merged_results:

            merged_results[rys]["powody_odrzucenia"].append(blad_ai)
        else:
        
            merged_results[rys] = {
                "rysunek": rys,
                "format": image_text(language, "from_pdf"),
                "powody_odrzucenia": [blad_ai]
            }
            
    final_list = list(merged_results.values())
    
    final_list.sort(key=lambda x: figure_sort_key(x["rysunek"]))

    return final_list + failed_checks

if __name__ == "__main__":
    
    import json
    from analysis.modules.llm.config import THESIS_PATH
    from analysis.extraction.main_extractor import extractPDF
    from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
    
    logger.info("Rozpoczynam ekstrakcję do testu scalania...")
    doc_obj = extractPDF(str(THESIS_PATH))
    mapped_doc = PDFMapper().map_to_schema(doc_obj)
    
    final_report = get_full_image_quality_json(doc_obj, mapped_doc, THESIS_PATH, verbose=True)
    
    logger.info("\n--- OSTATECZNY JSON DLA PIPELINE ---")
    logger.info(json.dumps(final_report, indent=4, ensure_ascii=False))

# PRZYKŁADOWY OUTPUT GDY ZNAJDZIE BŁĄD, GDY NIE MA BLĘDÓW FUNKCJA ZWRACA PUSTĄ LISTE
#     [
#     {
#         "rysunek": "Rys. 1",
#         "format": "PNG",
#         "powody_odrzucenia": [
#             "[DPI]: Obraz został nadmiernie rozciągnięty, co spowodowało widoczną 'pikselozę'. (Wynik: ~42 DPI)"
#         ]
#     },
#     {
#         "rysunek": "Rys. 2.1",
#         "format": "Wyciągnięto z PDF",
#         "powody_odrzucenia": [
#             "[AI]: Model wizyjny uznał, że obraz jest niewyraźny lub rozmazany."
#         ]
#     },
#     {
#         "rysunek": "Rys. 3",
#         "format": "JPG",
#         "powody_odrzucenia": [
#             "[DPI]: Obraz został nadmiernie rozciągnięty, co spowodowało widoczną 'pikselozę'. (Wynik: ~30 DPI)",
#             "[AI]: Model wizyjny uznał, że obraz jest niewyraźny lub rozmazany."
#         ]
#     }
# ]