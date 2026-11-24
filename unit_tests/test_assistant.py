"""The thesis assistant: fragments with pages, the search, the checks of the answer (sources, "not in the thesis"),
the prompt budget and the chat panel. The model itself is not loaded here."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from analysis.modules.llm.assistant import answer as A  # noqa: E402
from analysis.modules.llm.assistant.chunks import build_chunks  # noqa: E402
from analysis.modules.llm.assistant.retrieval import (  # noqa: E402
    WINDOW_WORDS, ThesisIndex, chunk_text_for_embedding, sentence_windows, tokens)


def words(text, page, line=0, start=0):
    out, pos = [], start
    for i, w in enumerate(text.split()):
        out.append(SimpleNamespace(text=w, page_number=page, line=line, start_char=pos, end_char=pos + len(w),
                                   bbox=[70 + i * 30, 100 + line * 14, 95 + i * 30, 110 + line * 14]))
        pos += len(w) + 1
    return out


def block(kind, text, page, line=0):
    return SimpleNamespace(type=kind, content=text, words=words(text, page, line))


DOC = SimpleNamespace(logical_blocks=[
    block("toc", "1. Wstęp .......... 5", 1),
    block("heading", "1. WSTĘP", 4),
    block("paragraph", "Celem pracy jest wytrenowanie robota kroczącego w symulatorze Newton.", 4, 1),
    block("heading", "3. METODY", 20),
    block("paragraph", "Politykę trenowano algorytmem PPO na 32 środowiskach równoległych.", 20, 1),
    block("image_description", "Rys. 3.1. Schemat sieci neuronowej polityki.", 21),
    block("heading", "6. PODSUMOWANIE", 60),
    block("paragraph", "Robot nauczył się chodzić po nierównym terenie, co potwierdza założenia.", 60, 1),
])


def fake_encode(texts):
    """A bag of stems as a vector: enough to test the fusion without the embedding model."""
    vocab = sorted({t for c in DOC_CHUNKS for t in tokens(c["section"] + " " + c["text"])})
    rows = []
    for text in texts:
        v = np.array([1.0 if t in set(tokens(text)) else 0.0 for t in vocab], dtype=np.float32)
        n = np.linalg.norm(v)
        rows.append(v / n if n else v)
    return np.array(rows)


DOC_CHUNKS = build_chunks(DOC)["chunks"]


def fake_encode_for(data, texts):
    """fake_encode over the words of another set of fragments."""
    vocab = sorted({t for c in data["chunks"] for t in tokens(c["text"])})
    rows = []
    for text in texts:
        v = np.array([1.0 if t in set(tokens(text)) else 0.0 for t in vocab], dtype=np.float32)
        n = np.linalg.norm(v)
        rows.append(v / n if n else v)
    return np.array(rows)


class ChunksTest(unittest.TestCase):
    def setUp(self):
        self.data = build_chunks(DOC)

    def test_tables_of_contents_are_left_out_and_sections_kept(self):
        texts = " ".join(c["text"] for c in self.data["chunks"])
        self.assertNotIn("..........", texts)
        self.assertEqual([s["title"] for s in self.data["sections"]], ["1. WSTĘP", "3. METODY", "6. PODSUMOWANIE"])

    def test_a_fragment_keeps_its_page_section_and_line_boxes(self):
        ppo = next(c for c in self.data["chunks"] if "PPO" in c["text"])
        self.assertEqual((ppo["page"], ppo["section"]), (20, "3. METODY"))
        self.assertEqual(len(ppo["rects"]), 1)
        self.assertEqual(ppo["rects"][0][0], 20)

    def test_captions_are_their_own_fragments(self):
        caption = next(c for c in self.data["chunks"] if c["kind"] == "caption")
        self.assertIn("Schemat sieci", caption["text"])

    def test_a_long_paragraph_is_cut_at_sentence_ends(self):
        sentence = "Zdanie " + " ".join(["słowo"] * 59) + "."
        long_doc = SimpleNamespace(logical_blocks=[block("paragraph", " ".join([sentence] * 8), 3)])
        chunks = build_chunks(long_doc)["chunks"]
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(chunk["text"].endswith("."))


class RetrievalTest(unittest.TestCase):
    def setUp(self):
        self.index = ThesisIndex.build(build_chunks(DOC), fake_encode)

    def test_polish_word_forms_meet(self):
        self.assertEqual(tokens("trenowania")[0], tokens("trenowano")[0])

    def test_an_exact_term_finds_its_fragment(self):
        found = self.index.search("Jakiego algorytmu PPO użyto?", fake_encode, k=3)
        self.assertIn("PPO", found[0][0]["text"])

    def test_the_introduction_and_conclusions_lead_for_a_question_about_the_whole_thesis(self):
        found = self.index.search("Jaki jest główny wniosek pracy?", fake_encode, k=3, boost=A.overview_boost)
        self.assertIn(found[0][0]["section"], ("1. WSTĘP", "6. PODSUMOWANIE"))

    def test_the_index_is_saved_and_read_back(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.index.save(tmp)
            loaded = ThesisIndex.load(tmp)
        self.assertEqual(len(loaded.chunks), len(self.index.chunks))
        self.assertEqual(loaded.search("PPO", fake_encode, k=1)[0][0]["text"],
                         self.index.search("PPO", fake_encode, k=1)[0][0]["text"])

    def test_a_missing_or_old_index_is_not_used(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ThesisIndex.load(tmp))

    def test_a_long_fragment_gets_vectors_of_its_sentences(self):
        chunk = {"section": "7. BADANIA", "text": " ".join(["Pierwsze zdanie o czymś innym."] * 12)
                 + " Polityka była uczona na 32 środowiskach."}
        windows = sentence_windows(chunk)
        self.assertGreater(len(windows), 1)
        self.assertTrue(all(w.startswith("7. BADANIA: ") for w in windows))
        self.assertTrue(all(len(w.split()) <= WINDOW_WORDS + 3 for w in windows))
        self.assertIn("32 środowiskach", windows[-1])

    def test_a_sentence_close_to_the_question_lifts_its_whole_fragment(self):
        filler = " ".join(f"Zdanie numer {i} opisuje nagrodę za chód robota." for i in range(30))
        data = {"chunks": [
            {"id": 0, "kind": "paragraph", "section": "", "page": 1, "text": filler + " Liczba środowisk wynosiła 32.",
             "rects": []},
            {"id": 1, "kind": "paragraph", "section": "", "page": 2, "text": "Opis chwytaka.", "rects": []}]}
        whole_only = ThesisIndex(data, fake_encode_for(data, [chunk_text_for_embedding(c) for c in data["chunks"]]))
        with_windows = ThesisIndex.build(data, lambda t: fake_encode_for(data, t))
        query = fake_encode_for(data, ["środowisk"])[0]
        self.assertGreater(with_windows._cosines(query)[0], whole_only._cosines(query)[0])

    def test_phrases_written_by_the_model_help_but_the_question_counts_most(self):
        found = self.index.search_many(["Czym jest sieć?", "algorytm PPO"], fake_encode, k=3)
        self.assertTrue(any("PPO" in c["text"] for c, _ in found))
        self.assertEqual(self.index.search_many(["", "  "], fake_encode), [])


class AnswerTest(unittest.TestCase):
    def setUp(self):
        self.chunks = build_chunks(DOC)["chunks"]
        self.found = [(c, {"bm25": 1.0, "cosine": 0.5, "score": 0.1}) for c in self.chunks]

    def test_questions_about_the_whole_thesis(self):
        self.assertTrue(A.is_whole_thesis_question("Jakie są główne wnioski?"))
        self.assertTrue(A.is_whole_thesis_question("O czym jest ta praca?"))
        self.assertFalse(A.is_whole_thesis_question("Jaki krok uczenia przyjęto?"))

    def test_nothing_relevant_means_no_model_call(self):
        self.assertTrue(A.nothing_relevant([(self.chunks[0], {"bm25": 0.0, "cosine": 0.1, "score": 0.0})]))
        self.assertFalse(A.nothing_relevant([(self.chunks[0], {"bm25": 0.0, "cosine": 0.6, "score": 0.0})]))

    def test_rules_are_in_the_user_turn_because_gemma_drops_a_system_message(self):
        messages, sources = A.build_messages("Jaki algorytm?", self.found, [], [], "pl", lambda s: len(s) // 3, 3000)
        self.assertNotIn("system", [m["role"] for m in messages])
        self.assertIn(A.NOT_FOUND["pl"], messages[-1]["content"])
        self.assertTrue(messages[-1]["content"].rstrip().endswith('"'))      # the reminder comes last
        self.assertEqual(set(sources), {str(i) for i in range(1, len(self.found) + 1)})

    def test_the_context_never_exceeds_the_budget(self):
        count = lambda s: len(s) // 3       # noqa: E731
        messages, sources = A.build_messages("Pytanie?", self.found * 20, [], [("a" * 3000, "b" * 3000)] * 5,
                                             "pl", count, 1200)
        self.assertLessEqual(sum(count(m["content"]) for m in messages), 1200 + 100)
        self.assertGreater(len(sources), 0)

    def test_citations_of_fragments_not_given_are_removed(self):
        result = A.check_answer("Użyto PPO [2]. Robot ma 4 nogi [7].", {"2": {"chunk": self.chunks[2]}}, "pl")
        self.assertEqual(result["text"], "Użyto PPO [2]. Robot ma 4 nogi.")
        self.assertEqual((result["kind"], result["citations"]), ("answer", ["2"]))

    def test_an_answer_without_sources_is_marked(self):
        self.assertEqual(A.check_answer("Robot jest szybki.", {"1": {"chunk": self.chunks[0]}}, "pl")["kind"],
                         "unsourced")

    def test_the_not_found_sentence(self):
        self.assertEqual(A.check_answer("W pracy nie znalazłem informacji na ten temat", {}, "pl")["kind"],
                         "not_found")

    def test_a_count_question_favours_a_number_before_its_word(self):
        boost = A.count_boost("Ile środowisk równoległych użyto?")
        self.assertGreater(boost({"text": "Polityka była uczona na 32 środowiskach."}), 0)
        self.assertEqual(boost({"text": "Rysunek 7.2. Środowisko z przeszkodami."}), 0)
        self.assertEqual(boost({"text": "Środowisko symulacyjne Isaac."}), 0)
        self.assertIsNone(A.count_boost("Jakie środowisko wybrano?"))
        both = A.combine_boosts(A.overview_boost, boost)
        self.assertGreater(both({"section": "1. WSTĘP", "text": "na 32 środowiskach"}),
                           both({"section": "1. WSTĘP", "text": "bez liczby"}))
        self.assertIsNone(A.combine_boosts(None, None))

    def test_the_phrases_of_the_model_are_cleaned(self):
        phrases = A.parse_expansion('1. "liczba środowisk"\n- środowiska równoległe\n• liczba środowisk\nx\n' + "a" * 80)
        self.assertEqual(phrases, ["liczba środowisk", "środowiska równoległe"])
        self.assertLessEqual(len(A.parse_expansion("\n".join(f"fraza {i}" for i in range(20)))), A.MAX_PHRASES)

    def test_a_stray_not_found_sentence_is_dropped_from_a_sourced_answer(self):
        result = A.check_answer("Użyto PPO [2]. " + A.NOT_FOUND["pl"], {"2": {"chunk": self.chunks[2]}}, "pl")
        self.assertEqual(result["kind"], "answer")
        self.assertNotIn(A.NOT_FOUND["pl"].rstrip("."), result["text"])

    def test_the_rules_tell_the_authors_work_from_cited_works(self):
        messages, _ = A.build_messages("Na jakim robocie?", self.found, [], [], "pl", lambda s: len(s) // 3, 3000)
        self.assertIn("własną pracę autora od opisywanych w niej cudzych prac", messages[0]["content"])

    def test_a_summary_points_at_its_chapter(self):
        sections = build_chunks(DOC)["sections"]
        view = A.source_view("S1", {"summary": {"display": "6. PODSUMOWANIE", "summary": "Robot chodzi."}}, sections)
        self.assertEqual(view["page"], 60)


class PanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_citations_become_links_to_pages(self):
        from ui.assistant_panel import answer_html
        html = answer_html({"text": "Użyto PPO [1].", "kind": "answer",
                            "sources": [{"key": "1", "page": 19, "label": "3. METODY", "rects": []}]})
        self.assertIn('href="src:0"', html)
        self.assertIn("20", html)                                     # pages are shown counted from 1

    def test_an_unsourced_answer_shows_a_warning(self):
        from ui.assistant_panel import answer_html
        from ui.i18n import t
        self.assertIn(t("assistant.unsourced")[:20], answer_html({"text": "x", "kind": "unsourced", "sources": []}))

    def test_a_conversation_and_a_click_on_a_page(self):
        from PySide6.QtWidgets import QWidget
        from ui.assistant_panel import AssistantPanel
        host = QWidget()
        panel = AssistantPanel(host)
        asked, clicked = [], []
        panel.askRequested.connect(asked.append)
        panel.sourceClicked.connect(clicked.append)
        panel.toggle()
        panel._submit("  Jaki   algorytm? ")
        self.assertEqual(asked, ["Jaki algorytm?"])
        self.assertIsNotNone(panel._typing)                            # the answer bubble is being written
        panel.show_answer({"text": "PPO [1].", "kind": "answer",
                           "sources": [{"key": "1", "page": 19, "label": "", "rects": [[19, 1, 2, 3, 4]]}]})
        self.assertIsNone(panel._typing)
        self.assertEqual(len(panel._bubbles), 2)                       # the question and the answer
        panel._link("src0:0")
        self.assertEqual(clicked[0]["page"], 19)
        panel.clear()
        self.assertEqual(panel._bubbles, [])


class ControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _controller(self, available=(True, None)):
        from PySide6.QtWidgets import QWidget
        from ui.assistant_panel import AssistantController, AssistantPanel

        class FakeClient:
            def __init__(self, on_event):
                self.on_event, self.sent, self.stopped = on_event, [], 0

            def open_document(self, path, summaries=None):
                self.sent.append(("open", path, summaries))

            def ask(self, qid, question, history, language):
                self.sent.append(("ask", qid, question, list(history)))

            def cancel(self):
                self.sent.append(("cancel",))

            def stop(self):
                self.stopped += 1

            def forget_document(self):
                pass

            def running(self):
                return True

        class FakeView:
            def __init__(self):
                self.shown = None

            def clear_source(self):
                pass

            def show_source(self, page, rects):
                self.shown = (page, rects)

        self.host = QWidget()
        panel = AssistantPanel(self.host)
        view = FakeView()
        controller = AssistantController(panel, view, availability=lambda: available, client_factory=FakeClient)
        return controller, panel, view

    def test_nothing_starts_before_the_panel_is_opened(self):
        controller, panel, _ = self._controller()
        controller.set_document("/x/praca.pdf", {"section_summaries": [{"display": "1", "summary": "s"}]})
        self.assertIsNone(controller.client)
        panel.toggle()
        self.assertEqual(controller.client.sent[0][0], "open")
        self.assertEqual(controller.client.sent[0][2], [{"display": "1", "summary": "s"}])

    def test_question_answer_history_and_source(self):
        controller, panel, view = self._controller()
        controller.set_document("/x/praca.pdf")
        controller.ask("Jaki algorytm?")
        qid = controller.client.sent[-1][1]
        controller._on_message(("answer", qid, {"text": "PPO [1].", "kind": "answer",
                                                "sources": [{"key": "1", "page": 5, "label": "", "rects": []}]}))
        self.assertEqual(controller.history, [("Jaki algorytm?", "PPO [1].")])
        controller.ask("A dlaczego?")
        self.assertEqual(controller.client.sent[-1][3], [("Jaki algorytm?", "PPO [1].")])
        controller.show_source({"page": 5, "rects": [[5, 1, 2, 3, 4]]})
        self.assertEqual(view.shown[0], 5)

    def test_an_analysis_stops_the_assistant(self):
        controller, panel, _ = self._controller()
        controller.set_document("/x/praca.pdf")
        controller.ask("Jaki algorytm?")
        controller.suspend()
        self.assertEqual(controller.client.stopped, 1)
        self.assertIsNone(controller._pending)
        controller.ask("Drugie pytanie?")                               # refused while the analysis runs
        self.assertEqual(sum(1 for m in controller.client.sent if m[0] == "ask"), 1)

    def test_a_crash_is_shown_and_the_next_question_reopens_the_thesis(self):
        controller, panel, _ = self._controller()
        controller.set_document("/x/praca.pdf")
        controller.ask("Jaki algorytm?")
        controller._on_message(("crashed", "brak pamięci karty"))
        self.assertIsNone(controller._pending)
        self.assertIsNone(controller.opened_path)
        controller.ask("Jeszcze raz?")
        self.assertEqual([m[0] for m in controller.client.sent][-2:], ["open", "ask"])

    def test_hidden_without_the_gpu_mode(self):
        controller, panel, _ = self._controller(available=(False, "assistant.off_cpu"))
        self.assertTrue(panel.isHidden())
        controller, panel, _ = self._controller(available=(False, "assistant.off_models"))
        self.assertFalse(panel.isHidden())
        self.assertFalse(panel.input.isEnabled())


class ContextSizeTest(unittest.TestCase):
    def test_a_smaller_card_gets_a_smaller_context(self):
        from app.assistant_process import context_size
        self.assertEqual(context_size(16), 8192)
        self.assertEqual(context_size(12), 6144)
        self.assertEqual(context_size(8), 4096)


if __name__ == "__main__":
    unittest.main()
