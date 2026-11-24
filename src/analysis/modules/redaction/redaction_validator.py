"""
Znajduje się tu główna klasa RedactionValidator, która zajmuje się
...walidowaniem...
pdf'a pod względem błędów z redakcji i "zaawansowanej" redakcji.

"""

from analysis.extraction.raw_extraction.bare_struct import DocumentData
from analysis.extraction.linguistics_conversion.schema import FinalDocument
from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper, get_acronym_pages
from common.errors.error_struct import Error, FileError, Module
from collections import Counter
from dataclasses import dataclass
from typing import List
import json
import logging
import os
import re

logger = logging.getLogger(__name__)


def _comparable_title(text):
    """A title for comparing a list entry with the document: extracting an entry turns "1. Wstęp" into "1 Wstęp", so
    the text it is looked for in has to go through the same cleaning (see front_and_back_matter). Spaces do not count:
    extraction can add one next to a bracket or a math symbol."""
    return "".join(re.sub(r"[\.\s·-]{2,}", " ", text.lower().strip().rstrip(".")).split())


def _comparable_toc_title(text):
    # Contents may spell out "Dodatek A", whereas the heading prints "A.".
    text = re.sub(
        r"^(?:dodatek|appendix|załącznik|zalacznik|aneks)\s+([a-z])(?=[.\s])",
        r"\1", text.strip(), flags=re.IGNORECASE,
    )
    return _comparable_title(text)


VALID_PAGE_OFFSETS = (0, 1)     # the numbering starts after the title page, or counts it as page 1

MONOSPACE_FONTS = (
    "courier", "consolas", "mono", "code", "typewriter", "menlo", "inconsolata", "cmtt", "sftt", "t1xtt", "txtt",
)
# TeX fonts keep the style in the name (CMBX12 = bold CMR12), so they are mapped to one family
TEX_FONT_FAMILIES = {
    "cmr": "cm", "cmbx": "cm", "cmti": "cm", "cmsl": "cm", "cmcsc": "cm", "cmb": "cm",
    "sfrm": "ec", "sfbx": "ec", "sfti": "ec", "sfsl": "ec", "sfcc": "ec", "sfbi": "ec",
}
SMALL_MARK_RATIO = 0.7      # text this much smaller than the main size is a mark (listing line number), not running text

# errors of running text, not reported in lists (TOC/TOF/TOT), images, tables and the acronym list (redaction_info.md);
# the names are the categories the checks give their errors
TYPOGRAPHY_CATEGORIES = ("orphan", "widow", "bastard", "shoemaker", "corridor", "justification")


def _font_family(font):
    """Font name without style, size and subset prefix (TimesNewRomanPS-BoldMT -> timesnewromanps, CMBX12 -> cm),
    so that bold and italic of the main font count as the main font. Same rule as font_family in linguistics/helpers.py,
    which is not imported here because that module loads spaCy."""
    name = (font or "").split("+")[-1]
    name = re.split(r"[-,]", name, maxsplit=1)[0]
    tex = re.fullmatch(r"([a-z]+)\d*", name.lower())
    if tex and tex.group(1) in TEX_FONT_FAMILIES:
        return TEX_FONT_FAMILIES[tex.group(1)]
    name = re.sub(r"MT$", "", name)
    name = re.sub(r"(bold|italic|ital|oblique)$", "", name, flags=re.IGNORECASE)
    return re.sub(r"\d+$", "", name).lower()


def _is_monospace(font):
    return any(mono in (font or "").lower() for mono in MONOSPACE_FONTS)


def _footer_number(page):
    """The page number printed in the footer of a page, None when there is none."""
    # the last lines of the text can be taken for the footer too, and a citation such as [17] in them is no page number:
    # the number is the lowest footer on the page
    footers = sorted((block for block in page.text_blocks if block.block_type == "footer"),
                     key=lambda block: block.bbox[3], reverse=True)
    for block in footers:
        text = " ".join(span.text for line in block.lines for span in line.spans)
        match = re.search(r"\d+", text)
        if match:
            return int(match.group())
    return None


def _printed_page_offset(document_data):
    """How much the numbers printed on the pages differ from page.number. Theses leave out different front pages from
    the numbering, so what counts as a page's number is what most of the document prints."""
    differences = Counter(
        number - page.number
        for page in document_data.pages
        if (number := _footer_number(page)) is not None
    )
    return differences.most_common(1)[0][0] if differences else 0


def _caption_title(text):
    # PDF line wrapping splits words; list extraction also removes sentence dots.
    text = re.sub(r"(?<=\w)[-\u00ad]\s+(?=\w)", "", text)
    return _comparable_title(text).replace(".", "")


_CAPTION = re.compile(
    r"^(?P<kind>Rysunek|Rys|Figure|Fig|Tabela|Table|Tab)\.?\s+"
    r"(?P<number>(?:[A-Z]\.|\d+\.)*\d+)\.?\s+", re.IGNORECASE | re.MULTILINE
)


SAME_START = 30


def _same_caption(listed, printed, numbered):
    """A numbered list entry and a caption of the same number agree when they start the same way: the list may hold a
    shorter or reworded caption after its first sentence."""
    if listed in printed:
        return True
    if not numbered:
        return False
    return len(os.path.commonprefix([listed, printed])) >= SAME_START


def _listed_caption_on_page(page, entry, kind):
    """Check captions even when image/table detection lost their association."""
    expected = _caption_title(entry.title)
    if not expected:
        return False
    number = str(getattr(entry, "number", "")).rstrip(".").casefold()
    objects = page.images if kind == "figure" else page.tables
    for obj in objects:
        description = obj.description
        if not description:
            continue
        match = _CAPTION.match(description)
        if number and (not match or match['number'].casefold() != number):
            continue
        title = _caption_title(description[match.end():] if match else description)
        if title and (_same_caption(expected, title, bool(number)) or (not number and title in expected)):
            return True

    # Keep line starts to distinguish actual captions from prose references.
    text = "\n".join(
        " ".join(span.text for span in line.spans)
        for block in page.text_blocks
        if block.block_type not in {"footer", "header"}
        for line in block.lines
    )
    captions = list(_CAPTION.finditer(text))
    for i, match in enumerate(captions):
        caption_kind = "figure" if match['kind'].lower().startswith(("rys", "fig")) else "table"
        if caption_kind != kind or (number and match['number'].casefold() != number):
            continue
        end = captions[i + 1].start() if i + 1 < len(captions) else len(text)
        printed = _caption_title(text[match.end():end])
        if printed.startswith(expected) or (number and _same_caption(expected, printed, True)):
            return True
    return False


def widow_max_words_setting():
    """How many words a short last line may have to be a widow: 2 (the default: one or two words) or 1 (only a single
    word), chosen in the analysis dialog and kept in app_config.json as "widow_max_words"."""
    try:
        from analysis.modules.llm.config import load_config
        return 1 if int(load_config().get("widow_max_words", 2)) == 1 else 2
    except Exception:
        return 2


