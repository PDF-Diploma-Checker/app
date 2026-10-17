import concurrent.futures
import importlib
import logging
import os
import threading

from analysis.extraction.service import ExtractionService
from analysis.modules.linguistics.linguistics_service import LinguisticsService
from common.models import FinalReport, ModuleResult

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    def __init__(self):
        self.extraction_service = ExtractionService()
        self.linguistics_service = LinguisticsService()
        self.llm_service = None

    def run(self, input_document, progress_callback=None, use_llm=True, config_path=None, language="pl", check_images=True):
        def report_progress(value, text):
            if progress_callback:
                progress_callback(value, text)

        if input_document is None:
            raise ValueError("Input document was not provided.")

        pdf_path = getattr(input_document, "pdf_path", None)

        if not pdf_path or not os.path.exists(pdf_path):
            raise FileNotFoundError(f"File not found: {pdf_path}")

        report_progress(10, "Starting text extraction from PDF...")

        from analysis.extraction.main_extractor import extractPDF
        from analysis.extraction.raw_extraction.image_extractor import get_raster_figure_numbers

        doc_obj = extractPDF(pdf_path)
        doc_dict = doc_obj._to_dict()

        try:
            raster_figure_numbers = get_raster_figure_numbers(doc_obj)
        except Exception:
            raster_figure_numbers = []

        extraction_result = ModuleResult(
            module_name="extraction",
            status="done",
            comments=["Document extraction completed successfully."],
            details={"page_count": doc_obj.get_page_count()},
        )

        ling_ready_event = threading.Event()

        def task_llm():
            ling_ready_event.wait()
            try:
                from app.llm_task import run_task_llm

                return run_task_llm(
                    doc_obj=doc_obj,
                    pdf_path=pdf_path,
                    language=language,
                    use_llm=use_llm,
                    check_images=check_images,
                )

            except Exception as e:
                logger.error(f"[PIPELINE] LLM script execution error: {e}", exc_info=True)
                return None, None, "LLM analysis error."

        def task_linguistics():
            try:
                import language_tool_python  # noqa: F401  (warm up before the LLM thread starts)
            except Exception as e:
                logger.warning(f"[PIPELINE] Warning during LanguageTool startup: {e}")
            finally:
                ling_ready_event.set()

            try:
                from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper

                mapper = PDFMapper()

                # Regular import so PyInstaller can see run_linguistics and everything it imports.
                ling_module = importlib.import_module("analysis.modules.linguistics.run_linguistics")

                raw_blocks = mapper.map_to_schema(doc_obj)

                for block in raw_blocks.logical_blocks:
                    block.language = language

                ling_matches, sentence_analysis = ling_module.run_linguistics(raw_blocks)

                logger.info(f"[PIPELINE] Found {len(ling_matches)} linguistic issues.")

                stats = {
                    "active_ratio": getattr(sentence_analysis, "active_ratio", "0%"),
                    "passive_ratio": getattr(sentence_analysis, "passive_ratio", "0%"),
                    "verbless_ratio": getattr(sentence_analysis, "verbless_ratio", "0%"),
                }

                return ling_matches, stats

            except Exception as e:
                logger.error(f"[PIPELINE] Linguistic analysis error: {e}", exc_info=True)

                return [], {
                    "active_ratio": "0%",
                    "passive_ratio": "0%",
                    "verbless_ratio": "0%",
                }

        def task_redaction():
            try:
                from analysis.modules.redaction.redaction_validator import RedactionValidator
                from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper

                mapper = PDFMapper()

                validator = RedactionValidator(
                    document_data=doc_obj,
                    document_data_linguistics=mapper.map_to_schema(doc_obj),
                    config_path=config_path,
                    language=language,
                )
                font_usage = doc_obj.get_font_size_usage()
                doc_obj.get_most_common_font_size = (
                    lambda: max(font_usage, key=font_usage.get, default=12)
                    if font_usage
                    else 12
                )

                redaction_errors = validator.validate()

                logger.info(f"[PIPELINE] Found {len(redaction_errors)} redaction errors.")

                return redaction_errors

            except Exception as e:
                logger.error(f"[PIPELINE] Redaction validation error: {e}", exc_info=True)
                return []

        report_progress(30, "Starting analyses...")

        redaction_errors = task_redaction()

        report_progress(50, "Redaction completed. Running remaining analyses...")

        workers_count = 2 if use_llm else 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers_count) as executor:
            future_ling = executor.submit(task_linguistics)

            if use_llm:
                future_llm = executor.submit(task_llm)

            ling_matches, ling_stats = future_ling.result()

            if use_llm:
                llm_result, content_grade_result, llm_summary_text = future_llm.result()
            else:
                llm_result = None
                content_grade_result = None
                llm_summary_text = "LLM analysis was skipped."

        report_progress(100, "Generating final report...")

        all_errors = ling_matches + redaction_errors

        final_report = FinalReport(
            document_name=os.path.basename(pdf_path),
            processed_document=doc_dict,
            extraction_result=extraction_result,
            llm_result=llm_result,
            summary=[
                "Extraction completed.",
                "Linguistic analysis completed.",
                "Redaction analysis completed.",
                llm_summary_text,
                f"Found {len(all_errors)} errors to display on screen.",
            ],
            recommendations=[],
        )

        if final_report.llm_result is None:
            final_report.llm_result = {}

        image_analysis = final_report.llm_result.get("image_analysis")
        if not isinstance(image_analysis, dict):
            image_analysis = {
                "total": 0,
                "bad_count": 0,
                "good_count": 0,
                "details": [],
            }

        image_analysis["image_raster"] = raster_figure_numbers
        final_report.llm_result["image_analysis"] = image_analysis
        final_report.llm_result["statystyki_zdan"] = ling_stats

        final_report.llm_result["language"] = language

        final_report.linguistics_errors = all_errors

        return final_report