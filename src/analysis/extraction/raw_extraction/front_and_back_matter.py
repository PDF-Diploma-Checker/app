from abc import ABC, abstractmethod
import fitz  # PyMuPDF
import logging
import re

from analysis.extraction.raw_extraction.bare_struct import (
    PageData,
    TocData,
    TocEntry,
    TofData,
    TofEntry,
    TotData,
    TotEntry,
)


# lists a thesis may have after its figures and tables: their entries look the same ("4.1 Konfiguracja ... 45")
OTHER_LISTS = (
    "spis listingów", "spis listingow", "wykaz listingów", "wykaz listingow", "list of listings",
    "spis kodów", "spis kodow", "wykaz kodów", "wykaz kodow", "spis algorytmów", "spis algorytmow",
    "wykaz algorytmów", "wykaz algorytmow", "list of algorithms", "spis załączników", "wykaz załączników",
)

LIST_TITLES = (
    "spis rysunkow", "spis rysunków", "spis ilustracji", "spis wykresow", "spis wykresów", "wykaz rysunkow", "wykaz rysunków",
    "list of figures", "table of figures", "table of graphs",
    "spis tabel", "spis tablic", "wykaz tabel", "list of tables",
) + OTHER_LISTS


def _clean_title(text):
    """A title for comparing: LaTeX fonts can leave an accent apart from its letter, "SPIS RYSUNK ´ OW"."""
    return " ".join(re.sub(r"\s*[´`˙˛¸]\s*", "", text.lower()).split())


def _opens_with_title(page, titles):
    """True when the page starts with one of the titles (its top lines, a running header may come first)."""
    top = [
        " ".join(span.text.strip() for span in line.spans if span.text.strip())
        for block in page.text_blocks
        for line in block.lines
        if line.bbox[1] < page.height * 0.15
    ]
    return any(_clean_title(text).startswith(titles) for text in top)


def _rows(page):
    """The lines of a page grouped into rows, keyed by the top of each row. A title with a formula in it sits a little
    higher than its number and page ("5.2." at 498, "Transformata ... sin(2π⋅50t)" at 496), so a row is the lines
    whose middles fall within the first line of the row, not the lines of the same rounded top."""
    rows = {}
    bounds = []
    for line in sorted((line for block in page.text_blocks for line in block.lines), key=lambda line: line.bbox[1]):
        middle = (line.bbox[1] + line.bbox[3]) / 2
        key = next((top for top, bottom in bounds if top <= middle <= bottom), None)
        if key is None:
            key = line.bbox[1]
            bounds.append((line.bbox[1], line.bbox[3]))
        rows.setdefault(key, []).append(line)
    return rows


def _continues_title(match, open_number):
    """True when a line of a list that looks like a new entry goes on with the open one: a title wrapped after "0," reads
    "2 m przed nim", but the numbers of a list are all as deep as each other (5.1, 5.2), and "2" is not."""
    return bool(match and open_number) and match.group(1).count(".") != open_number.count(".")


LIST_INDENT_SHIFT = 60


def _goes_on_with_list(listed, page_entries):
    """True when the entries read on the page after a list carry that list on. The page after a list can be a chapter
    whose figure holds lines like "A.1 ... 0": they point back in the document and stand away from the list's left edge,
    while a list goes on with page numbers that do not go back and with entries under each other."""
    if not listed:
        return True
    left = min(entry.bbox[0] for entry in listed)
    return page_entries[0].page >= listed[-1].page and min(entry.bbox[0] for entry in page_entries) - left < LIST_INDENT_SHIFT


class Extractor(ABC):
    """Base class for all extractors."""

    @abstractmethod
    def extract(self, *args, **kwargs):
        pass


