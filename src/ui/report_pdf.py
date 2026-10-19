"""The "Detailed content analysis report" as a designed PDF: a header band, score tiles, cards with progress bars,
status pills and figure lists, a running header and "page x of y" footers.

    build_report_pdf(report_data, document_name, lang, save_path, ...)

`report_data` is the AI result the app stores for a document (content_grade, ocena, r1..r3, image_analysis,
jakosc_obrazkow, czcionki_obrazkow, statystyki_zdan). No Qt here: only PyMuPDF, so it can be tested on its own.
"""

import datetime
import os
import re

import fitz

from . import styles

# ----------------------------------------------------------------------------- texts
STRINGS = {
    "pl": {
        "yes_upper": "TAK", "no_upper": "NIE", "error": "Błąd", "success": "Sukces",
        "warning": "Ostrzeżenie", "unknown_fig": "Nieznany rysunek", "no_format": "Brak formatu",
        "no_title": "Brak tytułu", "panel_pts": "pkt", "panel_fig_prefix": "Rys.",
        "rep_no_data_warn": "Brak danych szczegółowej analizy merytorycznej dla tego dokumentu.",
        "rep_file_prefix": "Raport_Merytoryczny_", "rep_dialog_title": "Zapisz Raport Szczegółowy",
        "rep_main_title": "Szczegółowy Raport Analizy Merytorycznej", "rep_doc_label": "Dokument:",
        "rep_eval_title": "Ogólna ocena merytoryczna", "rep_score_lbl": "Wynik punktowy:",
        "rep_off_topic_lbl": "Podrozdziały poza tematem:", "rep_off_topic_ident": "Zidentyfikowane sekcje niezgodne z celem pracy:",
        "rep_theory_title": "Weryfikacja merytoryczna rozdziału teoretycznego", "rep_chapter_analyzed": "Analizowany rozdział:",
        "rep_completion_lvl": "Poziom realizacji wytycznych:", "rep_crit_1": "Analiza i ocena istniejących rozwiązań",
        "rep_crit_2": "Wskazanie luki badawczej lub problemu naukowego", "rep_crit_3": "Synteza i krytyczne porównanie metod",
        "rep_ai_eval_title": "Ogólna ocena merytoryczna (AI)", "rep_skipped_fast": "Analiza została pominięta (wybrano Tryb Szybki).",
        "rep_img_title": "Analiza spójności grafik i wykresów (AI)", "rep_img_total": "Zweryfikowane rysunki",
        "rep_img_bad": "Z błędnym opisem w tekście", "rep_img_good": "Poprawne",
        "rep_raster_ident": "Zidentyfikowane grafiki rastrowe podlegające badaniu:", "rep_img_details": "Lista szczegółowa rozbieżności:",
        "rep_qual_title": "Ocena jakości obrazów (DPI i czytelność)", "rep_qual_all_ok": "Wszystkie obrazy mają odpowiednią jakość i czytelność.",
        "rep_qual_err_1": "Wykryto problemy z jakością w", "rep_qual_err_2": "obrazach:", "rep_format_lbl": "Format:",
        "rep_fonts_title": "Spójność czcionek na obrazach", "rep_fonts_all_ok": "Brak wykrytych problemów ze spójnością czcionek na rysunkach.",
        "rep_fonts_err_1": "Wykryto problemy z czcionkami w", "rep_fonts_err_2": "elementach:",
        "rep_img_skip_title": "Ocena jakości obrazów i czcionek", "rep_img_skip_desc": "Analiza została pominięta na życzenie użytkownika lub dokument nie zawiera grafik.",
        "rep_stats_title": "Analiza statystyczna struktury zdań", "rep_stats_desc": "Struktura gramatyczna i stylistyczna badanej pracy dyplomowej:",
        "rep_active_lbl": "Zdania w stronie czynnej", "rep_active_desc": "Zalecana forma wypowiedzi w tekstach naukowych podnosząca dynamikę wywodu.",
        "rep_passive_lbl": "Zdania w stronie biernej", "rep_passive_desc": "Stosowana przy opisie procedur badawczych oraz stanu wiedzy.",
        "rep_verbless_lbl": "Równoważniki zdań", "rep_verbless_desc": "Konstrukcje bezorzecznikowe, dopuszczalne głównie w nagłówkach i spisach.",
        "rep_stats_no_data": "Brak dostępnych danych statystycznych (uruchom analizę w Trybie Dokładnym).",
        "rep_footer_date": "Data:", "rep_success_saved": "Raport został zapisany pomyślnie:\n{}", "rep_err_gen": "Błąd podczas generowania raportu:\n{}",
        "rep_page": "Strona {n} z {total}", "rep_summary": "Podsumowanie", "rep_tile_score": "Ocena merytoryczna",
        "rep_tile_completion": "Realizacja wytycznych", "rep_tile_figures": "Rysunki poprawne", "rep_tile_off": "Sekcje poza tematem",
        "rep_off_pct": "{count} ({percent}%)", "rep_figs_of": "{good} z {total}",
    },
    "en": {
        "yes_upper": "YES", "no_upper": "NO", "error": "Error", "success": "Success",
        "warning": "Warning", "unknown_fig": "Unknown figure", "no_format": "No format",
        "no_title": "No title", "panel_pts": "pts", "panel_fig_prefix": "Fig.",
        "rep_no_data_warn": "No detailed substantive analysis data for this document.",
        "rep_file_prefix": "Content_Report_", "rep_dialog_title": "Save Detailed Report",
        "rep_main_title": "Detailed Content Analysis Report", "rep_doc_label": "Document:",
        "rep_eval_title": "Overall Content Evaluation", "rep_score_lbl": "Score:",
        "rep_off_topic_lbl": "Off-topic subsections:", "rep_off_topic_ident": "Identified sections irrelevant to the thesis objective:",
        "rep_theory_title": "Theoretical Chapter Verification", "rep_chapter_analyzed": "Analyzed chapter:",
        "rep_completion_lvl": "Guideline completion level:", "rep_crit_1": "Analysis and evaluation of existing solutions",
        "rep_crit_2": "Identification of research gap or problem", "rep_crit_3": "Synthesis and critical comparison of methods",
        "rep_ai_eval_title": "Overall Content Evaluation (AI)", "rep_skipped_fast": "Analysis skipped (Fast Mode selected).",
        "rep_img_title": "Graphics and Charts Consistency Analysis (AI)", "rep_img_total": "Verified figures",
        "rep_img_bad": "With incorrect description in text", "rep_img_good": "Correct",
        "rep_raster_ident": "Identified raster graphics subject to analysis:", "rep_img_details": "Detailed list of discrepancies:",
        "rep_qual_title": "Image Quality Assessment (DPI & Legibility)", "rep_qual_all_ok": "All images have adequate quality and legibility.",
        "rep_qual_err_1": "Quality issues detected in", "rep_qual_err_2": "images:", "rep_format_lbl": "Format:",
        "rep_fonts_title": "Font Consistency in Images", "rep_fonts_all_ok": "No font consistency issues detected in figures.",
        "rep_fonts_err_1": "Font issues detected in", "rep_fonts_err_2": "elements:",
        "rep_img_skip_title": "Image Quality and Fonts Assessment", "rep_img_skip_desc": "Analysis skipped by user request or document contains no graphics.",
        "rep_stats_title": "Sentence Structure Statistical Analysis", "rep_stats_desc": "Grammatical and stylistic structure of the analyzed thesis:",
        "rep_active_lbl": "Active voice sentences", "rep_active_desc": "Recommended form of expression in academic texts, enhancing narrative dynamics.",
        "rep_passive_lbl": "Passive voice sentences", "rep_passive_desc": "Used when describing research procedures and state of knowledge.",
        "rep_verbless_lbl": "Sentence equivalents", "rep_verbless_desc": "Verbless constructions, acceptable mainly in headers and lists.",
        "rep_stats_no_data": "No statistical data available (run analysis in Detailed Mode).",
        "rep_footer_date": "Date:", "rep_success_saved": "Report saved successfully:\n{}", "rep_err_gen": "Error during report generation:\n{}",
        "rep_page": "Page {n} of {total}", "rep_summary": "Summary", "rep_tile_score": "Content score",
        "rep_tile_completion": "Guideline completion", "rep_tile_figures": "Correct figures", "rep_tile_off": "Off-topic sections",
        "rep_off_pct": "{count} ({percent}%)", "rep_figs_of": "{good} of {total}",
    },
}