@dataclass
class Configuration:
    interlinia: float
    min_stron: int
    max_stron: int
    font_size: int
    margin_type: str
    format: str
    orientation: str
    justowanie: bool
    font_list: List[str]

    def __init__(self, config_path: str):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._validateAndAssign(data)

            logger.info(f"Konfiguracja załadowana pomyślnie z {config_path}")

        except FileNotFoundError:
            raise FileNotFoundError(f"nie znaleziono konfiguracji {config_path}")
        except json.JSONDecodeError:
            raise FileError(f"nieporpawny format jsona {config_path}")

    def _validateAndAssign(self, data: dict):
        lang = getattr(self, "language", "pl")
        try:
            self.interlinia = float(data["interlinia"])
            self.min_stron = int(data["minimalna_liczba_stron"])
            self.max_stron = int(data["maksymalna_liczba_stron"])
            self.font_size = int(data["rozmiar_czcionki"])

            if self.min_stron > self.max_stron:
                if lang == "en":
                    raise FileError("min_stron > max_stron, config error")
                else:
                    raise FileError("min_stron > max_stron, błąd konfiguracji")

            if data["margines"].lower() not in ["lustrzany", "standardowy"]:
                if lang == "en":
                    raise FileError(
                        "Incorrect margin, expected 'lustrzany' (mirror) or 'standardowy' (standard)"
                    )
                else:
                    raise FileError(
                        "błędny margines, oczekiwano 'lustrzany' lub 'standardowy'"
                    )
            self.margin_type = data["margines"]

            if data["format"].lower() not in ["a3", "a4", "a5"]:
                if lang == "en":
                    raise FileError(
                        "Incorrect page format, expected 'a3', 'a4' or 'a5'"
                    )
                else:
                    raise FileError(
                        "błędny format strony, oczekiwano 'a3', 'a4' lub 'a5'"
                    )
            self.format = data["format"]

            if data["orientacja"].lower() not in ["pionowa", "pozioma"]:
                if lang == "en":
                    raise FileError(
                        "Incorrect orientation, expected 'pionowa' (vertical) or 'pozioma' (horizontal)"
                    )
                else:
                    raise FileError(
                        "błędna orientacja, oczekiwano 'pionowa' lub 'pozioma'"
                    )
            self.orientation = data["orientacja"]

            if data["justowanie"].lower() not in ["tak", "nie"]:
                if lang == "en":
                    raise FileError(
                        "Incorrect justification, expected 'tak' (yes) or 'nie' (no)"
                    )
                else:
                    raise FileError("błędne justowanie, oczekiwano 'tak' lub 'nie'")
            self.justowanie = data["justowanie"].lower() == "tak"

            czcionki_dict = data.get("czcionka", {})
            self.font_list = list(czcionki_dict.values())

            if not self.font_list:
                if lang == "en":
                    logger.warning(
                        "Allowed fonts are not provided in the configuration file"
                    )
                else:
                    logger.warning("brak dozwolonych czcionek w konfiguracji")

        except KeyError as e:
            if lang == "en":
                raise FileError(f"Lacking key in the configuration file: {e}")
            else:
                raise FileError(f"brakujący klucz w konfiguracji: {e}")
        except ValueError as e:
            if lang == "en":
                raise FileError(f"Incorrect data type in the configuration file: {e}")
            else:
                raise FileError(f"niepoprawny typ danych w konfiguracji: {e}")