class TableOfContentsExtractor(Extractor):
    """Extractor for Table of Contents (TOC)."""

    def extract(self, doc: fitz.Document, pages: list[PageData]) -> TocData | None:
        try:
            keywords = ["spis treści", "spis tresci", "table of contents", "contents", "toc"]
            all_entries = []
            toc_pages = []
            base_x = None

            is_detecting = True

            for page_obj in pages[:15]:
                if not is_detecting:
                    break
                if toc_pages and _opens_with_title(page_obj, LIST_TITLES):  # looks like more of the contents, but is not
                    break

                y_groups = {}
                y_groups.update(_rows(page_obj))

                page_entries = []
                page_text = ""

                for y in sorted(y_groups.keys()):
                    lines_on_y = sorted(y_groups[y], key=lambda line: line.bbox[0])

                    fragments = []
                    for line in lines_on_y:
                        for span in line.spans:
                            txt = span.text.strip()
                            if txt:
                                fragments.append(txt)

                    if not fragments:
                        continue

                    line_full_text = " ".join(fragments)
                    page_text += line_full_text + " "

                    match = re.search(r"^(.*?)(?:\.|\s)*\s+(\d+)$", line_full_text)

                    if match:
                        title_raw, p_num = match.groups()
                        title_clean = re.sub(r"[\.\s·-]{2,}", " ", title_raw).strip()

                        if len(title_clean) < 3:
                            continue

                        current_x = lines_on_y[0].bbox[0]
                        if base_x is None:
                            base_x = current_x

                        gap_level = 1 + int(max(0, current_x - base_x) / 12)

                        num_match = re.match(r"^(\d+(?:\.\d+)*)\.?", title_clean)
                        dotted_level = num_match.group(1).count(".") + 1 if num_match else 1

                        is_bold = any(
                            "bold" in span.font.lower()
                            for line in lines_on_y
                            for span in line.spans
                        )

                        if is_bold and gap_level == 1:
                            final_level = 1
                        else:
                            final_level = max(gap_level, dotted_level)

                        page_entries.append(
                            TocEntry(
                                level=final_level,
                                title=title_clean,
                                page=int(p_num),
                                bbox=lines_on_y[0].bbox,
                                src_page=page_obj.number,
                            )
                        )

                low_page_text = page_text.lower()
                has_keyword = any(word in low_page_text for word in keywords)

                if (has_keyword and len(page_entries) >= 2) or len(page_entries) >= 5:
                    all_entries.extend(page_entries)
                    if page_obj.number not in toc_pages:
                        toc_pages.append(page_obj.number)
                elif len(toc_pages) > 0:
                    is_detecting = False

            if all_entries:
                return TocData(
                    page_nums=toc_pages, entries=all_entries, text="Wykryto wizualnie "
                )

            built_in_toc = doc.get_toc()
            if built_in_toc:
                entries = [
                    TocEntry(
                        level=level,
                        title=title.strip(),
                        page=page,
                        bbox=(0, 0, 0, 0),
                        src_page=-1,
                    )
                    for level, title, page in built_in_toc
                ]
                return TocData(page_nums=[-1], entries=entries, text="Wykryto z metadanych")

            return None
        except Exception as e:
            logging.error(f"Error extracting Table of Contents: {e}")
            return None


