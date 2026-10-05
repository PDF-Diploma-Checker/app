from models import ModuleResult
import logging

logger = logging.getLogger(__name__)


class LinguisticsService:
    def analyze(self, processed_document):
        pages = processed_document.get("pages", [])

        return ModuleResult(
            module_name="linguistics",
            status="done",
            comments=["Analiza językowa została uruchomiona poprawnie."],
            details={
                "page_count_seen_by_linguistics": len(pages)
            }
        )