# ----------------------------------------------------------------------------- look
PAGE_W, PAGE_H = 595.0, 842.0
MARGIN = 42.0
CONTENT_W = PAGE_W - 2 * MARGIN
TOP = 66.0                      # first line below the running header of the following pages
BOTTOM = PAGE_H - 56.0          # last line above the footer
HERO_H = 124.0
PAD = 15.0                      # inside a card
LEADING = 1.42


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


C = {
    "primary": _rgb(styles.PRIMARY), "primary_dark": _rgb(styles.PRIMARY_PRESSED), "primary_50": _rgb(styles.PRIMARY_50),
    "primary_100": _rgb(styles.PRIMARY_100), "primary_200": _rgb(styles.PRIMARY_200),
    "text": _rgb(styles.TEXT), "text2": _rgb(styles.TEXT_2), "text3": _rgb(styles.TEXT_3),
    "border": _rgb(styles.BORDER), "bg": _rgb(styles.BG), "white": (1, 1, 1), "neutral_bg": _rgb(styles.NEUTRAL_BG),
    "success": _rgb(styles.SUCCESS), "success_bg": _rgb(styles.SUCCESS_BG), "success_dot": _rgb(styles.SUCCESS_DOT),
    "warning": _rgb(styles.WARNING), "warning_bg": _rgb(styles.WARNING_BG), "warning_dot": _rgb(styles.WARNING_DOT),
    "danger": _rgb(styles.DANGER), "danger_bg": _rgb(styles.DANGER_BG), "danger_dot": _rgb(styles.DANGER_DOT),
    "indigo": _rgb("#6366F1"), "track": _rgb("#E5E7EB"),
}


