import logging

from analysis.modules.llm.image_analysis.figures import collect_figures, image_text
from analysis.modules.llm.image_analysis.vision_engine import VisionEngine

logger = logging.getLogger(__name__)


def get_vision_quality_report(doc_obj, mapped_doc, verbose=False, language="pl"):
    images = collect_figures(doc_obj)
    bad_images_report = []
    
    if not images: 
        return bad_images_report
        
    with VisionEngine("Jakość rysunków") as engine:
        for img in images:
            if verbose:
                logger.info(" -> Ocena wizualna rysunku %s...", img["id"])
            try:
                blurry = engine.is_blurry(img["bytes"])
            except Exception:
                logger.exception("Image quality assessment inference failed")
                bad_images_report.append({"rysunek": img["id"], "analysis_failed": True})
                continue
            if blurry:
                bad_images_report.append({"rysunek": img["id"], "blad_wizyjny": image_text(language, "blurry")})

    return bad_images_report