class TableOfFiguresExtractor(Extractor):
    """Extractor for Table of Figures (TOF)."""

    def extract(
        self, pages: list[PageData], toc_pages: list[int]
    ) -> TofData | None:
        try:
            keywords = [
                "spis rysunków",
                "spis rysunkow",
                "spis ilustracji",
                "list of figures",
                "table of figures",
                "wykaz rysunkow",
                "wykaz rysunków",
                "spis wykresów",
                "table of graphs",
            ]
            anti_keywords = [
                "spis tabel",
                "spis tablic",
                "list of tables",
                "wykaz tabel",
                "bibliografia",
                "bibliography",
            ] + list(OTHER_LISTS)
            all_entries = []
            tof_pages = []
            is_detecting = False

            for page_obj in pages:
                if page_obj.number in toc_pages:
                    continue
                page_text = ""
                y_groups = {}

                y_groups.update(_rows(page_obj))

                has_keyword_on_top = False
                has_anti_keyword_on_top = False
                top_lines_text = ""

                for y in sorted(y_groups.keys()):
                    first_line_in_group = y_groups[y][0]
                    if first_line_in_group.bbox[1] < (page_obj.height * 0.15):
                        lines_on_y = sorted(y_groups[y], key=lambda line: line.bbox[0])
                        for line in lines_on_y:
                            top_lines_text += (
                                " ".join(
                                    [
                                        span.text.strip()
                                        for span in line.spans
                                        if span.text.strip()
                                    ]
                                )
                                + " "
                            )
                    else:
                        break

                top_text_low = _clean_title(top_lines_text)
                if any(word in top_text_low for word in keywords):
                    has_keyword_on_top = True
                if any(word in top_text_low for word in anti_keywords):
                    has_anti_keyword_on_top = True

                if has_keyword_on_top:
                    is_detecting = True
                elif is_detecting:
                    if has_anti_keyword_on_top or (
                        tof_pages and page_obj.number != (tof_pages[-1] + 1)
                    ):
                        is_detecting = False

                page_entries = []
                list_ended = False
                cut_obj_num = ""
                cut_title = ""
                for y in sorted(y_groups.keys()):
                    lines_on_y = sorted(y_groups[y], key=lambda line: line.bbox[0])
                    fragments = []
                    for line in lines_on_y:
                        for span in line.spans:
                            txt = span.text.strip()
                            if txt:
                                fragments.append(txt)
                    if not fragments:
                        continue

                    line_full_text = " ".join(fragments)
                    if _clean_title(line_full_text) in keywords:
                        page_text += line_full_text + " "
                        continue
                    if _clean_title(line_full_text) in anti_keywords:
                        # another list starts on the same page: the rest of the page is not this list
                        list_ended = True
                        break

                    page_text += line_full_text + " "
                    match_full = re.search(
                        r"^(?:[A-Z][a-zśł]{3,10}\.?\s*)?((?:[A-Z]\.)?\d+(?:\.\d+)*)\.?\s+(.*?)(?:\.|\s)*\s+(\d+)$",
                        line_full_text,
                    )
                    match_start = re.match(
                        r"^(?:[A-Z][a-zśł]{3,10}\.?\s*)?((?:[A-Z]\.)?\d+(?:\.\d+)*)\.?\s+(.*)",
                        line_full_text,
                    )
                    match_end = re.search(r"(.*?)(?:\.|\s)*\s+(\d+)$", line_full_text)
                    if _continues_title(match_full or match_start, cut_obj_num):
                        match_full = match_start = None

                    if match_full:
                        obj_num, title_raw, p_num = match_full.groups()
                        sep = "" if cut_title.endswith("-") else " "
                        base_title = cut_title[:-1] if cut_title.endswith("-") else cut_title
                        full_title = (base_title + sep + title_raw).strip()
                        title_clean = re.sub(r"[\.\s·-]{2,}", " ", full_title).strip()
                        page_entries.append(
                            TofEntry(
                                number=obj_num,
                                title=title_clean,
                                page=int(p_num),
                                bbox=lines_on_y[0].bbox,
                                src_page=page_obj.number,
                            )
                        )
                        cut_obj_num = ""
                        cut_title = ""
                    elif match_start:
                        cut_obj_num = match_start.group(1)
                        cut_title = match_start.group(2)
                    elif match_end and cut_obj_num:
                        title_part, p_num = match_end.groups()
                        sep = "" if cut_title.endswith("-") else " "
                        base_title = cut_title[:-1] if cut_title.endswith("-") else cut_title
                        full_title = (base_title + sep + title_part).strip()
                        title_clean = re.sub(r"[\.\s·-]{2,}", " ", full_title).strip()
                        page_entries.append(
                            TofEntry(
                                number=cut_obj_num,
                                title=title_clean,
                                page=int(p_num),
                                bbox=lines_on_y[0].bbox,
                                src_page=page_obj.number,
                            )
                        )
                        cut_obj_num = ""
                        cut_title = ""
                    elif cut_obj_num:
                        sep = "" if cut_title.endswith("-") else " "
                        base_title = cut_title[:-1] if cut_title.endswith("-") else cut_title
                        cut_title = base_title + sep + line_full_text

                if is_detecting and page_entries:
                    if len(tof_pages) == 0 and len(page_entries) < 2 and not _opens_with_title(page_obj, tuple(keywords)):
                        is_detecting = False
                    elif not has_keyword_on_top and not _goes_on_with_list(all_entries, page_entries):
                        is_detecting = False
                    else:
                        all_entries.extend(page_entries)
                        if page_obj.number not in tof_pages:
                            tof_pages.append(page_obj.number)
                elif is_detecting and not page_entries:
                    is_detecting = False
                if list_ended:
                    is_detecting = False

            # a list with its title and nothing in it, for a thesis without such elements, is still there
            title_pages = [page.number for page in pages if page.number not in toc_pages and _opens_with_title(page, tuple(keywords))]
            if all_entries or title_pages:
                return TofData(page_nums=tof_pages or title_pages, entries=all_entries, text="Spis Rysunków")
            return None
        except Exception as e:
            logging.error(f"Error extracting Table of Figures: {e}")
            return None