def _ratio_colors(ratio):
    """(text colour, background, bar colour) for a 0..1 score: green, amber or red."""
    if ratio >= 0.7:
        return C["success"], C["success_bg"], C["success_dot"]
    if ratio >= 0.4:
        return C["warning"], C["warning_bg"], C["warning_dot"]
    return C["danger"], C["danger_bg"], C["danger_dot"]


def _number(value, default=0.0):
    try:
        return float(str(value).replace("%", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def _fmt(value):
    """12.0 -> "12", 7.25 -> "7.25"."""
    value = _number(value)
    return str(int(value)) if value == int(value) else f"{value:.1f}".rstrip("0").rstrip(".")


class _Writer:
    """Page-by-page layout: running header, cards that continue on the next page, footers."""

    def __init__(self, pdf, strings, document_name, today, regular, bold, logo_path):
        self.pdf, self.s, self.name, self.today = pdf, strings, document_name, today
        self.logo_path = logo_path if logo_path and os.path.exists(logo_path) else None
        self.regular_file, self.bold_file = regular, bold
        if regular and bold and os.path.exists(regular) and os.path.exists(bold):
            self.f_main, self.f_bold = "roboto", "roboto-bold"
            self.m_main, self.m_bold = fitz.Font(fontfile=regular), fitz.Font(fontfile=bold)
        else:
            self.regular_file = self.bold_file = None
            self.f_main, self.f_bold = "helv", "hebo"
            self.m_main, self.m_bold = fitz.Font("helv"), fitz.Font("hebo")
        self.page = None
        self.y = 0.0
        self._pending = None
        self.first = True
        self._new_page()

    # ------------------------------------------------------------ pages
    def _fonts(self, page):
        if self.regular_file:
            page.insert_font(fontname=self.f_main, fontfile=self.regular_file, encoding=0)
            page.insert_font(fontname=self.f_bold, fontfile=self.bold_file, encoding=0)

    def _new_page(self):
        self.page = self.pdf.new_page(width=PAGE_W, height=PAGE_H)
        self._fonts(self.page)
        if self.first:
            self._hero()
            self.first = False
            self.y = HERO_H + 26
        else:
            self.text(MARGIN, 34, self.s["rep_main_title"], 9, bold=True, color=C["primary"])
            self.text(PAGE_W - MARGIN - self.width(self.name, 9), 34, self.name, 9, color=C["text2"])
            self.page.draw_line((MARGIN, 44), (PAGE_W - MARGIN, 44), color=C["border"], width=0.8)
            self.y = TOP

    def _hero(self):
        p = self.page
        p.draw_rect(fitz.Rect(0, 0, PAGE_W, HERO_H), color=None, fill=C["primary"])
        p.draw_circle((PAGE_W - 40, 16), 120, color=None, fill=C["white"], fill_opacity=0.07)
        p.draw_circle((PAGE_W - 150, HERO_H + 34), 82, color=None, fill=C["white"], fill_opacity=0.06)
        x = MARGIN
        if self.logo_path:
            p.draw_rect(fitz.Rect(MARGIN, 30, MARGIN + 38, 68), color=None, fill=C["white"], radius=0.22)
            try:
                p.insert_image(fitz.Rect(MARGIN + 6, 36, MARGIN + 32, 62), filename=self.logo_path, keep_proportion=True)
            except Exception:
                pass
            x = MARGIN + 52
        self.text(x, 46, "DiplomaChecker", 11, bold=True, color=(0.86, 0.93, 1.0))
        self.text(x, 62, self.s["rep_footer_date"] + " " + str(self.today), 9, color=(0.86, 0.93, 1.0))
        title_lines = self.wrap(self.s["rep_main_title"], 22, CONTENT_W - 40, bold=True)
        y = 96 if len(title_lines) == 1 else 90
        for line in title_lines[:2]:
            self.text(MARGIN, y, line, 22, bold=True, color=C["white"])
            y += 26
        name = self.fit(f"{self.s['rep_doc_label']} {self.name}", 10.5, CONTENT_W)
        self.text(MARGIN, HERO_H - 8 if len(title_lines) == 1 else HERO_H - 4, name, 10.5, color=(0.86, 0.93, 1.0))

    def ensure(self, height):
        if self.y + height > BOTTOM:
            self._new_page()

    def finish(self):
        total = len(self.pdf)
        for number, page in enumerate(self.pdf, 1):
            self.page = page
            page.draw_line((MARGIN, PAGE_H - 42), (PAGE_W - MARGIN, PAGE_H - 42), color=C["border"], width=0.8)
            self.text(MARGIN, PAGE_H - 27, f"{self.s['rep_footer_date']} {self.today}", 8.5, color=C["text2"])
            label = self.s["rep_page"].format(n=number, total=total)
            self.text(PAGE_W - MARGIN - self.width(label, 8.5), PAGE_H - 27, label, 8.5, color=C["text2"])

    # ------------------------------------------------------------ text
    def width(self, text, size, bold=False):
        return (self.m_bold if bold else self.m_main).text_length(text, fontsize=size)

    def text(self, x, y, text, size, bold=False, color=None):
        self.page.insert_text((x, y), text, fontsize=size, fontname=self.f_bold if bold else self.f_main,
                              color=color or C["text"])

    def wrap(self, text, size, max_width, bold=False):
        lines, current = [], ""
        for word in str(text).split():
            while self.width(word, size, bold) > max_width:       # a word longer than the line: break it
                cut = len(word)
                while cut > 1 and self.width(word[:cut], size, bold) > max_width:
                    cut -= 1
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:cut])
                word = word[cut:]
            trial = f"{current} {word}".strip()
            if self.width(trial, size, bold) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def fit(self, text, size, max_width, bold=False):
        if self.width(text, size, bold) <= max_width:
            return text
        while len(text) > 1 and self.width(text + "…", size, bold) > max_width:
            text = text[:-1]
        return text + "…"

    # ------------------------------------------------------------ building blocks
    def heading(self, title, subtitle=None):
        """Remembered and drawn together with the block that follows, so it is never left alone at a page bottom."""
        self._pending = (title, subtitle)

    def _heading_height(self):
        if not self._pending:
            return 0.0
        title, subtitle = self._pending
        lines = len(self.wrap(subtitle, 9.5, CONTENT_W - 12)) if subtitle else 0
        return 24 + lines * 14 + 8

    def _begin_block(self, height):
        """Start a block of `height` points (after the pending heading): move to a new page when it does not fit."""
        if self.y + self._heading_height() + height > BOTTOM and self.y > TOP + 1:
            self._new_page()
        if self._pending:
            title, subtitle = self._pending
            self._pending = None
            self.page.draw_rect(fitz.Rect(MARGIN, self.y, MARGIN + 4, self.y + 17), color=None, fill=C["primary"], radius=0.5)
            self.text(MARGIN + 12, self.y + 13.5, title, 14.5, bold=True)
            self.y += 24
            if subtitle:
                for line in self.wrap(subtitle, 9.5, CONTENT_W - 12):
                    self.text(MARGIN + 12, self.y + 8, line, 9.5, color=C["text2"])
                    self.y += 14
            self.y += 8

    def tiles(self, items):
        """A row of equal summary tiles: [(value, caption, accent colour)]."""
        gap, h = 10.0, 64.0
        width = (CONTENT_W - gap * (len(items) - 1)) / len(items)
        self._begin_block(h + 12)
        for i, (value, caption, accent) in enumerate(items):
            x = MARGIN + i * (width + gap)
            rect = fitz.Rect(x, self.y, x + width, self.y + h)
            self.page.draw_rect(rect, color=C["border"], fill=C["white"], width=0.8, radius=0.1)
            self.page.draw_rect(fitz.Rect(x, self.y + 12, x + 3.5, self.y + h - 12), color=None, fill=accent, radius=0.5)
            self.text(x + 14, self.y + 29, self.fit(value, 19, width - 22, True), 19, bold=True, color=accent)
            for j, line in enumerate(self.wrap(caption, 8.5, width - 24)[:2]):
                self.text(x + 14, self.y + 45 + j * 10.5, line, 8.5, color=C["text2"])
        self.y += h + 16

    def card(self, rows, keep=False):
        """rows: [(height, draw(x, y, width))]. The card continues on the next page when it does not fit, unless
        `keep` is set and it fits on one page: then it moves there whole."""
        inner = CONTENT_W - 2 * PAD
        segment, used = [], 0.0
        total = sum(h for h, _ in rows) + 2 * PAD
        if keep and total <= BOTTOM - TOP:
            self._begin_block(total)
        else:
            self._begin_block(2 * PAD + (rows[0][0] if rows else 0))

        def flush():
            nonlocal segment, used
            if not segment:
                return
            height = used + 2 * PAD
            radius = min(0.5, 9.0 / min(CONTENT_W, height))
            self.page.draw_rect(fitz.Rect(MARGIN, self.y, MARGIN + CONTENT_W, self.y + height),
                                color=C["border"], fill=C["white"], width=0.8, radius=radius)
            y = self.y + PAD
            for h, draw in segment:
                draw(MARGIN + PAD, y, inner)
                y += h
            self.y += height + 14
            segment, used = [], 0.0

        for height, draw in rows:
            if segment and self.y + used + 2 * PAD + height > BOTTOM:
                flush()
                self._new_page()
            elif not segment and self.y + 2 * PAD + height > BOTTOM:
                self._new_page()
            segment.append((height, draw))
            used += height
        flush()

    # --- rows
    def group(self, rows):
        """Several rows that must stay on one page (e.g. a figure and its list of problems)."""
        def draw(x, y, w):
            for h, fn in rows:
                fn(x, y, w)
                y += h
        return sum(h for h, _ in rows), draw

    def r_gap(self, h):
        return h, lambda x, y, w: None

    def r_text(self, text, size=10.5, bold=False, color=None, indent=0.0, after=3.0):
        lines = self.wrap(text, size, CONTENT_W - 2 * PAD - indent, bold)      # a card's inner width is fixed
        step = size * LEADING

        def draw(x, y, w):
            for i, line in enumerate(lines):
                self.text(x + indent, y + size + i * step - 1, line, size, bold, color)
        return len(lines) * step + after, draw

    def r_bullets(self, items, size=10, color=None, bullet_color=None):
        rows = []
        for item in items:
            rows.append(self._bullet(str(item), size, color, bullet_color or C["primary"]))
        return rows

    def _bullet(self, text, size, color, bullet_color):
        inner = CONTENT_W - 2 * PAD
        lines = self.wrap(text, size, inner - 16)
        step = size * LEADING

        def draw(x, y, w):
            self.page.draw_circle((x + 4, y + size * 0.62), 2.1, color=None, fill=bullet_color)
            for i, line in enumerate(lines):
                self.text(x + 16, y + size + i * step - 1, line, size, False, color)
        return len(lines) * step + 4, draw

    def r_bar(self, label, value_text, ratio, description=None, color=None):
        ratio = max(0.0, min(1.0, ratio))
        text_c, _bg, bar_c = _ratio_colors(ratio)
        bar_c = color or bar_c
        text_c = color or text_c
        desc_lines = self.wrap(description, 9, CONTENT_W - 2 * PAD) if description else []
        height = 17 + 12 + len(desc_lines) * 12.5 + 4

        def draw(x, y, w):
            self.text(x, y + 11, label, 10.5, bold=True)
            self.text(x + w - self.width(value_text, 11, True), y + 11, value_text, 11, bold=True, color=text_c)
            self.page.draw_rect(fitz.Rect(x, y + 19, x + w, y + 26), color=None, fill=C["track"], radius=0.5)
            if ratio > 0:
                self.page.draw_rect(fitz.Rect(x, y + 19, x + max(w * ratio, 7), y + 26), color=None, fill=bar_c, radius=0.5)
            for i, line in enumerate(desc_lines):
                self.text(x, y + 41 + i * 12.5 - 3, line, 9, color=C["text2"])
        return height, draw

    def r_status(self, label, met):
        pill = self.s["yes_upper"] if met else self.s["no_upper"]
        text_c, bg, dot = (C["success"], C["success_bg"], C["success_dot"]) if met else (C["danger"], C["danger_bg"], C["danger_dot"])
        inner = CONTENT_W - 2 * PAD
        lines = self.wrap(label, 10.5, inner - 34 - 56)
        height = max(24, len(lines) * 14.5 + 8) + 4

        def draw(x, y, w):
            cy = y + height / 2 - 2
            self.page.draw_circle((x + 10, cy), 10, color=None, fill=bg)
            if met:
                self.page.draw_polyline([(x + 5.5, cy + 0.5), (x + 8.7, cy + 3.6), (x + 14.5, cy - 3.2)],
                                        color=text_c, width=1.7, closePath=False)
            else:
                self.page.draw_line((x + 6.5, cy - 3.5), (x + 13.5, cy + 3.5), color=text_c, width=1.7)
                self.page.draw_line((x + 13.5, cy - 3.5), (x + 6.5, cy + 3.5), color=text_c, width=1.7)
            top = cy - (len(lines) * 14.5) / 2 + 11
            for i, line in enumerate(lines):
                self.text(x + 30, top + i * 14.5 - 1, line, 10.5, color=C["text"])
            pw = self.width(pill, 9, True) + 20
            self.page.draw_rect(fitz.Rect(x + w - pw, cy - 9.5, x + w, cy + 9.5), color=None, fill=bg, radius=0.5)
            self.text(x + w - pw + 10, cy + 3.2, pill, 9, bold=True, color=text_c)
        return height, draw

    def r_note(self, text, kind="ok"):
        """A coloured notice: green (all fine), red (problem) or grey (skipped)."""
        text_c, bg, dot = {"ok": (C["success"], C["success_bg"], C["success_dot"]),
                           "bad": (C["danger"], C["danger_bg"], C["danger_dot"]),
                           "off": (C["text2"], C["neutral_bg"], C["text2"])}[kind]
        inner = CONTENT_W - 2 * PAD
        lines = self.wrap(text, 10.5, inner - 36)
        height = len(lines) * 14.5 + 20

        def draw(x, y, w):
            self.page.draw_rect(fitz.Rect(x, y, x + w, y + height), color=None, fill=bg, radius=min(0.5, 8 / height))
            self.page.draw_circle((x + 16, y + height / 2), 3.5, color=None, fill=dot)
            top = y + height / 2 - (len(lines) - 1) * 7.25 + 3.9
            for i, line in enumerate(lines):
                self.text(x + 30, top + i * 14.5, line, 10.5, color=text_c)
        return height, draw

    def r_chips(self, labels):
        """Small rounded labels flowing over several lines."""
        inner = CONTENT_W - 2 * PAD
        placed, x, row = [], 0.0, 0
        for label in labels:
            w = self.width(label, 9.5, True) + 18
            if x + w > inner and x > 0:
                x, row = 0.0, row + 1
            placed.append((x, row, w, label))
            x += w + 7
        height = (row + 1) * 25 + 2

        def draw(px, py, w):
            for cx, r, cw, label in placed:
                rect = fitz.Rect(px + cx, py + r * 25, px + cx + cw, py + r * 25 + 20)
                self.page.draw_rect(rect, color=C["primary_200"], fill=C["primary_50"], width=0.7, radius=0.5)
                self.text(px + cx + 9, py + r * 25 + 14, label, 9.5, bold=True, color=C["primary_dark"])
        return height, draw

    def r_label(self, text, color=None, size=10.5, after=6.0):
        return self.r_text(text, size, True, color or C["text"], 0.0, after)

    def r_figure(self, title, subtitle, reasons):
        """One figure with its list of problems: title line, small meta line, bullets."""
        rows = [self.r_text(title, 10.5, True, C["text"], 0.0, 0.0)]
        if subtitle:
            rows.append(self.r_text(subtitle, 9, False, C["text2"], 0.0, 3.0))
        rows += self.r_bullets(reasons, 9.8, C["text3"], C["danger_dot"])
        rows.append(self.r_gap(5))
        return [self.group(rows)]


