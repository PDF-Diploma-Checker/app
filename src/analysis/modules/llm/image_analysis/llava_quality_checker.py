import sys
import gc
import base64
import logging
from pathlib import Path
from llama_cpp.llama_chat_format import Llava15ChatHandler

current_dir = Path(__file__).resolve().parent
sys.path.append(str(current_dir.parent))
sys.path.append(str(current_dir.parents[3]))
from analysis.modules.llm import config
from analysis.modules.llm.image_analysis.figures import collect_figures
from analysis.modules.llm.llama_factory import make_llama

logger = logging.getLogger(__name__)


class LlavaQualityEngine:
    def __init__(self, model_path=None, mmproj_path=None):
        model_path = model_path or str(config.LLAVA_MODEL_PATH)
        mmproj_path = mmproj_path or str(config.LLAVA_MMPROJ_PATH)
        logger.info("Loading quality-assessment LLaVA model from %s", model_path)
        try:
            self.chat_handler = Llava15ChatHandler(clip_model_path=mmproj_path)
            self.llm = make_llama(
                purpose="Jakość rysunków",
                model_path=model_path,
                chat_handler=self.chat_handler,
                n_ctx=4096,
                n_gpu_layers=config.N_GPU_LAYERS,
                logits_all=True,
                verbose=False
            )
        except Exception as e:
            logger.exception("Failed to load quality-assessment LLaVA model from %s", model_path)
            raise RuntimeError(f"Failed to load quality-assessment LLaVA model from {model_path}") from e

    def assess_quality(self, image_bytes):
        base64_img = base64.b64encode(image_bytes).decode('utf-8')
        data_uri = f"data:image/jpeg;base64,{base64_img}"
        

        prompt = "Analyze the quality of this image. Is the text clear and readable? Is the image sharp? Answer ONLY 'YES' if it is good quality and readable. Answer ONLY 'NO' if it is blurry, pixelated, or unreadable. Do not explain."
        
        try:
            response = self.llm.create_chat_completion(
                messages=[{
                    "role": "user", 
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}}, 
                        {"type": "text", "text": prompt}
                    ]
                }],
                temperature=0.0,
                max_tokens=15 
            )
            
            result_text = response["choices"][0]["message"]["content"].strip().lower()
            
            if "yes" in result_text:
                return {"czytelny": True, "powod": "OK"}
            elif "no" in result_text:
                return {"czytelny": False, "powod": "Model LLaVA uznał, że obraz jest niewyraźny lub rozmazany."}
            else:
            
                return {"czytelny": True, "powod": "OK"}
                
        except Exception as e:
            logger.exception("Image quality assessment inference failed")
            return {"czytelny": False, "powod": f"Błąd weryfikacji wizualnej AI: {str(e)}"}

def get_llava_quality_report(doc_obj, mapped_doc, verbose=False):
    images = collect_figures(doc_obj)
    bad_images_report = []
    
    if not images: 
        return bad_images_report
        
    if verbose: 
        logger.info("[AI] Ladowanie modelu do oceny wizualnej...")
        
    llava = LlavaQualityEngine()
    
    for img in images:
        if verbose: 
            logger.info(f" -> LLaVA ocenia Rysunek {img['id']}...")
            
        assessment = llava.assess_quality(img["bytes"])
        czytelny = assessment.get("czytelny", True)
        
        if str(czytelny).lower() == "false":
            bad_images_report.append({
                "rysunek": img["id"], 
                "blad_llava": assessment.get("powod", "Obraz nieczytelny.")
            })
            
    if verbose: 
        logger.info("[AI] Zwalnianie VRAM.")
        
    del llava
    gc.collect()
    
    return bad_images_report