class RedactionValidator:
    def __init__(
        self,
        document_data: DocumentData,
        document_data_linguistics: FinalDocument,
        config_path: str = None,
        language="pl",
        widow_max_words=None,
    ):
        self.document_data = document_data
        self.widow_max_words = widow_max_words if widow_max_words is not None else widow_max_words_setting()
        self.language = language
        self.document_data_linguistics = document_data_linguistics
        if config_path is not None:
            self.config = Configuration(config_path)
        else:
            self.config = None

        self.module = Module.REDACTION
        self.id_counter = 0
        self.errors = []
        self._main_font = None

    def _main_font_and_size(self):
        if getattr(self, "_main_font", None) is None:
            self._main_font = (
                self.document_data.get_most_common_font(),
                self.document_data.get_most_common_font_size(),
            )
        return self._main_font

    def _in_other_font(self, words):
        """
        True when the words flagged by a typographic check (orphan, widow, bastard, shoemaker) are not set in the
        main text font.
        """
        main_font, main_size = self._main_font_and_size()
        words = [w for w in words if (getattr(w, "text", "") or "").strip()]
        if not main_font or not words:
            return False
        regular = [w for w in words if not main_size or (getattr(w, "size", 0) or 0) >= main_size * SMALL_MARK_RATIO]
        if not regular:
            return True
        if all(_is_monospace(getattr(w, "font", "")) for w in regular):
            return True
        main_family = _font_family(main_font)
        return all(_font_family(getattr(w, "font", "")) != main_family for w in regular)

    def _get_next_id(self):
        id = f"ERR_RED_{self.id_counter}"
        self.id_counter += 1
        return id

    def validate(
        self,
        config_ckeck: bool = True,
        basic_redaction_check: bool = True,
        advanced_redaction_check: bool = True,
    ):
        self.errors.clear()
        self.id_counter = 0
        self._main_font = None
        # --------------------config check
        if self.config is not None and config_ckeck:
            self.check_interline_spacing(self.document_data)
            self.check_page_count(self.document_data)
            self.check_font_size(self.document_data)
            self.check_margins(self.document_data)
            self.check_orientation(self.document_data)
            self.check_fonts(self.document_data)
            self.check_justification(self.document_data)
            self.check_format(self.document_data)

        # --------------------basic redaction check
        if basic_redaction_check:
            self.check_blank_page()
            self.check_footers()
            self.check_toc()
            self.check_tof()
            self.check_tot()
            self.check_raster_images()

            self.check_list_order()

        # --------------------advanced redaction check
        if advanced_redaction_check:
            self.check_orphans()
            self.check_widows()
            self.check_bekarts()
            self.check_szewce()
            self.check_bibliography()
            # self.check_korytarze()
            self.check_bibliography_summary()
            self.check_caption_sources()

        self.remove_errors_from_toc_tof_tot()
        self.remove_errors_from_images()
        self.remove_errors_from_tables()
        self.remove_errors_from_acronyms_symbols()
        self.remove_errors_from_title_page()
        self.remove_errors_from_bibliography()
        self.replace_global_errors()
        self.log_all_errors()

        return self.errors

    def last_errors_to_json(self):
        return json.dumps(
            [error.__dict__ for error in self.errors], ensure_ascii=False, indent=4
        )

    def last_errors_to_file(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.last_errors_to_json())

    def replace_global_errors(self):
        for page in self.document_data.pages:
            errors_on_page = []
            for error in self.errors:
                if error.bounding_box == (0, 0, 0, 0):
                    if error.page_number == page.number or (
                        page.number == 1 and error.page_number is None
                    ):
                        errors_on_page.append(error)

            num_errors = len(errors_on_page)
            if num_errors > 0:
                slot_width = page.width / num_errors

                for i, error in enumerate(errors_on_page):
                    new_x1 = i * slot_width + 5
                    new_x2 = (i + 1) * slot_width - 5
                    error.bounding_box = (round(new_x1, 2), 5, round(new_x2, 2), 45)

    def remove_errors_from_bibliography(self):
        """In the bibliography only the findings of bibliography_check (linguistics module) are shown.."""
        areas = []                                       # (page, x0, y0, x1, y1) of a bibliography block on a page
        for block in self.document_data_linguistics.logical_blocks:
            if not getattr(block, "is_bibliography", False):
                continue
            words = [w for item in getattr(block, "items", []) or [] for w in item.words or []] or getattr(block, "words", []) or []
            for page in {w.page_number for w in words}:
                boxes = [w.bbox for w in words if w.page_number == page]
                areas.append((page, min(b[0] for b in boxes), min(b[1] for b in boxes),
                              max(b[2] for b in boxes), max(b[3] for b in boxes)))

        def in_bibliography(error):
            box = error.bounding_box
            if not box or tuple(box) == (0, 0, 0, 0):
                return False
            return any(page == error.page_number and box[0] >= x0 - 5 and box[1] >= y0 - 5
                       and box[2] <= x1 + 5 and box[3] <= y1 + 5 for page, x0, y0, x1, y1 in areas)

        kept = []
        for error in self.errors:
            if in_bibliography(error):
                logger.info("[DROPPED] %s page=%s text=%r reason=in the bibliography (only bibliography_check is shown there)",
                            error.category, error.page_number, error.text)
            else:
                kept.append(error)
        self.errors = kept

    def remove_errors_from_title_page(self):
        for error in self.errors[:]:
            if error.page_number == 0:
                self.errors.remove(error)

    def remove_errors_from_toc_tof_tot(self):
        if self.document_data.toc and self.document_data.toc.page_nums:
            toc_pages = self.document_data.toc.page_nums
        else:
            toc_pages = []

        if self.document_data.tof and self.document_data.tof.page_nums:
            tof_pages = self.document_data.tof.page_nums
        else:
            tof_pages = []

        if self.document_data.tot and self.document_data.tot.page_nums:
            tot_pages = self.document_data.tot.page_nums
        else:
            tot_pages = []

        errors_fixed = []
        for error in self.errors:
            is_in_toc = error.page_number in toc_pages
            is_in_tof = error.page_number in tof_pages
            is_in_tot = error.page_number in tot_pages
            is_exluded = error.category in TYPOGRAPHY_CATEGORIES

            if (is_in_toc or is_in_tof or is_in_tot) and is_exluded:
                continue

            errors_fixed.append(error)
        self.errors = errors_fixed

    def remove_errors_from_images(self):
        def is_inside(error_bbox, image_bbox):
            return (
                error_bbox[0] >= image_bbox[0] - 10
                and error_bbox[1] >= image_bbox[1] - 10
                and error_bbox[2] <= image_bbox[2] + 10
                and error_bbox[3] <= image_bbox[3] + 10
            )

        filtered_errors = []

        for error in self.errors:
            error_to_remove = False

            if error.category in TYPOGRAPHY_CATEGORIES:
                for page in self.document_data.pages:
                    if error.page_number == page.number:
                        for image in page.images:
                            if is_inside(error.bounding_box, image.bbox):
                                error_to_remove = True
                                break
                        break

            if not error_to_remove:
                filtered_errors.append(error)

        self.errors = filtered_errors

    def _matches_caption_text(self, error, descriptions) -> bool:
        if not error.text:
            return False
        err_norm = " ".join(error.text.split()).casefold()
        if len(err_norm) < 5:
            return False

        for desc in descriptions:
            if not desc:
                continue
            desc_norm = " ".join(desc.split()).casefold()
            if err_norm in desc_norm:
                return True
        return False

    def remove_errors_from_tables(self):
        def is_inside(error_bbox, table_bbox):
            return (
                error_bbox[0] >= table_bbox[0] - 10
                and error_bbox[1] >= table_bbox[1] - 10
                and error_bbox[2] <= table_bbox[2] + 10
                and error_bbox[3] <= table_bbox[3] + 10
            )

        filtered_errors = []

        for error in self.errors:
            error_to_remove = False

            if error.category in TYPOGRAPHY_CATEGORIES:
                for page in self.document_data.pages:
                    if error.page_number == page.number:
                        for table in page.tables:
                            if is_inside(error.bounding_box, table.bbox):
                                error_to_remove = True
                                break

                        if (
                            not error_to_remove
                            and error.category == "shoemaker"
                            and self._matches_caption_text(
                                error, [t.description for t in page.tables]
                            )
                        ):
                            error_to_remove = True
                        break

            if not error_to_remove:
                filtered_errors.append(error)

        self.errors = filtered_errors

    def remove_errors_from_acronyms_symbols(self):
        mapper = PDFMapper()
        linguistics_doc = mapper.map_to_schema(self.document_data)

        pages = get_acronym_pages(linguistics_doc) if linguistics_doc else []
        if pages is None:
            pages = []

        errors_fixed = []
        for error in self.errors:
            is_in_acronyms = error.page_number in pages
            is_exluded = error.category in TYPOGRAPHY_CATEGORIES

            if is_in_acronyms and is_exluded:
                continue

            errors_fixed.append(error)
        self.errors = errors_fixed

    def check_orphans(self):
        """This function checks every line in the document for orphans."""
        orphans = []
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Orphan detected - Conjunction at the end of the line."
        else:
            comment = "Wykryto sierotę - spójnik na końcu linii."

        MATH_FONTS = (
            "math", "cmmi", "cmsy", "symbol", "rntx", "mnsymbol", "txmi", "nimbusrom"
        )

        CONJUCTIONS = {"i", "z", "o", "a", "w", "u"}

        most_common_size = self.document_data.get_most_common_font_size() or 10.0

        for page in self.document_data.pages:
            for block in page.text_blocks:
                if getattr(block, "block_type", "text") in ("math", "equation", "formula"):
                    continue

                for line in block.lines:
                    if line.spans is None or len(line.spans) == 0:
                        continue

                    last_span = None
                    for span in line.spans[::-1]:
                        if span.text.strip() == "":
                            continue
                        last_span = span
                        break

                    if last_span is None:
                        continue

                    text_clean = last_span.text.strip()

                    if not text_clean.isalpha():
                        continue

                    if len(text_clean) == 1 and text_clean.lower() in CONJUCTIONS:
                        prev_span = None
                        seen_last = False
                        for sp in line.spans[::-1]:
                            if sp is last_span:
                                seen_last = True
                                continue
                            if seen_last and sp.text.strip() != "":
                                prev_span = sp
                                break
                        if prev_span is None:
                            continue
                        prev_text = prev_span.text.strip()
                        if (len(prev_text) == 1 and prev_text.isalnum()) or (
                            prev_span.size < last_span.size * 0.85
                        ):
                            continue
                        font_lower = getattr(last_span, "font", "").lower()
                        if any(mf in font_lower for mf in MATH_FONTS):
                            continue
                        if getattr(last_span, "italic", False):
                            continue

                        if last_span.size < most_common_size * 0.88:
                            continue
                        if self._in_other_font([last_span]):
                            continue

                        rect = (
                            last_span.bbox[2] + 3,
                            last_span.bbox[1] + 1,
                            page.width - 1,
                            last_span.bbox[3] - 1,
                        )
                        if self.document_data.is_rect_intersecting(rect, page) != []:
                            continue

                        orphans.append(last_span)
                        self.errors.append(
                            Error(
                                id=self._get_next_id(),
                                module=self.module,
                                category="orphan",
                                page_number=page.number,
                                bounding_box=last_span.bbox,
                                text=last_span.text,
                                comments=comment,
                            )
                        )
        return orphans

    def check_korytarze(self):
        korytarze = []
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Corridor detected - overlapping white gaps between words in neighbouring lines."
        else:
            comment = "Wykryto korytarz - nakładające się przerwy między wyrazami w sąsiednich liniach."
        for page in self.document_data.pages:
            if page.number < 3:
                continue
            for block in page.text_blocks:
                if block.lines is None or len(block.lines) <= 1:
                    continue

                paths_to_check = []
                first_line = block.lines[0]

                if first_line.spans and len(first_line.spans) >= 2:
                    for i in range(len(first_line.spans) - 1):
                        span = first_line.spans[i]
                        next_span = first_line.spans[i + 1]
                        paths_to_check.append((span.bbox[2], next_span.bbox[0]))

                for line in block.lines[1:]:
                    if not line.spans:
                        continue

                    for span in line.spans:
                        for x1, x2 in paths_to_check:
                            if (span.bbox[0] > x1 and span.bbox[0] < x2) or (
                                span.bbox[2] > x1 and span.bbox[2] < x2
                            ):
                                korytarze.append(span)
                                self.errors.append(
                                    Error(
                                        id=self._get_next_id(),
                                        module=self.module,
                                        category="corridor",
                                        page_number=page.number,
                                        bounding_box=(
                                            x1,
                                            span.bbox[1] - 15,
                                            x2,
                                            span.bbox[3],
                                        ),
                                        text=None,
                                        comments=comment,
                                    )
                                )

                    paths_to_check = []
                    if len(line.spans) >= 2:
                        for i in range(len(line.spans) - 1):
                            s = line.spans[i]
                            ns = line.spans[i + 1]
                            paths_to_check.append((s.bbox[2], ns.bbox[0]))

        return korytarze

    def check_blank_page(self):
        blank_pages = []
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Blank page detected."
        else:
            comment = "Wykryto pustą stronę."

        for page in self.document_data.pages:
            if page.is_blank:
                blank_pages.append(page)
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="blank_page",
                        page_number=page.number,
                        bounding_box=(0, 0, 0, 0),
                        text="",
                        comments=comment,
                    )
                )

        return blank_pages

    def check_raster_images(self):
        """
        Checking whether image type is raster (image_type == 'raster').
        """
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Raster image detected - it is recommended to use vector images. Consider changing an image format"
        else:
            comment = "Wykryto grafikę rastrową - zaleca się stosowanie grafik wektorowych. Rozważ zmianę formatu grafiki."

        for page in self.document_data.pages:
            for img in page.images:
                if getattr(img, "image_type", "") == "raster":
                    self.errors.append(
                        Error(
                            id=self._get_next_id(),
                            module=self.module,
                            category="raster_image",
                            page_number=page.number,
                            bounding_box=img.bbox,
                            text=img.description,
                            comments=comment,
                        )
                    )

    def check_bibliography(self):
        """
        Iterates through the logical blocks to identify words flagged with
        incorrect or missing bibliography references. It generates and appends
        an Error object for each flagged instance.
        """
        for block in self.document_data_linguistics.logical_blocks:
            words = getattr(block, "words", [])
            for word in words:
                if getattr(word, "incorrect_bibliography", 0) == 1:
                    error = self._handle_bibliography(word)
                    if error:
                        self.errors.append(error)
                if getattr(word, "missing_bib_space", 0) == 1:
                    self.errors.append(self._handle_bibliography_space(word))

    def _handle_bibliography_space(self, word):
        """Error for a bibliography reference written without a space after the text: "tekst[17]"."""
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Missing space between the text and the bibliography reference (e.g. 'text [17]', not 'text[17]')."
        else:
            comment = "Brak spacji między tekstem a odwołaniem do bibliografii (powinno być np. „tekst [17]”, a nie „tekst[17]”)."

        return Error(
            id=self._get_next_id(),
            module=self.module,
            category="missing_space_before_citation",
            page_number=word.page_number,
            bounding_box=word.bbox,
            text=word.text,
            comments=comment,
        )

    def _handle_bibliography(self, word):
        """
        Constructs an Error object for an invalid or missing bibliography reference.

        Args:
            word (WordInfo): The word object containing the invalid citation and its metadata.

        Returns:
            Error: A formatted error object detailing the citation mismatch.
        """
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Incorrect bibliography reference detected - element is not included in bibliography section or does not exist."
        else:
            comment = "Wykryto niepoprawne odwołanie do bibliografii - element nie występuje w spisie bibliografii lub ten nie istnieje."

        return Error(
            id=self._get_next_id(),
            module=self.module,
            category="incorrect bibiography refference",
            page_number=word.page_number,
            bounding_box=word.bbox,
            text=word.text,
            comments=comment,
        )

    def _is_reported_widow(self, words):
        """A widow of `words` words is reported; with "only a single word" (widow_max_words 1) a last line of two or
        more words is not."""
        if words <= 0:
            return False
        return words == 1 or getattr(self, "widow_max_words", 2) >= 2

    def check_widows(self):
        """
        Scans all paragraph blocks for 'widow' flags (a very short line left at the
        end of a paragraph). If detected, it processes and logs the corresponding error.
        """
        for block in self.document_data_linguistics.logical_blocks:
            if getattr(block, "type", "") == "paragraph":
                # Flaga: wdowy
                widow_which = getattr(block, "is_widow", 0)
                if self._is_reported_widow(widow_which):
                    error = self._handle_widow(block, widow_which)
                    if error:
                        self.errors.append(error)
            elif getattr(block, "type", "") == "list" or getattr(block, "is_bibliography", False):
                # elementy listy (m.in. wpisy bibliografii): wdowa jest zapisana przy kazdym elemencie
                for item in getattr(block, "items", []):
                    item_widow = getattr(item, "is_widow", 0)
                    if self._is_reported_widow(item_widow):
                        error = self._handle_widow(item, item_widow)
                        if error:
                            self.errors.append(error)

    def check_bibliography_summary(self):
        """
        Compiles a complete list of all recognized bibliography entries from the
        document and appends them as a single, informational summary Error object
        for easy review.
        """
        bib_entries = []
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Summary: List of all items detected in the bibliography."
        else:
            comment = "Podsumowanie: Lista wszystkich pozycji wykrytych w spisie bibliograficznym."

        for block in self.document_data_linguistics.logical_blocks:
            if getattr(block, "is_bibliography", False) and hasattr(block, "items"):
                for item in block.items:
                    text_content = item.text.strip()
                    if text_content:
                        marker = item.words[0].text if item.words else ""
                        bib_entries.append(f"{marker} {text_content}\n")

                        # bib_entries.append(text_content)

        if bib_entries:
            summary_text = "\n".join(bib_entries)

            summary_error = Error(
                id=self._get_next_id(),
                module=self.module,
                category="bibliography_summary",
                page_number=3,
                bounding_box=(0, 0, 0, 0),
                text=summary_text,
                comments=comment,
            )
            self.errors.append(summary_error)

    def _handle_widow(self, block, widow_which):
        """
        Calculates the precise bounding box for the isolated words constituting
        a 'widow' and constructs the corresponding Error object.

        Args:
            block (ParagraphBlock): The paragraph block containing the widow.
            widow_which (int): The number of words that make up the widow at the end of the block.

        Returns:
            Error: A formatted error object representing the typographical widow.
        """

        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Widow detected - very short line left at end of a paragraph."
        else:
            comment = (
                "Wykryto wdowę - bardzo krótki wiersz pozostawiony na końcu akapitu."
            )

        if not block.words:
            return

        widow_words = block.words[-widow_which:]
        if self._in_other_font(widow_words):
            return
        first_word = widow_words[0]
        last_word = widow_words[-1]
        found_text = " ".join([w.text for w in widow_words])

        left_x = first_word.bbox[0]
        right_x = last_word.bbox[2]
        top_y = min([w.bbox[1] for w in widow_words])
        bottom_y = max([w.bbox[3] for w in widow_words])
        widow_bbox = (
            round(left_x, 2),
            round(top_y, 2),
            round(right_x, 2),
            round(bottom_y, 2),
        )

        return Error(
            id=self._get_next_id(),
            module=self.module,
            category="widow",
            page_number=last_word.page_number,
            bounding_box=widow_bbox,
            text=found_text,
            comments=comment,
        )

    def check_bekarts(self):
        """
        Scans all paragraph blocks for 'bastard' flags (the last line of a paragraph
        isolated at the top of the following page). If detected, it processes and
        logs the corresponding error.
        """
        for block in self.document_data_linguistics.logical_blocks:
            if getattr(block, "type", "") == "paragraph":
                # Flaga: bękarty
                bekart_which = getattr(block, "is_bekart", 0)
                if bekart_which != 0:
                    error = self._handle_bekart(block, bekart_which)
                    if error:
                        self.errors.append(error)

    def _handle_bekart(self, block, bekart_which):
        """
        Calculates the precise bounding box for the isolated words constituting
        a 'bastard' and constructs the corresponding Error object.

        Args:
            block (ParagraphBlock): The paragraph block containing the bastard.
            bekart_which (int): The number of words that make up the bastard on the new page.

        Returns:
            Error: A formatted error object representing the typographical bastard.
        """

        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = (
                "Bastard detected - last line of a paragraph left on the next page"
            )
        else:
            comment = "Wykryto bękarta - ostatni wiersz akapitu pozostawiony na kolejnej stronie."

        if not block.words:
            return

        bekart_words = block.words[-bekart_which:]
        if self._in_other_font(bekart_words):
            return
        first_word = bekart_words[0]
        last_word = bekart_words[-1]
        found_text = " ".join([w.text for w in bekart_words])

        left_x = first_word.bbox[0]
        right_x = last_word.bbox[2]
        top_y = min([w.bbox[1] for w in bekart_words])
        bottom_y = max([w.bbox[3] for w in bekart_words])
        bekart_bbox = (
            round(left_x, 2),
            round(top_y, 2),
            round(right_x, 2),
            round(bottom_y, 2),
        )

        return Error(
            id=self._get_next_id(),
            module=self.module,
            category="bastard",
            page_number=last_word.page_number,
            bounding_box=bekart_bbox,
            text=found_text,
            comments=comment,
        )

    def check_szewce(self):
        """
        Scans all paragraph blocks for 'shoemaker' flags (the first line of a new
        paragraph isolated at the bottom of the previous page). If detected, it
        processes and logs the corresponding error.
        """
        for block in self.document_data_linguistics.logical_blocks:
            if getattr(block, "type", "") == "paragraph":
                # Flaga: szewce
                szewc_which = getattr(block, "is_szewc", 0)
                if szewc_which != 0:
                    error = self._handle_szewc(block, szewc_which)
                    if error:
                        self.errors.append(error)

    def _handle_szewc(self, block, szewc_which):
        """
        Calculates the precise bounding box for the isolated words constituting
        a 'shoemaker' and constructs the corresponding Error object.

        Args:
            block (ParagraphBlock): The paragraph block containing the shoemaker.
            szewc_which (int): The number of words that make up the shoemaker at the beginning of the block.

        Returns:
            Error: A formatted error object representing the typographical shoemaker.
        """

        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Shoemaker detected - first line of paragraph left on the previous page."
        else:
            comment = "Wykryto szewca - pierwszy wiersz akapitu pozostawiony na poprzedniej stronie."

        if not block.words:
            return

        szewc_words = block.words[:szewc_which]
        if self._in_other_font(szewc_words):
            return
        first_word = szewc_words[0]
        last_word = szewc_words[-1]
        found_text = " ".join([w.text for w in szewc_words])

        left_x = first_word.bbox[0]
        right_x = last_word.bbox[2]
        top_y = min([w.bbox[1] for w in szewc_words])
        bottom_y = max([w.bbox[3] for w in szewc_words])
        szewc_bbox = (
            round(left_x, 2),
            round(top_y, 2),
            round(right_x, 2),
            round(bottom_y, 2),
        )

        return Error(
            id=self._get_next_id(),
            module=self.module,
            category="shoemaker",
            page_number=first_word.page_number,
            bounding_box=szewc_bbox,
            text=found_text,
            comments=comment,
        )

    def check_caption_sources(self):
        """
        Iterates through the text blocks acting as visual captions to verify if they
        lack proper source attributions or bibliography citations. Calculates the
        bounding box of the flagged caption and appends a corresponding Error object.
        """

        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "The caption does not contain a reference to the bibliography (e.g. [1]) or information about the source (e.g. 'Source: ...')."
        else:
            comment = "Podpis nie zawiera odwołania do bibliografii (np. [1]) ani informacji o źródle (np. 'Źródło: opracowanie własne')."

        reported_captions = set()

        def caption_key(page, text):
            return page, " ".join(text.split()).casefold()

        for block in self.document_data_linguistics.logical_blocks:
            if getattr(block, "incorrect_caption", 0) == 1:
                if getattr(block, "words", []):
                    left_x = min(w.bbox[0] for w in block.words)
                    top_y = min(w.bbox[1] for w in block.words)
                    right_x = max(w.bbox[2] for w in block.words)
                    bottom_y = max(w.bbox[3] for w in block.words)
                    caption_bbox = (
                        round(left_x, 2),
                        round(top_y, 2),
                        round(right_x, 2),
                        round(bottom_y, 2),
                    )
                    page_num = block.words[0].page_number
                else:
                    caption_bbox = (0, 0, 0, 0)
                    page_num = 1

                key = caption_key(page_num, getattr(block, "content", ""))
                if key[1] and key in reported_captions:
                    continue
                reported_captions.add(key)
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="missing_caption_source",
                        page_number=page_num,
                        bounding_box=caption_bbox,
                        text=getattr(block, "content", ""),
                        comments=comment,
                    )
                )

        if lang == "en":
            comment = "The figure does not have a valid source or bibliography reference in its caption."
        else:
            comment = "Rysunek nie posiada poprawnego źródła lub odwołania do bibliografii w swoim podpisie."

        for visual in self.document_data_linguistics.floating_elements.visual_elements:
            if getattr(visual, "type", None) == "table":
                continue
            if getattr(visual, "incorrect_caption", 0) == 1:
                caption_dict = getattr(visual, "caption", {})
                caption_text = (
                    caption_dict.get("text", "")
                    if isinstance(caption_dict, dict)
                    else ""
                )

                key = caption_key(getattr(visual, "page_number", 1), caption_text)
                if caption_text and key in reported_captions:
                    continue
                reported_captions.add(key)
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="missing_caption_source",
                        page_number=getattr(visual, "page_number", 1),
                        bounding_box=getattr(visual, "bbox", (0, 0, 0, 0)),
                        text=caption_text,
                        comments=comment,
                    )
                )

    def check_toc(self):
        wrong_entries = []
        is_toc = True
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = "Missing table of contents detected"
        else:
            comment = "Wykryto brak spisu treści."

        if self.document_data.toc is None:
            error = Error(
                id=self._get_next_id(),
                module=self.module,
                category="lack_of_TOC",
                page_number=1,
                bounding_box=(0, 0, 0, 0),
                text=None,
                comments=comment,
            )
            self.errors.append(error)
            is_toc = False
            return None, is_toc

        offset = _printed_page_offset(self.document_data)
        toc_pages = getattr(self.document_data.toc, "page_nums", [])
        for entry in self.document_data.toc.entries:
            # PyMuPDF bookmarks contain one-based physical destinations, not
            # printed page numbers (including when the PDF has page labels).
            is_bookmark = entry.src_page == -1
            expected_page = entry.page - (1 if is_bookmark else offset)
            expected_title = _comparable_toc_title(entry.title)
            correct_page = False

            for page in self.document_data.pages:
                if is_bookmark:
                    matches_page = page.number == expected_page
                else:
                    # Back matter can restart numbering. Prefer the number on
                    # the actual page; use the document offset only if absent.
                    printed_number = _footer_number(page)
                    matches_page = (
                        printed_number == entry.page if printed_number is not None
                        else page.number == expected_page
                    )
                    # A contents row must not validate itself. A self-reference
                    # is valid only at the actual heading on the opening page.
                    if page.number in toc_pages:
                        contents_titles = {"spistreści", "spistresci", "tableofcontents", "contents", "toc"}
                        has_heading = expected_title in contents_titles and any(
                            line.bbox[1] < page.height * 0.15
                            and _comparable_toc_title(" ".join(span.text for span in line.spans)) == expected_title
                            for block in page.text_blocks
                            if block.block_type not in {"footer", "header"}
                            for line in block.lines
                        )
                        matches_page = matches_page and has_heading
                if matches_page:
                    page_full_text = ""
                    for block in page.text_blocks:
                        for line in block.lines:
                            line_text = " ".join([s.text for s in line.spans])
                            page_full_text += line_text + " "

                    page_full_text = _comparable_toc_title(page_full_text)

                    if expected_title in page_full_text:
                        correct_page = True
                        break
            if lang == "en":
                comment = f"Chapter/Subchapter '{entry.title}' is not on the specified page (page {entry.page})."
            else:
                comment = f"Rozdział/Podrozdział '{entry.title}' nie znajduje się na wskazanej stronie (strona {entry.page})."

            if not correct_page:
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="TOC_mismatch",
                        page_number=entry.src_page,
                        bounding_box=entry.bbox,
                        text=entry.title,
                        comments=comment,
                    )
                )
                wrong_entries.append(entry)

        return wrong_entries, is_toc

    def check_tot(self):
        wrong_entries = []
        lang = getattr(self, "language", "pl")

        if lang == "en":
            comment = "Missing table list detected."
        else:
            comment = "Wykryto brak spisu tabel."

        if self.document_data.tot is None:
            if not any(table.description for page in self.document_data.pages for table in page.tables):
                return                  # no table to list
            error = Error(
                id=self._get_next_id(),
                module=self.module,
                category="lack_of_TOT",
                page_number=1,
                bounding_box=(0, 0, 0, 0),
                text=None,
                comments=comment,
            )
            self.errors.append(error)
            return

        offset = _printed_page_offset(self.document_data)
        list_pages = set(getattr(self.document_data.tot, "page_nums", ()))
        for entry in self.document_data.tot.entries:
            correct_page = any(
                page.number not in list_pages
                and (_footer_number(page) if _footer_number(page) is not None
                     else page.number + offset) == entry.page
                and _listed_caption_on_page(page, entry, "table")
                for page in self.document_data.pages
            )

            if lang == "en":
                comment = f"The table titled '{entry.title}' is not on the specified page (page {entry.page})."
            else:
                comment = f"Tabela o tytule '{entry.title}' nie znajduje się na wskazanej stronie (strona {entry.page})."

            if not correct_page:
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="TOT_mismatch",
                        page_number=entry.src_page,
                        bounding_box=entry.bbox,
                        text=entry.title,
                        comments=comment,
                    )
                )
                wrong_entries.append(entry)

        return wrong_entries

    def check_tof(self):
        wrong_entries = []
        lang = getattr(self, "language", "pl")

        if lang == "en":
            comment = "Missing list of figures detected."
        else:
            comment = "Wykryto brak spisu rysunków."

        if self.document_data.tof is None:
            if not any(image.description for page in self.document_data.pages for image in page.images):
                return None, False      # no figure to list
            error = Error(
                id=self._get_next_id(),
                module=self.module,
                category="lack_of_TOF",
                page_number=1,
                bounding_box=(0, 0, 0, 0),
                text=None,
                comments=comment,
            )
            self.errors.append(error)
            is_toc = False
            return None, is_toc

        offset = _printed_page_offset(self.document_data)
        list_pages = set(getattr(self.document_data.tof, "page_nums", ()))
        for entry in self.document_data.tof.entries:
            correct_page = any(
                page.number not in list_pages
                and (_footer_number(page) if _footer_number(page) is not None
                     else page.number + offset) == entry.page
                and _listed_caption_on_page(page, entry, "figure")
                for page in self.document_data.pages
            )

            if lang == "en":
                comment = f"The figure titled '{entry.title}' is not on the specified page (Page {entry.page})."
            else:
                comment = f"Rysunek o tytule '{entry.title}' nie znajduje się na wskazanej stronie (Strona {entry.page})."

            if not correct_page:
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="TOF_mismatch",
                        page_number=entry.src_page,
                        bounding_box=entry.bbox,
                        text=entry.title,
                        comments=comment,
                    )
                )
                wrong_entries.append(entry)

        return wrong_entries

    def check_footers(self):
        first_chapter_page = None
        lang = getattr(self, "language", "pl")
        offset = _printed_page_offset(self.document_data)
        keywords = [
            "streszczenie",
            "abstract",
            "wstęp",
            "wstep",
            "introduction",
            "spis treści",
            "spis tresci",
            "table of contents",
            "table of content",
            "toc",
            "spis rysunków",
            "spis rysunkow",
            "list of figures",
            "tof",
            "spis tabel",
            "spis tablic",
            "list of tables",
            "tot",
            "wykaz skrótów",
            "wykaz skrotow",
            "list of abbreviations",
        ]

        font_sizes = []
        for page in self.document_data.pages:
            for block in page.text_blocks:
                for line in block.lines:
                    for span in line.spans:
                        if span.text and span.text.strip() and hasattr(span, "size"):
                            font_sizes.append(span.size)

        main_font_size = 12.0
        if font_sizes:
            font_sizes.sort()
            main_font_size = font_sizes[len(font_sizes) // 2]

        for page in self.document_data.pages:
            if page.number > 10:
                break

            line_counter = 0
            found_keyword = False

            for block in page.text_blocks:
                for line in block.lines:
                    line_text_lower = ""
                    max_span_size = 0.0

                    for span in line.spans:
                        if span.text:
                            line_text_lower += span.text.lower() + " "
                            if hasattr(span, "size") and span.size > max_span_size:
                                max_span_size = span.size

                    line_text_lower = line_text_lower.strip()
                    if not line_text_lower:
                        continue

                    line_counter += 1

                    if line_counter <= 4:
                        if max_span_size >= (main_font_size + 1.5):
                            if any(
                                word == line_text_lower
                                or line_text_lower.startswith(word)
                                for word in keywords
                            ):
                                found_keyword = True
                                break
                if found_keyword:
                    break

            if found_keyword:
                if page.number > 0:
                    first_chapter_page = page.number
                    break

        if (
            first_chapter_page is None
            and self.document_data.toc
            and self.document_data.toc.entries
        ):
            first_chapter_page = self.document_data.toc.entries[0].page - offset

        wrong_pages = []
        for page in self.document_data.pages:
            footer_block = None

            for block in page.text_blocks:
                if block.block_type == "footer":
                    footer_block = block

            if first_chapter_page is not None and page.number < first_chapter_page:
                if footer_block:
                    if lang == "en":
                        comment = f"Numbering detected on page{page.number}, which comes before the first chapter or heading (expected from page {first_chapter_page})."
                    else:
                        comment = f"Wykryto numerację na stronie {page.number}, która znajduje się przed pierwszym rozdziałem lub nagłówkiem (oczekiwano od strony {first_chapter_page})."

                    self.errors.append(
                        Error(
                            id=self._get_next_id(),
                            module=self.module,
                            category="Footer_on_forbidden_page",
                            page_number=page.number,
                            bounding_box=footer_block.bbox,
                            text="Footer detected",
                            comments=comment,
                        )
                    )
            else:
                if footer_block is None:
                    if lang == "en":
                        comment = (
                            f"Missing page numbering detected on page {page.number}"
                        )
                    else:
                        comment = f"Wykryto brak numeracji na stronie {page.number}"

                    self.errors.append(
                        Error(
                            id=self._get_next_id(),
                            module=self.module,
                            category="No_footer",
                            page_number=page.number,
                            bounding_box=(
                                self.document_data.pages[page.number].width / 2 - 20,
                                self.document_data.pages[page.number].height - 60,
                                self.document_data.pages[page.number].width / 2 + 20,
                                self.document_data.pages[page.number].height - 30,
                            ),
                            text=None,
                            comments=comment,
                        )
                    )
                else:
                    raw_text = " ".join(
                        [
                            " ".join([span.text for span in line.spans])
                            for line in footer_block.lines
                        ]
                    )
                    match = re.search(r"(\d+)", raw_text)

                    if match:
                        detected_num = int(match.group(1))
                        if detected_num != page.number + offset:
                            wrong_pages.append(
                                (page.number, detected_num, footer_block.bbox, raw_text)
                            )

        # Błędna numeracja zwykle przesuwa się na wszystkie kolejne strony,
        # więc zgłaszamy ją raz - przy pierwszym wystąpieniu
        if wrong_pages:
            page_nr, detected_num, bbox, raw_text = wrong_pages[0]
            other_pages = ", ".join(str(p[0]) for p in wrong_pages[1:])
            if lang == "en":
                comment = f"Invalid page number. Detected: {detected_num}, expected: {page_nr + offset}."
                if other_pages:
                    comment += f" Check the following pages as well - incorrect numbering also detected on pages: {other_pages}."
            else:
                comment = f"Błędny numer strony. Wykryto: {detected_num}, oczekiwano: {page_nr + offset}."
                if other_pages:
                    comment += f" Sprawdź również kolejne strony - błędną numerację wykryto także na stronach: {other_pages}."

            self.errors.append(
                Error(
                    id=self._get_next_id(),
                    module=self.module,
                    category="Wrong_page_number",
                    page_number=page_nr,
                    bounding_box=bbox,
                    text=raw_text,
                    comments=comment,
                )
            )

        # A thesis numbered from a wrong start is reported once. Its lists can still be checked: they use the same numbers.
        # Errors on page 0 are dropped with the title page, so it is reported on the first page after it.
        page = next((p for p in self.document_data.pages if p.number > 0 and _footer_number(p) is not None), None)
        if offset not in VALID_PAGE_OFFSETS and page is not None:
            printed, expected = _footer_number(page), page.number + 1
            if lang == "en":
                comment = f"The page numbering starts from a wrong number. Detected: {printed}, expected: {expected}."
            else:
                comment = f"Numeracja stron zaczyna się od złego numeru. Wykryto: {printed}, oczekiwano: {expected}."
            footer = next(b for b in page.text_blocks if b.block_type == "footer")
            self.errors.append(
                Error(
                    id=self._get_next_id(),
                    module=self.module,
                    category="Wrong_page_numbering_start",
                    page_number=page.number,
                    bounding_box=footer.bbox,
                    text=str(printed),
                    comments=comment,
                )
            )

        is_ftr_error = False
        for error in self.errors:
            if error.category == "No_footer" or error.category == "Wrong_page_number":
                is_ftr_error = True
        if is_ftr_error:
            if lang == "en":
                comment = "Due to incorrect page numbering, it is impossible to check the correctness of the table of contents, figures and tables."
            else:
                comment = "Z racji niepoprawnej numeracji stron, niemożliwe jest sprawdzenie poprawności spisu treści, rysunków oraz tabel."

            self.errors.append(
                Error(
                    id=self._get_next_id(),
                    module=self.module,
                    category="numeration_invalid",
                    page_number=1,
                    bounding_box=(0, 0, 0, 0),
                    text=None,
                    comments=comment,
                )
            )
        return None

    # ------------------config checks-----------------------
    def check_interline_spacing(self, doc_data: DocumentData) -> bool:
        line_spacing = doc_data.get_dominant_line_spacing()
        lang = getattr(self, "language", "pl")
        if lang == "en":
            comment = f"The line spacing used ({line_spacing}) does not match the required line spacing ({self.config.interlinia})."
        else:
            comment = f"Używana interlinia ({line_spacing}) jest niezgodna z wymaganą interlinią ({self.config.interlinia})."

        if line_spacing is None:
            if lang == "en":
                logger.warning("Redaction: cannot specify line spacing")
            else:
                logger.warning("Redaction: nie można określić interlinii")
            return True
        elif abs(line_spacing - self.config.interlinia) > 0.1:
            self.errors.append(
                Error(
                    id=self._get_next_id(),
                    module=self.module,
                    category="config_file",
                    page_number=None,
                    bounding_box=(0, 0, 0, 0),
                    text=None,
                    comments=comment,
                )
            )
            return False
        else:
            return True

    def check_page_count(self, doc_data: DocumentData) -> bool:
        page_count = doc_data.get_page_count()
        lang = getattr(self, "language", "pl")

        if lang == "en":
            comment = f"The document has {page_count} pages, less than the minimum number of {self.config.min_stron}"
        else:
            comment = f"Dokument ma {page_count} stron, mniej niż minimalna liczba {self.config.min_stron}"

        if page_count < self.config.min_stron:
            self.errors.append(
                Error(
                    id=self._get_next_id(),
                    module=self.module,
                    category="config_file",
                    page_number=None,
                    bounding_box=(0, 0, 0, 0),
                    text=None,
                    comments=comment,
                )
            )
            return False
        elif page_count > self.config.max_stron:
            if lang == "en":
                comment = f"The document has {page_count} pages, more than the maximum number of {self.config.max_stron}."
            else:
                comment = f"Dokument ma {page_count} stron, więcej niż maksymalna liczba {self.config.max_stron}."

            self.errors.append(
                Error(
                    id=self._get_next_id(),
                    module=self.module,
                    category="config_file",
                    page_number=None,
                    bounding_box=(0, 0, 0, 0),
                    text=None,
                    comments=comment,
                )
            )
            return False
        else:
            return True

    def check_font_size(self, doc_data: DocumentData) -> bool:
        most_used_font_size = max(
            doc_data.get_font_size_usage(),
            key=doc_data.get_font_size_usage().get,
            default=None,
        )
        lang = getattr(self, "language", "pl")
        if most_used_font_size is None:
            if lang == "en":
                logger.warning("Redaction: Unable to determine font size.")
            else:
                logger.warning("Redaction: nie można określić rozmiaru czcionki.")
            return True
        elif abs(most_used_font_size - self.config.font_size) > 0.1:
            if lang == "en":
                comment = f"The font size used ({most_used_font_size}) does not match the required font size ({self.config.font_size})."
            else:
                comment = f"Używany rozmiar czcionki ({most_used_font_size}) jest niezgodny z wymaganym rozmiarem czcionki ({self.config.font_size})."
            self.errors.append(
                Error(
                    id=self._get_next_id(),
                    module=self.module,
                    category="config_file",
                    page_number=None,
                    bounding_box=(0, 0, 0, 0),
                    text=None,
                    comments=comment,
                )
            )
            return False
        else:
            return True

    def check_margins(self, doc_data: DocumentData) -> bool:
        margins = doc_data.get_margins()
        lang = getattr(self, "language", "pl")
        if not margins:
            if lang == "en":
                logger.warning("Redaction: Cannot determine margins")
            else:
                logger.warning("Redaction: nie można określić marginesów")
            return True
        if self.config.margin_type != "lustrzany":
            return True

        # Visible text bounds are not the configured text area: short symbol
        # lists, headings and last paragraph lines cannot prove a margin error.
        evidence = {}
        for page in doc_data.pages:
            lines = []
            for block in getattr(page, "text_blocks", []):
                for line in block.lines:
                    text = " ".join(span.text for span in line.spans)
                    box = line.bbox
                    if sum(ch.isalpha() for ch in text) >= 20 and box[2] - box[0] >= page.width * .60:
                        lines.append(box)
            if len(lines) < 3:
                continue
            left = min(box[0] for box in lines)
            right = max(box[2] for box in lines)
            if sum(abs(box[0] - left) <= 5 and abs(box[2] - right) <= 5 for box in lines) < 3:
                continue
            evidence[page.number] = (left, page.width - right)

        groups = {parity: [v for n, v in evidence.items() if n % 2 == parity] for parity in (0, 1)}
        if any(len(values) < 2 for values in groups.values()):
            return True  # insufficient full-width text on both page sides
        def median(values):
            values = sorted(values)
            middle = len(values) // 2
            return (values[middle] + values[~middle]) / 2

        references = {parity: tuple(median([v[i] for v in values]) for i in (0, 1))
                      for parity, values in groups.items()}
        tolerance = 8.5  # 3 mm: font bearings and PDF extraction rounding
        mirror_pattern = (abs(references[0][0] - references[1][1]) <= tolerance
                          and abs(references[0][1] - references[1][0]) <= tolerance
                          and abs(references[0][0] - references[0][1]) > tolerance)
        bad_pages = []
        for page_num, margin in evidence.items():
            expected = references[page_num % 2]
            # Indentation and short lines may enlarge the visible margins. Only
            # text intruding into an established margin proves a violation.
            if mirror_pattern and all(a >= b - tolerance for a, b in zip(margin, expected)):
                continue
            bad_pages.append(page_num)
        if not bad_pages:
            return True

        # One finding for the whole thesis (shown as its own section: all pages or ranges of pages), not a marker on
        # every page. `text` carries the data: the pages and how many pages could be measured.
        share = len(bad_pages) / len(evidence)
        if lang == "en":
            comment = (f"Inconsistent mirror margins on {len(bad_pages)} of {len(evidence)} measured pages "
                       f"({share:.0%}).")
        else:
            comment = (f"Niespójne marginesy lustrzane na {len(bad_pages)} z {len(evidence)} ocenionych stron "
                       f"({share:.0%}).")
        self.errors.append(Error(id=self._get_next_id(), module=self.module, category="inconsistent_margins",
                                 page_number=None, bounding_box=(0, 0, 0, 0),
                                 text=json.dumps({"pages": sorted(bad_pages), "evaluated": len(evidence)}),
                                 comments=comment))
        return False

    def check_format(self, doc_data: DocumentData) -> bool:
        tolerance = 10
        lang = getattr(self, "language", "pl")

        formats = {"a5": (420, 595), "a4": (595, 842), "a3": (842, 1191)}

        expected_format = self.config.format.lower()

        if expected_format not in formats:
            if lang == "en":
                logger.warning(
                    "Redaction: unknown page format in the configuration file"
                )
            else:
                logger.warning("Redaction: nieznany format strony w konfiguracji")

            return False
        exp_w, exp_h = formats[expected_format]
        for page_num, (width, height) in doc_data.get_page_dimensions().items():
            if lang == "en":
                comment = f"The page format used (dimensions: {width}x{height}) does not comply with the requirements of {expected_format.upper()}"
            else:
                comment = f"Używany format strony (wymiary: {width}x{height})jest niezgodny z wymaganiami {expected_format.upper()}"

            if not (
                (abs(width - exp_w) <= tolerance and abs(height - exp_h) <= tolerance)
                or (
                    abs(width - exp_h) <= tolerance and abs(height - exp_w) <= tolerance
                )
            ):
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="config_file",
                        page_number=page_num,
                        bounding_box=(0, 0, 0, 0),
                        text=None,
                        comments=comment,
                    )
                )
                return False
        return True

    def check_orientation(self, doc_data: DocumentData) -> bool:
        doc_data.get_page_dimensions()
        lang = getattr(self, "language", "pl")
        for page_num, (width, height) in doc_data.get_page_dimensions().items():
            if self.config.orientation == "pionowa" and width > height:
                if lang == "en":
                    comment = f"Page orientation ({width}x{height}) does not meet requirements (vertical)."
                else:
                    comment = f"Orientacja strony ({width}x{height}) niezgodna z wymaganiami (pionowa)."

                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="config_file",
                        page_number=page_num,
                        bounding_box=(0, 0, 0, 0),
                        text=None,
                        comments=comment,
                    )
                )
                return False
            elif self.config.orientation == "pozioma" and height > width:
                if lang == "en":
                    comment = f"Page orientation ({width}x{height}) does not meet requirements (horizontal)."
                else:
                    comment = f"Orientacja strony ({width}x{height}) niezgodna z wymaganiami (pozioma)."

                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="config_file",
                        page_number=page_num,
                        bounding_box=(0, 0, 0, 0),
                        text=None,
                        comments=comment,
                    )
                )
                return False
            else:
                return True

    def check_fonts(self, doc_data: DocumentData) -> bool:
        font_usage = doc_data.get_font_usage()
        lang = getattr(self, "language", "pl")
        if not font_usage:
            if lang == "en":
                logger.warning("Redaction: Unable to determine used fonts")
            else:
                logger.warning("Redaction: nie można określić używanych czcionek")
            return True
        for font in font_usage.keys():
            if font not in self.config.font_list:
                if lang == "en":
                    comment = (
                        f"The font used ({font}) does not match the required font."
                    )
                else:
                    comment = (
                        f"Używana czcionka ({font}) jest niezgodna z wymaganą czcionką."
                    )
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="config_file",
                        page_number=None,
                        bounding_box=(0, 0, 0, 0),
                        text=None,
                        comments=comment,
                    )
                )
                return False
        return True

    def check_justification(self, doc_data: DocumentData) -> bool:
        expected_justified = self.config.justowanie
        errors_found = False
        lang = getattr(self, "language", "pl")

        for page in doc_data.pages:
            for block in page.text_blocks:
                if self.is_paragraph(block):
                    lines = block.lines

                    if len(lines) <= 1:
                        continue

                    for i in range(len(lines) - 1):
                        line = lines[i]

                        if not line.spans:
                            continue

                        is_justified = line.alignement == "justified"

                        if expected_justified and not is_justified:
                            if lang == "en":
                                comment = f"Lack of justification detected in the paragraph (line {i + 1})"
                            else:
                                comment = f"Wykryto brak justowania w akapicie (linia {i + 1})"
                            self.errors.append(
                                Error(
                                    id=self._get_next_id(),
                                    module=self.module,
                                    category="justification",
                                    page_number=page.number,
                                    bounding_box=line.bbox,
                                    text=None,
                                    comments=comment,
                                )
                            )
                            errors_found = True

                        elif not expected_justified and is_justified:
                            if lang == "en":
                                comment = f"Incorrect justification detected in the paragraph (line {i + 1})"
                            else:
                                comment = f"Wykryto niepoprawne justowanie w akapicie (linia {i + 1})"
                            self.errors.append(
                                Error(
                                    id=self._get_next_id(),
                                    module=self.module,
                                    category="justification",
                                    page_number=page.number,
                                    bounding_box=line.bbox,
                                    text=None,
                                    comments=comment,
                                )
                            )
                            errors_found = True

        if not errors_found:
            if lang == "en":
                logger.info("Redaction: Justification as required")
            else:
                logger.info("Redaction: justowanie zgodne z wymaganiami")

        return not errors_found

    def check_list_order(self):
        lang = getattr(self, "language", "pl")
        if self.document_data.toc and self.document_data.toc.entries:
            error_found_toc = False
            entries_toc = self.document_data.toc.entries

            for i in range(1, len(entries_toc)):
                current_entry_toc = entries_toc[i]
                previous_entry_toc = entries_toc[i - 1]

                if current_entry_toc.page < previous_entry_toc.page:
                    error_found_toc = True
                    break

            if error_found_toc:
                if lang == "en":
                    comment = "Descending numbering in the table of contents has been detected. Subsequent table of contents entries should be arranged in non-descending order relative to the page number they appear on."
                else:
                    comment = "Wykryto malejącą numerację w spisie treści. Kolejne wpisy spisu treści powinny zostać ustawione niemalejąco względem numeru strony, na którym się znajdują."
                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="toc_order_error",
                        page_number=self.document_data.toc.page_nums[0],
                        bounding_box=(0, 0, 0, 0),
                        text=None,
                        comments=comment,
                    )
                )

        if self.document_data.tof and self.document_data.tof.entries:
            error_found_tof = False
            entries_tof = self.document_data.tof.entries

            for i in range(1, len(entries_tof)):
                current_entry_tof = entries_tof[i]
                previous_entry_tof = entries_tof[i - 1]

                if current_entry_tof.page < previous_entry_tof.page:
                    error_found_tof = True
                    break

            if error_found_tof:
                if lang == "en":
                    comment = "Descending numbering has been detected in the figure list. Subsequent figure list entries should be set non-descendingly relative to the page number they appear on."
                else:
                    comment = "Wykryto malejącą numerację w spisie figur. Kolejne wpisy spisu figur powinny zostać ustawione niemalejąco względem numeru strony, na którym się znajdują."

                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="tof_order_error",
                        page_number=self.document_data.tof.page_nums[0],
                        bounding_box=(0, 0, 0, 0),
                        text=None,
                        comments=comment,
                    )
                )

        if self.document_data.tot and self.document_data.tot.entries:
            error_found_tot = False
            entries_tot = self.document_data.tot.entries

            for i in range(1, len(entries_tot)):
                current_entry_tot = entries_tot[i]
                previous_entry_tot = entries_tot[i - 1]

                if current_entry_tot.page < previous_entry_tot.page:
                    error_found_tot = True
                    break

            if error_found_tot:
                if lang == "en":
                    comment = "Descending numbering has been detected in the table list. Subsequent table list entries should be set non-descendingly relative to the page number they appear on."
                else:
                    comment = "Wykryto malejącą numerację w spisie tabel. Kolejne wpisy spisu tabel powinny zostać ustawione niemalejąco względem numeru strony, na którym się znajdują."

                self.errors.append(
                    Error(
                        id=self._get_next_id(),
                        module=self.module,
                        category="tot_order_error",
                        page_number=self.document_data.tot.page_nums[0],
                        bounding_box=(0, 0, 0, 0),
                        text=None,
                        comments=comment,
                    )
                )
        return

    def is_paragraph(self, block):
        """
        Funkcja sprawdzająca, czy bloki to paragraph
        """
        block_type = getattr(block, "type", "")
        if block_type is None:
            block_type = ""

        block_type_lower = block_type.lower()
        types = ["paragraph"]

        if any(i_type in block_type_lower for i_type in types):
            return True

        return False


    def log_all_errors(self):
        """
        Iterates through every error to get logging info
        """
        if not self.errors:
            logger.info("No errors to log")
            return

        logger.info(f" Redaction Error Summary ({len(self.errors)}) errors")
        for error in self.errors:
            error_id = getattr(error, "id", "No ID")
            category = getattr(error, "category", "No Category")
            page = getattr(error, "page_number", "Unknown")
            text = getattr(error, "text", "")
            
            if text:
                text_preview = text.strip().replace("\n", " ")
                if len(text_preview) > 60:
                    text_preview = text_preview[:57] + "..."
            else:
                text_preview = ""

            logger.info(
                f"ID: {error_id} | type: {category} | page: {page} | text: {text_preview!r}"
            )