def build_report_pdf(report_data, document_name, lang, save_path, font_regular=None, font_bold=None, logo_path=None,
                     today=None):
    """Write the report for one document to `save_path`."""
    s = STRINGS.get(lang, STRINGS["pl"])
    report_data = report_data or {}
    pdf = fitz.open()
    w = _Writer(pdf, s, document_name, today or datetime.date.today(), font_regular, font_bold, logo_path)
    try:
        _content(w, s, report_data)
        w.finish()
        pdf.set_metadata({"title": f"{s['rep_main_title']} - {document_name}", "producer": "DiplomaChecker"})
        pdf.save(save_path, deflate=True, garbage=3)
    finally:
        pdf.close()


# ----------------------------------------------------------------------------- the report itself
def _content(w, s, data):
    grade_info = data.get("content_grade")
    img = data.get("image_analysis")
    img = img if isinstance(img, dict) else {}
    has_images = _number(img.get("total", 0)) > 0
    stats = data.get("statystyki_zdan")

    # ---- summary tiles
    tiles = []
    max_g, grade = 100.0, None
    off_topic, p_off, headings = 0, 0, []
    if grade_info is not None:
        if isinstance(grade_info, dict):
            grade = _number(grade_info.get("grade", 0))
            max_g = _number(grade_info.get("max_grade", 100), 100.0) or 100.0
            off_topic = int(_number(grade_info.get("off_topic_sections", 0)))
            p_off = grade_info.get("p_off", 0)
            headings = grade_info.get("off_topic_headings", []) or []
        else:
            grade = _number(grade_info)
        tiles.append((f"{_fmt(grade)} / {_fmt(max_g)}", s["rep_tile_score"], _ratio_colors(grade / max_g)[0]))
        completion = _number(data.get("ocena", 0))
        tiles.append((f"{_fmt(completion)}%", s["rep_tile_completion"], _ratio_colors(completion / 100)[0]))
        tiles.append((s["rep_off_pct"].format(count=off_topic, percent=_fmt(p_off)), s["rep_tile_off"],
                      C["danger"] if off_topic else C["success"]))
    if has_images:
        good, total = int(_number(img.get("good_count", 0))), int(_number(img.get("total", 0)))
        tiles.append((s["rep_figs_of"].format(good=good, total=total), s["rep_tile_figures"],
                      _ratio_colors(good / total if total else 1)[0]))
    if tiles:
        w.heading(s["rep_summary"])
        w.tiles(tiles[:4])

    # ---- overall evaluation
    w.heading(s["rep_eval_title"] if grade_info is not None else s["rep_ai_eval_title"])
    if grade_info is None:
        w.card([w.r_note(s["rep_skipped_fast"], "off")])
    else:
        rows = [w.r_bar(s["rep_score_lbl"].rstrip(":"), f"{_fmt(grade)} / {_fmt(max_g)} {s['panel_pts']}", grade / max_g),
                w.r_gap(4),
                w.r_text(f"{s['rep_off_topic_lbl']} {off_topic} ({_fmt(p_off)}%)", 10.5, False, C["text3"])]
        if off_topic > 0 and headings:
            rows += [w.r_gap(6), w.r_label(s["rep_off_topic_ident"], C["danger"], 10.5, 4)]
            rows += w.r_bullets(headings, 10, C["text"], C["danger_dot"])
        w.card(rows)

        # ---- theoretical chapter
        w.heading(s["rep_theory_title"])
        completion = _number(data.get("ocena", 0))
        rows = [w.r_text(f"{s['rep_chapter_analyzed']} {data.get('tytul') or s['no_title']}", 10.5, True, C["text"], 0.0, 8),
                w.r_bar(s["rep_completion_lvl"].rstrip(":"), f"{_fmt(completion)}%", completion / 100),
                w.r_gap(6)]
        for label, met in ((s["rep_crit_1"], data.get("r1")), (s["rep_crit_2"], data.get("r2")),
                           (s["rep_crit_3"], data.get("r3"))):
            rows.append(w.r_status(label, bool(met)))
        w.card(rows, keep=True)

    # ---- images
    if has_images:
        w.heading(s["rep_img_title"])
        bad = int(_number(img.get("bad_count", 0)))
        rows = [w.r_text(f"{s['rep_img_total']}: {int(_number(img.get('total', 0)))}   |   "
                         f"{s['rep_img_bad']}: {bad}   |   {s['rep_img_good']}: {int(_number(img.get('good_count', 0)))}",
                         10.5, True, C["danger"] if bad else C["success"], 0.0, 4)]
        raster = img.get("raster_numbers", img.get("image_raster", [])) or []
        if raster:
            rows += [w.r_gap(6), w.r_label(s["rep_raster_ident"], C["primary_dark"], 10, 6),
                     w.r_chips([f"{s['panel_fig_prefix']} {n}" for n in raster])]
        details = img.get("details", []) or []
        if details:
            rows += [w.r_gap(8), w.r_label(s["rep_img_details"], C["text"], 10.5, 5)]
            rows += w.r_bullets(details, 10, C["text"], C["danger_dot"])
        w.card(rows)

        w.heading(s["rep_qual_title"])
        quality = data.get("jakosc_obrazkow") or []
        if not quality:
            w.card([w.r_note(s["rep_qual_all_ok"], "ok")])
        else:
            rows = [w.r_note(f"{s['rep_qual_err_1']} {len(quality)} {s['rep_qual_err_2']}", "bad"), w.r_gap(8)]
            for err in quality:
                err = err if isinstance(err, dict) else {"powody_odrzucenia": [str(err)]}
                rows += w.r_figure(str(err.get("rysunek", s["unknown_fig"])),
                                   f"{s['rep_format_lbl']} {err.get('format', s['no_format'])}",
                                   err.get("powody_odrzucenia", []) or [])
            w.card(rows)

        w.heading(s["rep_fonts_title"])
        fonts = data.get("czcionki_obrazkow") or []
        if not fonts:
            w.card([w.r_note(s["rep_fonts_all_ok"], "ok")])
        else:
            rows = [w.r_note(f"{s['rep_fonts_err_1']} {len(fonts)} {s['rep_fonts_err_2']}", "bad"), w.r_gap(8)]
            for err in fonts:
                if isinstance(err, dict):
                    rows += w.r_figure(str(err.get("rysunek", s["unknown_fig"])), None,
                                       [str(b) for b in err.get("errors", err.get("powody_odrzucenia", [str(err)]))])
                else:
                    rows += w.r_bullets([str(err)], 9.8, C["text3"], C["danger_dot"])
            w.card(rows)
    else:
        w.heading(s["rep_img_skip_title"])
        w.card([w.r_note(s["rep_img_skip_desc"], "off")])

    # ---- sentence statistics
    w.heading(s["rep_stats_title"], s["rep_stats_desc"] if stats else None)
    if stats:
        rows = []
        for key, label, desc, colour in (("active_ratio", "rep_active_lbl", "rep_active_desc", C["primary"]),
                                          ("passive_ratio", "rep_passive_lbl", "rep_passive_desc", C["indigo"]),
                                          ("verbless_ratio", "rep_verbless_lbl", "rep_verbless_desc", C["text2"])):
            value = _number(stats.get(key, 0))
            rows += [w.r_bar(s[label], f"{_fmt(value)}%", value / 100, s[desc], color=colour), w.r_gap(6)]
        w.card(rows[:-1], keep=True)
    else:
        w.card([w.r_note(s["rep_stats_no_data"], "off")])