class TableOfTablesExtractor(Extractor):
    """Extractor for Table of Tables (TOT)."""

    def extract(
        self, pages: list[PageData], toc_pages: list[int]
    ) -> TotData | None:
        try:
            keywords = ["spis tabel", "spis tablic", "list of tables", "wykaz tabel"]
            anti_keywords = [
                "spis rysunków",
                "spis rysunkow",
                "spis ilustracji",
                "list of figures",
                "table of figures",
                "wykaz rysunkow",
                "wykaz rysunków",
                "spis wykresów",
                "table of graphs",
                "bibliografia",
                "bibliography",
            ] + list(OTHER_LISTS)
            all_entries = []
            tot_pages = []
            is_detecting = False

            for page_obj in pages:
                if page_obj.number in toc_pages:
                    continue
                page_text = ""
                y_groups = {}

                y_groups.update(_rows(page_obj))

                has_keyword_on_top = False
                has_anti_keyword_on_top = False
                top_lines_text = ""

                for y in sorted(y_groups.keys()):
                    first_line_in_group = y_groups[y][0]
                    if first_line_in_group.bbox[1] < (page_obj.height * 0.15):
                        lines_on_y = sorted(y_groups[y], key=lambda line: line.bbox[0])
                        for line in lines_on_y:
                            top_lines_text += (
                                " ".join(
                                    [
                                        span.text.strip()
                                        for span in line.spans
                                        if span.text.strip()
                                    ]
                                )
                                + " "
                            )
                    else:
                        break

                top_text_low = _clean_title(top_lines_text)
                if any(word in top_text_low for word in keywords):
                    has_keyword_on_top = True
                if any(word in top_text_low for word in anti_keywords):
                    has_anti_keyword_on_top = True

                if has_keyword_on_top:
                    is_detecting = True
                elif is_detecting:
                    if has_anti_keyword_on_top or (
                        tot_pages and page_obj.number != (tot_pages[-1] + 1)
                    ):
                        is_detecting = False

                page_entries = []
                list_ended = False
                cut_obj_num = ""
                cut_title = ""
                for y in sorted(y_groups.keys()):
                    lines_on_y = sorted(y_groups[y], key=lambda line: line.bbox[0])
                    fragments = []
                    for line in lines_on_y:
                        for span in line.spans:
                            txt = span.text.strip()
                            if txt:
                                fragments.append(txt)
                    if not fragments:
                        continue

                    line_full_text = " ".join(fragments)
                    if _clean_title(line_full_text) in keywords:
                        page_text += line_full_text + " "
                        continue
                    if _clean_title(line_full_text) in anti_keywords:
                        # another list starts on the same page: the rest of the page is not this list
                        list_ended = True
                        break

                    page_text += line_full_text + " "
                    match_full = re.search(
                        r"^(?:[A-Z][a-zśł]{3,10}\.?\s*)?((?:[A-Z]\.)?\d+(?:\.\d+)*)\.?\s+(.*?)(?:\.|\s)*\s+(\d+)$",
                        line_full_text,
                    )
                    match_start = re.match(
                        r"^(?:[A-Z][a-zśł]{3,10}\.?\s*)?((?:[A-Z]\.)?\d+(?:\.\d+)*)\.?\s+(.*)",
                        line_full_text,
                    )
                    match_end = re.search(r"(.*?)(?:\.|\s)*\s+(\d+)$", line_full_text)
                    if _continues_title(match_full or match_start, cut_obj_num):
                        match_full = match_start = None

                    if match_full:
                        obj_num, title_raw, p_num = match_full.groups()
                        sep = "" if cut_title.endswith("-") else " "
                        base_title = cut_title[:-1] if cut_title.endswith("-") else cut_title
                        full_title = (base_title + sep + title_raw).strip()
                        title_clean = re.sub(r"[\.\s·-]{2,}", " ", full_title).strip()
                        page_entries.append(
                            TotEntry(
                                number=obj_num,
                                title=title_clean,
                                page=int(p_num),
                                bbox=lines_on_y[0].bbox,
                                src_page=page_obj.number,
                            )
                        )
                        cut_obj_num = ""
                        cut_title = ""
                    elif match_start:
                        cut_obj_num = match_start.group(1)
                        cut_title = match_start.group(2)
                    elif match_end and cut_obj_num:
                        title_part, p_num = match_end.groups()
                        sep = "" if cut_title.endswith("-") else " "
                        base_title = cut_title[:-1] if cut_title.endswith("-") else cut_title
                        full_title = (base_title + sep + title_part).strip()
                        title_clean = re.sub(r"[\.\s·-]{2,}", " ", full_title).strip()
                        page_entries.append(
                            TotEntry(
                                number=cut_obj_num,
                                title=title_clean,
                                page=int(p_num),
                                bbox=lines_on_y[0].bbox,
                                src_page=page_obj.number,
                            )
                        )
                        cut_obj_num = ""
                        cut_title = ""
                    elif cut_obj_num:
                        sep = "" if cut_title.endswith("-") else " "
                        base_title = cut_title[:-1] if cut_title.endswith("-") else cut_title
                        cut_title = base_title + sep + line_full_text

                if is_detecting and page_entries:
                    if len(tot_pages) == 0 and len(page_entries) < 2 and not _opens_with_title(page_obj, tuple(keywords)):
                        is_detecting = False
                    elif not has_keyword_on_top and not _goes_on_with_list(all_entries, page_entries):
                        is_detecting = False
                    else:
                        all_entries.extend(page_entries)
                        if page_obj.number not in tot_pages:
                            tot_pages.append(page_obj.number)
                elif is_detecting and not page_entries:
                    is_detecting = False
                if list_ended:
                    is_detecting = False

            # a list with its title and nothing in it, for a thesis without such elements, is still there
            title_pages = [page.number for page in pages if page.number not in toc_pages and _opens_with_title(page, tuple(keywords))]
            if all_entries or title_pages:
                return TotData(page_nums=tot_pages or title_pages, entries=all_entries, text="Spis Tabel")
            return None
        except Exception as e:
            logging.error(f"Error extracting Table of Tables: {e}")
            return None